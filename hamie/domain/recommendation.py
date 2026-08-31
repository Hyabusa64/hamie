"""Canonical recommendation domain model (HAMIE Phase 2A).

This is the durable, versioned representation every current and future
HAMIE analyzer or advisory pipeline can use to describe one maintenance
recommendation -- deterministic identity, lifecycle, evidence,
dependency safety, risk, and confidence in one place.

Phase 2A is foundational only:

- No remediation action is executed by anything in this module.
- ``execution_supported``/``execution_action_type`` are reserved fields
  for a later, separately reviewed execution engine (Phase 2B) and are
  never interpreted or acted on here.
- Nothing in this module calls Home Assistant, a connector, or any
  network boundary. It is pure, deterministic domain logic, matching
  the existing ``domain/`` package's own constraint (see
  ``domain/findings.py``, ``domain/evaluations.py``).

Root cause this model exists to fix (see docs/RECOMMENDATION_DOMAIN_MODEL.md
for the full write-up): the existing ``AIRecommendation``
(``domain/intelligence.py``) is keyed by
``stable_digest(response["generated_at"], *cited_findings, *cited_groups)``
-- a fingerprint seeded by the AI provider's own generation timestamp.
Analyzing the identical finding set twice therefore always produces a
different ``recommendation_id``, and ``operations_service.async_request_ai``
unconditionally appends every result
(``(*state.recommendations, recommendation)[-MAX_RECOMMENDATIONS:]``) with
no matching/dedup step at all -- the literal cause of the reported
"repeated recommendations for the same underlying entities" defect.
This model's fingerprint (``compute_recommendation_fingerprint``)
deliberately excludes every volatile input responsible for that bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .common import canonical_json, require_non_empty, require_utc, stable_digest
from .evidence import EvidenceValue
from .findings import Confidence, Risk
from .identity import SubjectIdentity
from .llm_proposal import LlmProposedAction

RECOMMENDATION_SCHEMA_VERSION = 1
RECOMMENDATION_FINGERPRINT_VERSION = 1

MAX_TEXT_LENGTH = 4_000
MAX_LIST_ITEMS = 64
MAX_LIST_ITEM_LENGTH = 1_000

# Bound for the durable, deduplicated canonical recommendation store,
# scaled like the repository's other bounded collections (MAX_AUDIT_RECORDS,
# MAX_SUPPRESSION_RULES) in ``domain/intelligence.py``.
MAX_CANONICAL_RECOMMENDATIONS = 256


class ProvenanceSource(StrEnum):
    """How one recommendation, evidence item, or dependency fact was produced.

    ``LLM_ANALYSIS`` is deliberately distinguished from every other
    source everywhere this enum is used: an LLM may summarize verified
    evidence and propose alternatives, but it must never be the sole
    basis for promoting an unverified claim (dependency safety, rollback
    availability) into a verified one -- see
    ``CanonicalRecommendation.__post_init__``.
    """

    DETERMINISTIC_ANALYZER = "deterministic_analyzer"
    CONNECTOR_RESPONSE = "connector_response"
    HOME_ASSISTANT_INSPECTION = "home_assistant_inspection"
    RECORDER_STATISTICS = "recorder_statistics"
    HKG_QUERY = "hkg_query"
    N8N_RESPONSE = "n8n_response"
    MCP_RESPONSE = "mcp_response"
    LLM_ANALYSIS = "llm_analysis"
    MANUAL_INPUT = "manual_input"
    MIGRATION = "migration"


class RecommendationDisposition(StrEnum):
    """What HAMIE recommends doing about the affected object."""

    INVESTIGATE = "investigate"
    REPAIR = "repair"
    RECONFIGURE = "reconfigure"
    DISABLE = "disable"
    REMOVE = "remove"
    EXCLUDE = "exclude"
    OPTIMIZE = "optimize"
    MONITOR = "monitor"
    NO_ACTION = "no_action"


# A disposition that removes, disables, or excludes an object requires
# complete, verified dependency analysis before it may claim
# safe_to_delete=True. "investigate"/"repair"/"reconfigure"/"optimize"/
# "monitor"/"no_action" never delete or disable anything and are exempt.
DESTRUCTIVE_DISPOSITIONS = frozenset(
    {
        RecommendationDisposition.DISABLE,
        RecommendationDisposition.REMOVE,
        RecommendationDisposition.EXCLUDE,
    }
)


class RecommendationLifecycleState(StrEnum):
    """Technical lifecycle of a recommendation's underlying issue."""

    ACTIVE = "active"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class RecommendationReviewState(StrEnum):
    """Human review state, deliberately separate from lifecycle state."""

    UNREVIEWED = "unreviewed"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    ACCEPTED_FOR_FUTURE_ACTION = "accepted_for_future_action"
    REJECTED = "rejected"
    ACKNOWLEDGED = "acknowledged"


