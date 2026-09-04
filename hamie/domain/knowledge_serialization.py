"""Explicit versioned JSON serialization for durable knowledge records."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from .findings import Confidence, ConfidenceFactor, ConfidenceLevel
from .implementation_groups import (
    ImplementationGroup,
    ImplementationGroupClassification,
    UnresolvedDecision,
)
from .knowledge_provenance import KnowledgeProvenance
from .serialization import decode_evidence, encode_evidence
from .successors import (
    EntitySuccessorRelationship,
    SuccessorRelationshipType,
    SuccessorStatus,
)

KNOWLEDGE_SERIALIZATION_VERSION = 1


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


def _sequence(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _enum[T: Enum](enum_type: type[T], value: object, name: str) -> T:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{name} has an unsupported value") from err


def _strings(value: object, name: str) -> tuple[str, ...]:
    sequence = _sequence(value, name)
    if not all(isinstance(item, str) for item in sequence):
        raise ValueError(f"{name} must contain strings")
    return tuple(sequence)


def _encode_confidence(value: Confidence) -> dict[str, Any]:
    return {
        "level": value.level.value,
        "rule_revision": value.rule_revision,
        "factors": [
            {"code": item.code, "effect": item.effect, "rationale": item.rationale}
            for item in value.factors
        ],
    }


def _decode_confidence(raw: object) -> Confidence:
    data = _mapping(raw, "confidence")
    factors = tuple(
        ConfidenceFactor(
            code=item["code"], effect=item["effect"], rationale=item["rationale"]
        )
        for item in (
            _mapping(raw_item, "confidence.factor")
            for raw_item in _sequence(data["factors"], "confidence.factors")
        )
    )
    return Confidence(
        level=_enum(ConfidenceLevel, data["level"], "confidence.level"),
        factors=factors,
        rule_revision=data["rule_revision"],
    )


def encode_entity_successor(value: EntitySuccessorRelationship) -> dict[str, Any]:
    """Encode a durable entity-successor relationship."""
    return {
        "relationship_id": value.relationship_id,
        "fingerprint": value.fingerprint,
        "stale_entity_id": value.stale_entity_id,
        "canonical_entity_id": value.canonical_entity_id,
        "relationship_type": value.relationship_type.value,
        "confidence": _encode_confidence(value.confidence),
        "evidence": [encode_evidence(item) for item in value.evidence],
        "first_observed": _time(value.first_observed),
        "last_verified": _time(value.last_verified),
        "provenance": value.provenance.value,
        "status": value.status.value,
        "reference_remediated": value.reference_remediated,
        "behavior_changed": value.behavior_changed,
        "source_artifact": value.source_artifact,
        "source_artifact_hash": value.source_artifact_hash,
        "superseded_by_fingerprint": value.superseded_by_fingerprint,
        "notes": value.notes,
    }


def decode_entity_successor(raw: object) -> EntitySuccessorRelationship:
    """Decode and validate a durable entity-successor relationship."""
    data = _mapping(raw, "entity_successor")
    return EntitySuccessorRelationship(
        stale_entity_id=data["stale_entity_id"],
        canonical_entity_id=data["canonical_entity_id"],
        relationship_type=_enum(
            SuccessorRelationshipType,
            data["relationship_type"],
            "entity_successor.relationship_type",
        ),
        confidence=_decode_confidence(data["confidence"]),
        evidence=tuple(
            decode_evidence(item)
            for item in _sequence(data["evidence"], "entity_successor.evidence")
        ),
        first_observed=_parse_time(
            data["first_observed"], "entity_successor.first_observed"
        ),
        last_verified=_parse_time(
            data["last_verified"], "entity_successor.last_verified"
        ),
        provenance=_enum(
            KnowledgeProvenance, data["provenance"], "entity_successor.provenance"
        ),
        status=_enum(SuccessorStatus, data["status"], "entity_successor.status"),
        reference_remediated=data.get("reference_remediated", False),
        behavior_changed=data.get("behavior_changed", False),
        source_artifact=data.get("source_artifact"),
        source_artifact_hash=data.get("source_artifact_hash"),
        superseded_by_fingerprint=data.get("superseded_by_fingerprint"),
        notes=data.get("notes", ""),
    )


def _encode_unresolved_decision(value: UnresolvedDecision | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "decision_type": value.decision_type,
        "question": value.question,
        "context": value.context,
    }


def _decode_unresolved_decision(raw: object) -> UnresolvedDecision | None:
    if raw is None:
        return None
    data = _mapping(raw, "unresolved_decision")
    return UnresolvedDecision(
        decision_type=data["decision_type"],
        question=data["question"],
        context=data["context"],
    )


def encode_implementation_group(value: ImplementationGroup) -> dict[str, Any]:
    """Encode a durable implementation group."""
    return {
        "group_record_id": value.group_record_id,
        "fingerprint": value.fingerprint,
        "group_id": value.group_id,
        "members": list(value.members),
        "classification": value.classification.value,
        "confidence": _encode_confidence(value.confidence),
        "evidence": [encode_evidence(item) for item in value.evidence],
        "first_observed": _time(value.first_observed),
        "last_verified": _time(value.last_verified),
        "provenance": value.provenance.value,
        "unresolved_decision": _encode_unresolved_decision(value.unresolved_decision),
        "automatic_cleanup_allowed": value.automatic_cleanup_allowed,
        "source_artifact": value.source_artifact,
        "notes": value.notes,
    }


def decode_implementation_group(raw: object) -> ImplementationGroup:
    """Decode and validate a durable implementation group."""
    data = _mapping(raw, "implementation_group")
    return ImplementationGroup(
        group_id=data["group_id"],
        members=_strings(data["members"], "implementation_group.members"),
        classification=_enum(
            ImplementationGroupClassification,
            data["classification"],
            "implementation_group.classification",
        ),
        confidence=_decode_confidence(data["confidence"]),
        evidence=tuple(
            decode_evidence(item)
            for item in _sequence(data["evidence"], "implementation_group.evidence")
        ),
        first_observed=_parse_time(
            data["first_observed"], "implementation_group.first_observed"
        ),
        last_verified=_parse_time(
            data["last_verified"], "implementation_group.last_verified"
        ),
        provenance=_enum(
            KnowledgeProvenance,
            data["provenance"],
            "implementation_group.provenance",
        ),
        unresolved_decision=_decode_unresolved_decision(
            data.get("unresolved_decision")
        ),
        # Never decoded as True regardless of a stored value -- see
        # ImplementationGroup.__post_init__, which rejects True
        # unconditionally. A tampered/corrupt document claiming True
        # fails loudly at construction rather than silently granting
        # cleanup authority.
        automatic_cleanup_allowed=data.get("automatic_cleanup_allowed", False),
        source_artifact=data.get("source_artifact"),
        notes=data.get("notes", ""),
    )
