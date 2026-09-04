"""Deterministic reconciliation for canonical recommendations (Phase 2A).

Matches newly detected candidate recommendations against previously
persisted ones by deterministic fingerprint (see
``compute_recommendation_fingerprint`` in ``recommendation.py``),
updates occurrence tracking and evidence in place, distinguishes
recurrence from continued occurrence, and never silently resolves a
recommendation whose absence from a scan is not actually proven by
complete detector coverage.

Nothing here calls Home Assistant, a connector, or performs I/O -- pure,
deterministic, unit-testable domain logic, matching the rest of
``domain/``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from .common import require_utc
from .recommendation import (
    CanonicalRecommendation,
    DependencyAnalysisResult,
    RecommendationLifecycleState,
    RecommendationReviewState,
    compute_content_digest_from_parts,
)

# Lifecycle states from which a matching candidate counts as a genuine
# recurrence (the issue was considered handled and has come back), as
# opposed to a snoozed recommendation resurfacing on its own schedule or
# an already-active one simply being observed again.
_RECURRENCE_SOURCE_STATES = frozenset(
    {
        RecommendationLifecycleState.RESOLVED,
        RecommendationLifecycleState.DISMISSED,
        RecommendationLifecycleState.SUPERSEDED,
        RecommendationLifecycleState.INVALIDATED,
    }
)

# Ordinal completeness of a dependency analysis, used only to decide
# whether an incoming candidate's dependency_analysis may safely replace
# an existing one -- a re-scan that did not even attempt dependency
# analysis must never silently erase a prior, more complete result.
_DEPENDENCY_COMPLETENESS_RANK = {
    "not_started": 0,
    "unavailable": 1,
    "failed": 1,
    "incomplete": 2,
    "complete": 3,
}


@dataclass(frozen=True, slots=True)
class ReconciliationOutcome:
    """One recommendation's fate during a single reconciliation pass."""

    fingerprint: str
    recommendation_id: str
    # "inserted" | "updated" | "recurred" | "unchanged" | "resolved" |
    # "rejected_stale"
    action: str


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """The complete, deterministic outcome of one reconciliation pass."""

    recommendations: tuple[CanonicalRecommendation, ...]
    outcomes: tuple[ReconciliationOutcome, ...]

    @property
    def inserted(self) -> tuple[str, ...]:
        return tuple(
            item.fingerprint for item in self.outcomes if item.action == "inserted"
        )

    @property
    def recurred(self) -> tuple[str, ...]:
        return tuple(
            item.fingerprint for item in self.outcomes if item.action == "recurred"
        )

    @property
    def resolved(self) -> tuple[str, ...]:
        return tuple(
            item.fingerprint for item in self.outcomes if item.action == "resolved"
        )

    @property
    def rejected_stale(self) -> tuple[str, ...]:
        return tuple(
            item.fingerprint
            for item in self.outcomes
            if item.action == "rejected_stale"
        )


def _merge_dependency_analysis(
    existing: CanonicalRecommendation, candidate: CanonicalRecommendation
) -> DependencyAnalysisResult:
    existing_rank = _DEPENDENCY_COMPLETENESS_RANK[
        existing.dependency_analysis.status.value
    ]
    candidate_rank = _DEPENDENCY_COMPLETENESS_RANK[
        candidate.dependency_analysis.status.value
    ]
    if candidate_rank >= existing_rank:
        return candidate.dependency_analysis
    return existing.dependency_analysis


