"""Durable incident model and deterministic finding-to-incident reduction.

Findings remain the analyzer-owned observations.  Incidents are the smaller,
user-facing engineering units that connect related findings to one explicit
root-cause hypothesis.  This module is deliberately pure: it performs no Home
Assistant I/O, never calls an AI provider, and cannot execute remediation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .common import require_non_empty, require_utc, stable_digest
from .findings import (
    ConfidenceLevel,
    Finding,
    FindingLifecycle,
    FindingSeverity,
    RecommendationKind,
    RemediationSafetyGate,
    finding_is_diagnostic_entity,
)
from .reviews import ReviewState

INCIDENT_SCHEMA_VERSION = 1
INCIDENT_ENGINE_REVISION = "incident-engine@1"
MAX_INCIDENTS = 2_000
MAX_INCIDENT_MEMBERS = 1_000
_NUMBERED_SUFFIX = re.compile(r"_(?:copy_)?\d+$", re.IGNORECASE)


class EvidenceStatus(StrEnum):
    """How strongly deterministic evidence supports one hypothesis."""

    VERIFIED = "verified"
    STRONGLY_INFERRED = "strongly_inferred"
    POSSIBLE = "possible"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_A_PROBLEM = "not_a_problem"


class IncidentPriority(StrEnum):
    """Action priority independent from the number of member findings."""

    P0 = "p0"
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"
    INFO = "info"


class IncidentLifecycle(StrEnum):
    """Durable incident lifecycle."""

    NEW = "new"
    INVESTIGATING = "investigating"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    IGNORED = "ignored"
    RESOLVED = "resolved"
    RECURRING = "recurring"
    REGRESSED = "regressed"


ACTIVE_INCIDENT_STATES = frozenset(
    {
        IncidentLifecycle.NEW,
        IncidentLifecycle.INVESTIGATING,
        IncidentLifecycle.CONFIRMED,
        IncidentLifecycle.RECURRING,
        IncidentLifecycle.REGRESSED,
    }
)


@dataclass(frozen=True, slots=True)
class IncidentHypothesis:
    """One clearly-labelled explanation and its supporting evidence."""

    statement: str
    status: EvidenceStatus
    evidence_ids: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        require_non_empty(self.statement, "incident hypothesis statement")
        require_non_empty(self.rationale, "incident hypothesis rationale")
        if len(self.statement) > 1_000 or len(self.rationale) > 2_000:
            raise ValueError("incident hypothesis text exceeds its bound")
        evidence_ids = tuple(sorted(set(self.evidence_ids)))
        if not evidence_ids:
            raise ValueError("incident hypothesis requires evidence")
        if len(evidence_ids) > 128:
            raise ValueError("incident hypothesis evidence exceeds its bound")
        object.__setattr__(self, "evidence_ids", evidence_ids)


@dataclass(frozen=True, slots=True)
class Incident:
    """Durable root-cause-oriented engineering incident."""

    incident_id: str
    schema_version: int
    engine_revision: str
    root_key: str
    title: str
    category: str
    root_cause: str
    evidence_status: EvidenceStatus
    confidence: float
    priority: IncidentPriority
    lifecycle: IncidentLifecycle
    finding_ids: tuple[str, ...]
    affected_subject_ids: tuple[str, ...]
    affected_systems: tuple[str, ...]
    hypotheses: tuple[IncidentHypothesis, ...]
    recommended_next_step: str
    first_seen: datetime
    last_seen: datetime
    occurrence_count: int
    latest_scan_id: str
    content_revision: int
    material_digest: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.incident_id, "incident_id"),
            (self.engine_revision, "engine_revision"),
            (self.root_key, "root_key"),
            (self.title, "title"),
            (self.category, "category"),
            (self.root_cause, "root_cause"),
            (self.recommended_next_step, "recommended_next_step"),
            (self.latest_scan_id, "latest_scan_id"),
            (self.material_digest, "material_digest"),
        ):
            require_non_empty(value, name)
        if self.schema_version != INCIDENT_SCHEMA_VERSION:
            raise ValueError("unsupported incident schema version")
        if not 0 <= self.confidence <= 1:
            raise ValueError("incident confidence must be between zero and one")
        if self.occurrence_count < 1 or self.content_revision < 1:
            raise ValueError("incident occurrence/content revision must be positive")
        first_seen = require_utc(self.first_seen, "first_seen")
        last_seen = require_utc(self.last_seen, "last_seen")
        if last_seen < first_seen:
            raise ValueError("incident last_seen cannot precede first_seen")
        finding_ids = tuple(sorted(set(self.finding_ids)))
        affected = tuple(sorted(set(self.affected_subject_ids)))
        systems = tuple(sorted(set(self.affected_systems)))
        if not finding_ids or not affected or not self.hypotheses:
            raise ValueError("incident requires findings, affected subjects, and hypotheses")
        if len(finding_ids) > MAX_INCIDENT_MEMBERS:
            raise ValueError("incident member count exceeds its bound")
        object.__setattr__(self, "first_seen", first_seen)
        object.__setattr__(self, "last_seen", last_seen)
        object.__setattr__(self, "finding_ids", finding_ids)
        object.__setattr__(self, "affected_subject_ids", affected)
        object.__setattr__(self, "affected_systems", systems)

    @property
    def is_active(self) -> bool:
        return self.lifecycle in ACTIVE_INCIDENT_STATES

    def public_dict(self, *, include_evidence_ids: bool = False) -> dict[str, object]:
        """Return a bounded, secret-free API representation."""
        hypotheses = []
        for item in self.hypotheses:
            value: dict[str, object] = {
                "statement": item.statement,
                "status": item.status.value,
                "rationale": item.rationale,
                "evidence_count": len(item.evidence_ids),
            }
            if include_evidence_ids:
                value["evidence_ids"] = list(item.evidence_ids)
            hypotheses.append(value)
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "category": self.category,
            "root_cause": self.root_cause,
            "evidence_status": self.evidence_status.value,
            "confidence": round(self.confidence, 2),
            "priority": self.priority.value,
            "lifecycle": self.lifecycle.value,
            "finding_ids": list(self.finding_ids[:100]),
            "finding_count": len(self.finding_ids),
            "affected_subject_ids": list(self.affected_subject_ids[:100]),
            "affected_subject_count": len(self.affected_subject_ids),
            "affected_systems": list(self.affected_systems),
            "hypotheses": hypotheses,
            "recommended_next_step": self.recommended_next_step,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "occurrence_count": self.occurrence_count,
            "latest_scan_id": self.latest_scan_id,
            "content_revision": self.content_revision,
        }


@dataclass(frozen=True, slots=True)
class IncidentBuildResult:
    """Bounded reduction result used for telemetry and acceptance checks."""

    incidents: tuple[Incident, ...]
    candidate_finding_count: int
    represented_finding_count: int
    normal_finding_ids: tuple[str, ...]
    suppressed_finding_ids: tuple[str, ...]

    @property
    def context_reduction_ratio(self) -> float:
        if not self.candidate_finding_count:
            return 1.0
        return 1 - (len(self.incidents) / self.candidate_finding_count)


def _support_value(finding: Finding, prefix: str) -> str | None:
    marker = f"{prefix}:"
    return next(
        (
            value.removeprefix(marker)
            for value in finding.recommendation.dependency_assessment.supporting_subject_ids
            if value.startswith(marker)
        ),
        None,
    )


def _duplicate_base(entity_id: str) -> str:
    domain, separator, object_id = entity_id.partition(".")
    base = _NUMBERED_SUFFIX.sub("", object_id)
    return f"{domain}{separator}{base}"


def _platform(finding: Finding) -> str | None:
    """Return a captured platform value without inferring one from the domain."""
    return next(
        (
            item.value
            for item in finding.evidence
            if item.predicate == "hamie.entity.platform@1"
            and isinstance(item.value, str)
            and item.value
        ),
        None,
    )


def _root_descriptor(finding: Finding) -> tuple[str, str, str]:
    """Return stable root key, user title, and evidence-grounded hypothesis."""
    condition = finding.condition_key.casefold()
    entity_id = finding.subject.source_id
    device_id = _support_value(finding, "device")
    config_entry_id = _support_value(finding, "config_entry")
    integration = _support_value(finding, "integration")

    related_subjects = getattr(finding, "related_subjects", ())
    if "duplicate" in condition or "migration" in condition or related_subjects:
        base = min(
            _duplicate_base(item)
            for item in (
                entity_id,
                *(subject.source_id for subject in related_subjects),
            )
        )
        return (
            f"duplicate:{base}:{finding.analyzer_id}:{finding.condition_key}",
            f"Duplicate or migration residue: {base}",
            "A replacement or parallel entity exists and the older identity may still "
            "be referenced or retained.",
        )

    platform = _platform(finding)
    domain = entity_id.partition(".")[0]
    pattern_text = f"{condition} {finding.analyzer_id.casefold()}"
    pattern_scope = (
        platform or domain
        if any(marker in pattern_text for marker in ("orphan", "unavailable"))
        else None
    )
    root = device_id or config_entry_id or integration or pattern_scope
    root_kind = (
        "device"
        if device_id
        else "config_entry"
        if config_entry_id
        else "integration"
        if integration
        else "platform"
        if platform and pattern_scope
        else "domain"
    )
    scope_key = f"{root_kind}:{root}" if root else f"entity:{entity_id}"
    descriptions = (
        ("self_reference", "Automation targets itself", "An automation action resolves to its own entity."),
        ("wrong_domain", "Automation action uses the wrong domain", "An automation action domain conflicts with the target entity domain."),
        ("broken_reference", "Reference targets an obsolete entity", "An active writer still targets an unavailable or replaced entity identity."),
        ("removed_integration", "Removed integration left registry objects", "Registry objects remain associated with an integration that is no longer present."),
        ("abandoned_bugfix", "Older workaround may now be obsolete", "A local workaround overlaps a newer authoritative implementation."),
        ("orphan", "Object has no authoritative source definition", "A registry object could not be mapped to an active source definition."),
        ("unavailable", "Related entities are unavailable", "Entities sharing one deterministic source root are unavailable beyond the configured grace period."),
    )
    for marker, title, cause in descriptions:
        if marker in condition or marker in finding.analyzer_id.casefold():
            label = root or entity_id
            return (
                f"{finding.analyzer_id}:{finding.condition_key}:{scope_key}",
                f"{title}: {label}",
                cause,
            )
    return (
        f"{finding.analyzer_id}:{finding.condition_key}:{scope_key}",
        f"{finding.category.replace('_', ' ').title()}: {root or entity_id}",
        "Related findings share the same analyzer condition and deterministic source root.",
    )


def _is_normal_or_suppressed(finding: Finding) -> tuple[bool, bool]:
    """Classify non-incidents without treating missing evidence as healthy."""
    if finding.lifecycle is not FindingLifecycle.OPEN:
        return True, False
    if finding.review_state in {
        ReviewState.DISMISSED,
        ReviewState.RETAINED,
        ReviewState.SNOOZED,
    }:
        return False, True
    recommendation = finding.recommendation
    dependency = recommendation.dependency_assessment
    if recommendation.kind in {
        RecommendationKind.KEEP,
        RecommendationKind.NO_ACTION,
        RecommendationKind.RETAIN,
    }:
        return True, False
    if (
        finding_is_diagnostic_entity(finding)
        and not dependency.referenced_by
        and recommendation.kind is RecommendationKind.MONITOR
    ):
        return True, False
    if (
        recommendation.safety_gate is RemediationSafetyGate.REPORT_ONLY
        and not dependency.referenced_by
        and finding.severity is FindingSeverity.INFO
    ):
        return True, False
    return False, False


def _evidence_status(members: tuple[Finding, ...]) -> EvidenceStatus:
    if any(
        item.recommendation.safety_gate
        is RemediationSafetyGate.BLOCKED_INSUFFICIENT_EVIDENCE
        or item.coverage_state.value != "complete"
        for item in members
    ):
        return EvidenceStatus.INSUFFICIENT_EVIDENCE
    levels = {item.recommendation.confidence.level for item in members}
    observed = all(any(evidence.kind.value == "observed" for evidence in item.evidence) for item in members)
    if levels == {ConfidenceLevel.HIGH} and observed:
        return EvidenceStatus.VERIFIED
    if ConfidenceLevel.LOW not in levels and ConfidenceLevel.HIGH in levels:
        return EvidenceStatus.STRONGLY_INFERRED
    return EvidenceStatus.POSSIBLE


def _priority(members: tuple[Finding, ...]) -> IncidentPriority:
    """Score impact/evidence, deliberately never member count."""
    categories = " ".join(item.category.casefold() for item in members)
    gates = {item.recommendation.safety_gate for item in members}
    severities = {item.severity for item in members}
    conditions = " ".join(item.condition_key.casefold() for item in members)
    referenced = any(
        item.recommendation.dependency_assessment.referenced_by for item in members
    )
    if (
        any(word in categories for word in ("security", "safety", "alarm", "lock"))
        and FindingSeverity.ERROR in severities
    ):
        return IncidentPriority.P0
    if any(
        marker in conditions
        for marker in ("broken_reference", "self_reference", "wrong_domain")
    ) or any(
        item.category == "duplicate_migration"
        and item.recommendation.kind is RecommendationKind.REPAIR
        for item in members
    ) or RemediationSafetyGate.FUNCTIONAL_BUG in gates or (
        FindingSeverity.ERROR in severities and referenced
    ):
        return IncidentPriority.P1
    if FindingSeverity.ERROR in severities or referenced:
        return IncidentPriority.P2
    if FindingSeverity.WARNING in severities:
        return IncidentPriority.P3
    return IncidentPriority.INFO


def _systems(members: tuple[Finding, ...]) -> tuple[str, ...]:
    result: set[str] = set()
    for item in members:
        entity_domain = item.subject.source_id.partition(".")[0]
        if entity_domain:
            result.add(entity_domain)
        for prefix in ("integration", "config_entry", "device", "area"):
            value = _support_value(item, prefix)
            if value:
                result.add(f"{prefix}:{value}")
    return tuple(sorted(result))


def _affected_subjects(members: tuple[Finding, ...]) -> tuple[str, ...]:
    """Include explicit duplicate members without mistaking source roots for entities."""
    result = {item.subject.source_id for item in members}
    for item in members:
        for subject_id in item.recommendation.dependency_assessment.supporting_subject_ids:
            if "." in subject_id and not subject_id.startswith(
                ("device:", "config_entry:", "integration:", "area:")
            ):
                result.add(subject_id)
    return tuple(sorted(result))[:MAX_INCIDENT_MEMBERS]


def _confidence(status: EvidenceStatus) -> float:
    return {
        EvidenceStatus.VERIFIED: 0.98,
        EvidenceStatus.STRONGLY_INFERRED: 0.82,
        EvidenceStatus.POSSIBLE: 0.55,
        EvidenceStatus.INSUFFICIENT_EVIDENCE: 0.25,
        EvidenceStatus.NOT_A_PROBLEM: 1.0,
    }[status]


def _candidate_from_bucket(
    root_key: str, members: tuple[Finding, ...]
) -> Incident:
    ordered = tuple(sorted(members, key=lambda item: item.finding_id))
    _key, title, root_cause = _root_descriptor(ordered[0])
    evidence_ids = tuple(
        sorted({evidence.evidence_id for item in ordered for evidence in item.evidence})
    )[:128]
    status = _evidence_status(ordered)
    affected = _affected_subjects(ordered)
    finding_ids = tuple(item.finding_id for item in ordered)
    priority = _priority(ordered)
    category = ordered[0].category
    material_digest = stable_digest(
        INCIDENT_ENGINE_REVISION,
        root_key,
        category,
        priority.value,
        status.value,
        finding_ids,
        evidence_ids,
    )
    incident_id = f"inc_{stable_digest(INCIDENT_ENGINE_REVISION, root_key)[:32]}"
    recommended = max(
        ordered,
        key=lambda item: (
            {FindingSeverity.INFO: 0, FindingSeverity.WARNING: 1, FindingSeverity.ERROR: 2}[item.severity],
            bool(item.recommendation.dependency_assessment.referenced_by),
        ),
    ).recommendation.action
    return Incident(
        incident_id=incident_id,
        schema_version=INCIDENT_SCHEMA_VERSION,
        engine_revision=INCIDENT_ENGINE_REVISION,
        root_key=root_key,
        title=title,
        category=category,
        root_cause=root_cause,
        evidence_status=status,
        confidence=_confidence(status),
        priority=priority,
        lifecycle=IncidentLifecycle.NEW,
        finding_ids=finding_ids,
        affected_subject_ids=affected,
        affected_systems=_systems(ordered),
        hypotheses=(
            IncidentHypothesis(
                statement=root_cause,
                status=status,
                evidence_ids=evidence_ids,
                rationale=(
                    "Deterministic HAMIE analyzers linked these findings through the "
                    "same condition and source root. No model inference was used."
                ),
            ),
        ),
        recommended_next_step=recommended,
        first_seen=min(item.first_seen for item in ordered),
        last_seen=max(item.last_seen for item in ordered),
        occurrence_count=1,
        latest_scan_id=max(ordered, key=lambda item: item.last_seen).latest_scan_id,
        content_revision=1,
        material_digest=material_digest,
    )


def build_incidents(findings: tuple[Finding, ...]) -> IncidentBuildResult:
    """Reduce raw findings to bounded deterministic incident candidates."""
    buckets: dict[str, list[Finding]] = {}
    normal: list[str] = []
    suppressed: list[str] = []
    for finding in findings:
        is_normal, is_suppressed = _is_normal_or_suppressed(finding)
        if is_normal:
            normal.append(finding.finding_id)
            continue
        if is_suppressed:
            suppressed.append(finding.finding_id)
            continue
        root_key, _title, _cause = _root_descriptor(finding)
        buckets.setdefault(root_key, []).append(finding)
    candidates = []
    for key, members in buckets.items():
        ordered_members = sorted(members, key=lambda item: item.finding_id)
        chunked = len(ordered_members) > MAX_INCIDENT_MEMBERS
        for offset in range(0, len(ordered_members), MAX_INCIDENT_MEMBERS):
            chunk = tuple(ordered_members[offset : offset + MAX_INCIDENT_MEMBERS])
            chunk_key = (
                f"{key}:part:{offset // MAX_INCIDENT_MEMBERS + 1}"
                if chunked
                else key
            )
            candidates.append(_candidate_from_bucket(chunk_key, chunk))
    incidents = tuple(
        sorted(
            candidates,
            key=lambda item: (
                {
                    IncidentPriority.P0: 0,
                    IncidentPriority.P1: 1,
                    IncidentPriority.P2: 2,
                    IncidentPriority.P3: 3,
                    IncidentPriority.INFO: 4,
                }[item.priority],
                item.incident_id,
            ),
        )[:MAX_INCIDENTS]
    )
    return IncidentBuildResult(
        incidents=incidents,
        candidate_finding_count=len(findings),
        represented_finding_count=sum(len(item.finding_ids) for item in incidents),
        normal_finding_ids=tuple(sorted(normal)),
        suppressed_finding_ids=tuple(sorted(suppressed)),
    )


def reconcile_incidents(
    previous: tuple[Incident, ...],
    candidates: tuple[Incident, ...],
    *,
    at: datetime,
    scan_id: str,
) -> tuple[Incident, ...]:
    """Preserve incident decisions and make recurrence/regression explicit."""
    observed_at = require_utc(at, "at")
    require_non_empty(scan_id, "scan_id")
    previous_by_id = {item.incident_id: item for item in previous}
    current_ids = {item.incident_id for item in candidates}
    reconciled: list[Incident] = []
    for candidate in candidates:
        old = previous_by_id.get(candidate.incident_id)
        if old is None:
            reconciled.append(
                replace(candidate, last_seen=observed_at, latest_scan_id=scan_id)
            )
            continue
        material_changed = old.material_digest != candidate.material_digest
        if old.lifecycle is IncidentLifecycle.RESOLVED or (
            old.lifecycle in {IncidentLifecycle.DISMISSED, IncidentLifecycle.IGNORED}
            and material_changed
        ):
            lifecycle = IncidentLifecycle.REGRESSED
        elif old.lifecycle in {
            IncidentLifecycle.INVESTIGATING,
            IncidentLifecycle.CONFIRMED,
            IncidentLifecycle.DISMISSED,
            IncidentLifecycle.IGNORED,
        }:
            lifecycle = old.lifecycle
        else:
            lifecycle = IncidentLifecycle.RECURRING
        reconciled.append(
            replace(
                candidate,
                lifecycle=lifecycle,
                first_seen=old.first_seen,
                last_seen=observed_at,
                occurrence_count=old.occurrence_count + 1,
                latest_scan_id=scan_id,
                content_revision=old.content_revision + int(material_changed),
            )
        )
    for old in previous:
        if old.incident_id not in current_ids and old.lifecycle is not IncidentLifecycle.RESOLVED:
            reconciled.append(
                replace(
                    old,
                    lifecycle=IncidentLifecycle.RESOLVED,
                    last_seen=observed_at,
                    latest_scan_id=scan_id,
                    content_revision=old.content_revision + 1,
                )
            )
        elif old.incident_id not in current_ids:
            reconciled.append(old)
    return tuple(sorted(reconciled, key=lambda item: item.incident_id))[-MAX_INCIDENTS:]


def set_incident_lifecycle(
    incident: Incident, lifecycle: IncidentLifecycle, *, at: datetime
) -> Incident:
    """Apply an explicit user lifecycle decision without changing evidence."""
    if lifecycle not in {
        IncidentLifecycle.INVESTIGATING,
        IncidentLifecycle.CONFIRMED,
        IncidentLifecycle.DISMISSED,
        IncidentLifecycle.IGNORED,
    }:
        raise ValueError("incident lifecycle action is not user-settable")
    return replace(
        incident,
        lifecycle=lifecycle,
        last_seen=max(incident.last_seen, require_utc(at, "at")),
        content_revision=incident.content_revision + 1,
    )


def encode_incident(value: Incident) -> dict[str, object]:
    """Encode an incident into the versioned Store payload."""
    return {
        "incident_id": value.incident_id,
        "schema_version": value.schema_version,
        "engine_revision": value.engine_revision,
        "root_key": value.root_key,
        "title": value.title,
        "category": value.category,
        "root_cause": value.root_cause,
        "evidence_status": value.evidence_status.value,
        "confidence": value.confidence,
        "priority": value.priority.value,
        "lifecycle": value.lifecycle.value,
        "finding_ids": list(value.finding_ids),
        "affected_subject_ids": list(value.affected_subject_ids),
        "affected_systems": list(value.affected_systems),
        "hypotheses": [
            {
                "statement": item.statement,
                "status": item.status.value,
                "evidence_ids": list(item.evidence_ids),
                "rationale": item.rationale,
            }
            for item in value.hypotheses
        ],
        "recommended_next_step": value.recommended_next_step,
        "first_seen": value.first_seen.isoformat(),
        "last_seen": value.last_seen.isoformat(),
        "occurrence_count": value.occurrence_count,
        "latest_scan_id": value.latest_scan_id,
        "content_revision": value.content_revision,
        "material_digest": value.material_digest,
    }


def decode_incident(raw: object) -> Incident:
    """Decode and validate an incident from Store."""
    if not isinstance(raw, dict):
        raise ValueError("incident must be an object")
    return Incident(
        incident_id=raw["incident_id"],
        schema_version=raw["schema_version"],
        engine_revision=raw["engine_revision"],
        root_key=raw["root_key"],
        title=raw["title"],
        category=raw["category"],
        root_cause=raw["root_cause"],
        evidence_status=EvidenceStatus(raw["evidence_status"]),
        confidence=raw["confidence"],
        priority=IncidentPriority(raw["priority"]),
        lifecycle=IncidentLifecycle(raw["lifecycle"]),
        finding_ids=tuple(raw["finding_ids"]),
        affected_subject_ids=tuple(raw["affected_subject_ids"]),
        affected_systems=tuple(raw["affected_systems"]),
        hypotheses=tuple(
            IncidentHypothesis(
                statement=item["statement"],
                status=EvidenceStatus(item["status"]),
                evidence_ids=tuple(item["evidence_ids"]),
                rationale=item["rationale"],
            )
            for item in raw["hypotheses"]
        ),
        recommended_next_step=raw["recommended_next_step"],
        first_seen=datetime.fromisoformat(raw["first_seen"]),
        last_seen=datetime.fromisoformat(raw["last_seen"]),
        occurrence_count=raw["occurrence_count"],
        latest_scan_id=raw["latest_scan_id"],
        content_revision=raw["content_revision"],
        material_digest=raw["material_digest"],
    )
