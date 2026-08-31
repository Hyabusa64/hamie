"""Admin-authorized bounded WebSocket API for the HAMIE panel."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from hashlib import sha256
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api

from ..configuration import (
    CONFIGURATION_SCHEMA_VERSION,
    CONNECTOR_IDS,
    EDITABLE_SECTIONS,
    ConfigurationError,
    configuration_revision,
    normalize_section,
    sanitized_configuration,
    sanitized_section,
)
from ..connectors.base import classify_connector_failure, now_utc
from ..build_info import BUILD_INFO
from ..const import DOMAIN, VERSION
from ..domain.intelligence import (
    AIReviewState,
    GroupActionPreview,
    SuppressionAction,
)
from ..domain.incidents import IncidentLifecycle, IncidentPriority

API_REGISTERED = "hamie.websocket_api_registered"
CONFIGURATION_WRITES = "hamie.configuration_writes"
CONFIGURATION_UPDATE_GUARDS = "hamie.configuration_update_guards"
CONFIGURATION_MODEL_CACHE = "hamie.configuration_model_cache"
SUPPORTED_CONFIGURATION_SCHEMA_VERSIONS = (1, CONFIGURATION_SCHEMA_VERSION)
_LOGGER = logging.getLogger(__name__)


class ConfigurationReloadError(RuntimeError):
    """The candidate options could not be activated and were rolled back."""


def _runtime(hass: Any) -> Any:
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise RuntimeError("HAMIE is not loaded")
    return next(iter(entries.values()))


def _entry_context(hass: Any) -> tuple[str, Any]:
    """Return the single loaded entry identity and runtime."""
    entries = hass.data.get(DOMAIN, {})
    if len(entries) != 1:
        raise RuntimeError("HAMIE configuration entry is unavailable")
    return next(iter(entries.items()))


def _error(connection: Any, msg: dict[str, Any], err: Exception) -> None:
    connection.send_error(msg["id"], "hamie_error", classify_connector_failure(err))


def _structured_error(connection: Any, msg: dict[str, Any], err: Exception) -> None:
    """Send a stable non-sensitive configuration failure."""
    if isinstance(err, ConfigurationError):
        code = err.code
    elif type(err).__name__ in {"RevisionConflictError", "GenerationConflictError"}:
        code = "stale_revision"
    else:
        code = "configuration_failed"
    connection.send_error(msg["id"], code, code)


def _configuration_failure(
    section: str, err: Exception, *, code: str | None = None
) -> dict[str, Any]:
    """Return a bounded field-aware failure without exception or secret text."""
    if isinstance(err, ConfigurationError):
        error_code = (
            err.code
            if err.code in {"stale_revision", "idempotency_conflict"}
            else "validation_failed"
        )
        field_errors = {err.field: err.code} if err.field else {}
    else:
        error_code = code or "configuration_failed"
        field_errors = {}
        _LOGGER.error(
            "HAMIE configuration operation failed: error_type=%s",
            type(err).__name__,
        )
    return {
        "ok": False,
        "error_code": error_code,
        "section": section,
        "field_errors": field_errors,
        "message": (
            "Review the highlighted field."
            if field_errors
            else "HAMIE kept the previous configuration. Try again."
        ),
    }


def _connector_failure_code(err: Exception) -> str:
    """Map connector failures to fixed non-sensitive categories."""
    if isinstance(err, ConfigurationError):
        return err.code
    return classify_connector_failure(err)


def _config_entry(hass: Any) -> Any:
    entry_id, _runtime_value = _entry_context(hass)
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise ConfigurationError("entry_unavailable")
    return entry


def _request_fingerprint(section: str, values: dict[str, Any]) -> str:
    return sha256(
        json.dumps([section, values], sort_keys=True, default=str).encode()
    ).hexdigest()


def _configuration_write_cache(hass: Any) -> dict[str, tuple[str, dict[str, Any]]]:
    cache = hass.data.setdefault(CONFIGURATION_WRITES, {})
    if not isinstance(cache, dict):
        raise RuntimeError("configuration write cache is invalid")
    return cache


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/configuration/get",
        vol.Required("schema_version"): vol.In(SUPPORTED_CONFIGURATION_SCHEMA_VERSIONS),
    }
)
def ws_configuration_get(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return current options, field schemas, and runtime views without secrets."""
    try:
        entry = _config_entry(hass)
        result = sanitized_configuration(dict(entry.options))
        runtime = _runtime(hass)
        result["suppression_rules"] = runtime.operations.suppression_rules()
        result["connector_status"] = runtime.operations.connector_status()
        result["audit_revision"] = runtime.projection.snapshot.projection_revision
        # Runtime-only, process-cached from the last successful Test
        # Connection (ConnectorManager.discovered_models) -- surfaced here
        # so the model list is populated on page load whenever Ollama has
        # already been tested this process lifetime, instead of always
        # starting empty until the user re-tests the exact same already-
        # working connection every time they open this editor.
        result["sections"]["ollama"]["metadata"]["discovered_models"] = list(
            runtime.operations.discovered_ai_models()
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _structured_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/configuration/validate",
        vol.Required("schema_version"): vol.In(SUPPORTED_CONFIGURATION_SCHEMA_VERSIONS),
        vol.Required("section"): vol.In(EDITABLE_SECTIONS),
        vol.Required("values"): dict,
    }
)
def ws_configuration_validate(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Validate one unsaved settings section without side effects."""
    try:
        entry = _config_entry(hass)
        candidate = normalize_section(
            msg["section"], msg["values"], dict(entry.options)
        )
        connection.send_result(
            msg["id"],
            {
                "ok": True,
                "valid": True,
                "schema_version": CONFIGURATION_SCHEMA_VERSION,
                "section": sanitized_section(msg["section"], candidate),
            },
        )
    except Exception as err:
        if msg["schema_version"] == 1:
            _structured_error(connection, msg, err)
        else:
            connection.send_result(
                msg["id"], _configuration_failure(msg["section"], err)
            )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/configuration/save",
        vol.Required("schema_version"): vol.In(SUPPORTED_CONFIGURATION_SCHEMA_VERSIONS),
        vol.Required("section"): vol.In(EDITABLE_SECTIONS),
        vol.Required("expected_revision"): vol.All(str, vol.Length(min=24, max=24)),
        vol.Required("idempotency_token"): vol.All(str, vol.Length(min=16, max=128)),
        vol.Required("values"): dict,
    }
)
@websocket_api.async_response
async def ws_configuration_save(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Persist one validated options section and let one update listener reload."""
    try:
        entry = _config_entry(hass)
        current = dict(entry.options)
        current_revision = configuration_revision(current)
        token = msg["idempotency_token"]
        fingerprint = _request_fingerprint(msg["section"], msg["values"])
        cache = _configuration_write_cache(hass)
        replay = cache.get(token)
        if replay is not None:
            if replay[0] != fingerprint:
                raise ConfigurationError("idempotency_conflict")
            connection.send_result(msg["id"], replay[1])
            return
        if msg["expected_revision"] != current_revision:
            raise ConfigurationError("stale_revision")
        candidate = normalize_section(msg["section"], msg["values"], current)
        changed = candidate != current
        result = {
            "ok": True,
            "saved": changed,
            "reloaded": changed,
            "schema_version": CONFIGURATION_SCHEMA_VERSION,
            "section": msg["section"],
            "revision": configuration_revision(candidate),
            "section_state": sanitized_section(msg["section"], candidate),
        }
        if changed:
            try:
                await _async_apply_configuration(hass, entry, current, candidate)
            except ConfigurationReloadError as err:
                if msg["schema_version"] == 1:
                    connection.send_error(msg["id"], "reload_failed", "reload_failed")
                else:
                    connection.send_result(
                        msg["id"],
                        _configuration_failure(
                            msg["section"], err, code="reload_failed"
                        ),
                    )
                return
        cache[token] = (fingerprint, result)
        while len(cache) > 128:
            cache.pop(next(iter(cache)))
        connection.send_result(msg["id"], result)
    except Exception as err:
        if msg["schema_version"] == 1:
            _structured_error(connection, msg, err)
        else:
            connection.send_result(
                msg["id"], _configuration_failure(msg["section"], err)
            )


async def _async_guarded_options_update(
    hass: Any, entry: Any, options: dict[str, Any]
) -> None:
    """Update options and wait until the update listener has skipped reload."""
    guards = hass.data.setdefault(CONFIGURATION_UPDATE_GUARDS, {})
    future = asyncio.get_running_loop().create_future()
    guards[entry.entry_id] = future
    hass.config_entries.async_update_entry(entry, options=options)
    try:
        await asyncio.wait_for(future, timeout=5)
    finally:
        guards.pop(entry.entry_id, None)
        if not guards:
            hass.data.pop(CONFIGURATION_UPDATE_GUARDS, None)


async def _async_apply_configuration(
    hass: Any,
    entry: Any,
    previous: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    """Activate candidate options exactly once or restore the previous options."""
    await _async_guarded_options_update(hass, entry, candidate)
    try:
        reloaded = await hass.config_entries.async_reload(entry.entry_id)
        if not reloaded:
            raise ConfigurationReloadError
    except Exception as err:
        await _async_guarded_options_update(hass, entry, previous)
        await _record_configuration_failure_audit(hass, entry.entry_id)
        raise ConfigurationReloadError from err
    await _record_configuration_success_audit(hass, entry.entry_id)


async def _record_configuration_success_audit(hass: Any, entry_id: str) -> None:
    try:
        await _runtime(hass).operations.async_record_audit(
            "configuration_changed",
            actor="home_assistant_settings_panel",
            target_ids=(entry_id,),
        )
    except Exception as err:
        _LOGGER.error(
            "HAMIE configuration audit failed: error_type=%s",
            type(err).__name__,
        )


async def _record_configuration_failure_audit(hass: Any, entry_id: str) -> None:
    try:
        await _runtime(hass).operations.async_record_audit(
            "configuration_change_failed",
            actor="home_assistant_settings_panel",
            target_ids=(entry_id,),
        )
    except Exception:
        return


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/configuration/test",
        vol.Required("schema_version"): vol.In(SUPPORTED_CONFIGURATION_SCHEMA_VERSIONS),
        vol.Required("connector_id"): vol.In(CONNECTOR_IDS),
        vol.Required("values"): dict,
    }
)
@websocket_api.async_response
async def ws_configuration_test(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Test validated unsaved connector values without persisting or reloading."""
    manager = None
    try:
        entry = _config_entry(hass)
        candidate = normalize_section(
            msg["connector_id"],
            msg["values"],
            dict(entry.options),
            for_test=True,
        )
        if not candidate.get(f"{msg['connector_id']}_enabled"):
            raise ConfigurationError("connector_disabled")
        from ..connectors.manager import ConnectorManager

        manager = ConnectorManager(
            options=candidate,
            hass=hass,
            installation_id=entry.data.get("installation_id", entry.entry_id),
        )
        tested = await manager.async_test(msg["connector_id"])
        response: dict[str, Any] = {
            "ok": True,
            "connected": True,
            "connector_id": msg["connector_id"],
            "status": tested.get("status", "unknown"),
            "latency_ms": tested.get("latency_ms"),
            "result": tested,
        }
        if msg["connector_id"] == "ollama":
            models = tuple(
                str(item) for item in tested.get("details", {}).get("models", [])[:100]
            )
            response["models"] = list(models)
            cache = hass.data.setdefault(CONFIGURATION_MODEL_CACHE, {})
            cache[entry.entry_id] = {
                "endpoint": candidate.get("ollama_base_url", ""),
                "models": models,
            }
        await _record_configuration_test_audit(
            hass, msg["connector_id"], succeeded=True
        )
        connection.send_result(
            msg["id"],
            response,
        )
    except Exception as err:
        await _record_configuration_test_audit(
            hass, msg["connector_id"], succeeded=False
        )
        code = _connector_failure_code(err)
        if msg["schema_version"] == 1:
            connection.send_error(msg["id"], code, code)
        else:
            field = getattr(err, "field", None)
            connection.send_result(
                msg["id"],
                {
                    "ok": False,
                    "connected": False,
                    "error_code": code,
                    "section": msg["connector_id"],
                    "field_errors": {field: code} if field else {},
                    "message": (
                        "Review the highlighted field."
                        if field
                        else "Connection test failed. Review the connector details."
                    ),
                },
            )
    finally:
        if manager is not None:
            await manager.async_close()


async def _record_configuration_test_audit(
    hass: Any, connector_id: str, *, succeeded: bool
) -> None:
    """Best-effort secret-free audit of one explicit unsaved connection test."""
    try:
        await _runtime(hass).operations.async_record_audit(
            ("connector_test_succeeded" if succeeded else "connector_test_failed"),
            actor="home_assistant_settings_panel",
            target_ids=(connector_id,),
        )
    except Exception:
        return


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "hamie/explorer/overview"})
def ws_overview(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return aggregate panel data without persistence I/O."""
    try:
        runtime = _runtime(hass)
        result = {
            **runtime.operations.overview(),
            "runtime": runtime.projection.snapshot,
            "connectors": runtime.operations.connector_status(),
        }
        options = dict(_config_entry(hass).options)
        general = sanitized_section("general", options)["values"]
        findings = sanitized_section("findings", options)["values"]
        result["preferences"] = {
            "page_size": general["default_findings_page_size"],
            "sort": general["default_findings_sort"],
            "suppression_visibility": general["default_suppression_visibility"],
            "severity": findings["default_severity_filters"],
            "lifecycle": findings["default_lifecycle_filters"],
        }
        snapshot = result.pop("runtime")
        result.update(
            {
                "availability_health": snapshot.availability_health,
                "operational_health": snapshot.operational_health,
                "registry_cleanliness": snapshot.registry_cleanliness,
                "critical_findings": snapshot.findings_critical,
                "warning_findings": snapshot.findings_warning,
                "new_findings": snapshot.findings_new,
                "resolved_findings": snapshot.findings_resolved,
                "last_scan": (
                    snapshot.scan_completed.isoformat()
                    if snapshot.scan_completed
                    else None
                ),
                "last_scan_id": snapshot.last_scan_id,
                "scan_duration": snapshot.scan_duration,
                "coverage": snapshot.coverage_state,
                "scan_status": snapshot.scan_status.value,
                "version": VERSION,
                **BUILD_INFO.as_dict(),
                "ai_last_coverage": (
                    runtime.operations.last_ai_coverage.public_dict()
                    if runtime.operations.last_ai_coverage is not None
                    else None
                ),
            }
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/explorer/findings",
        vol.Optional("search", default=""): str,
        vol.Optional("filters", default={}): dict,
        vol.Optional("sort", default="priority"): str,
        vol.Optional("offset", default=0): int,
        vol.Optional("limit", default=50): int,
    }
)
def ws_findings(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return one bounded indexed findings page."""
    try:
        connection.send_result(
            msg["id"],
            _runtime(hass).operations.query_findings(
                search=msg["search"],
                filters=msg["filters"],
                sort=msg["sort"],
                offset=msg["offset"],
                limit=msg["limit"],
            ),
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/explorer/groups",
        vol.Optional("search", default=""): str,
        vol.Optional("offset", default=0): int,
        vol.Optional("limit", default=25): int,
    }
)
def ws_groups(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return one deterministic group page."""
    try:
        connection.send_result(
            msg["id"],
            _runtime(hass).operations.query_groups(
                search=msg["search"], offset=msg["offset"], limit=msg["limit"]
            ),
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/incidents/list",
        vol.Optional("search", default=""): str,
        vol.Optional("lifecycle", default="active"): vol.In(
            {"active", "all", *(item.value for item in IncidentLifecycle)}
        ),
        vol.Optional("priority", default=""): vol.In(
            {"", *(item.value for item in IncidentPriority)}
        ),
        vol.Optional("offset", default=0): int,
        vol.Optional("limit", default=50): int,
    }
)
def ws_incidents(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return a bounded page of durable root-cause incidents."""
    try:
        connection.send_result(
            msg["id"],
            _runtime(hass).operations.query_incidents(
                search=msg["search"],
                lifecycle=msg["lifecycle"],
                priority=msg["priority"],
                offset=msg["offset"],
                limit=msg["limit"],
            ),
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/incidents/get",
        vol.Required("incident_id"): str,
    }
)
def ws_incident(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return one incident and its evidence references."""
    try:
        connection.send_result(
            msg["id"], _runtime(hass).operations.incident(msg["incident_id"])
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/incidents/lifecycle",
        vol.Required("incident_id"): str,
        vol.Required("lifecycle"): vol.In(
            {
                IncidentLifecycle.INVESTIGATING.value,
                IncidentLifecycle.CONFIRMED.value,
                IncidentLifecycle.DISMISSED.value,
                IncidentLifecycle.IGNORED.value,
            }
        ),
        vol.Required("expected_revision"): int,
        vol.Required("idempotency_token"): str,
    }
)
@websocket_api.async_response
async def ws_incident_lifecycle(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Apply one explicit, revision-bound incident decision."""
    try:
        result = await _runtime(hass).operations.async_set_incident_lifecycle(
            msg["incident_id"],
            IncidentLifecycle(msg["lifecycle"]),
            expected_revision=msg["expected_revision"],
            actor=f"home_assistant_user:{connection.user.id}",
            token=msg["idempotency_token"],
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/explorer/dependencies",
        vol.Optional("finding_id"): str,
        vol.Optional("group_id"): str,
    }
)
@websocket_api.async_response
async def ws_dependencies(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return one bounded attributed dependency graph."""
    try:
        connection.send_result(
            msg["id"],
            await _runtime(hass).operations.async_dependency_graph(
                finding_id=msg.get("finding_id"), group_id=msg.get("group_id")
            ),
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/group/preview",
        vol.Required("group_id"): str,
        vol.Required("action"): vol.In(
            {"acknowledge", "dismiss", "snooze", "retain", "suppress"}
        ),
    }
)
def ws_group_preview(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Freeze a group command preview for explicit confirmation."""
    try:
        preview = _runtime(hass).operations.preview_group(
            msg["group_id"], msg["action"]
        )
        connection.send_result(
            msg["id"],
            {
                "group_id": preview.group_id,
                "action": preview.action,
                "generation": preview.generation,
                "count": preview.count,
                "findings": [list(item) for item in preview.findings],
            },
        )
    except Exception as err:
        _error(connection, msg, err)


def _preview(msg: dict[str, Any]) -> GroupActionPreview:
    raw = msg["preview"]
    if not isinstance(raw, dict):
        raise ValueError("preview must be an object")
    findings = raw.get("findings")
    if not isinstance(findings, list) or len(findings) > 10_000:
        raise ValueError("preview findings exceed bounds")
    return GroupActionPreview(
        group_id=raw["group_id"],
        action=raw["action"],
        generation=raw["generation"],
        findings=tuple((str(item[0]), int(item[1])) for item in findings),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/group/apply",
        vol.Required("preview"): dict,
        vol.Required("idempotency_token"): str,
        vol.Optional("snooze_until"): str,
    }
)
@websocket_api.async_response
async def ws_group_apply(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Apply one explicitly confirmed frozen group review."""
    try:
        preview = _preview(msg)
        result = await _runtime(hass).operations.async_apply_group_review(
            preview,
            token=msg["idempotency_token"],
            actor=f"home_assistant_user:{connection.user.id}",
            snooze_until=(
                datetime.fromisoformat(msg["snooze_until"])
                if msg.get("snooze_until")
                else None
            ),
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/group/suppress",
        vol.Required("preview"): dict,
        vol.Required("idempotency_token"): str,
        vol.Required("reason"): str,
        vol.Optional("expiration"): str,
    }
)
@websocket_api.async_response
async def ws_group_suppress(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Create one HAMIE-only suppression rule after confirmation."""
    try:
        rule = await _runtime(hass).operations.async_suppress_group(
            _preview(msg),
            token=msg["idempotency_token"],
            actor=f"home_assistant_user:{connection.user.id}",
            reason=msg["reason"],
            expiration=(
                datetime.fromisoformat(msg["expiration"])
                if msg.get("expiration")
                else None
            ),
        )
        connection.send_result(
            msg["id"],
            {"rule_id": rule.rule_id, "revision": rule.revision},
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/grouping/create",
        vol.Required("name"): str,
        vol.Required("title"): str,
        vol.Required("matcher"): dict,
    }
)
@websocket_api.async_response
async def ws_grouping_create(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Create one deterministic user-owned grouping rule."""
    try:
        rule = await _runtime(hass).operations.async_create_grouping_rule(
            name=msg["name"],
            title=msg["title"],
            matcher=tuple(sorted((str(k), str(v)) for k, v in msg["matcher"].items())),
            actor=f"home_assistant_user:{connection.user.id}",
        )
        connection.send_result(msg["id"], {"rule_id": rule.rule_id})
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/suppression/preview",
        vol.Optional("schema_version", default=1): vol.Equal(1),
        vol.Required("matcher"): dict,
    }
)
def ws_suppression_preview(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Preview exact declarative suppression matches."""
    try:
        matcher = tuple(sorted((str(k), str(v)) for k, v in msg["matcher"].items()))
        connection.send_result(
            msg["id"], _runtime(hass).operations.preview_suppression(matcher)
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/suppression/create",
        vol.Optional("schema_version", default=1): vol.Equal(1),
        vol.Required("preview"): dict,
        vol.Required("name"): str,
        vol.Required("reason"): str,
        vol.Required("action"): vol.In(
            {"hide_from_default_view", "lower_priority", "auto_acknowledge", "snooze"}
        ),
        vol.Required("idempotency_token"): str,
        vol.Optional("expiration"): str,
    }
)
@websocket_api.async_response
async def ws_suppression_create(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Create one confirmed HAMIE-only suppression rule."""
    try:
        rule = await _runtime(hass).operations.async_create_suppression_rule(
            preview=msg["preview"],
            name=msg["name"],
            reason=msg["reason"],
            action=SuppressionAction(msg["action"]),
            expiration=(
                datetime.fromisoformat(msg["expiration"])
                if msg.get("expiration")
                else None
            ),
            token=msg["idempotency_token"],
            actor=f"home_assistant_user:{connection.user.id}",
        )
        connection.send_result(
            msg["id"], {"rule_id": rule.rule_id, "revision": rule.revision}
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "hamie/suppression/list"})
def ws_suppression_list(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return bounded secret-free suppression policies from projection memory."""
    try:
        connection.send_result(msg["id"], _runtime(hass).operations.suppression_rules())
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/suppression/update",
        vol.Optional("schema_version", default=1): vol.Equal(1),
        vol.Required("rule_id"): str,
        vol.Required("expected_revision"): int,
        vol.Required("enabled"): bool,
        vol.Required("reason"): str,
        vol.Required("action"): vol.In(
            {"hide_from_default_view", "lower_priority", "auto_acknowledge", "snooze"}
        ),
        vol.Optional("preview"): dict,
        vol.Optional("idempotency_token"): vol.All(str, vol.Length(min=16, max=128)),
        vol.Optional("expiration"): str,
    }
)
@websocket_api.async_response
async def ws_suppression_update(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Update one expected revision of a HAMIE-only policy."""
    try:
        runtime = _runtime(hass)
        rule = await runtime.operations.async_update_suppression_rule(
            msg["rule_id"],
            expected_revision=msg["expected_revision"],
            enabled=msg["enabled"],
            reason=msg["reason"],
            action=SuppressionAction(msg["action"]),
            expiration=(
                datetime.fromisoformat(msg["expiration"])
                if msg.get("expiration")
                else None
            ),
            actor=f"home_assistant_user:{connection.user.id}",
            token=msg.get("idempotency_token"),
            preview=msg.get("preview"),
        )
        connection.send_result(
            msg["id"], {"rule_id": rule.rule_id, "revision": rule.revision}
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/suppression/delete",
        vol.Optional("schema_version", default=1): vol.Equal(1),
        vol.Required("rule_id"): str,
        vol.Required("expected_revision"): int,
        vol.Optional("idempotency_token"): vol.All(str, vol.Length(min=16, max=128)),
        vol.Optional("confirmed", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_suppression_delete(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Delete one HAMIE policy without deleting any finding or HA object."""
    try:
        if not msg["confirmed"]:
            raise ConfigurationError("confirmation_required")
        await _runtime(hass).operations.async_delete_suppression_rule(
            msg["rule_id"],
            expected_revision=msg["expected_revision"],
            actor=f"home_assistant_user:{connection.user.id}",
            token=msg.get("idempotency_token"),
        )
        connection.send_result(msg["id"], {"deleted": True})
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/audit/list",
        vol.Optional("offset", default=0): int,
        vol.Optional("limit", default=50): int,
        vol.Optional("event_type", default=""): vol.All(str, vol.Length(max=128)),
        vol.Optional("actor", default=""): vol.All(str, vol.Length(max=128)),
        vol.Optional("target", default=""): vol.All(str, vol.Length(max=128)),
        vol.Optional("outcome", default=""): vol.All(str, vol.Length(max=64)),
        vol.Optional("date_from", default=""): vol.All(str, vol.Length(max=64)),
        vol.Optional("date_to", default=""): vol.All(str, vol.Length(max=64)),
        vol.Optional("proposal", default=""): vol.All(str, vol.Length(max=128)),
        vol.Optional("finding", default=""): vol.All(str, vol.Length(max=128)),
    }
)
def ws_audit(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return bounded audit history."""
    try:
        connection.send_result(
            msg["id"],
            _runtime(hass).operations.audit_page(
                offset=msg["offset"],
                limit=msg["limit"],
                event_type=msg["event_type"],
                actor=msg["actor"],
                target=msg["target"],
                outcome=msg["outcome"],
                date_from=msg["date_from"],
                date_to=msg["date_to"],
                proposal=msg["proposal"],
                finding=msg["finding"],
            ),
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/configuration/audit/export",
        vol.Required("schema_version"): vol.In(SUPPORTED_CONFIGURATION_SCHEMA_VERSIONS),
    }
)
def ws_audit_export(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Export bounded secret-free audit history without Store access."""
    try:
        connection.send_result(msg["id"], _runtime(hass).operations.audit_export())
    except Exception as err:
        _structured_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/configuration/audit/clear",
        vol.Required("schema_version"): vol.In(SUPPORTED_CONFIGURATION_SCHEMA_VERSIONS),
        vol.Required("expected_revision"): int,
        vol.Required("idempotency_token"): vol.All(str, vol.Length(min=16, max=128)),
        vol.Required("confirmed"): vol.Equal(True),
    }
)
@websocket_api.async_response
async def ws_audit_clear(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Clear audit history only after explicit revision-bound confirmation."""
    try:
        result = await _runtime(hass).operations.async_clear_audit(
            expected_revision=msg["expected_revision"],
            token=msg["idempotency_token"],
            actor=f"home_assistant_user:{connection.user.id}",
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _structured_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/recommendations/list",
        vol.Optional("offset", default=0): int,
        vol.Optional("limit", default=25): int,
    }
)
def ws_recommendations(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return bounded schema-validated advisory recommendations."""
    try:
        connection.send_result(
            msg["id"],
            _runtime(hass).operations.recommendations_page(
                offset=msg["offset"], limit=msg["limit"]
            ),
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "hamie/security/findings"})
def ws_security_findings(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return deterministic evidence-backed security decisions."""
    try:
        connection.send_result(msg["id"], _runtime(hass).operations.security_page())
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "hamie/connectors/status"})
def ws_connector_status(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return cached status without connection work."""
    try:
        connection.send_result(msg["id"], _runtime(hass).operations.connector_status())
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "hamie/scheduler/status"})
def ws_scheduler_status(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return automatic-scan and connector-heartbeat scheduling state."""
    try:
        runtime = _runtime(hass)
        options = dict(_config_entry(hass).options)
        scheduler = runtime.scan_scheduler
        snapshot = runtime.projection.snapshot
        interval_minutes = int(options.get("auto_scan_interval_minutes", 60))
        last_scan = snapshot.scan_completed
        next_scan_seconds: float | None = None
        if scheduler is not None and last_scan is not None:
            elapsed = (now_utc() - last_scan).total_seconds()
            next_scan_seconds = max(0.0, interval_minutes * 60 - elapsed)
        connection.send_result(
            msg["id"],
            {
                "auto_scan_enabled": scheduler is not None,
                "auto_scan_interval_minutes": interval_minutes,
                "connector_heartbeat_interval_seconds": int(
                    options.get("connector_heartbeat_interval_seconds", 60)
                ),
                "last_scan": last_scan.isoformat() if last_scan else None,
                "next_scan_seconds": next_scan_seconds,
                "last_scan_error_classification": (
                    snapshot.last_scan_error_classification
                ),
                "last_scan_error_summary": snapshot.last_scan_error_summary,
            },
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "hamie/updates/subscribe"})
def ws_updates_subscribe(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Subscribe to one canonical bounded change notification channel.

    A subscriber does not learn *what* changed, only that some HAMIE
    projection did -- callers already know how to refresh their own view
    on demand (every existing WS query is idempotent and cheap), so this
    stays deliberately coarse-grained rather than growing a bespoke event
    taxonomy. This is the single subscribe channel every view should reuse
    -- connector heartbeat, automatic scan completion, and manual actions
    all flow through RuntimeProjection's existing notify fan-out (see
    runtime_projection.py), so one subscription here covers all of them.
    """
    try:
        runtime = _runtime(hass)

        def _on_change() -> None:
            connection.send_event(msg["id"], {"changed": True})

        connection.subscriptions[msg["id"]] = runtime.projection.subscribe(_on_change)
        connection.send_result(msg["id"])
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "hamie/configuration/context"})
def ws_configuration_context(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Resolve the active config entry for native Options Flow navigation."""
    try:
        entry_id, runtime = _entry_context(hass)
        connection.send_result(
            msg["id"],
            {
                "config_entry_id": entry_id,
                "domain": DOMAIN,
                "supports_options": True,
                "fallback_path": (
                    f"/config/integrations/integration/{DOMAIN}#config_entry={entry_id}"
                ),
                "connectors": runtime.operations.connector_status(),
            },
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/configuration/frontend_error",
        vol.Required("reason"): vol.In(
            {
                "context_unavailable",
                "flow_start_failed",
                "flow_step_failed",
                "flow_render_failed",
            }
        ),
    }
)
@websocket_api.async_response
async def ws_configuration_frontend_error(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Record one bounded non-sensitive configuration navigation failure."""
    try:
        runtime = _runtime(hass)
        await runtime.operations.async_record_audit(
            "configuration_frontend_error",
            actor=f"home_assistant_user:{connection.user.id}",
            target_ids=(msg["reason"],),
        )
        connection.send_result(msg["id"], {"recorded": True})
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/connectors/test",
        vol.Required("connector_id"): vol.In({"ollama", "n8n", "mcp", "hkg"}),
    }
)
@websocket_api.async_response
async def ws_connector_test(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Run one explicit finite connection test."""
    try:
        result = await _runtime(hass).operations.async_test_connector(
            msg["connector_id"],
            actor=f"home_assistant_user:{connection.user.id}",
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


AI_TASK_DOMAIN = "ai_task"
AI_PROVIDER_TEST_TIMEOUT_SECONDS = 20
AI_PROVIDER_TEST_PROMPT = (
    "This is a bounded, non-destructive HAMIE connectivity test message. "
    "Do not call any tool, service, or control any device. "
    "Reply only with the single word: ready."
)


def _ai_entity_choice(state: Any) -> dict[str, Any]:
    name = state.attributes.get("friendly_name") or state.entity_id
    return {"entity_id": state.entity_id, "name": str(name)}


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "hamie/ai_providers/discover"})
def ws_ai_providers_discover(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Discover native AI Task entities from HA state.

    Uses only documented public APIs: hass.services.has_service to detect
    whether the building-block integration is loaded, and
    hass.states.async_all(domain) to enumerate its entities. No private or
    undocumented Home Assistant API is used.

    Conversation entities are deliberately never discovered here: they are
    reserved for a possible future interactive assistant and must never be
    offered as a background-analysis provider.
    """
    try:
        ai_task_available = hass.services.has_service(AI_TASK_DOMAIN, "generate_data")
        connection.send_result(
            msg["id"],
            {
                "ai_task_available": ai_task_available,
                "ai_task_entities": (
                    [
                        _ai_entity_choice(state)
                        for state in sorted(
                            hass.states.async_all(AI_TASK_DOMAIN),
                            key=lambda item: item.entity_id,
                        )
                    ]
                    if ai_task_available
                    else []
                ),
            },
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/ai_providers/test",
        vol.Required("connection_method"): vol.In({"ha_ai_task"}),
        vol.Required("entity_id"): vol.All(str, vol.Length(min=1, max=256)),
    }
)
@websocket_api.async_response
async def ws_ai_providers_test(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Run one bounded, non-mutating test through the documented HA action only.

    Uses the ai_task.generate_data action on the selected ai_task entity.
    This performs no direct provider-specific network call; HAMIE never
    copies credentials from, or bypasses, the native integration that owns
    the entity.
    """
    entity_id = msg["entity_id"]
    method = msg["connection_method"]
    try:
        state = hass.states.get(entity_id)
        if state is None or not entity_id.startswith(f"{AI_TASK_DOMAIN}."):
            raise ConfigurationError("entity_not_found", "entity_id")
        started = now_utc()
        response = await asyncio.wait_for(
            hass.services.async_call(
                AI_TASK_DOMAIN,
                "generate_data",
                {
                    "entity_id": entity_id,
                    "task_name": "hamie_connection_test",
                    "instructions": AI_PROVIDER_TEST_PROMPT,
                },
                blocking=True,
                return_response=True,
            ),
            timeout=AI_PROVIDER_TEST_TIMEOUT_SECONDS,
        )
        preview = (
            str(response.get("data", ""))[:200] if isinstance(response, dict) else ""
        )
        latency_ms = max(0, int((now_utc() - started).total_seconds() * 1_000))
        await _record_configuration_test_audit(
            hass, f"ai_provider:{method}", succeeded=True
        )
        connection.send_result(
            msg["id"],
            {
                "ok": True,
                "connected": True,
                "connection_method": method,
                "entity_id": entity_id,
                "latency_ms": latency_ms,
                "preview": preview,
            },
        )
    except Exception as err:
        await _record_configuration_test_audit(
            hass, f"ai_provider:{method}", succeeded=False
        )
        if isinstance(err, ConfigurationError):
            code = err.code
            field = err.field
        else:
            code = (
                "timeout"
                if isinstance(err, TimeoutError | asyncio.TimeoutError)
                else _connector_failure_code(err)
            )
            field = None
        connection.send_result(
            msg["id"],
            {
                "ok": False,
                "connected": False,
                "error_code": code,
                "section": "ollama",
                "field_errors": {field: code} if field else {},
                "message": (
                    "Review the highlighted field."
                    if field
                    else "Connection test failed. Review the connector details."
                ),
            },
        )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/ai/analyze",
        vol.Optional("finding_ids", default=[]): [str],
        vol.Optional("group_ids", default=[]): [str],
    }
)
@websocket_api.async_response
async def ws_ai_analyze(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Create one advisory recommendation from selected deterministic state."""
    operations = _runtime(hass).operations
    try:
        result = await operations.async_request_ai(
            finding_ids=tuple(msg["finding_ids"]),
            group_ids=tuple(msg["group_ids"]),
            actor=f"home_assistant_user:{connection.user.id}",
        )
        coverage = operations.last_ai_coverage
        all_recommendations = operations.last_ai_recommendations or (result,)
        connection.send_result(
            msg["id"],
            {
                "recommendation_id": result.recommendation_id,
                "recommendation_ids": [
                    item.recommendation_id for item in all_recommendations
                ],
                "groups_analyzed": result.root_cause_groups_analyzed,
                "groups_deferred": result.root_cause_groups_skipped,
                "groups_failed": list(operations.last_ai_failed_group_ids),
                "review_state": result.review_state.value,
                "stale": result.stale,
                "coverage": coverage.public_dict() if coverage is not None else None,
            },
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/ai/review",
        vol.Required("recommendation_id"): str,
        vol.Required("state"): vol.In(
            {"acknowledged", "rejected", "retained", "expired"}
        ),
    }
)
@websocket_api.async_response
async def ws_ai_review(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Review advisory output without executing it."""
    try:
        result = await _runtime(hass).operations.async_review_ai(
            msg["recommendation_id"],
            state_value=AIReviewState(msg["state"]),
            actor=f"home_assistant_user:{connection.user.id}",
        )
        connection.send_result(msg["id"], {"review_state": result.review_state.value})
    except Exception as err:
        _error(connection, msg, err)



# ---------------------------------------------------------------------------
# Remediation workflow (mission: close the UI/API gap).
#
# Three deliberately separate commands so the frontend cannot hide a mutation
# behind an innocent-looking button: INVESTIGATE never writes, DRY_RUN never
# writes, EXECUTE writes only with an explicit approver and only after the
# deterministic policy in application/remediation_tools.py agrees.
# ---------------------------------------------------------------------------


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/config_repair/investigate",
        vol.Required("question"): str,
        vol.Optional("evidence"): list,
    }
)
@websocket_api.async_response
async def ws_remediation_investigate(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Investigate a natural-language problem. Strictly read-only."""
    try:
        from ..application.investigator import EvidencePackage, Investigator
        from ..connectors.ollama import OllamaConnector  # noqa: F401  (availability)

        runtime = _runtime(hass)
        model = runtime.investigation_model
        result = await Investigator(model).async_investigate(
            EvidencePackage(
                question=msg["question"],
                items=tuple(msg.get("evidence") or ()),
            )
        )
        connection.send_result(msg["id"], result.as_dict())
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/config_repair/dry_run",
        vol.Required("request"): str,
        vol.Required("path"): str,
        vol.Required("old_entity"): str,
        vol.Required("new_entity"): str,
        vol.Optional("root_cause"): str,
        vol.Optional("evidence_ids"): list,
        vol.Optional("confidence"): vol.Coerce(float),
    }
)
@websocket_api.async_response
async def ws_remediation_dry_run(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Preview a remediation. Never writes; same code path as execute."""
    try:
        executor = _runtime(hass).remediation_executor
        txn = await executor.async_replace_entity_reference(
            request=msg["request"],
            path=msg["path"],
            old_entity=msg["old_entity"],
            new_entity=msg["new_entity"],
            root_cause=msg.get("root_cause", ""),
            evidence_ids=tuple(msg.get("evidence_ids") or ()),
            confidence=float(msg.get("confidence") or 0.0),
            dry_run=True,
        )
        connection.send_result(msg["id"], txn.as_dict())
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/config_repair/execute",
        vol.Required("request"): str,
        vol.Required("path"): str,
        vol.Required("old_entity"): str,
        vol.Required("new_entity"): str,
        vol.Required("approve"): True,
        vol.Optional("root_cause"): str,
        vol.Optional("evidence_ids"): list,
        vol.Optional("confidence"): vol.Coerce(float),
        vol.Optional("reload_domain"): str,
    }
)
@websocket_api.async_response
async def ws_remediation_execute(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Execute an approved remediation. Approval is bound to the HA user."""
    try:
        executor = _runtime(hass).remediation_executor
        txn = await executor.async_replace_entity_reference(
            request=msg["request"],
            path=msg["path"],
            old_entity=msg["old_entity"],
            new_entity=msg["new_entity"],
            root_cause=msg.get("root_cause", ""),
            evidence_ids=tuple(msg.get("evidence_ids") or ()),
            confidence=float(msg.get("confidence") or 0.0),
            dry_run=False,
            approved_by=f"home_assistant_user:{connection.user.id}",
            reload_domain=msg.get("reload_domain"),
        )
        connection.send_result(msg["id"], txn.as_dict())
    except Exception as err:
        _error(connection, msg, err)



@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/config_repair/triage_incident",
        vol.Required("incident_id"): str,
    }
)
@websocket_api.async_response
async def ws_triage_incident(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Closed-loop triage of one existing incident. Strictly non-mutating.

    Runs evidence assembly -> local investigation -> normalized intent ->
    deterministic target rediscovery -> risk/invariant evaluation -> automatic
    dry-run, and returns an operator-reviewable result. Execution remains the
    separate, explicitly approved hamie/config_repair/execute command.
    """
    try:
        pipeline = _runtime(hass).incident_remediation
        result = await pipeline.async_triage(msg["incident_id"])
        connection.send_result(msg["id"], result.as_dict())
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/incidents/reconcile",
        vol.Optional("priority", default=""): str,
        vol.Optional("limit", default=50): int,
    }
)
@websocket_api.async_response
async def ws_incidents_reconcile(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Re-verify whether active incidents are still real. READ-ONLY.

    Reports current validity separately from repairability. Zero repair
    candidates does not mean zero valid incidents -- live, all 22 active P1s
    are still_present while none yields a deterministic repair.
    """
    try:
        operations = _runtime(hass).operations
        result = await operations.async_reconcile_incidents(
            priority=msg.get("priority", ""), limit=int(msg.get("limit", 50))
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.websocket_command({vol.Required("type"): "hamie/ai/capability"})
def ws_ai_capability(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Report measured provider capability and whether analysis is permitted."""
    try:
        connection.send_result(msg["id"], _runtime(hass).operations.capability_status())
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "hamie/ai/capability/probe"})
@websocket_api.async_response
async def ws_ai_capability_probe(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Measure the configured model against HAMIE's contract.

    Sends controlled fixtures through the same analyze path production uses,
    so a pass means the real contract was satisfied. Every probe is a bounded
    advisory request: nothing is mutated and no finding is marked analyzed.
    """
    try:
        operations = _runtime(hass).operations
        result = await operations.async_probe_capability(
            actor=f"home_assistant_user:{connection.user.id}"
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/config_repair/execute_incident_repair",
        vol.Required("incident_id"): str,
        vol.Required("plan"): dict,
        vol.Required("plan_identity"): vol.All(str, vol.Length(min=32, max=64)),
        vol.Required("approve"): True,
        vol.Optional("advisory"): dict,
    }
)
@websocket_api.async_response
async def ws_execute_incident_repair(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Execute one approved repair and prove whether it solved the incident.

    Separate from triage on purpose: triage never writes, and this command
    cannot be reached without an explicit approval bound to the exact plan
    that was reviewed. It runs the whole post-approval lifecycle -- drift
    check, verified backup, mutation, configuration and runtime validation,
    protected-invariant re-check, a genuinely fresh scan, finding and
    incident reconciliation, regression detection and rollback where
    required -- and returns the deterministic outcome. A successful mutation
    alone never produces `resolved`.
    """
    try:
        lifecycle = _runtime(hass).remediation_lifecycle
        result = await lifecycle.async_execute(
            msg["incident_id"],
            approved_plan=msg["plan"],
            approved_plan_identity=msg["plan_identity"],
            approved_by=f"home_assistant_user:{connection.user.id}",
            advisory=msg.get("advisory"),
        )
        connection.send_result(msg["id"], result.as_dict())
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/config_repair/reconcile_incident",
        vol.Required("incident_id"): str,
        vol.Required("plan"): dict,
        vol.Required("plan_identity"): vol.All(str, vol.Length(min=32, max=64)),
        vol.Optional("baseline_incident_ids"): list,
        vol.Optional("baseline_finding_ids"): list,
    }
)
@websocket_api.async_response
async def ws_reconcile_incident_repair(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Complete the resolution proof for a repair already applied.

    Never writes configuration, never backs up and never rolls back: it runs
    a fresh scan, finding reconciliation, regression detection against the
    recorded pre-repair baseline, and incident reconciliation, using exactly
    the helpers the execution path uses. Exists because execution and proof
    are separable in practice -- Home Assistant can restart between the
    write and the rescan.
    """
    try:
        lifecycle = _runtime(hass).remediation_lifecycle
        result = await lifecycle.async_reconcile(
            msg["incident_id"],
            plan=msg["plan"],
            plan_identity=msg["plan_identity"],
            actor=f"home_assistant_user:{connection.user.id}",
            baseline_incident_ids=tuple(msg.get("baseline_incident_ids") or ()),
            baseline_finding_ids=tuple(msg.get("baseline_finding_ids") or ()),
        )
        connection.send_result(msg["id"], result.as_dict())
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/config_repair/interrupted",
        vol.Optional("key", default=""): str,
    }
)
def ws_repair_interrupted(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Recovery classification for repairs interrupted by process loss.

    Read-only. HAMIE classifies every incomplete remediation baseline at
    startup -- re-hashing the real files rather than trusting the record --
    and this returns those verdicts. Resuming or rolling one back stays an
    explicit, separately approved operator action.
    """
    try:
        lifecycle = _runtime(hass).remediation_lifecycle
        key = msg.get("key") or ""
        if key:
            connection.send_result(msg["id"], lifecycle.recovery_record(key))
            return
        seen: dict[str, dict[str, Any]] = {}
        for record in lifecycle.recovery_records():
            seen[record["plan_identity"]] = record
        connection.send_result(
            msg["id"], {"items": list(seen.values()), "total": len(seen)}
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/config_repair/lifecycle_status",
        vol.Required("key"): str,
    }
)
def ws_repair_lifecycle_status(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Retrieve the last lifecycle run for a plan identity or incident id.

    Read-only. The durable record lives in HAMIE's own audit history
    (`hamie/audit/list` filtered by the plan identity as target); this
    returns the assembled in-memory view of the most recent run.
    """
    try:
        lifecycle = _runtime(hass).remediation_lifecycle
        record = lifecycle.record(msg["key"])
        connection.send_result(
            msg["id"], record.as_dict() if record is not None else None
        )
    except Exception as err:
        _error(connection, msg, err)


COMMANDS = (
    ws_configuration_get,
    ws_configuration_validate,
    ws_configuration_save,
    ws_configuration_test,
    ws_overview,
    ws_findings,
    ws_groups,
    ws_incidents,
    ws_incident,
    ws_incident_lifecycle,
    ws_dependencies,
    ws_group_preview,
    ws_group_apply,
    ws_group_suppress,
    ws_grouping_create,
    ws_suppression_preview,
    ws_suppression_create,
    ws_suppression_list,
    ws_suppression_update,
    ws_suppression_delete,
    ws_audit,
    ws_audit_export,
    ws_audit_clear,
    ws_recommendations,
    ws_security_findings,
    ws_connector_status,
    ws_scheduler_status,
    ws_updates_subscribe,
    ws_configuration_context,
    ws_configuration_frontend_error,
    ws_connector_test,
    ws_ai_providers_discover,
    ws_ai_providers_test,
    ws_ai_analyze,
    ws_ai_review,
    ws_remediation_investigate,
    ws_remediation_dry_run,
    ws_remediation_execute,
    ws_triage_incident,
    ws_incidents_reconcile,
    ws_ai_capability,
    ws_ai_capability_probe,
    ws_execute_incident_repair,
    ws_reconcile_incident_repair,
    ws_repair_lifecycle_status,
    ws_repair_interrupted,
)


def async_register_commands(hass: Any) -> None:
    """Register command schemas once for the single-entry integration."""
    if hass.data.get(API_REGISTERED):
        return
    for command in COMMANDS:
        websocket_api.async_register_command(hass, command)
    hass.data[API_REGISTERED] = True
