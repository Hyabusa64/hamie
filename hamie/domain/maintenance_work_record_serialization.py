"""JSON-safe encode/decode for ``MaintenanceWorkRecord``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .maintenance_work_record import MaintenanceWorkRecord, WorkItemLifecycleState


def _time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a timestamp string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError(f"{name} is not a valid timestamp") from err


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object with string keys")
    return value


def encode_maintenance_work_record(value: MaintenanceWorkRecord) -> dict[str, Any]:
    return {
        "work_item_id": value.work_item_id,
        "source_scan_id": value.source_scan_id,
        "source_group_key": value.source_group_key,
        "classification": value.classification,
        "lifecycle_state": value.lifecycle_state.value,
        "affected_entity_ids": list(value.affected_entity_ids),
        "entity_count": value.entity_count,
        "title": value.title,
        "reason": value.reason,
        "dependency_status": value.dependency_status,
        "missing_evidence": list(value.missing_evidence),
        "recommended_capability_id": value.recommended_capability_id,
        "risk": value.risk,
        "confidence": value.confidence,
        "created_at": _time(value.created_at),
        "updated_at": _time(value.updated_at),
        "evidence_fingerprint": value.evidence_fingerprint,
        "target_fingerprint": value.target_fingerprint,
        "ai_provenance": value.ai_provenance,
    }


def decode_maintenance_work_record(raw: object) -> MaintenanceWorkRecord:
    data = _mapping(raw, "maintenance_work_record")
    return MaintenanceWorkRecord(
        work_item_id=data["work_item_id"],
        source_scan_id=data["source_scan_id"],
        source_group_key=data["source_group_key"],
        classification=data["classification"],
        lifecycle_state=WorkItemLifecycleState(data["lifecycle_state"]),
        affected_entity_ids=tuple(data.get("affected_entity_ids", [])),
        entity_count=data["entity_count"],
        title=data["title"],
        reason=data["reason"],
        dependency_status=data["dependency_status"],
        missing_evidence=tuple(data.get("missing_evidence", [])),
        recommended_capability_id=data.get("recommended_capability_id"),
        risk=data["risk"],
        confidence=data["confidence"],
        created_at=_parse_time(data["created_at"], "created_at"),
        updated_at=_parse_time(data["updated_at"], "updated_at"),
        evidence_fingerprint=data["evidence_fingerprint"],
        target_fingerprint=data.get("target_fingerprint"),
        ai_provenance=data.get("ai_provenance"),
    )