class DependencySourceCheckStatus(StrEnum):
    """Result of checking one dependency-evidence source."""

    SUCCEEDED = "succeeded"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class DependencyAnalysisStatus(StrEnum):
    """Overall dependency-analysis completeness for one recommendation."""

    NOT_STARTED = "not_started"
    INCOMPLETE = "incomplete"
    COMPLETE = "complete"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class SupportingObjectDirection(StrEnum):
    """Direction of a supporting-object relationship, from the affected object."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"
    BIDIRECTIONAL = "bidirectional"


def _require_bounded(
    value: str, field_name: str, *, max_length: int = MAX_TEXT_LENGTH
) -> str:
    require_non_empty(value, field_name)
    if len(value) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    return value


def _bounded_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    deduped = tuple(dict.fromkeys(values))
    if len(deduped) > MAX_LIST_ITEMS:
        raise ValueError(f"{field_name} exceeds {MAX_LIST_ITEMS} items")
    if any(not item or len(item) > MAX_LIST_ITEM_LENGTH for item in deduped):
        raise ValueError(f"{field_name} items must be bounded non-empty strings")
    return deduped


@dataclass(frozen=True, slots=True)
class RecommendationEvidence:
    """One structured, provenance-tagged observation supporting a recommendation.

    Distinct from ``domain/evidence.py``'s ``EvidenceItem`` (which is
    embedded directly inside an analyzer ``Finding``): this carries the
    richer provenance/collection-method/explanation fields a
    recommendation review needs, and is never assumed to originate from
    a single deterministic analyzer the way finding evidence is.
    """

    evidence_type: str
    provenance: ProvenanceSource
    source: str
    observed_value: EvidenceValue
    observed_at: datetime
    collection_method: str
    explanation: str
    expected_value: EvidenceValue = None
    source_object: SubjectIdentity | None = None
    confidence: str = "medium"

    def __post_init__(self) -> None:
        _require_bounded(self.evidence_type, "evidence_type", max_length=256)
        _require_bounded(self.source, "evidence source", max_length=256)
        _require_bounded(self.collection_method, "collection_method", max_length=256)
        _require_bounded(self.explanation, "evidence explanation")
        if self.confidence not in {"low", "medium", "high"}:
            raise ValueError("evidence confidence must be low, medium, or high")
        object.__setattr__(
            self, "observed_at", require_utc(self.observed_at, "evidence observed_at")
        )

    @property
    def evidence_id(self) -> str:
        """Return a stable, order-independent identity for this evidence item.

        Used to deduplicate evidence during reconciliation -- two
        evidence items with the same id are the same observation and
        must never be stored twice.
        """
        return stable_digest(
            self.evidence_type,
            self.provenance.value,
            self.source,
            str(self.observed_value),
            self.collection_method,
            self.source_object.identity_key if self.source_object else "",
        )


@dataclass(frozen=True, slots=True)
class SupportingObjectReference:
    """A typed reference from the affected object to a related object."""

    subject: SubjectIdentity
    relationship_type: str
    direction: SupportingObjectDirection
    confidence: str = "medium"
    evidence_source: str = ""

    def __post_init__(self) -> None:
        _require_bounded(self.relationship_type, "relationship_type", max_length=256)
        if "." not in self.relationship_type:
            raise ValueError("relationship_type must be namespaced")
        if self.confidence not in {"low", "medium", "high"}:
            raise ValueError(
                "supporting object confidence must be low, medium, or high"
            )


@dataclass(frozen=True, slots=True)
class DependencySourceResult:
    """The outcome of checking exactly one dependency-evidence source."""

    source: str
    method: str
    status: DependencySourceCheckStatus
    checked_at: datetime
    references_found: tuple[str, ...] = ()
    unresolved_references: tuple[str, ...] = ()
    confidence: str = "medium"
    error: str | None = None

    def __post_init__(self) -> None:
        _require_bounded(self.source, "dependency source", max_length=256)
        _require_bounded(self.method, "dependency method", max_length=256)
        if "@" not in self.method:
            raise ValueError("dependency method must include a schema version")
        if self.confidence not in {"low", "medium", "high"}:
            raise ValueError(
                "dependency source confidence must be low, medium, or high"
            )
        object.__setattr__(
            self, "checked_at", require_utc(self.checked_at, "dependency checked_at")
        )
        object.__setattr__(
            self,
            "references_found",
            _bounded_tuple(self.references_found, "references_found"),
        )
        object.__setattr__(
            self,
            "unresolved_references",
            _bounded_tuple(self.unresolved_references, "unresolved_references"),
        )
        if self.error is not None:
            error = self.error.strip()
            if not error or len(error) > MAX_TEXT_LENGTH:
                raise ValueError(
                    "dependency source error must be bounded and non-empty"
                )
            object.__setattr__(self, "error", error)
        if self.status is DependencySourceCheckStatus.SUCCEEDED and self.error:
            raise ValueError("a succeeded dependency source cannot carry an error")
        unresolved_statuses = {
            DependencySourceCheckStatus.FAILED,
            DependencySourceCheckStatus.UNAVAILABLE,
        }
        if self.status in unresolved_statuses and not self.error:
            raise ValueError(
                "a failed or unavailable dependency source requires an error"
            )


@dataclass(frozen=True, slots=True)
class DependencyAnalysisResult:
    """Canonical dependency-safety result for one recommendation.

    Enforces the hard safety invariants required before any recommendation
    may claim it is safe to delete or disable its affected object:
    ``safe_to_delete`` cannot be true unless dependency analysis is
    complete, and it cannot be true when any blocking (inbound/unresolved/
    unknown) dependency exists. "No dependencies" is never inferred from
    an empty list alone -- it requires ``status == COMPLETE``.
    """

    status: DependencyAnalysisStatus
    sources: tuple[DependencySourceResult, ...] = ()
    inbound_references: tuple[str, ...] = ()
    outbound_references: tuple[str, ...] = ()
    potential_breakages: tuple[str, ...] = ()
    repair_alternatives: tuple[str, ...] = ()
    unknown_dependencies: tuple[str, ...] = ()
    analyzed_at: datetime | None = None
    confidence: str = "low"
    safe_to_delete: bool = False

    def __post_init__(self) -> None:
        if self.confidence not in {"low", "medium", "high"}:
            raise ValueError(
                "dependency analysis confidence must be low, medium, or high"
            )
        object.__setattr__(
            self,
            "sources",
            tuple(sorted(self.sources, key=lambda item: (item.source, item.method))),
        )
        for field_name in (
            "inbound_references",
            "outbound_references",
            "potential_breakages",
            "repair_alternatives",
            "unknown_dependencies",
        ):
            object.__setattr__(
                self, field_name, _bounded_tuple(getattr(self, field_name), field_name)
            )
        if self.analyzed_at is not None:
            object.__setattr__(
                self, "analyzed_at", require_utc(self.analyzed_at, "analyzed_at")
            )
        if self.status is DependencyAnalysisStatus.NOT_STARTED and self.sources:
            raise ValueError(
                "not_started dependency analysis cannot carry source results"
            )
        unresolved_statuses = {
            DependencySourceCheckStatus.FAILED,
            DependencySourceCheckStatus.UNAVAILABLE,
        }
        failed_or_unavailable_sources = tuple(
            item for item in self.sources if item.status in unresolved_statuses
        )
        if (
            self.status is DependencyAnalysisStatus.COMPLETE
            and failed_or_unavailable_sources
        ):
            raise ValueError(
                "dependency analysis cannot be complete while a source is "
                "failed or unavailable"
            )
        if self.safe_to_delete:
            if self.status is not DependencyAnalysisStatus.COMPLETE:
                raise ValueError("safe_to_delete requires complete dependency analysis")
            if self.inbound_references or self.unknown_dependencies:
                raise ValueError(
                    "safe_to_delete cannot be true with inbound or unknown dependencies"
                )
            if not any(
                item.status is DependencySourceCheckStatus.SUCCEEDED
                for item in self.sources
            ):
                raise ValueError(
                    "safe_to_delete requires at least one successfully verified "
                    "dependency source"
                )


@dataclass(frozen=True, slots=True)
class RecommendationRisk:
    """Risk and rollback description for one recommendation.

    Composes the existing, already-validated ``Risk`` type
    (``domain/findings.py``) rather than duplicating its fields, and adds
    the rollback/impact-estimate fields a recommendation needs that a
    bare analyzer ``Risk`` does not carry.
    """

    risk: Risk
    estimated_operational_impact: str
    estimated_user_visible_impact: str
    estimated_benefit: str | None = None
    affected_capabilities: tuple[str, ...] = ()
    rollback_available: bool = False
    rollback_description: str | None = None
    rollback_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_bounded(
            self.estimated_operational_impact, "estimated_operational_impact"
        )
        _require_bounded(
            self.estimated_user_visible_impact, "estimated_user_visible_impact"
        )
        if self.estimated_benefit is not None:
            _require_bounded(self.estimated_benefit, "estimated_benefit")
        object.__setattr__(
            self,
            "affected_capabilities",
            _bounded_tuple(self.affected_capabilities, "affected_capabilities"),
        )
        object.__setattr__(
            self,
            "rollback_limitations",
            _bounded_tuple(self.rollback_limitations, "rollback_limitations"),
        )
        if self.rollback_available:
            if not self.rollback_description or not self.rollback_description.strip():
                raise ValueError(
                    "rollback_available requires a non-empty rollback_description"
                )
            object.__setattr__(
                self, "rollback_description", self.rollback_description.strip()
            )
        elif self.rollback_description is not None:
            raise ValueError(
                "rollback_description is only meaningful when rollback_available"
            )


def compute_recommendation_fingerprint(
    *,
    detector_id: str,
    category: str,
    subtype: str,
    affected_object: SubjectIdentity,
    installation_id: str,
) -> str:
    """Return the deterministic identity of one logical recommendation.

    Deliberately includes only stable, semantic dimensions and excludes
    every volatile input: generated prose (title/summary/explanation),
    evidence (content or order), confidence, risk, timestamps, and any
    random or provider-generated identifier. Two calls with the same
    detector, category, subtype, affected object, and installation
    always produce the same fingerprint, regardless of when they run,
    what evidence was collected, or what an LLM wrote.

    Scoped by ``installation_id`` and ``affected_object.identity_key``
    (which itself incorporates ``source_instance``) so that two
    installations, or two distinct objects, can never collide.
    """
    return stable_digest(
        RECOMMENDATION_FINGERPRINT_VERSION,
        detector_id,
        category,
        subtype,
        affected_object.identity_key,
        installation_id,
    )


@dataclass(frozen=True, slots=True)
class CanonicalRecommendation:
    """Complete durable, deterministic, non-executable recommendation record."""

    recommendation_id: str
    fingerprint: str
    fingerprint_version: int
    schema_version: int
    detector_id: str
    category: str
    subtype: str
    title: str
    summary: str
    detailed_explanation: str
    installation_id: str
    affected_object: SubjectIdentity
    evidence: tuple[RecommendationEvidence, ...]
    supporting_objects: tuple[SupportingObjectReference, ...]
    dependency_analysis: DependencyAnalysisResult
    risk: RecommendationRisk
    confidence: Confidence
    disposition: RecommendationDisposition
    suggested_action: str
    generated_by: ProvenanceSource
    first_seen_at: datetime
    last_seen_at: datetime
    last_scan_id: str
    content_revision: int
    content_digest: str
    lifecycle_state: RecommendationLifecycleState
    review_state: RecommendationReviewState
    created_at: datetime
    updated_at: datetime
    alternatives: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
    validation_requirements: tuple[str, ...] = ()
    backup_required: bool = False
    execution_supported: bool = False
    execution_action_type: str | None = None
    llm_proposed_action: LlmProposedAction | None = None
    occurrence_count: int = 1
    recurrence_count: int = 0
    resolved_at: datetime | None = None
    resolution_reason: str | None = None
    snoozed_until: datetime | None = None
    dismissed_at: datetime | None = None
    dismissal_reason: str | None = None
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.recommendation_id, "recommendation_id"),
            (self.fingerprint, "fingerprint"),
            (self.detector_id, "detector_id"),
            (self.category, "category"),
            (self.subtype, "subtype"),
            (self.title, "title"),
            (self.summary, "summary"),
            (self.installation_id, "installation_id"),
            (self.suggested_action, "suggested_action"),
            (self.last_scan_id, "last_scan_id"),
            (self.content_digest, "content_digest"),
        ):
            _require_bounded(value, name, max_length=512)
        _require_bounded(self.detailed_explanation, "detailed_explanation")
        if self.schema_version != RECOMMENDATION_SCHEMA_VERSION:
            raise ValueError("unsupported recommendation schema version")
        if self.fingerprint_version != RECOMMENDATION_FINGERPRINT_VERSION:
            raise ValueError("unsupported recommendation fingerprint version")
        expected_fingerprint = compute_recommendation_fingerprint(
            detector_id=self.detector_id,
            category=self.category,
            subtype=self.subtype,
            affected_object=self.affected_object,
            installation_id=self.installation_id,
        )
        if self.fingerprint != expected_fingerprint:
            raise ValueError("fingerprint does not match its declared inputs")
        first_seen = require_utc(self.first_seen_at, "first_seen_at")
        last_seen = require_utc(self.last_seen_at, "last_seen_at")
        created = require_utc(self.created_at, "created_at")
        updated = require_utc(self.updated_at, "updated_at")
        if last_seen < first_seen:
            raise ValueError("last_seen_at cannot precede first_seen_at")
        if updated < created:
            raise ValueError("updated_at cannot precede created_at")
        object.__setattr__(self, "first_seen_at", first_seen)
        object.__setattr__(self, "last_seen_at", last_seen)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        if self.occurrence_count < 1:
            raise ValueError("occurrence_count must be positive")
        if self.recurrence_count < 0:
            raise ValueError("recurrence_count cannot be negative")
        if self.content_revision < 1:
            raise ValueError("content_revision must be positive")
        if not self.evidence:
            raise ValueError("recommendation requires at least one evidence item")
        object.__setattr__(
            self,
            "evidence",
            tuple(
                sorted(
                    {item.evidence_id: item for item in self.evidence}.values(),
                    key=lambda item: item.evidence_id,
                )
            ),
        )
        object.__setattr__(
            self,
            "supporting_objects",
            tuple(
                sorted(
                    self.supporting_objects,
                    key=lambda item: (
                        item.subject.identity_key,
                        item.relationship_type,
                    ),
                )
            ),
        )
        # Recompute and cross-check content_digest the same way fingerprint
        # is cross-checked above: a caller passing a stale or hand-crafted
        # digest (rather than the real compute_content_digest output) is a
        # real, easy-to-make mistake this must reject rather than silently
        # accept -- reconciliation's change detection depends entirely on
        # this value being trustworthy.
        expected_content_digest = compute_content_digest(self)
        if self.content_digest != expected_content_digest:
            raise ValueError("content_digest does not match its declared inputs")
        for field_name in ("alternatives", "prerequisites", "validation_requirements"):
            object.__setattr__(
                self, field_name, _bounded_tuple(getattr(self, field_name), field_name)
            )
        blank_execution_type = (
            self.execution_action_type is not None
            and not self.execution_action_type.strip()
        )
        if blank_execution_type:
            raise ValueError("execution_action_type cannot be blank when provided")
        if self.execution_supported:
            raise ValueError(
                "execution_supported must be false in Phase 2A -- no executor exists"
            )

        # Dependency-safety guard: DependencyAnalysisResult already forbids
        # safe_to_delete without complete, verified analysis (see above);
        # this re-asserts that coupling at the recommendation level so a
        # destructive disposition can never disagree with it. A complete,
        # clean analysis that simply never sets safe_to_delete is fine --
        # the flag is deliberately opt-in, never inferred.
        if (
            self.disposition in DESTRUCTIVE_DISPOSITIONS
            and self.dependency_analysis.status != DependencyAnalysisStatus.COMPLETE
            and self.dependency_analysis.safe_to_delete
        ):
            raise ValueError(
                "a destructive disposition cannot claim safe_to_delete without "
                "complete dependency analysis"
            )
        if self.generated_by is ProvenanceSource.LLM_ANALYSIS:
            non_llm_evidence = any(
                item.provenance is not ProvenanceSource.LLM_ANALYSIS
                for item in self.evidence
            )
            if self.dependency_analysis.safe_to_delete and not non_llm_evidence:
                raise ValueError(
                    "an LLM-only-generated recommendation cannot itself assert "
                    "safe_to_delete without non-LLM evidence"
                )
            if self.risk.rollback_available and not non_llm_evidence:
                raise ValueError(
                    "an LLM-only-generated recommendation cannot itself assert "
                    "rollback_available without non-LLM evidence"
                )

        # Lifecycle/field consistency, mirroring domain/findings.py's
        # Finding.snooze_until pattern and domain/reviews.py's state model.
        if self.lifecycle_state is RecommendationLifecycleState.SNOOZED:
            if self.snoozed_until is None:
                raise ValueError("snoozed recommendation requires snoozed_until")
            object.__setattr__(
                self, "snoozed_until", require_utc(self.snoozed_until, "snoozed_until")
            )
        elif self.snoozed_until is not None:
            raise ValueError("only a snoozed recommendation may retain snoozed_until")

        if self.lifecycle_state is RecommendationLifecycleState.RESOLVED:
            if self.resolved_at is None or not self.resolution_reason:
                raise ValueError(
                    "resolved recommendation requires resolved_at and resolution_reason"
                )
            object.__setattr__(
                self, "resolved_at", require_utc(self.resolved_at, "resolved_at")
            )
        elif self.resolved_at is not None or self.resolution_reason is not None:
            raise ValueError(
                "only a resolved recommendation may retain "
                "resolved_at/resolution_reason"
            )

        if self.lifecycle_state is RecommendationLifecycleState.DISMISSED:
            if self.dismissed_at is None or not self.dismissal_reason:
                raise ValueError(
                    "dismissed recommendation requires dismissed_at and "
                    "dismissal_reason"
                )
            object.__setattr__(
                self, "dismissed_at", require_utc(self.dismissed_at, "dismissed_at")
            )
        elif self.dismissed_at is not None or self.dismissal_reason is not None:
            raise ValueError(
                "only a dismissed recommendation may retain "
                "dismissed_at/dismissal_reason"
            )

        if self.lifecycle_state is RecommendationLifecycleState.SUPERSEDED:
            if not self.superseded_by:
                raise ValueError("superseded recommendation requires superseded_by")
        elif self.superseded_by is not None:
            raise ValueError(
                "only a superseded recommendation may retain superseded_by"
            )

    @property
    def content_key(self) -> tuple[object, ...]:
        """Return the ordered content fields ``compute_content_digest`` covers."""
        return (
            self.category,
            self.subtype,
            self.disposition.value,
            self.summary,
            self.risk.risk.overall.value,
            self.confidence.level.value,
            self.dependency_analysis.status.value,
            self.dependency_analysis.safe_to_delete,
            tuple(item.evidence_id for item in self.evidence),
        )


def compute_content_digest_from_parts(
    *,
    fingerprint: str,
    category: str,
    subtype: str,
    disposition: RecommendationDisposition,
    summary: str,
    risk: RecommendationRisk,
    confidence: Confidence,
    dependency_analysis: DependencyAnalysisResult,
    evidence: tuple[RecommendationEvidence, ...],
) -> str:
    """Return a deterministic digest of one recommendation's material content.

    The single source of truth for content-digest computation: used both
    to validate an already-constructed ``CanonicalRecommendation``
    (``compute_content_digest``) and to compute the digest for a *new*
    candidate before construction (``build_recommendation``,
    ``recommendation_reconciliation._reconcile_one``) -- there is
    deliberately no path that constructs an intermediate, briefly
    inconsistent ``CanonicalRecommendation`` just to read its digest,
    since ``__post_init__`` now validates content_digest strictly.

    Mirrors ``Finding.material_digest``: two recommendations with the
    same fingerprint but different content (evidence, confidence, risk,
    disposition, dependency status) produce a different digest, which
    reconciliation uses to decide whether an in-place update actually
    changed anything meaningful.
    """
    deduped_evidence_ids = tuple(sorted({item.evidence_id for item in evidence}))
    content_key = (
        category,
        subtype,
        disposition.value,
        summary,
        risk.risk.overall.value,
        confidence.level.value,
        dependency_analysis.status.value,
        dependency_analysis.safe_to_delete,
        deduped_evidence_ids,
    )
    return stable_digest(
        fingerprint, canonical_json([str(part) for part in content_key])
    )


def compute_content_digest(recommendation: CanonicalRecommendation) -> str:
    """Return the content digest for an already-constructed recommendation."""
    return compute_content_digest_from_parts(
        fingerprint=recommendation.fingerprint,
        category=recommendation.category,
        subtype=recommendation.subtype,
        disposition=recommendation.disposition,
        summary=recommendation.summary,
        risk=recommendation.risk,
        confidence=recommendation.confidence,
        dependency_analysis=recommendation.dependency_analysis,
        evidence=recommendation.evidence,
    )


def build_recommendation(
    *,
    detector_id: str,
    category: str,
    subtype: str,
    title: str,
    summary: str,
    detailed_explanation: str,
    installation_id: str,
    affected_object: SubjectIdentity,
    evidence: tuple[RecommendationEvidence, ...],
    dependency_analysis: DependencyAnalysisResult,
    risk: RecommendationRisk,
    confidence: Confidence,
    disposition: RecommendationDisposition,
    suggested_action: str,
    generated_by: ProvenanceSource,
    seen_at: datetime,
    scan_id: str,
    supporting_objects: tuple[SupportingObjectReference, ...] = (),
    alternatives: tuple[str, ...] = (),
    prerequisites: tuple[str, ...] = (),
    validation_requirements: tuple[str, ...] = (),
    backup_required: bool = False,
) -> CanonicalRecommendation:
    """Build one newly detected, first-occurrence canonical recommendation.

    The one supported way to construct a *new* candidate: derives
    ``recommendation_id``/``fingerprint``/``content_digest`` deterministically
    rather than requiring the caller to pre-compute them (which is exactly
    the kind of hand-maintained duplication that produced the original
    ``AIRecommendation`` bug this model replaces). Reconciliation
    (``recommendation_reconciliation.py``) owns every subsequent update.
    """
    fingerprint = compute_recommendation_fingerprint(
        detector_id=detector_id,
        category=category,
        subtype=subtype,
        affected_object=affected_object,
        installation_id=installation_id,
    )
    deduped_evidence = tuple(
        sorted(
            {item.evidence_id: item for item in evidence}.values(),
            key=lambda item: item.evidence_id,
        )
    )
    content_digest = compute_content_digest_from_parts(
        fingerprint=fingerprint,
        category=category,
        subtype=subtype,
        disposition=disposition,
        summary=summary,
        risk=risk,
        confidence=confidence,
        dependency_analysis=dependency_analysis,
        evidence=deduped_evidence,
    )
    return CanonicalRecommendation(
        recommendation_id=f"rec_{fingerprint[:24]}",
        fingerprint=fingerprint,
        fingerprint_version=RECOMMENDATION_FINGERPRINT_VERSION,
        schema_version=RECOMMENDATION_SCHEMA_VERSION,
        detector_id=detector_id,
        category=category,
        subtype=subtype,
        title=title,
        summary=summary,
        detailed_explanation=detailed_explanation,
        installation_id=installation_id,
        affected_object=affected_object,
        evidence=deduped_evidence,
        supporting_objects=supporting_objects,
        dependency_analysis=dependency_analysis,
        risk=risk,
        confidence=confidence,
        disposition=disposition,
        suggested_action=suggested_action,
        generated_by=generated_by,
        first_seen_at=seen_at,
        last_seen_at=seen_at,
        last_scan_id=scan_id,
        content_revision=1,
        content_digest=content_digest,
        lifecycle_state=RecommendationLifecycleState.ACTIVE,
        review_state=RecommendationReviewState.UNREVIEWED,
        created_at=seen_at,
        updated_at=seen_at,
        alternatives=alternatives,
        prerequisites=prerequisites,
        validation_requirements=validation_requirements,
        backup_required=backup_required,
    )
