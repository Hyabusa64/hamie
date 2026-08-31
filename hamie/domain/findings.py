"""Finding, confidence, risk, and recommendation values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .common import canonical_json, require_non_empty, require_utc, stable_digest
from .dependencies import DependencyAssessment
from .evaluations import CoverageState
from .evidence import EvidenceItem
from .identity import SubjectIdentity
from .reviews import ReviewState

FINGERPRINT_VERSION = 1


class ConfidenceLevel(StrEnum):
    """Deterministic confidence level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ConfidenceFactor:
    """One transparent confidence input."""

    code: str
    effect: int
    rationale: str

    def __post_init__(self) -> None:
        require_non_empty(self.code, "confidence factor code")
        require_non_empty(self.rationale, "confidence factor rationale")
        if not -100 <= self.effect <= 100:
            raise ValueError("confidence factor effect must be between -100 and 100")


@dataclass(frozen=True, slots=True)
class Confidence:
    """Structured confidence with a versioned rule."""

    level: ConfidenceLevel
    factors: tuple[ConfidenceFactor, ...]
    rule_revision: str

    def __post_init__(self) -> None:
        require_non_empty(self.rule_revision, "confidence rule_revision")
        if not self.factors:
            raise ValueError("confidence requires at least one factor")
        object.__setattr__(
            self, "factors", tuple(sorted(self.factors, key=lambda item: item.code))
        )


