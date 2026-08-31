"""Explicit versioned JSON serialization for durable domain values."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from .common import canonical_json
from .dependencies import DependencyAssessment, DependencyCoverage
from .evaluations import (
    CoverageAssessment,
    CoverageState,
    EvaluationIdentity,
    EvaluationMetrics,
    EvaluationRecord,
    EvaluationState,
    SourceCapture,
)
from .evidence import EvidenceItem, EvidenceKind, Sensitivity
from .findings import (
    Confidence,
    ConfidenceFactor,
    ConfidenceLevel,
    Finding,
    FindingLifecycle,
    FindingSeverity,
    Recommendation,
    RecommendationKind,
    RemediationSafetyGate,
    Risk,
    RiskLevel,
)
from .identity import SubjectIdentity
from .reviews import ReviewAction, ReviewRecord, ReviewState

DOMAIN_SERIALIZATION_VERSION = 1


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


def encode_subject(value: SubjectIdentity) -> dict[str, Any]:
    """Encode a subject identity."""
    return {
        "durable_id": value.durable_id,
        "kind": value.kind,
        "source_instance": value.source_instance,
        "source_id": value.source_id,
        "display_hint": value.display_hint,
        "aliases": list(value.aliases),
        "tombstoned": value.tombstoned,
    }


def decode_subject(raw: object) -> SubjectIdentity:
    """Decode and validate a subject identity."""
    data = _mapping(raw, "subject")
    return SubjectIdentity(
        durable_id=data["durable_id"],
        kind=data["kind"],
        source_instance=data["source_instance"],
        source_id=data["source_id"],
        display_hint=data.get("display_hint"),
        aliases=_strings(data.get("aliases", []), "subject.aliases"),
        tombstoned=data.get("tombstoned", False),
    )


def encode_evidence(value: EvidenceItem) -> dict[str, Any]:
    """Encode evidence."""
    return {
        "subject": encode_subject(value.subject),
        "predicate": value.predicate,
        "value": value.value,
        "observed_at": _time(value.observed_at),
        "source_id": value.source_id,
        "source_revision": value.source_revision,
        "kind": value.kind.value,
        "sensitivity": value.sensitivity.value,
    }


def decode_evidence(raw: object) -> EvidenceItem:
    """Decode and validate evidence."""
    data = _mapping(raw, "evidence")
    value = data.get("value")
    if value is not None and not isinstance(value, str | int | float | bool):
        raise ValueError("evidence.value must be a JSON scalar")
    return EvidenceItem(
        subject=decode_subject(data["subject"]),
        predicate=data["predicate"],
        value=value,
        observed_at=_parse_time(data["observed_at"], "evidence.observed_at"),
        source_id=data["source_id"],
        source_revision=data["source_revision"],
        kind=_enum(EvidenceKind, data["kind"], "evidence.kind"),
        sensitivity=_enum(Sensitivity, data["sensitivity"], "evidence.sensitivity"),
    )


def _encode_dependency(value: DependencyAssessment) -> dict[str, Any]:
    return {
        "subject": encode_subject(value.subject),
        "required_capabilities": list(value.required_capabilities),
        "used_capabilities": list(value.used_capabilities),
        "coverage": value.coverage.value,
        "rationale": value.rationale,
        "supporting_subject_ids": list(value.supporting_subject_ids),
        "referenced_by": list(value.referenced_by),
        "safe_to_remove": value.safe_to_remove,
    }


def _decode_dependency(raw: object) -> DependencyAssessment:
    data = _mapping(raw, "dependency_assessment")
    return DependencyAssessment(
        subject=decode_subject(data["subject"]),
        required_capabilities=_strings(
            data["required_capabilities"], "required_capabilities"
        ),
        used_capabilities=_strings(data["used_capabilities"], "used_capabilities"),
        coverage=_enum(DependencyCoverage, data["coverage"], "dependency.coverage"),
        rationale=data["rationale"],
        supporting_subject_ids=_strings(
            data.get("supporting_subject_ids", []), "supporting_subject_ids"
        ),
        referenced_by=_strings(data.get("referenced_by", []), "referenced_by"),
        safe_to_remove=data.get("safe_to_remove", False),
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
            code=item["code"],
            effect=item["effect"],
            rationale=item["rationale"],
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


def _encode_recommendation(value: Recommendation) -> dict[str, Any]:
    return {
        "kind": value.kind.value,
        "action": value.action,
        "rationale": value.rationale,
        "evidence": [encode_evidence(item) for item in value.evidence],
        "confidence": _encode_confidence(value.confidence),
        "dependency_assessment": _encode_dependency(value.dependency_assessment),
        "risk": _encode_risk(value.risk),
        "analyzer_id": value.analyzer_id,
        "rule_revision": value.rule_revision,
        "preconditions": list(value.preconditions),
        "disqualifiers": list(value.disqualifiers),
        "safety_gate": value.safety_gate.value,
        "blocked_reason": value.blocked_reason,
    }


def _decode_recommendation(raw: object) -> Recommendation:
    data = _mapping(raw, "recommendation")
    return Recommendation(
        kind=_enum(RecommendationKind, data["kind"], "recommendation.kind"),
        action=data["action"],
        rationale=data["rationale"],
        evidence=tuple(
            decode_evidence(item)
            for item in _sequence(data["evidence"], "recommendation.evidence")
        ),
        confidence=_decode_confidence(data["confidence"]),
        dependency_assessment=_decode_dependency(data["dependency_assessment"]),
        risk=_decode_risk(data["risk"]),
        analyzer_id=data["analyzer_id"],
        rule_revision=data["rule_revision"],
        preconditions=_strings(data.get("preconditions", []), "preconditions"),
        disqualifiers=_strings(data.get("disqualifiers", []), "disqualifiers"),
        # Additive (mission Part 3): a record persisted before this
        # field existed simply has no "safety_gate" key -- decoded as
        # the same conservative RECOMMEND_REVIEW default the dataclass
        # itself uses, never fabricated as a stronger gate.
        safety_gate=(
            _enum(RemediationSafetyGate, data["safety_gate"], "recommendation.safety_gate")
            if "safety_gate" in data
            else RemediationSafetyGate.RECOMMEND_REVIEW
        ),
        blocked_reason=data.get("blocked_reason"),
    )


def encode_finding(value: Finding) -> dict[str, Any]:
    """Encode a durable finding."""
    return {
        "finding_id": value.finding_id,
        "fingerprint": value.fingerprint,
        "analyzer_id": value.analyzer_id,
        "rule_version": value.rule_version,
        "condition_key": value.condition_key,
        "subject": encode_subject(value.subject),
        "category": value.category,
        "title_key": value.title_key,
        "description_arguments": [list(item) for item in value.description_arguments],
        "severity": value.severity.value,
        "evidence": [encode_evidence(item) for item in value.evidence],
        "recommendation": _encode_recommendation(value.recommendation),
        "first_seen": _time(value.first_seen),
        "last_seen": _time(value.last_seen),
        "occurrence_count": value.occurrence_count,
        "latest_scan_id": value.latest_scan_id,
        "content_revision": value.content_revision,
        "material_digest": value.material_digest,
        "lifecycle": value.lifecycle.value,
        "review_state": value.review_state.value,
        "coverage_state": value.coverage_state.value,
        "snooze_until": _time(value.snooze_until) if value.snooze_until else None,
    }


def decode_finding(raw: object) -> Finding:
    """Decode and validate a durable finding."""
    data = _mapping(raw, "finding")
    arguments = _sequence(data["description_arguments"], "description_arguments")
    if any(
        not isinstance(item, list)
        or len(item) != 2
        or not all(isinstance(value, str) for value in item)
        for item in arguments
    ):
        raise ValueError("description_arguments must be string pairs")
    return Finding(
        finding_id=data["finding_id"],
        fingerprint=data["fingerprint"],
        analyzer_id=data["analyzer_id"],
        rule_version=data["rule_version"],
        condition_key=data["condition_key"],
        subject=decode_subject(data["subject"]),
        category=data["category"],
        title_key=data["title_key"],
        description_arguments=tuple((item[0], item[1]) for item in arguments),
        severity=_enum(FindingSeverity, data["severity"], "finding.severity"),
        evidence=tuple(
            decode_evidence(item)
            for item in _sequence(data["evidence"], "finding.evidence")
        ),
        recommendation=_decode_recommendation(data["recommendation"]),
        first_seen=_parse_time(data["first_seen"], "finding.first_seen"),
        last_seen=_parse_time(data["last_seen"], "finding.last_seen"),
        occurrence_count=data["occurrence_count"],
        latest_scan_id=data["latest_scan_id"],
        content_revision=data["content_revision"],
        material_digest=data["material_digest"],
        lifecycle=_enum(FindingLifecycle, data["lifecycle"], "finding.lifecycle"),
        review_state=_enum(ReviewState, data["review_state"], "finding.review_state"),
        coverage_state=_enum(
            CoverageState, data["coverage_state"], "finding.coverage_state"
        ),
        snooze_until=(
            _parse_time(data["snooze_until"], "finding.snooze_until")
            if data.get("snooze_until") is not None
            else None
        ),
    )


def encode_review(value: ReviewRecord) -> dict[str, Any]:
    """Encode a review transition."""
    return {
        "finding_id": value.finding_id,
        "action": value.action.value,
        "actor": value.actor,
        "at": _time(value.at),
        "finding_content_revision": value.finding_content_revision,
        "prior_state": value.prior_state.value,
        "resulting_state": value.resulting_state.value,
        "reason": value.reason,
        "snooze_until": _time(value.snooze_until) if value.snooze_until else None,
    }


def decode_review(raw: object) -> ReviewRecord:
    """Decode and validate a review transition."""
    data = _mapping(raw, "review")
    return ReviewRecord(
        finding_id=data["finding_id"],
        action=_enum(ReviewAction, data["action"], "review.action"),
        actor=data["actor"],
        at=_parse_time(data["at"], "review.at"),
        finding_content_revision=data["finding_content_revision"],
        prior_state=_enum(ReviewState, data["prior_state"], "review.prior_state"),
        resulting_state=_enum(
            ReviewState, data["resulting_state"], "review.resulting_state"
        ),
        reason=data.get("reason"),
        snooze_until=(
            _parse_time(data["snooze_until"], "review.snooze_until")
            if data.get("snooze_until") is not None
            else None
        ),
    )


def encode_evaluation(value: EvaluationRecord) -> dict[str, Any]:
    """Encode an evaluation summary."""
    return {
        "identity": {
            "scan_id": value.identity.scan_id,
            "generation": value.identity.generation,
        },
        "trigger": value.trigger,
        "started_at": _time(value.started_at),
        "ended_at": _time(value.ended_at),
        "state": value.state.value,
        "captures": [
            {
                "source_id": item.source_id,
                "capability_id": item.capability_id,
                "revision": item.revision,
                "capture_started_at": _time(item.capture_started_at),
                "capture_ended_at": _time(item.capture_ended_at),
                "observed_at": _time(item.observed_at),
                "max_age_seconds": item.max_age_seconds,
                "requested_scopes": list(item.requested_scopes),
                "captured_scopes": list(item.captured_scopes),
                "missing_scopes": list(item.missing_scopes),
                "warnings": list(item.warnings),
                "consistent": item.consistent,
            }
            for item in value.captures
        ],
        "coverage": [
            {
                "analyzer_id": item.analyzer_id,
                "policy_version": item.policy_version,
                "state": item.state.value,
                "requested_subjects": list(item.requested_subjects),
                "covered_subjects": list(item.covered_subjects),
                "excluded_subjects": list(item.excluded_subjects),
                "uncovered_subjects": list(item.uncovered_subjects),
                "stale_subjects": list(item.stale_subjects),
                "indeterminate_subjects": list(item.indeterminate_subjects),
                "rule_version": item.rule_version,
            }
            for item in value.coverage
        ],
        "metrics": {
            name: getattr(value.metrics, name)
            for name in EvaluationMetrics.__dataclass_fields__
        },
        "warnings": list(value.warnings),
    }


def decode_evaluation(raw: object) -> EvaluationRecord:
    """Decode and validate an evaluation summary."""
    data = _mapping(raw, "evaluation")
    identity = _mapping(data["identity"], "evaluation.identity")
    captures = []
    for raw_capture in _sequence(data["captures"], "evaluation.captures"):
        item = _mapping(raw_capture, "capture")
        captures.append(
            SourceCapture(
                source_id=item["source_id"],
                capability_id=item["capability_id"],
                revision=item["revision"],
                capture_started_at=_parse_time(
                    item["capture_started_at"], "capture_started_at"
                ),
                capture_ended_at=_parse_time(
                    item["capture_ended_at"], "capture_ended_at"
                ),
                observed_at=_parse_time(item["observed_at"], "observed_at"),
                max_age_seconds=item["max_age_seconds"],
                requested_scopes=_strings(item["requested_scopes"], "requested_scopes"),
                captured_scopes=_strings(item["captured_scopes"], "captured_scopes"),
                missing_scopes=_strings(
                    item.get("missing_scopes", []), "missing_scopes"
                ),
                warnings=_strings(item.get("warnings", []), "warnings"),
                consistent=item.get("consistent", True),
            )
        )
    coverage = []
    for raw_coverage in _sequence(data["coverage"], "evaluation.coverage"):
        item = _mapping(raw_coverage, "coverage")
        coverage.append(
            CoverageAssessment(
                analyzer_id=item["analyzer_id"],
                policy_version=item["policy_version"],
                state=_enum(CoverageState, item["state"], "coverage.state"),
                requested_subjects=_strings(
                    item["requested_subjects"], "requested_subjects"
                ),
                covered_subjects=_strings(item["covered_subjects"], "covered_subjects"),
                excluded_subjects=_strings(
                    item.get("excluded_subjects", []), "excluded_subjects"
                ),
                uncovered_subjects=_strings(
                    item.get("uncovered_subjects", []), "uncovered_subjects"
                ),
                stale_subjects=_strings(
                    item.get("stale_subjects", []), "stale_subjects"
                ),
                indeterminate_subjects=_strings(
                    item.get("indeterminate_subjects", []),
                    "indeterminate_subjects",
                ),
                rule_version=item.get("rule_version", 1),
            )
        )
    metrics = _mapping(data["metrics"], "evaluation.metrics")
    return EvaluationRecord(
        identity=EvaluationIdentity(
            scan_id=identity["scan_id"], generation=identity["generation"]
        ),
        trigger=data["trigger"],
        started_at=_parse_time(data["started_at"], "started_at"),
        ended_at=_parse_time(data["ended_at"], "ended_at"),
        state=_enum(EvaluationState, data["state"], "evaluation.state"),
        captures=tuple(captures),
        coverage=tuple(coverage),
        metrics=EvaluationMetrics(**metrics),
        warnings=_strings(data.get("warnings", []), "evaluation.warnings"),
    )


def canonical_domain_json(value: Finding | ReviewRecord | EvaluationRecord) -> str:
    """Return versioned deterministic JSON for a supported domain value."""
    if isinstance(value, Finding):
        kind, payload = "finding", encode_finding(value)
    elif isinstance(value, ReviewRecord):
        kind, payload = "review", encode_review(value)
    elif isinstance(value, EvaluationRecord):
        kind, payload = "evaluation", encode_evaluation(value)
    else:
        raise TypeError("unsupported domain value")
    return canonical_json(
        {
            "serialization_version": DOMAIN_SERIALIZATION_VERSION,
            "kind": kind,
            "value": payload,
        }
    )
