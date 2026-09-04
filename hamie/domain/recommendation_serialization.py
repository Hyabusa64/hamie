"""Explicit versioned JSON serialization for canonical recommendations.

Mirrors ``domain/serialization.py``'s conventions exactly (the same
``_mapping``/``_sequence``/``_strings``/``_enum``/``_time``/``_parse_time``
shape, duplicated locally rather than importing that module's private
helpers, to avoid coupling this new, additive module to another file's
internal implementation details).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from .findings import Confidence, ConfidenceFactor, ConfidenceLevel, Risk, RiskLevel
from .llm_proposal import LlmProposedAction
from .recommendation import (
    CanonicalRecommendation,
    DependencyAnalysisResult,
    DependencyAnalysisStatus,
    DependencySourceCheckStatus,
    DependencySourceResult,
    ProvenanceSource,
    RecommendationDisposition,
    RecommendationEvidence,
    RecommendationLifecycleState,
    RecommendationReviewState,
    RecommendationRisk,
    SupportingObjectDirection,
    SupportingObjectReference,
)
from .serialization import decode_subject, encode_subject

RECOMMENDATION_SERIALIZATION_VERSION = 1


def _time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def encode_llm_proposed_action(
    value: LlmProposedAction | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "resource_id": value.resource_id,
        "action_type": value.action_type,
        "operation": dict(value.operation),
        "evidence_ids": list(value.evidence_ids),
        "reason": value.reason,
    }


def decode_llm_proposed_action(raw: object) -> LlmProposedAction | None:
    if raw is None:
        return None
    data = _mapping(raw, "llm_proposed_action")
    return LlmProposedAction(
        resource_id=data["resource_id"],
        action_type=data["action_type"],
        operation=tuple(dict(data["operation"]).items()),
        evidence_ids=tuple(data["evidence_ids"]),
        reason=data["reason"],
    )


def _optional_time(value: datetime | None) -> str | None:
    return _time(value) if value is not None else None


def _parse_time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a timestamp string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError(f"{name} is not a valid timestamp") from err


def _parse_optional_time(value: object, name: str) -> datetime | None:
    return _parse_time(value, name) if value is not None else None


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


def _scalar(value: object, name: str) -> Any:
    if value is not None and not isinstance(value, str | int | float | bool):
        raise ValueError(f"{name} must be a JSON scalar")
    return value


def encode_recommendation_evidence(value: RecommendationEvidence) -> dict[str, Any]:
    return {
        "evidence_type": value.evidence_type,
        "provenance": value.provenance.value,
        "source": value.source,
        "observed_value": value.observed_value,
        "expected_value": value.expected_value,
        "observed_at": _time(value.observed_at),
        "collection_method": value.collection_method,
        "explanation": value.explanation,
        "source_object": (
            encode_subject(value.source_object) if value.source_object else None
        ),
        "confidence": value.confidence,
    }


def decode_recommendation_evidence(raw: object) -> RecommendationEvidence:
    data = _mapping(raw, "recommendation_evidence")
    return RecommendationEvidence(
        evidence_type=data["evidence_type"],
        provenance=_enum(ProvenanceSource, data["provenance"], "evidence.provenance"),
        source=data["source"],
        observed_value=_scalar(data.get("observed_value"), "evidence.observed_value"),
        expected_value=_scalar(data.get("expected_value"), "evidence.expected_value"),
        observed_at=_parse_time(data["observed_at"], "evidence.observed_at"),
        collection_method=data["collection_method"],
        explanation=data["explanation"],
        source_object=(
            decode_subject(data["source_object"])
            if data.get("source_object") is not None
            else None
        ),
        confidence=data.get("confidence", "medium"),
    )


def encode_supporting_object(value: SupportingObjectReference) -> dict[str, Any]:
    return {
        "subject": encode_subject(value.subject),
        "relationship_type": value.relationship_type,
        "direction": value.direction.value,
        "confidence": value.confidence,
        "evidence_source": value.evidence_source,
    }


def decode_supporting_object(raw: object) -> SupportingObjectReference:
    data = _mapping(raw, "supporting_object")
    return SupportingObjectReference(
        subject=decode_subject(data["subject"]),
        relationship_type=data["relationship_type"],
        direction=_enum(
            SupportingObjectDirection, data["direction"], "supporting_object.direction"
        ),
        confidence=data.get("confidence", "medium"),
        evidence_source=data.get("evidence_source", ""),
    )


def encode_dependency_source_result(value: DependencySourceResult) -> dict[str, Any]:
    return {
        "source": value.source,
        "method": value.method,
        "status": value.status.value,
        "checked_at": _time(value.checked_at),
        "references_found": list(value.references_found),
        "unresolved_references": list(value.unresolved_references),
        "confidence": value.confidence,
        "error": value.error,
    }


def decode_dependency_source_result(raw: object) -> DependencySourceResult:
    data = _mapping(raw, "dependency_source_result")
    return DependencySourceResult(
        source=data["source"],
        method=data["method"],
        status=_enum(
            DependencySourceCheckStatus, data["status"], "dependency_source.status"
        ),
        checked_at=_parse_time(data["checked_at"], "dependency_source.checked_at"),
        references_found=_strings(data.get("references_found", []), "references_found"),
        unresolved_references=_strings(
            data.get("unresolved_references", []), "unresolved_references"
        ),
        confidence=data.get("confidence", "medium"),
        error=data.get("error"),
    )


def encode_dependency_analysis(value: DependencyAnalysisResult) -> dict[str, Any]:
    return {
        "status": value.status.value,
        "sources": [encode_dependency_source_result(item) for item in value.sources],
        "inbound_references": list(value.inbound_references),
        "outbound_references": list(value.outbound_references),
        "potential_breakages": list(value.potential_breakages),
        "repair_alternatives": list(value.repair_alternatives),
        "unknown_dependencies": list(value.unknown_dependencies),
        "analyzed_at": _optional_time(value.analyzed_at),
        "confidence": value.confidence,
        "safe_to_delete": value.safe_to_delete,
    }


def decode_dependency_analysis(raw: object) -> DependencyAnalysisResult:
    data = _mapping(raw, "dependency_analysis")
    return DependencyAnalysisResult(
        status=_enum(
            DependencyAnalysisStatus, data["status"], "dependency_analysis.status"
        ),
        sources=tuple(
            decode_dependency_source_result(item)
            for item in _sequence(
                data.get("sources", []), "dependency_analysis.sources"
            )
        ),
        inbound_references=_strings(
            data.get("inbound_references", []), "inbound_references"
        ),
        outbound_references=_strings(
            data.get("outbound_references", []), "outbound_references"
        ),
        potential_breakages=_strings(
            data.get("potential_breakages", []), "potential_breakages"
        ),
        repair_alternatives=_strings(
            data.get("repair_alternatives", []), "repair_alternatives"
        ),
        unknown_dependencies=_strings(
            data.get("unknown_dependencies", []), "unknown_dependencies"
        ),
        analyzed_at=_parse_optional_time(
            data.get("analyzed_at"), "dependency_analysis.analyzed_at"
        ),
        confidence=data.get("confidence", "low"),
        safe_to_delete=data.get("safe_to_delete", False),
    )


def _encode_risk(value: Risk) -> dict[str, Any]:
    return {
        "likelihood": value.likelihood.value,
        "impact": value.impact.value,
        "reversible": value.reversible,
        "affected_scope": value.affected_scope,
        "overall": value.overall.value,
        "rationale": value.rationale,
    }


def _decode_risk(raw: object) -> Risk:
    data = _mapping(raw, "risk")
    return Risk(
        likelihood=_enum(RiskLevel, data["likelihood"], "risk.likelihood"),
        impact=_enum(RiskLevel, data["impact"], "risk.impact"),
        reversible=data["reversible"],
        affected_scope=data["affected_scope"],
        overall=_enum(RiskLevel, data["overall"], "risk.overall"),
        rationale=data["rationale"],
    )


def encode_recommendation_risk(value: RecommendationRisk) -> dict[str, Any]:
    return {
        "risk": _encode_risk(value.risk),
        "estimated_operational_impact": value.estimated_operational_impact,
        "estimated_user_visible_impact": value.estimated_user_visible_impact,
        "estimated_benefit": value.estimated_benefit,
        "affected_capabilities": list(value.affected_capabilities),
        "rollback_available": value.rollback_available,
        "rollback_description": value.rollback_description,
        "rollback_limitations": list(value.rollback_limitations),
    }


def decode_recommendation_risk(raw: object) -> RecommendationRisk:
    data = _mapping(raw, "recommendation_risk")
    return RecommendationRisk(
        risk=_decode_risk(data["risk"]),
        estimated_operational_impact=data["estimated_operational_impact"],
        estimated_user_visible_impact=data["estimated_user_visible_impact"],
        estimated_benefit=data.get("estimated_benefit"),
        affected_capabilities=_strings(
            data.get("affected_capabilities", []), "affected_capabilities"
        ),
        rollback_available=data.get("rollback_available", False),
        rollback_description=data.get("rollback_description"),
        rollback_limitations=_strings(
            data.get("rollback_limitations", []), "rollback_limitations"
        ),
    )


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


def encode_canonical_recommendation(value: CanonicalRecommendation) -> dict[str, Any]:
    """Encode one canonical recommendation for durable storage."""
    return {
        "recommendation_id": value.recommendation_id,
        "fingerprint": value.fingerprint,
        "fingerprint_version": value.fingerprint_version,
        "schema_version": value.schema_version,
        "detector_id": value.detector_id,
        "category": value.category,
        "subtype": value.subtype,
        "title": value.title,
        "summary": value.summary,
        "detailed_explanation": value.detailed_explanation,
        "installation_id": value.installation_id,
        "affected_object": encode_subject(value.affected_object),
        "evidence": [encode_recommendation_evidence(item) for item in value.evidence],
        "supporting_objects": [
            encode_supporting_object(item) for item in value.supporting_objects
        ],
        "dependency_analysis": encode_dependency_analysis(value.dependency_analysis),
        "risk": encode_recommendation_risk(value.risk),
        "confidence": _encode_confidence(value.confidence),
        "disposition": value.disposition.value,
        "suggested_action": value.suggested_action,
        "alternatives": list(value.alternatives),
        "prerequisites": list(value.prerequisites),
        "validation_requirements": list(value.validation_requirements),
        "backup_required": value.backup_required,
        "execution_supported": value.execution_supported,
        "execution_action_type": value.execution_action_type,
        "llm_proposed_action": encode_llm_proposed_action(value.llm_proposed_action),
        "generated_by": value.generated_by.value,
        "first_seen_at": _time(value.first_seen_at),
        "last_seen_at": _time(value.last_seen_at),
        "last_scan_id": value.last_scan_id,
        "content_revision": value.content_revision,
        "content_digest": value.content_digest,
        "lifecycle_state": value.lifecycle_state.value,
        "review_state": value.review_state.value,
        "created_at": _time(value.created_at),
        "updated_at": _time(value.updated_at),
        "occurrence_count": value.occurrence_count,
        "recurrence_count": value.recurrence_count,
        "resolved_at": _optional_time(value.resolved_at),
        "resolution_reason": value.resolution_reason,
        "snoozed_until": _optional_time(value.snoozed_until),
        "dismissed_at": _optional_time(value.dismissed_at),
        "dismissal_reason": value.dismissal_reason,
        "superseded_by": value.superseded_by,
    }


def decode_canonical_recommendation(raw: object) -> CanonicalRecommendation:
    """Decode and validate one durable canonical recommendation."""
    data = _mapping(raw, "canonical_recommendation")
    return CanonicalRecommendation(
        recommendation_id=data["recommendation_id"],
        fingerprint=data["fingerprint"],
        fingerprint_version=data["fingerprint_version"],
        schema_version=data["schema_version"],
        detector_id=data["detector_id"],
        category=data["category"],
        subtype=data["subtype"],
        title=data["title"],
        summary=data["summary"],
        detailed_explanation=data["detailed_explanation"],
        installation_id=data["installation_id"],
        affected_object=decode_subject(data["affected_object"]),
        evidence=tuple(
            decode_recommendation_evidence(item)
            for item in _sequence(data["evidence"], "canonical_recommendation.evidence")
        ),
        supporting_objects=tuple(
            decode_supporting_object(item)
            for item in _sequence(
                data.get("supporting_objects", []),
                "canonical_recommendation.supporting_objects",
            )
        ),
        dependency_analysis=decode_dependency_analysis(data["dependency_analysis"]),
        risk=decode_recommendation_risk(data["risk"]),
        confidence=_decode_confidence(data["confidence"]),
        disposition=_enum(
            RecommendationDisposition, data["disposition"], "recommendation.disposition"
        ),
        suggested_action=data["suggested_action"],
        alternatives=_strings(data.get("alternatives", []), "alternatives"),
        prerequisites=_strings(data.get("prerequisites", []), "prerequisites"),
        validation_requirements=_strings(
            data.get("validation_requirements", []), "validation_requirements"
        ),
        backup_required=data.get("backup_required", False),
        execution_supported=data.get("execution_supported", False),
        execution_action_type=data.get("execution_action_type"),
        llm_proposed_action=decode_llm_proposed_action(data.get("llm_proposed_action")),
        generated_by=_enum(
            ProvenanceSource, data["generated_by"], "recommendation.generated_by"
        ),
        first_seen_at=_parse_time(data["first_seen_at"], "first_seen_at"),
        last_seen_at=_parse_time(data["last_seen_at"], "last_seen_at"),
        last_scan_id=data["last_scan_id"],
        content_revision=data["content_revision"],
        content_digest=data["content_digest"],
        lifecycle_state=_enum(
            RecommendationLifecycleState,
            data["lifecycle_state"],
            "recommendation.lifecycle_state",
        ),
        review_state=_enum(
            RecommendationReviewState,
            data["review_state"],
            "recommendation.review_state",
        ),
        created_at=_parse_time(data["created_at"], "created_at"),
        updated_at=_parse_time(data["updated_at"], "updated_at"),
        occurrence_count=data.get("occurrence_count", 1),
        recurrence_count=data.get("recurrence_count", 0),
        resolved_at=_parse_optional_time(data.get("resolved_at"), "resolved_at"),
        resolution_reason=data.get("resolution_reason"),
        snoozed_until=_parse_optional_time(data.get("snoozed_until"), "snoozed_until"),
        dismissed_at=_parse_optional_time(data.get("dismissed_at"), "dismissed_at"),
        dismissal_reason=data.get("dismissal_reason"),
        superseded_by=data.get("superseded_by"),
    )