class RiskLevel(StrEnum):
    """Risk level independent from confidence."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Risk:
    """Structured risk of following the recommendation."""

    likelihood: RiskLevel
    impact: RiskLevel
    reversible: bool
    affected_scope: str
    overall: RiskLevel
    rationale: str

    def __post_init__(self) -> None:
        require_non_empty(self.affected_scope, "affected_scope")
        require_non_empty(self.rationale, "risk rationale")


class RecommendationKind(StrEnum):
    """Advisory-only recommendation kinds. HAMIE never executes any of
    these itself -- every one is a suggestion surfaced to a human;
    remediation only ever runs through the fully separate, explicitly
    human-gated plan -> approve -> execute pipeline in
    ``application/remediation/`` (see
    ``application/remediation/coordinator.py``'s ``async_execute_plan``,
    which requires a matching ``ApprovalRecord`` bound to the exact
    plan fingerprint, and ``presentation/remediation_api.py``, where
    plan creation, approval, and execution are three separate
    ``@websocket_api.require_admin`` commands -- a recommendation kind
    alone, however strongly worded, can never reach that pipeline on
    its own).

    The original six (``REPAIR``/``RETAIN``/``DISABLE``/``MONITOR``/
    ``NEEDS_EVIDENCE``/``REVIEW_CONFIGURATION``) are unchanged and keep
    their exact existing string values -- every already-persisted
    ``Finding``/``Recommendation`` and every existing analyzer
    (``unavailable_entities.py``, and ``orphaned_definitions.py``'s
    non-``DELETE_CANDIDATE`` path) keeps working unmodified.

    The six additional members below extend that vocabulary (mission
    Part 2) so newer analyzers (``orphaned_definitions.py``'s
    delete-eligible path, the duplicate/migration analyzer) can express
    a more specific verdict than the original six allow, while staying
    a strict superset -- nothing here removes or renames a prior
    member. Where a new member's meaning overlaps with an existing one,
    the existing member's current callers are deliberately left
    unchanged (never silently migrated) and the relationship is
    documented so a future analyzer can pick the more precise term
    deliberately:

    - ``KEEP`` vs. ``RETAIN``: same meaning ("no cleanup action; this
      subject is fine as-is"). ``RETAIN`` remains exactly what it
      always was; ``KEEP`` is the newer analyzers' preferred spelling
      and also the advisory-kind counterpart of
      ``cleanup_classifier.BenchmarkTaxonomy.KEEP``.
    - ``INVESTIGATE`` vs. ``MONITOR``: distinct, not aliases.
      ``MONITOR`` (``unavailable_entities.py``'s only recommendation
      kind) means "keep passively watching this over time, no action
      needed today." ``INVESTIGATE`` means "a human should actively
      look into this specific ambiguity now" -- a stronger, more
      immediate ask.
    - ``DISABLE_CANDIDATE`` vs. ``DISABLE``: ``DISABLE`` is
      ``orphaned_definitions.py``'s existing, unmodified recommendation
      for an orphan whose safety could not be fully confirmed (e.g. a
      reference scan was not supplied, or found remaining references).
      ``DISABLE_CANDIDATE`` is available for a future analyzer that
      wants the benchmark-taxonomy-aligned spelling without disturbing
      today's ``DISABLE`` semantics or fingerprints.
    - ``DELETE_CANDIDATE``: new. The advisory counterpart of
      ``cleanup_classifier.BenchmarkTaxonomy.DELETE_CANDIDATE`` --
      HAMIE still never deletes anything itself (see the class
      docstring above); this only lets a confirmed orphan with
      complete, zero-reference dependency coverage surface a stronger
      signal than ``DISABLE`` to a human reviewer (see
      ``analysis/analyzers/orphaned_definitions.py``).
    - ``REVIEW_DUPLICATE``: new. Specific to the suffix-duplicate/
      migration-leftover analyzer's ``AMBIGUOUS_DUPLICATE_GROUP``
      outcome (see ``domain/duplicate_classifier.py``) -- distinct from
      the pre-existing, broader ``REVIEW_CONFIGURATION``.
    - ``NO_ACTION``: new. For a candidate that was actively evaluated
      and cleared (e.g. temporal evidence contradicts a cleanup
      hypothesis) -- distinct from ``KEEP``/``RETAIN`` in that those
      imply "this is a legitimate, ongoing thing," while ``NO_ACTION``
      means "nothing about this warrants a recommendation at all,"
      recorded for auditability.
    """

    REPAIR = "repair"
    RETAIN = "retain"
    DISABLE = "disable"
    MONITOR = "monitor"
    NEEDS_EVIDENCE = "needs_evidence"
    REVIEW_CONFIGURATION = "review_configuration"
    KEEP = "keep"
    INVESTIGATE = "investigate"
    REVIEW_DUPLICATE = "review_duplicate"
    DISABLE_CANDIDATE = "disable_candidate"
    DELETE_CANDIDATE = "delete_candidate"
    NO_ACTION = "no_action"


class RemediationSafetyGate(StrEnum):
    """Orthogonal "how confident/safe" axis, separate from
    ``RecommendationKind``'s "what to do" (mission Part 3).

    ``RecommendationKind`` is documented above as answering "what to
    do" (repair/disable/monitor/...). These seven members answer a
    different question -- "how much unattended trust does this specific
    recommendation deserve right now" -- which does not collapse onto
    any existing ``RecommendationKind`` member cleanly (e.g. two
    findings can both carry ``kind=REPAIR`` while one is
    ``SAFE_TO_FIX_SOURCE`` and the other is ``PROTECTED``). Kept as a
    second field on ``Recommendation`` (``safety_gate``, additive with
    a conservative default) rather than folded into ``kind`` itself, so
    every existing analyzer/consumer that only ever reasoned about
    ``kind`` keeps working unmodified -- see
    ``Recommendation.safety_gate``'s own docstring for the exact
    backward-compatibility contract.

    - ``REPORT_ONLY``: surfaced for awareness; no action implied at all
      (e.g. ``LIKELY_DISTINCT_ENTITIES``/``NO_ACTION``-shaped findings).
    - ``RECOMMEND_REVIEW``: a human should look at this; the default,
      most conservative "there is something here" gate.
    - ``SAFE_TO_FIX_SOURCE``: strong enough evidence that editing a
      config/package file (never a registry mutation) is a defensible
      suggestion -- still only ever advisory text, HAMIE never edits a
      file itself.
    - ``SAFE_TO_REMOVE_REGISTRY``: the strongest gate -- confirmed
      orphan, zero references, not protected. Mirrors
      ``DependencyAssessment.safe_to_remove=True``'s bar exactly; never
      set when a subject is protected (see
      ``domain/protection.py::cap_safety_gate_for_protection``).
    - ``BLOCKED_INSUFFICIENT_EVIDENCE``: an analyzer looked and could
      not reach a confident verdict (e.g. short recorder retention).
    - ``PROTECTED``: the subject matched
      ``domain/protection.py``'s safety/security signals -- caps any
      analyzer's gate at this value or weaker, regardless of how clean
      the technical evidence otherwise looks.
    - ``FUNCTIONAL_BUG``: the finding describes an active defect (not
      just registry hygiene) -- e.g. Analyzer 1's self-reference
      regression, or ``BROKEN_REFERENCE_TO_OLD_SIBLING``-shaped
      findings. A human should treat this as higher priority than a
      plain hygiene suggestion, but it is still never auto-fixed.
    """

    REPORT_ONLY = "report_only"
    RECOMMEND_REVIEW = "recommend_review"
    SAFE_TO_FIX_SOURCE = "safe_to_fix_source"
    SAFE_TO_REMOVE_REGISTRY = "safe_to_remove_registry"
    BLOCKED_INSUFFICIENT_EVIDENCE = "blocked_insufficient_evidence"
    PROTECTED = "protected"
    FUNCTIONAL_BUG = "functional_bug"


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Complete non-executable human recommendation."""

    kind: RecommendationKind
    action: str
    rationale: str
    evidence: tuple[EvidenceItem, ...]
    confidence: Confidence
    dependency_assessment: DependencyAssessment
    risk: Risk
    analyzer_id: str
    rule_revision: str
    preconditions: tuple[str, ...] = ()
    disqualifiers: tuple[str, ...] = ()
    # Additive (mission Part 3): defaults to the most conservative
    # non-``REPORT_ONLY`` gate so an analyzer written before this field
    # existed (every pre-Part-3 analyzer) implicitly reads as "a human
    # should review this" -- never silently upgraded to a stronger
    # unattended-trust gate it never actually earned. See
    # ``RemediationSafetyGate``'s own docstring for the full contract.
    safety_gate: RemediationSafetyGate = RemediationSafetyGate.RECOMMEND_REVIEW
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.action, "recommendation action")
        require_non_empty(self.rationale, "recommendation rationale")
        require_non_empty(self.analyzer_id, "recommendation analyzer_id")
        require_non_empty(self.rule_revision, "recommendation rule_revision")
        if not self.evidence:
            raise ValueError("recommendation requires evidence")
        if (
            self.safety_gate is RemediationSafetyGate.BLOCKED_INSUFFICIENT_EVIDENCE
            and not (self.blocked_reason or "").strip()
        ):
            raise ValueError("BLOCKED_INSUFFICIENT_EVIDENCE requires blocked_reason")
        if (
            self.safety_gate is RemediationSafetyGate.SAFE_TO_REMOVE_REGISTRY
            and not self.dependency_assessment.safe_to_remove
        ):
            raise ValueError(
                "SAFE_TO_REMOVE_REGISTRY requires dependency_assessment.safe_to_remove"
            )
        object.__setattr__(
            self,
            "evidence",
            tuple(sorted(self.evidence, key=lambda item: item.evidence_id)),
        )
        object.__setattr__(
            self, "preconditions", tuple(sorted(set(self.preconditions)))
        )
        object.__setattr__(
            self, "disqualifiers", tuple(sorted(set(self.disqualifiers)))
        )


