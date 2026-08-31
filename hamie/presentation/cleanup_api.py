"""Admin-authorized bounded WebSocket API for the cleanup orchestrator.

Thin presentation-layer adapter only, matching
``presentation/remediation_api.py``'s and
``presentation/ai_control_api.py``'s own discipline: this command
validates a bounded request shape, calls the one canonical
``application/cleanup_coordinator.py`` pipeline, and translates the
result. It never re-implements classification, dependency scanning, or
execution -- there is no second cleanup pipeline here.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api

from ..application import cleanup_coordinator
from ..connectors.base import now_utc
from ..const import DOMAIN
from ..domain.maintenance_work_record import MaintenanceDecision
from ..domain.maintenance_work_record_serialization import (
    encode_maintenance_work_record,
)
from .api import _config_entry

CLEANUP_API_REGISTERED = "hamie.cleanup_websocket_api_registered"
_LOGGER = logging.getLogger(__name__)


def _runtime(hass: Any) -> Any:
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise RuntimeError("HAMIE is not loaded")
    return next(iter(entries.values()))


def _actor(connection: Any) -> str:
    return f"home_assistant_user:{connection.user.id}"


def _batch_dict(batch: cleanup_coordinator.CleanupBatchOutcome) -> dict[str, Any]:
    plan = batch.plan
    return {
        "batch_label": batch.batch_label,
        "entity_count": len(batch.entity_ids),
        "entity_ids": list(batch.entity_ids),
        "remediation_plan_id": plan.remediation_plan_id if plan is not None else None,
        "plan_state": plan.state.value if plan is not None else None,
        "auto_executed": batch.auto_executed,
        "execution_succeeded": batch.execution_succeeded,
        "error": batch.error,
    }


def _work_item_dict(item: Any) -> dict[str, Any]:
    return {
        "group_key": item.group_key,
        "classification": item.classification.value,
        "reason_code": item.reason_code,
        "entity_count": item.entity_count,
        "sample_entity_ids": list(item.sample_entity_ids),
        "reason": item.reason,
        "next_action_id": item.next_action_id,
        "next_action_label": item.next_action_label,
        "device_id": item.device_id,
        "integration": item.integration,
    }


def _summary_dict(summary: cleanup_coordinator.CleanupSummary) -> dict[str, Any]:
    return {
        "total_findings_considered": summary.total_findings_considered,
        "classification_counts": dict(summary.classification_counts),
        "non_actionable_reason_counts": dict(summary.non_actionable_reason_counts),
        "maintenance_work_items": [
            _work_item_dict(item) for item in summary.maintenance_work_items
        ],
        "persisted_maintenance_work_items": [
            encode_maintenance_work_record(item)
            for item in summary.persisted_maintenance_work_items
        ],
        "safe_auto_fix_count": len(summary.safe_auto_fix_entity_ids),
        "safe_with_approval_count": len(summary.safe_with_approval_entity_ids),
        "actionable_candidate_count": summary.actionable_candidate_count,
        "entities_auto_disabled": summary.entities_auto_disabled,
        "configured_ai_mode": summary.configured_ai_mode,
        "effective_ai_mode": summary.effective_ai_mode,
        "dependency_scanned_sources": list(summary.dependency_scanned_sources),
        "dependency_unscanned_sources": list(summary.dependency_unscanned_sources),
        "batches": [_batch_dict(item) for item in summary.batches],
    }


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "hamie/cleanup/run"})
@websocket_api.async_response
async def ws_cleanup_run(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Run the complete cleanup pipeline once and return its summary.

    The single "Clean Up" entry point: obtains current findings,
    classifies every candidate, builds dependency evidence, proposes
    batch cleanup into Review Queue, and -- according to the configured
    AI operating mode -- may auto-execute eligible low-risk batches.
    Never raises for an ordinary per-batch outcome; each batch's own
    result (including any failure) is reported in the response.
    """
    try:
        runtime = _runtime(hass)
        options = dict(_config_entry(hass).options)
        summary = await cleanup_coordinator.async_run_cleanup(
            runtime.repository,
            hass,
            options=options,
            now=now_utc(),
            actor=_actor(connection),
        )
        connection.send_result(msg["id"], _summary_dict(summary))
    except Exception as err:
        _LOGGER.error("HAMIE cleanup run failed: error_type=%s", type(err).__name__)
        connection.send_error(
            msg["id"],
            "cleanup_internal_error",
            "An unexpected error occurred while running cleanup.",
        )