def _reconcile_one(
    existing: CanonicalRecommendation,
    candidate: CanonicalRecommendation,
    *,
    seen_at: datetime,
    scan_id: str,
) -> tuple[CanonicalRecommendation, str]:
    """Merge one matched candidate into its existing record."""
    if candidate.last_seen_at < existing.last_seen_at:
        # A late-arriving or out-of-order scan result must never overwrite
        # fresher persisted data.
        return existing, "rejected_stale"

    merged_evidence = existing.evidence + candidate.evidence
    dependency_analysis = _merge_dependency_analysis(existing, candidate)

    is_recurrence = existing.lifecycle_state in _RECURRENCE_SOURCE_STATES
    snooze_expired = (
        existing.lifecycle_state is RecommendationLifecycleState.SNOOZED
        and existing.snoozed_until is not None
        and seen_at >= existing.snoozed_until
    )
    snooze_active = (
        existing.lifecycle_state is RecommendationLifecycleState.SNOOZED
        and not snooze_expired
    )

    disposition = candidate.disposition
    summary = candidate.summary
    risk = candidate.risk
    confidence = candidate.confidence

    lifecycle_state = existing.lifecycle_state
    review_state = existing.review_state
    resolved_at = existing.resolved_at
    resolution_reason = existing.resolution_reason
    dismissed_at = existing.dismissed_at
    dismissal_reason = existing.dismissal_reason
    superseded_by = existing.superseded_by
    snoozed_until = existing.snoozed_until
    recurrence_count = existing.recurrence_count

    if snooze_active:
        # Respect the snooze: keep accumulating evidence/occurrence in the
        # background, but do not wake the recommendation or reset review.
        action = "updated"
    elif is_recurrence or snooze_expired:
        lifecycle_state = RecommendationLifecycleState.ACTIVE
        review_state = RecommendationReviewState.UNREVIEWED
        resolved_at = None
        resolution_reason = None
        dismissed_at = None
        dismissal_reason = None
        superseded_by = None
        snoozed_until = None
        if is_recurrence:
            recurrence_count = existing.recurrence_count + 1
        action = "recurred"
    else:
        action = "updated"

    new_digest = compute_content_digest_from_parts(
        fingerprint=existing.fingerprint,
        category=existing.category,
        subtype=existing.subtype,
        disposition=disposition,
        summary=summary,
        risk=risk,
        confidence=confidence,
        dependency_analysis=dependency_analysis,
        evidence=merged_evidence,
    )
    content_revision = existing.content_revision
    content_digest = existing.content_digest
    if new_digest != existing.content_digest:
        content_revision = existing.content_revision + 1
        content_digest = new_digest
    elif action == "updated" and {item.evidence_id for item in candidate.evidence} <= {
        item.evidence_id for item in existing.evidence
    }:
        # Nothing at all changed -- same content, no newly distinct
        # evidence (comparing by evidence_id, not raw equality, since an
        # identical observation re-collected later has a new
        # observed_at). Still bump last_seen_at/occurrence_count (a real
        # re-observation happened) but report it distinctly.
        action = "unchanged"

    updated = replace(
        existing,
        last_seen_at=candidate.last_seen_at,
        last_scan_id=scan_id,
        occurrence_count=existing.occurrence_count + 1,
        evidence=merged_evidence,
        dependency_analysis=dependency_analysis,
        risk=risk,
        confidence=confidence,
        title=candidate.title,
        summary=summary,
        detailed_explanation=candidate.detailed_explanation,
        disposition=disposition,
        suggested_action=candidate.suggested_action,
        alternatives=candidate.alternatives,
        supporting_objects=candidate.supporting_objects,
        updated_at=seen_at,
        lifecycle_state=lifecycle_state,
        review_state=review_state,
        resolved_at=resolved_at,
        resolution_reason=resolution_reason,
        dismissed_at=dismissed_at,
        dismissal_reason=dismissal_reason,
        superseded_by=superseded_by,
        snoozed_until=snoozed_until,
        recurrence_count=recurrence_count,
        content_revision=content_revision,
        content_digest=content_digest,
    )
    return updated, action


def reconcile_recommendations(
    existing: tuple[CanonicalRecommendation, ...],
    candidates: tuple[CanonicalRecommendation, ...],
    *,
    scan_id: str,
    seen_at: datetime,
    complete_coverage_fingerprints: frozenset[str] = frozenset(),
) -> ReconciliationResult:
    """Reconcile newly detected candidates against persisted recommendations.

    ``complete_coverage_fingerprints`` must contain exactly the
    fingerprints this scan had complete, authoritative detector coverage
    for. An existing active recommendation whose fingerprint is *not* in
    that set is never auto-resolved just because it is absent from
    ``candidates`` -- absence only proves resolution when coverage
    proves the detector actually looked and found nothing. Passing an
    empty set (the default) is always safe: it just means nothing gets
    auto-resolved this pass.
    """
    seen_at = require_utc(seen_at, "seen_at")
    existing_by_fingerprint = {item.fingerprint: item for item in existing}
    candidate_fingerprints = {item.fingerprint for item in candidates}

    results: dict[str, CanonicalRecommendation] = dict(existing_by_fingerprint)
    outcomes: list[ReconciliationOutcome] = []

    for candidate in candidates:
        matched = existing_by_fingerprint.get(candidate.fingerprint)
        if matched is None:
            results[candidate.fingerprint] = candidate
            outcomes.append(
                ReconciliationOutcome(
                    fingerprint=candidate.fingerprint,
                    recommendation_id=candidate.recommendation_id,
                    action="inserted",
                )
            )
            continue
        updated, action = _reconcile_one(
            matched, candidate, seen_at=seen_at, scan_id=scan_id
        )
        results[candidate.fingerprint] = updated
        outcomes.append(
            ReconciliationOutcome(
                fingerprint=candidate.fingerprint,
                recommendation_id=updated.recommendation_id,
                action=action,
            )
        )

    for fingerprint, current in existing_by_fingerprint.items():
        if fingerprint in candidate_fingerprints:
            continue
        if current.lifecycle_state is not RecommendationLifecycleState.ACTIVE:
            continue
        if fingerprint not in complete_coverage_fingerprints:
            continue
        resolved = replace(
            current,
            lifecycle_state=RecommendationLifecycleState.RESOLVED,
            resolved_at=seen_at,
            resolution_reason=(
                "not detected in a scan with complete detector coverage "
                f"for this issue (scan {scan_id})"
            ),
            last_scan_id=scan_id,
            updated_at=seen_at,
        )
        results[fingerprint] = resolved
        outcomes.append(
            ReconciliationOutcome(
                fingerprint=fingerprint,
                recommendation_id=resolved.recommendation_id,
                action="resolved",
            )
        )

    ordered = tuple(sorted(results.values(), key=lambda item: item.recommendation_id))
    return ReconciliationResult(recommendations=ordered, outcomes=tuple(outcomes))