class FindingSeverity(StrEnum):
    """Finding presentation severity."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class FindingLifecycle(StrEnum):
    """Analyzer-owned finding lifecycle."""

    OPEN = "open"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class CandidateFinding:
    """Validated analyzer candidate before reconciliation."""

    analyzer_id: str
    rule_version: str
    condition_key: str
    subject: SubjectIdentity
    category: str
    title_key: str
    description_arguments: tuple[tuple[str, str], ...]
    severity: FindingSeverity
    evidence: tuple[EvidenceItem, ...]
    recommendation: Recommendation
    related_subjects: tuple[SubjectIdentity, ...] = ()

    def __post_init__(self) -> None:
        for value, name in (
            (self.analyzer_id, "analyzer_id"),
            (self.rule_version, "rule_version"),
            (self.condition_key, "condition_key"),
            (self.category, "category"),
            (self.title_key, "title_key"),
        ):
            require_non_empty(value, name)
        if not self.evidence:
            raise ValueError("candidate finding requires evidence")
        if self.recommendation.evidence != tuple(
            sorted(self.evidence, key=lambda item: item.evidence_id)
        ):
            raise ValueError("recommendation evidence must match finding evidence")
        if self.recommendation.analyzer_id != self.analyzer_id:
            raise ValueError("recommendation analyzer must match candidate analyzer")
        object.__setattr__(
            self, "description_arguments", tuple(sorted(self.description_arguments))
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(sorted(self.evidence, key=lambda item: item.evidence_id)),
        )
        object.__setattr__(
            self,
            "related_subjects",
            tuple(sorted(self.related_subjects, key=lambda item: item.identity_key)),
        )

    @property
    def fingerprint(self) -> str:
        """Return stable semantic finding identity."""
        return stable_digest(
            FINGERPRINT_VERSION,
            self.analyzer_id,
            self.rule_version.split(".", maxsplit=1)[0],
            self.subject.identity_key,
            self.condition_key,
        )

    @property
    def finding_id(self) -> str:
        """Return compact stable finding identifier."""
        return f"hamie_{self.fingerprint[:32]}"

    @property
    def material_digest(self) -> str:
        """Return a deterministic signature of finding-owned content."""
        return stable_digest(
            self.fingerprint,
            canonical_json(
                {
                    "category": self.category,
                    "title_key": self.title_key,
                    "description_arguments": self.description_arguments,
                    "severity": self.severity.value,
                    "evidence": [item.evidence_id for item in self.evidence],
                    "recommendation": {
                        "kind": self.recommendation.kind.value,
                        "action": self.recommendation.action,
                        "rationale": self.recommendation.rationale,
                        "rule_revision": self.recommendation.rule_revision,
                        "preconditions": self.recommendation.preconditions,
                        "disqualifiers": self.recommendation.disqualifiers,
                        "safety_gate": self.recommendation.safety_gate.value,
                        "blocked_reason": self.recommendation.blocked_reason,
                        "confidence": {
                            "level": self.recommendation.confidence.level.value,
                            "rule_revision": (
                                self.recommendation.confidence.rule_revision
                            ),
                            "factors": [
                                (item.code, item.effect, item.rationale)
                                for item in self.recommendation.confidence.factors
                            ],
                        },
                        "dependency": {
                            "coverage": (
                                self.recommendation.dependency_assessment.coverage.value
                            ),
                            "rationale": (
                                self.recommendation.dependency_assessment.rationale
                            ),
                            "supporting_subject_ids": (
                                self.recommendation.dependency_assessment.supporting_subject_ids
                            ),
                            "referenced_by": (
                                self.recommendation.dependency_assessment.referenced_by
                            ),
                            "safe_to_remove": (
                                self.recommendation.dependency_assessment.safe_to_remove
                            ),
                        },
                        "risk": {
                            "likelihood": self.recommendation.risk.likelihood.value,
                            "impact": self.recommendation.risk.impact.value,
                            "reversible": self.recommendation.risk.reversible,
                            "affected_scope": self.recommendation.risk.affected_scope,
                            "overall": self.recommendation.risk.overall.value,
                            "rationale": self.recommendation.risk.rationale,
                        },
                    },
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class Finding:
    """Current durable maintenance intelligence record."""

    finding_id: str
    fingerprint: str
    analyzer_id: str
    rule_version: str
    condition_key: str
    subject: SubjectIdentity
    category: str
    title_key: str
    description_arguments: tuple[tuple[str, str], ...]
    severity: FindingSeverity
    evidence: tuple[EvidenceItem, ...]
    recommendation: Recommendation
    first_seen: datetime
    last_seen: datetime
    occurrence_count: int
    latest_scan_id: str
    content_revision: int
    material_digest: str
    lifecycle: FindingLifecycle
    review_state: ReviewState
    coverage_state: CoverageState
    snooze_until: datetime | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.finding_id, "finding_id"),
            (self.fingerprint, "fingerprint"),
            (self.analyzer_id, "analyzer_id"),
            (self.rule_version, "rule_version"),
            (self.condition_key, "condition_key"),
            (self.latest_scan_id, "latest_scan_id"),
            (self.material_digest, "material_digest"),
        ):
            require_non_empty(value, name)
        first_seen = require_utc(self.first_seen, "first_seen")
        last_seen = require_utc(self.last_seen, "last_seen")
        if last_seen < first_seen:
            raise ValueError("last_seen cannot precede first_seen")
        if self.occurrence_count < 1 or self.content_revision < 1:
            raise ValueError("occurrence_count and content_revision must be positive")
        if not self.evidence:
            raise ValueError("finding requires evidence")
        object.__setattr__(self, "first_seen", first_seen)
        object.__setattr__(self, "last_seen", last_seen)
        object.__setattr__(
            self, "description_arguments", tuple(sorted(self.description_arguments))
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(sorted(self.evidence, key=lambda item: item.evidence_id)),
        )
        if self.review_state is ReviewState.SNOOZED:
            if self.snooze_until is None:
                raise ValueError("snoozed finding requires snooze_until")
            object.__setattr__(
                self,
                "snooze_until",
                require_utc(self.snooze_until, "snooze_until"),
            )
        elif self.snooze_until is not None:
            raise ValueError("only a snoozed finding may retain snooze_until")

    @classmethod
    def from_candidate(
        cls,
        candidate: CandidateFinding,
        *,
        seen_at: datetime,
        scan_id: str,
        coverage_state: CoverageState,
    ) -> Finding:
        """Create a new durable finding from a validated candidate."""
        return cls(
            finding_id=candidate.finding_id,
            fingerprint=candidate.fingerprint,
            analyzer_id=candidate.analyzer_id,
            rule_version=candidate.rule_version,
            condition_key=candidate.condition_key,
            subject=candidate.subject,
            category=candidate.category,
            title_key=candidate.title_key,
            description_arguments=candidate.description_arguments,
            severity=candidate.severity,
            evidence=candidate.evidence,
            recommendation=candidate.recommendation,
            first_seen=seen_at,
            last_seen=seen_at,
            occurrence_count=1,
            latest_scan_id=scan_id,
            content_revision=1,
            material_digest=candidate.material_digest,
            lifecycle=FindingLifecycle.OPEN,
            review_state=ReviewState.NEW,
            coverage_state=coverage_state,
            snooze_until=None,
        )


def finding_is_diagnostic_entity(finding: Finding) -> bool:
    """Return whether this finding's subject is a diagnostic/optional
    Home Assistant entity rather than a primary one.

    Reads the real `home_assistant.entity.entity_category@1` evidence
    item every unavailable-entity finding carries (see
    analysis/analyzers/unavailable_entities.py) -- a finding without that
    evidence item (a different analyzer, or evidence predating this
    field) is conservatively treated as primary, never assumed
    diagnostic. Used to separate operational health from registry
    clutter (mission: hundreds of stale diagnostic entities must never
    be reported as the whole house being operationally unhealthy).
    """
    return any(
        item.predicate == "home_assistant.entity.entity_category@1"
        and item.value == "diagnostic"
        for item in finding.evidence
    )