def _gather_evidence_dict(
    result: cleanup_coordinator.GatherEvidenceResult,
) -> dict[str, Any]:
    return {
        "request_id": result.request_id,
        "work_item_id": result.work_item_id,
        "started_at": result.started_at.isoformat(),
        "completed_at": result.completed_at.isoformat(),
        "previous_lifecycle_state": result.previous_lifecycle_state,
        "resolved": result.resolved,
        "new_lifecycle_state": result.new_lifecycle_state,
        "new_classification": result.new_classification,
        "still_missing": list(result.still_missing),
        "created_plan_id": result.created_plan_id,
        "collector_statuses": dict(result.collector_statuses),
    }


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/remediation/gather_evidence",
        vol.Required("work_item_id"): vol.All(str, vol.Length(min=1, max=64)),
    }
)
@websocket_api.async_response
async def ws_gather_evidence(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Re-check one durable maintenance work item's missing evidence.

    Idempotent and scoped: re-runs the same canonical classify/
    dependency/persist pipeline ``hamie/cleanup/run`` uses (proven to
    upsert rather than duplicate on unchanged evidence), then reports
    exactly what happened to the one item the caller asked about --
    resolved, reclassified, or still genuinely blocked with the exact
    missing evidence named. Never a full-house rescan; HAMIE's own
    dependency collectors are already bounded and fast.
    """
    try:
        runtime = _runtime(hass)
        options = dict(_config_entry(hass).options)
        result = await cleanup_coordinator.async_gather_evidence(
            runtime.repository,
            hass,
            work_item_id=msg["work_item_id"],
            options=options,
            now=now_utc(),
            actor=_actor(connection),
        )
        connection.send_result(msg["id"], _gather_evidence_dict(result))
    except cleanup_coordinator.GatherEvidenceError as err:
        connection.send_error(msg["id"], err.code, err.message)
    except Exception as err:
        _LOGGER.error("HAMIE gather evidence failed: error_type=%s", type(err).__name__)
        connection.send_error(
            msg["id"],
            "cleanup_internal_error",
            "An unexpected error occurred while gathering evidence.",
        )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/maintenance/decide",
        vol.Required("work_item_id"): vol.All(str, vol.Length(min=1, max=64)),
        vol.Required("decision"): vol.In({"keep", "unsure"}),
    }
)
@websocket_api.async_response
async def ws_maintenance_decide(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Record an explicit user Keep/Unsure decision for one durable
    maintenance work item.

    Keep persists as a user-managed lifecycle state (see
    domain/maintenance_work_record.py's USER_MANAGED_STATES) -- a future
    Clean Up pass will never silently re-surface the same unchanged
    object as a new candidate. Unsure marks it for re-investigation; a
    future Clean Up pass or Gather Evidence may resolve it once new
    evidence arrives. This never mutates Home Assistant itself -- it only
    records a review decision.
    """
    try:
        runtime = _runtime(hass)
        record = await cleanup_coordinator.async_decide_maintenance_work(
            runtime.repository,
            work_item_id=msg["work_item_id"],
            decision=MaintenanceDecision(msg["decision"]),
            now=now_utc(),
        )
        if runtime.operations is not None:
            await runtime.operations.async_record_audit(
                f"maintenance_work_{msg['decision']}",
                actor=_actor(connection),
                target_ids=(msg["work_item_id"],),
            )
        connection.send_result(msg["id"], encode_maintenance_work_record(record))
    except cleanup_coordinator.MaintenanceDecisionError as err:
        connection.send_error(
            msg["id"], err.code, "That maintenance work item could not be found."
        )
    except Exception as err:
        _LOGGER.error(
            "HAMIE maintenance decide failed: error_type=%s", type(err).__name__
        )
        connection.send_error(
            msg["id"],
            "cleanup_internal_error",
            "That decision could not be recorded.",
        )


COMMANDS = (ws_cleanup_run, ws_gather_evidence, ws_maintenance_decide)


def async_register_commands(hass: Any) -> None:
    """Register the cleanup command schema once per HA instance."""
    if hass.data.get(CLEANUP_API_REGISTERED):
        return
    for command in COMMANDS:
        websocket_api.async_register_command(hass, command)
    hass.data[CLEANUP_API_REGISTERED] = True
