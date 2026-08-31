"""Authenticated bounded n8n command endpoint."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView

from ..connectors.n8n import N8nConnector
from ..const import DOMAIN
from ..domain.common import stable_digest

N8N_VIEW_REGISTERED = "hamie.n8n_view_registered"
MAX_INBOUND_BODY = 32_000


def _runtime(hass: Any) -> Any:
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise RuntimeError("HAMIE is not loaded")
    return next(iter(entries.values()))


def _response(
    *,
    accepted: bool,
    command_id: str,
    runtime: Any | None,
    result: dict[str, Any] | None = None,
    error_code: str | None = None,
    status: int = 200,
) -> web.Response:
    snapshot = runtime.projection.snapshot if runtime is not None else None
    return web.json_response(
        {
            "schema_version": 1,
            "accepted": accepted,
            "command_id": command_id,
            "result": result or {},
            "generation": snapshot.generation if snapshot is not None else 0,
            "projection_revision": (
                snapshot.projection_revision if snapshot is not None else 0
            ),
            "error_code": error_code,
        },
        status=status,
    )


class HamieN8nCommandView(HomeAssistantView):
    """Receive only authenticated, fixed HAMIE commands."""

    url = "/api/hamie/n8n"
    name = "api:hamie:n8n"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """Validate and dispatch one bounded command."""
        hass = request.app[KEY_HASS]
        runtime: Any | None = None
        command_id = ""
        try:
            runtime = _runtime(hass)
            connector = runtime.connectors.connector("n8n")
            if not isinstance(connector, N8nConnector):
                return _response(
                    accepted=False,
                    command_id=command_id,
                    runtime=runtime,
                    error_code="connector_disabled",
                    status=503,
                )
            maximum = min(MAX_INBOUND_BODY, connector.config.maximum_payload_size)
            if request.content_length is not None and request.content_length > maximum:
                raise web.HTTPRequestEntityTooLarge(
                    max_size=maximum, actual_size=request.content_length
                )
            raw = await request.read()
            if len(raw) > maximum:
                raise web.HTTPRequestEntityTooLarge(
                    max_size=maximum, actual_size=len(raw)
                )
            try:
                payload = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as err:
                raise ValueError("malformed_json") from err
            if not isinstance(payload, dict):
                raise ValueError("malformed_json")
            raw_token = payload.get("idempotency_token")
            if isinstance(raw_token, str) and raw_token:
                command_id = f"cmd_{stable_digest(raw_token)[:24]}"
            verified = await connector.async_verify_and_reserve_inbound(
                payload,
                {
                    "Authorization": request.headers.get("Authorization", ""),
                    "X-HAMIE-Signature": request.headers.get("X-HAMIE-Signature", ""),
                },
                current_revision=runtime.projection.snapshot.generation,
            )
            result = await _dispatch(runtime, verified)
            await runtime.operations.async_record_audit(
                "n8n_command_accepted",
                actor="n8n_authenticated_command",
                target_ids=(verified["command"], command_id),
            )
            return _response(
                accepted=True,
                command_id=command_id,
                runtime=runtime,
                result=result,
            )
        except web.HTTPRequestEntityTooLarge:
            error_code = "request_too_large"
            status = 413
        except PermissionError:
            error_code = "authentication_or_command_rejected"
            status = 403
        except ValueError as err:
            error_code = str(err) if str(err) == "malformed_json" else "invalid_schema"
            status = 400
        except RuntimeError as err:
            error_code = (
                "stale_expected_revision"
                if str(err) == "stale_expected_revision"
                else "runtime_unavailable"
            )
            status = 409 if error_code == "stale_expected_revision" else 503
        except Exception:
            error_code = "command_failed"
            status = 409
        if runtime is not None:
            try:
                await runtime.operations.async_record_audit(
                    "n8n_command_rejected",
                    actor="n8n_command_endpoint",
                    target_ids=(command_id or "unknown",),
                    details=(("error", error_code),),
                )
            except Exception:
                pass
        return _response(
            accepted=False,
            command_id=command_id,
            runtime=runtime,
            error_code=error_code,
            status=status,
        )


async def _dispatch(runtime: Any, envelope: dict[str, Any]) -> dict[str, Any]:
    """Map the fixed command vocabulary to existing application methods."""
    command = envelope["command"]
    payload = envelope["payload"]
    token = envelope["idempotency_token"]
    actor = "n8n_authenticated_command"
    if command == "request_scan":
        result = await runtime.application.async_start_full_evaluation()
        return {"scan_id": result.evaluation.identity.scan_id}
    if command == "request_group_refresh":
        page = runtime.operations.query_groups(offset=0, limit=100)
        return {"group_count": page["total"]}
    if command == "request_ai_analysis":
        recommendation = await runtime.operations.async_request_ai(
            finding_ids=tuple(payload["finding_ids"]),
            group_ids=tuple(payload["group_ids"]),
            actor=actor,
        )
        return {"recommendation_id": recommendation.recommendation_id}
    action = {
        "acknowledge_group": "acknowledge",
        "dismiss_group": "dismiss",
        "snooze_group": "snooze",
        "retain_group": "retain",
        "suppress_group": "suppress",
    }[command]
    preview = runtime.operations.preview_group(payload["group_id"], action)
    if preview.generation != envelope["expected_revision"]:
        raise RuntimeError("stale_expected_revision")
    if command == "suppress_group":
        rule = await runtime.operations.async_suppress_group(
            preview,
            token=token,
            actor=actor,
            reason=payload["reason"],
        )
        return {"rule_id": rule.rule_id}
    result = await runtime.operations.async_apply_group_review(
        preview,
        token=token,
        actor=actor,
        snooze_until=(
            datetime.fromisoformat(payload["snooze_until"])
            if command == "snooze_group"
            else None
        ),
    )
    return result


def async_register_n8n_view(hass: Any) -> None:
    """Register once; the view returns unavailable whenever HAMIE is unloaded."""
    if hass.data.get(N8N_VIEW_REGISTERED):
        return
    hass.http.register_view(HamieN8nCommandView)
    hass.data[N8N_VIEW_REGISTERED] = True
