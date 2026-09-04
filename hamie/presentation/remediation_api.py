"""Admin-authorized bounded WebSocket API for the Phase 2B remediation engine.

This module is a thin presentation-layer adapter only. It never
reimplements planning, preview, approval, locking, precondition
verification, execution, rollback, or serialization -- every command
here does nothing but validate a bounded request shape, call one
function in ``application/remediation/service.py``, and translate the
typed result into a JSON-safe response using the existing
``domain/*_serialization.py`` encoders.

Every command is ``@websocket_api.require_admin`` -- there is no path
by which a non-admin user can list, approve, reject, revoke, or
execute a remediation. No command accepts an adapter identifier, raw
execution steps, or a fabricated approval; the server always re-derives
these from persisted state (see ``service.py``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api

from ..application.remediation import service
from ..connectors.base import now_utc
from ..const import DOMAIN
from ..domain.maintenance_work_record_serialization import (
    encode_maintenance_work_record,
)
from ..domain.recommendation_serialization import encode_canonical_recommendation
from ..domain.remediation_serialization import (
    encode_approval,
    encode_execution_record,
    encode_remediation_plan,
    encode_rollback_record,
)

REMEDIATION_API_REGISTERED = "hamie.remediation_websocket_api_registered"
_LOGGER = logging.getLogger(__name__)

MAX_ID_LENGTH = 128
MAX_TOKEN_LENGTH = 200
MIN_TOKEN_LENGTH = 8
MAX_REASON_LENGTH = 500
MAX_WARNINGS_ACKNOWLEDGED = 20
MAX_WARNING_LENGTH = 200

QUEUE_STATUSES = frozenset(
    {
        "needs_review",
        "approved",
        "blocked",
        "executing",
        "verified",
        "failed",
        "rolled_back",
        "rollback_failed",
        "rejected",
        "snoozed",
    }
)

_ID = vol.All(str, vol.Length(min=1, max=MAX_ID_LENGTH))
_TOKEN = vol.All(str, vol.Length(min=MIN_TOKEN_LENGTH, max=MAX_TOKEN_LENGTH))
_REASON = vol.All(str, vol.Length(min=1, max=MAX_REASON_LENGTH))


def _runtime(hass: Any) -> Any:
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise RuntimeError("HAMIE is not loaded")
    return next(iter(entries.values()))


def _actor(connection: Any) -> str:
    return f"home_assistant_user:{connection.user.id}"


def _remediation_error(connection: Any, msg: dict[str, Any], err: Exception) -> None:
    """Send a stable, non-sensitive error. Never leaks a traceback."""
    if isinstance(err, service.RemediationServiceError):
        connection.send_error(msg["id"], err.code, err.message)
        return
    _LOGGER.error(
        "HAMIE remediation operation failed: error_type=%s", type(err).__name__
    )
    connection.send_error(
        msg["id"],
        "remediation_internal_error",
        "An unexpected error occurred while processing the remediation request.",
    )


def _queue_item_dict(item: service.QueueItem) -> dict[str, Any]:
    return {
        "recommendation_id": item.recommendation_id,
        "title": item.title,
        "category": item.category,
        "subtype": item.subtype,
        "action_type": item.action_type,
        "execution_supported": item.execution_supported,
        "unsupported_reason": item.unsupported_reason,
        "confidence": item.confidence,
        "risk_level": item.risk_level,
        "affected_object": item.affected_object,
        "dependency_status": item.dependency_status,
        "estimated_impact": item.estimated_impact,
        "status": item.status,
        "section": item.section,
        "plan_id": item.plan_id,
        "plan_fingerprint": item.plan_fingerprint,
        "snooze_until": (item.snooze_until.isoformat() if item.snooze_until else None),
        "snooze_reason": item.snooze_reason,
        "updated_at": item.updated_at.isoformat(),
    }


def _detail_dict(detail: service.DetailResult) -> dict[str, Any]:
    return {
        "recommendation": encode_canonical_recommendation(detail.recommendation),
        "plan": encode_remediation_plan(detail.plan) if detail.plan else None,
        "approval": encode_approval(detail.approval) if detail.approval else None,
        "executions": [encode_execution_record(item) for item in detail.executions],
        "rollbacks": [encode_rollback_record(item) for item in detail.rollbacks],
        "status": detail.status,
    }


def _preview_dict(preview: service.PreviewRunResult) -> dict[str, Any]:
    return {
        "remediation_plan_id": preview.remediation_plan_id,
        "plan_fingerprint": preview.plan_fingerprint,
        "preview_digest": preview.preview_digest,
        "steps": [
            {
                "step_index": step.step_index,
                "action_type": step.action_type,
                "adapter_id": step.adapter_id,
                "rendered_before": step.rendered_before,
                "rendered_after": step.rendered_after,
                "warnings": list(step.warnings),
            }
            for step in preview.steps
        ],
    }


def _execution_status_dict(result: service.ExecutionStatusResult) -> dict[str, Any]:
    return {
        "executions": [encode_execution_record(item) for item in result.executions],
        "rollbacks": [encode_rollback_record(item) for item in result.rollbacks],
    }


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/queue/list",
        vol.Optional("category"): vol.All(str, vol.Length(max=MAX_ID_LENGTH)),
        vol.Optional("status"): vol.In(QUEUE_STATUSES),
        vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0)),
        vol.Optional("limit", default=50): vol.All(int, vol.Range(min=1, max=200)),
    }
)
@websocket_api.async_response
async def ws_remediation_queue_list(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """List review-queue rows. Read-only."""
    try:
        result = await service.async_list_queue(
            _runtime(hass).repository,
            category=msg.get("category"),
            status=msg.get("status"),
            offset=msg["offset"],
            limit=msg["limit"],
            now=now_utc(),
        )
        connection.send_result(
            msg["id"],
            {
                "items": [_queue_item_dict(item) for item in result.items],
                "total": result.total,
                "offset": result.offset,
                "limit": result.limit,
                "section_counts": dict(result.section_counts),
                "maintenance_work_items": [
                    encode_maintenance_work_record(item)
                    for item in result.maintenance_work_items
                ],
                "last_cleanup_scan_id": result.last_cleanup_scan_id,
            },
        )
    except Exception as err:
        _remediation_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/detail/get",
        vol.Required("recommendation_id"): _ID,
    }
)
@websocket_api.async_response
async def ws_remediation_detail_get(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Return full detail for one recommendation. Read-only."""
    try:
        detail = await service.async_get_detail(
            _runtime(hass).repository, msg["recommendation_id"], now=now_utc()
        )
        connection.send_result(msg["id"], _detail_dict(detail))
    except Exception as err:
        _remediation_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/plan/create",
        vol.Required("recommendation_id"): _ID,
        vol.Required("idempotency_token"): _TOKEN,
    }
)
@websocket_api.async_response
async def ws_remediation_plan_create(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Create or refresh a deterministic plan. Never executes anything."""
    try:
        plan = await service.async_create_plan(
            _runtime(hass).repository,
            msg["recommendation_id"],
            actor=_actor(connection),
            idempotency_token=msg["idempotency_token"],
            now=now_utc(),
        )
        connection.send_result(msg["id"], encode_remediation_plan(plan))
    except Exception as err:
        _remediation_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/preview/generate",
        vol.Required("remediation_plan_id"): _ID,
        vol.Required("idempotency_token"): _TOKEN,
    }
)
@websocket_api.async_response
async def ws_remediation_preview_generate(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Render a plan's preview. Never mutates Home Assistant."""
    try:
        preview = await service.async_generate_preview(
            _runtime(hass).repository,
            msg["remediation_plan_id"],
            actor=_actor(connection),
            idempotency_token=msg["idempotency_token"],
            now=now_utc(),
            hass=hass,
        )
        connection.send_result(msg["id"], _preview_dict(preview))
    except Exception as err:
        _remediation_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/snooze",
        vol.Required("remediation_plan_id"): _ID,
        vol.Exclusive("duration_minutes", "snooze_time"): vol.All(
            int, vol.Range(min=15, max=43_200)
        ),
        vol.Exclusive("snooze_until", "snooze_time"): vol.All(
            str, vol.Length(min=10, max=64)
        ),
        vol.Optional("reason"): vol.All(str, vol.Length(max=MAX_REASON_LENGTH)),
        vol.Required("idempotency_token"): _TOKEN,
    }
)
@websocket_api.async_response
async def ws_remediation_snooze(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Snooze one reviewable proposal without approving or executing it."""
    try:
        now = now_utc()
        if "duration_minutes" in msg:
            snooze_until = now + timedelta(minutes=msg["duration_minutes"])
        elif "snooze_until" in msg:
            try:
                snooze_until = datetime.fromisoformat(
                    msg["snooze_until"].replace("Z", "+00:00")
                )
                if snooze_until.utcoffset() is None:
                    raise ValueError("timezone required")
            except ValueError as err:
                raise service.RemediationServiceError(
                    "remediation_snooze_invalid", "The Snooze time is invalid."
                ) from err
        else:
            raise service.RemediationServiceError(
                "remediation_snooze_invalid", "Choose a Snooze duration."
            )
        plan = await service.async_snooze_plan(
            _runtime(hass).repository,
            msg["remediation_plan_id"],
            actor=_actor(connection),
            snooze_until=snooze_until,
            reason=msg.get("reason") or None,
            idempotency_token=msg["idempotency_token"],
            now=now,
        )
        connection.send_result(msg["id"], encode_remediation_plan(plan))
    except Exception as err:
        _remediation_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/resume",
        vol.Required("remediation_plan_id"): _ID,
        vol.Required("idempotency_token"): _TOKEN,
    }
)
@websocket_api.async_response
async def ws_remediation_resume(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Resume one snoozed proposal without restoring approval."""
    try:
        plan = await service.async_resume_plan(
            _runtime(hass).repository,
            msg["remediation_plan_id"],
            actor=_actor(connection),
            idempotency_token=msg["idempotency_token"],
            now=now_utc(),
        )
        connection.send_result(msg["id"], encode_remediation_plan(plan))
    except Exception as err:
        _remediation_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/approve",
        vol.Required("remediation_plan_id"): _ID,
        vol.Required("plan_fingerprint"): _ID,
        vol.Required("preview_digest"): _ID,
        vol.Required("destructive_acknowledged"): bool,
        vol.Required("backup_acknowledged"): bool,
        vol.Optional("warnings_acknowledged", default=[]): vol.All(
            [vol.All(str, vol.Length(max=MAX_WARNING_LENGTH))],
            vol.Length(max=MAX_WARNINGS_ACKNOWLEDGED),
        ),
        vol.Required("idempotency_token"): _TOKEN,
    }
)
@websocket_api.async_response
async def ws_remediation_approve(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Grant approval bound to the exact plan fingerprint and preview digest."""
    try:
        approval = await service.async_approve_plan(
            _runtime(hass).repository,
            msg["remediation_plan_id"],
            plan_fingerprint=msg["plan_fingerprint"],
            preview_digest=msg["preview_digest"],
            actor=_actor(connection),
            destructive_acknowledged=msg["destructive_acknowledged"],
            backup_acknowledged=msg["backup_acknowledged"],
            warnings_acknowledged=tuple(msg["warnings_acknowledged"]),
            idempotency_token=msg["idempotency_token"],
            now=now_utc(),
            hass=hass,
        )
        connection.send_result(msg["id"], encode_approval(approval))
    except Exception as err:
        _remediation_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/reject",
        vol.Required("remediation_plan_id"): _ID,
        vol.Required("reason"): _REASON,
        vol.Required("idempotency_token"): _TOKEN,
    }
)
@websocket_api.async_response
async def ws_remediation_reject(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Record an explicit rejection. Never deletes historical evidence."""
    try:
        approval = await service.async_reject_plan(
            _runtime(hass).repository,
            msg["remediation_plan_id"],
            actor=_actor(connection),
            reason=msg["reason"],
            idempotency_token=msg["idempotency_token"],
            now=now_utc(),
        )
        connection.send_result(msg["id"], encode_approval(approval))
    except Exception as err:
        _remediation_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/revoke",
        vol.Required("approval_id"): _ID,
        vol.Required("reason"): _REASON,
        vol.Required("idempotency_token"): _TOKEN,
    }
)
@websocket_api.async_response
async def ws_remediation_revoke(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Revoke a previously granted approval. Preserves original evidence."""
    try:
        approval = await service.async_revoke_approval(
            _runtime(hass).repository,
            msg["approval_id"],
            actor=_actor(connection),
            reason=msg["reason"],
            idempotency_token=msg["idempotency_token"],
            now=now_utc(),
        )
        connection.send_result(msg["id"], encode_approval(approval))
    except Exception as err:
        _remediation_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/execute",
        vol.Required("remediation_plan_id"): _ID,
        vol.Required("approval_id"): _ID,
        vol.Required("idempotency_token"): _TOKEN,
        vol.Required("confirmed"): vol.Equal(True),
    }
)
@websocket_api.async_response
async def ws_remediation_execute(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Execute one approved plan through the canonical coordinator only."""
    try:
        execution = await service.async_execute_plan(
            _runtime(hass).repository,
            msg["remediation_plan_id"],
            approval_id=msg["approval_id"],
            actor=_actor(connection),
            idempotency_token=msg["idempotency_token"],
            now=now_utc(),
            hass=hass,
        )
        connection.send_result(msg["id"], encode_execution_record(execution))
    except Exception as err:
        _remediation_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/rollback",
        vol.Required("remediation_plan_id"): _ID,
        vol.Required("execution_id"): _ID,
        vol.Required("idempotency_token"): _TOKEN,
        vol.Required("confirmed"): vol.Equal(True),
    }
)
@websocket_api.async_response
async def ws_remediation_rollback(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Rollback one verified repair through its immutable rollback payload."""
    try:
        rollback = await service.async_rollback_execution(
            _runtime(hass).repository,
            msg["remediation_plan_id"],
            execution_id=msg["execution_id"],
            actor=_actor(connection),
            idempotency_token=msg["idempotency_token"],
            now=now_utc(),
            hass=hass,
        )
        connection.send_result(msg["id"], encode_rollback_record(rollback))
    except Exception as err:
        _remediation_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/execution/status",
        vol.Required("remediation_plan_id"): _ID,
    }
)
@websocket_api.async_response
async def ws_remediation_execution_status(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Return persisted execution/rollback evidence. Read-only."""
    try:
        result = await service.async_get_execution_status(
            _runtime(hass).repository,
            msg["remediation_plan_id"],
        )
        connection.send_result(msg["id"], _execution_status_dict(result))
    except Exception as err:
        _remediation_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "hamie/remediation/capabilities"}
)
def ws_remediation_capabilities(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Return a static, read-only capability summary."""
    try:
        connection.send_result(msg["id"], service.get_capabilities())
    except Exception as err:
        _remediation_error(connection, msg, err)


COMMANDS = (
    ws_remediation_queue_list,
    ws_remediation_detail_get,
    ws_remediation_plan_create,
    ws_remediation_preview_generate,
    ws_remediation_snooze,
    ws_remediation_resume,
    ws_remediation_approve,
    ws_remediation_reject,
    ws_remediation_revoke,
    ws_remediation_execute,
    ws_remediation_rollback,
    ws_remediation_execution_status,
    ws_remediation_capabilities,
)


def async_register_commands(hass: Any) -> None:
    """Register the remediation command schemas once per HA instance."""
    if hass.data.get(REMEDIATION_API_REGISTERED):
        return
    for command in COMMANDS:
        websocket_api.async_register_command(hass, command)
    hass.data[REMEDIATION_API_REGISTERED] = True
