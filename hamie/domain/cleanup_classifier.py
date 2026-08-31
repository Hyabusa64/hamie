"""Deterministic cleanup classification engine (mission Part 3/4).

Turns raw unavailable-entity evidence into exactly one of nine
mission-defined outcomes. Pure and I/O-free, like every other
``domain/`` module: every input here is already computed by a caller
(the analyzer's evidence, ``domain/dependency_references.py``'s
coverage/reference data, and configured policy) -- this module only
applies deterministic rules, never fetches anything and never asks an
LLM.

Design intent: for ~500 raw findings, HAMIE should produce a small
number of useful decisions, not 500 equally-weighted warnings. This
classifier is the mechanism -- every candidate lands in exactly one
bucket, and every bucket has an unambiguous next step (auto-fix, ask
for approval, keep for manual review, or explain why it is blocked).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .common import require_non_empty
from .dependency_references import DependencyScanCoverage

MINIMUM_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
PARENT_FAILURE_RATIO_THRESHOLD = 0.6
MIN_SIBLINGS_FOR_PARENT_FAILURE = 3


class CleanupClassification(StrEnum):
    """Every cleanup candidate lands in exactly one of these (mission Part 3)."""

    SAFE_AUTO_FIX = "safe_auto_fix"
    SAFE_WITH_APPROVAL = "safe_with_approval"
    MANUAL_REVIEW = "manual_review"
    BLOCKED_DEPENDENCY = "blocked_dependency"
    BLOCKED_UNCERTAIN = "blocked_uncertain"
    TRANSIENT_ISSUE = "transient_issue"
    PARENT_INTEGRATION_FAILURE = "parent_integration_failure"
    EXPECTED_BEHAVIOR = "expected_behavior"
    ALREADY_CLEAN = "already_clean"


# Classifications a cleanup batch may ever auto-execute or offer for
# one-click approval -- every other classification is display-only /
# blocked and can never reach an execution path.
ACTIONABLE_CLASSIFICATIONS = frozenset(
    {CleanupClassification.SAFE_AUTO_FIX, CleanupClassification.SAFE_WITH_APPROVAL}
)


@dataclass(frozen=True, slots=True)
class CleanupPolicy:
    """The configured cleanup-eligibility policy (mission Part 2)."""

    minimum_unavailable_duration_seconds: int
    minimum_confidence: str
    dependency_coverage_requirement: str  # "complete" | "partial_allowed"
    excluded_integrations: frozenset[str] = frozenset()
    excluded_devices: frozenset[str] = frozenset()
    excluded_entity_domains: frozenset[str] = frozenset()
    excluded_entity_ids: frozenset[str] = frozenset()
    excluded_areas: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.minimum_unavailable_duration_seconds < 0:
            raise ValueError("minimum_unavailable_duration_seconds cannot be negative")
        if self.minimum_confidence not in MINIMUM_CONFIDENCE_RANK:
            raise ValueError("minimum_confidence must be low, medium, or high")
        if self.dependency_coverage_requirement not in {"complete", "partial_allowed"}:
            raise ValueError(
                "dependency_coverage_requirement must be complete or partial_allowed"
            )


@dataclass(frozen=True, slots=True)
class CleanupCandidate:
    """Everything the classifier needs about one entity, pre-computed."""

    entity_id: str
    domain: str
    entity_category: str | None
    already_disabled: bool
    unavailable_seconds: int | None
    dependency_coverage: DependencyScanCoverage
    referenced_by_count: int
    integration: str | None = None
    device_id: str | None = None
    area_id: str | None = None
    parent_unavailable_ratio: float | None = None
    parent_sibling_count: int = 0
    ai_confidence: str | None = None
    expected_unavailable: bool = False
    expected_unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.entity_id, "entity_id")
        require_non_empty(self.domain, "domain")
        if self.unavailable_seconds is not None and self.unavailable_seconds < 0:
            raise ValueError("unavailable_seconds cannot be negative")
        if self.referenced_by_count < 0:
            raise ValueError("referenced_by_count cannot be negative")
        if self.parent_unavailable_ratio is not None and not (
            0.0 <= self.parent_unavailable_ratio <= 1.0
        ):
            raise ValueError("parent_unavailable_ratio must be between 0 and 1")
        if self.ai_confidence is not None and self.ai_confidence not in (
            MINIMUM_CONFIDENCE_RANK
        ):
            raise ValueError("ai_confidence must be low, medium, or high")


class CleanupReasonCode(StrEnum):
    """Machine-readable reason behind every ``CleanupDecision``.

    ``CleanupDecision.reason`` is free English prose meant for a human;
    this is its stable, aggregatable counterpart -- forensic tooling and
    the "why isn't this actionable?" UI both need to group and count
    decisions without parsing sentences.
    """

    POLICY_EXCLUDED = "policy_excluded"
    ALREADY_DISABLED = "already_disabled"
    CURRENTLY_AVAILABLE = "currently_available"
    EXPECTED_UNAVAILABLE = "expected_unavailable"
    PARENT_HEALTH_UNKNOWN = "parent_health_unknown"
    UNAVAILABLE_DURATION_INSUFFICIENT = "unavailable_duration_insufficient"
    DYNAMIC_REFERENCE_UNRESOLVED = "dynamic_reference_unresolved"
    DEPENDENCY_COVERAGE_INCOMPLETE = "dependency_coverage_incomplete"
    AI_CONFIDENCE_BELOW_MINIMUM = "ai_confidence_below_minimum"
    SAFE_OPTIONAL_ENTITY = "safe_optional_entity"
    SAFE_PRIMARY_ENTITY = "safe_primary_entity"


@dataclass(frozen=True, slots=True)
class CleanupDecision:
    """One classification result with its concrete, cited reason."""

    entity_id: str
    classification: CleanupClassification
    reason: str
    reason_code: CleanupReasonCode
    blocking_factors: tuple[str, ...] = ()

    @property
    def is_actionable(self) -> bool:
        return self.classification in ACTIONABLE_CLASSIFICATIONS


def classify_cleanup_candidate(
    candidate: CleanupCandidate, policy: CleanupPolicy
) -> CleanupDecision:
    """Classify one candidate. Never raises for an ordinary business reason."""

    def _decision(
        classification: CleanupClassification,
        reason: str,
        reason_code: CleanupReasonCode,
        *,
        blocking: tuple[str, ...] = (),
    ) -> CleanupDecision:
        return CleanupDecision(
            entity_id=candidate.entity_id,
            classification=classification,
            reason=reason,
            reason_code=reason_code,
            blocking_factors=blocking,
        )

    excluded_by = _matched_exclusion(candidate, policy)
    if excluded_by is not None:
        return _decision(
            CleanupClassification.MANUAL_REVIEW,
            f"excluded from automatic cleanup by configured policy: {excluded_by}",
            CleanupReasonCode.POLICY_EXCLUDED,
            blocking=(excluded_by,),
        )

    if candidate.already_disabled:
        return _decision(
            CleanupClassification.ALREADY_CLEAN,
            "entity is already disabled",
            CleanupReasonCode.ALREADY_DISABLED,
        )

    if candidate.unavailable_seconds is None:
        return _decision(
            CleanupClassification.ALREADY_CLEAN,
            "entity is currently available",
            CleanupReasonCode.CURRENTLY_AVAILABLE,
        )

    if candidate.expected_unavailable:
        return _decision(
            CleanupClassification.EXPECTED_BEHAVIOR,
            candidate.expected_unavailable_reason
            or "evidence indicates this unavailability is expected",
            CleanupReasonCode.EXPECTED_UNAVAILABLE,
        )

    if (
        candidate.entity_category not in {"diagnostic", "config"}
        and candidate.parent_unavailable_ratio is not None
        and candidate.parent_sibling_count >= MIN_SIBLINGS_FOR_PARENT_FAILURE
        and candidate.parent_unavailable_ratio >= PARENT_FAILURE_RATIO_THRESHOLD
    ):
        percent = round(candidate.parent_unavailable_ratio * 100)
        return _decision(
            CleanupClassification.PARENT_INTEGRATION_FAILURE,
            f"{percent}% of {candidate.parent_sibling_count} sibling entities from "
            "the same integration/device are also unavailable -- the integration "
            "or device is the root cause, not this individual entity",
            CleanupReasonCode.PARENT_HEALTH_UNKNOWN,
        )

    if candidate.unavailable_seconds < policy.minimum_unavailable_duration_seconds:
        return _decision(
            CleanupClassification.TRANSIENT_ISSUE,
            "has not been unavailable long enough yet to qualify for cleanup "
            f"({candidate.unavailable_seconds}s < "
            f"{policy.minimum_unavailable_duration_seconds}s configured minimum)",
            CleanupReasonCode.UNAVAILABLE_DURATION_INSUFFICIENT,
        )

    if candidate.referenced_by_count > 0:
        return _decision(
            CleanupClassification.BLOCKED_DEPENDENCY,
            f"referenced by {candidate.referenced_by_count} object(s)",
            CleanupReasonCode.DYNAMIC_REFERENCE_UNRESOLVED,
        )

    coverage_ok = (
        candidate.dependency_coverage.implemented_sources_succeeded
        if policy.dependency_coverage_requirement == "complete"
        else not (
            candidate.dependency_coverage.failed_sources
        )  # partial_allowed still requires no outright scan failures
    )
    if not coverage_ok:
        blocking = (
            *candidate.dependency_coverage.failed_sources,
            *candidate.dependency_coverage.unavailable_sources,
        )
        return _decision(
            CleanupClassification.BLOCKED_UNCERTAIN,
            "dependency coverage requirement not met "
            f"({policy.dependency_coverage_requirement})",
            CleanupReasonCode.DEPENDENCY_COVERAGE_INCOMPLETE,
            blocking=blocking,
        )

    if candidate.ai_confidence is not None and (
        MINIMUM_CONFIDENCE_RANK[candidate.ai_confidence]
        < MINIMUM_CONFIDENCE_RANK[policy.minimum_confidence]
    ):
        return _decision(
            CleanupClassification.BLOCKED_UNCERTAIN,
            f"AI confidence ({candidate.ai_confidence}) is below the configured "
            f"minimum ({policy.minimum_confidence})",
            CleanupReasonCode.AI_CONFIDENCE_BELOW_MINIMUM,
        )

    if candidate.entity_category in {"diagnostic", "config"}:
        return _decision(
            CleanupClassification.SAFE_AUTO_FIX,
            "optional diagnostic/configuration entity, unreferenced among "
            "scanned sources, unavailable past the configured minimum duration",
            CleanupReasonCode.SAFE_OPTIONAL_ENTITY,
        )
    return _decision(
        CleanupClassification.SAFE_WITH_APPROVAL,
        "primary entity, unreferenced among scanned sources, unavailable past "
        "the configured minimum duration -- requires approval because it is "
        "not a diagnostic/configuration entity",
        CleanupReasonCode.SAFE_PRIMARY_ENTITY,
    )


def _matched_exclusion(
    candidate: CleanupCandidate, policy: CleanupPolicy
) -> str | None:
    if candidate.integration and candidate.integration in policy.excluded_integrations:
        return f"integration:{candidate.integration}"
    if candidate.device_id and candidate.device_id in policy.excluded_devices:
        return f"device:{candidate.device_id}"
    if candidate.domain in policy.excluded_entity_domains:
        return f"domain:{candidate.domain}"
    if candidate.entity_id in policy.excluded_entity_ids:
        return f"entity:{candidate.entity_id}"
    if candidate.area_id and candidate.area_id in policy.excluded_areas:
        return f"area:{candidate.area_id}"
    return None


@dataclass(frozen=True, slots=True)
class EntityAvailabilitySignal:
    """One entity's device/category/availability, independent of whether
    it is itself an open cleanup candidate.

    Computing a device's primary-entity outage ratio from only the
    entities that already happen to be open findings is self-fulfilling
    -- every candidate is, by construction, already unavailable, so any
    device with three or more non-diagnostic open findings would always
    show a 100% ratio regardless of how many of that device's *other*
    entities are perfectly healthy. This signal instead comes from the
    device's **complete** live entity population (available and
    unavailable alike), so the ratio reflects the device's actual
    health, not just the shape of today's findings.
    """

    entity_id: str
    device_id: str | None
    entity_category: str | None
    is_unavailable: bool


class BenchmarkTaxonomy(StrEnum):
    """The independent entity-hygiene benchmark's four-way outcome model
    (see ``benchmark/entity_hygiene_dry_run_report.md``).

    Distinct from ``CleanupClassification`` on purpose:
    ``CleanupClassification`` is HAMIE's own richer, execution-oriented
    nine-way model (mission Part 3) with separate buckets for *why*
    something is blocked (dependency vs. uncertain vs. policy-excluded,
    etc.) that the remediation subsystem and presentation layer already
    consume; this is purely a comparison-only projection of that model
    (plus the new orphaned-definition analyzer's output) onto the
    benchmark's coarser vocabulary, used only by
    ``benchmark/run_validation.py``. Nothing in ``ACTIONABLE_CLASSIFICATIONS``
    or ``CleanupDecision`` changes -- this is strictly additive.
    """

    KEEP = "KEEP"
    DISABLE_CANDIDATE = "DISABLE_CANDIDATE"
    DELETE_CANDIDATE = "DELETE_CANDIDATE"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"


# Every one of HAMIE's nine cleanup classifications maps onto exactly
# one benchmark bucket. SAFE_AUTO_FIX/SAFE_WITH_APPROVAL are HAMIE's
# "this candidate cleared every check" outcomes for *unavailable*
# entities -- the benchmark's closest analogue is DISABLE_CANDIDATE
# (HAMIE is advisory-only and never proposes deletion for this
# analyzer; see cleanup_classifier module docstring). Everything
# HAMIE blocks on missing/uncertain evidence maps to NEEDS_EVIDENCE;
# every other outcome (already clean, expected, transient, blocked by
# a real dependency, or explained by a parent-integration failure) is
# a real KEEP -- HAMIE has an affirmative reason not to touch it, not
# merely insufficient evidence.
_CLASSIFICATION_TO_TAXONOMY: dict[CleanupClassification, BenchmarkTaxonomy] = {
    CleanupClassification.SAFE_AUTO_FIX: BenchmarkTaxonomy.DISABLE_CANDIDATE,
    CleanupClassification.SAFE_WITH_APPROVAL: BenchmarkTaxonomy.DISABLE_CANDIDATE,
    CleanupClassification.MANUAL_REVIEW: BenchmarkTaxonomy.NEEDS_EVIDENCE,
    CleanupClassification.BLOCKED_DEPENDENCY: BenchmarkTaxonomy.KEEP,
    CleanupClassification.BLOCKED_UNCERTAIN: BenchmarkTaxonomy.NEEDS_EVIDENCE,
    CleanupClassification.TRANSIENT_ISSUE: BenchmarkTaxonomy.KEEP,
    CleanupClassification.PARENT_INTEGRATION_FAILURE: BenchmarkTaxonomy.KEEP,
    CleanupClassification.EXPECTED_BEHAVIOR: BenchmarkTaxonomy.KEEP,
    CleanupClassification.ALREADY_CLEAN: BenchmarkTaxonomy.KEEP,
}


def to_benchmark_taxonomy(decision: CleanupDecision) -> BenchmarkTaxonomy:
    """Project one ``CleanupDecision`` onto the benchmark's four-way model."""
    return _CLASSIFICATION_TO_TAXONOMY[decision.classification]


def orphaned_definition_taxonomy(*, referenced_by_count: int) -> BenchmarkTaxonomy:
    """Benchmark-comparable classification for one
    ``hamie.orphaned_definitions`` finding (mission Part 3/4).

    A definition genuinely absent from live config, with zero
    references found among scanned sources, is exactly the
    DELETE_CANDIDATE case the benchmark's own methodology defines (see
    "DELETE_CANDIDATE -- orphaned automation/script/scene registry
    entries" in ``benchmark/entity_hygiene_dry_run_report.md``). A
    definition-missing entity that is *still* referenced somewhere
    scanned is downgraded to NEEDS_EVIDENCE rather than trusted
    outright -- matching this module's existing dependency-first
    conservatism (see ``BLOCKED_DEPENDENCY`` above).
    """
    if referenced_by_count < 0:
        raise ValueError("referenced_by_count cannot be negative")
    if referenced_by_count > 0:
        return BenchmarkTaxonomy.NEEDS_EVIDENCE
    return BenchmarkTaxonomy.DELETE_CANDIDATE


def compute_parent_unavailable_ratios(
    signals: tuple[EntityAvailabilitySignal, ...],
) -> dict[str, tuple[float, int]]:
    """Compute each device's unavailable-sibling ratio from its full population.

    Pure grouping helper: returns ``{"device:<id>": (ratio, member_count)}``.

    Deliberately considers only **primary** (non-diagnostic/config)
    members for both the numerator and the denominator, and groups by
    device only (not by integration) -- one struggling device's primary
    entity must never taint every other, otherwise-healthy device under
    the same integration. A device that exposes hundreds of optional
    diagnostic/feature entities which are *always* unavailable because
    those features simply aren't in use (the mission's own "148
    optional Dreame entities appear unused" example) must never be
    misclassified as a device outage just because every one of those
    optional entities is unavailable -- that is the normal, expected
    state, not a failure signal. A genuine outage is a *primary* entity
    (the vacuum itself, the hub, the sensor a user actually relies on)
    going unavailable among a device's *entire* primary population, not
    just the fraction of it that already happens to be a finding.
    """
    groups: dict[str, list[EntityAvailabilitySignal]] = {}
    for signal in signals:
        if signal.entity_category in {"diagnostic", "config"}:
            continue
        if not signal.device_id:
            continue
        groups.setdefault(f"device:{signal.device_id}", []).append(signal)
    result: dict[str, tuple[float, int]] = {}
    for key, members in groups.items():
        total = len(members)
        unavailable = sum(1 for item in members if item.is_unavailable)
        result[key] = (unavailable / total if total else 0.0, total)
    return result
