"""Coverage-gated deterministic finding reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from ..analysis.supervisor import SupervisionResult
from ..domain.common import require_utc
from ..domain.findings import Finding, FindingLifecycle
from ..domain.reviews import ReviewAction, ReviewRecord, ReviewState


@dataclass(frozen=True, slots=True)
class ReconciliationCounts:
    """Finding reconciliation metrics."""

    created: int
    retained: int
    resolved: int
    unchanged: int


def reopen_expired_snoozes(
    findings: tuple[Finding, ...],
    reviews: tuple[ReviewRecord, ...],
    *,
    reconfirmed_finding_ids: frozenset[str],
    at: datetime,
) -> tuple[tuple[Finding, ...], tuple[ReviewRecord, ...]]:
    """Reopen expired snoozes only after a scan reconfirms the condition."""
    reopened_at = require_utc(at, "at")
    reopened: list[Finding] = []
    additions: list[ReviewRecord] = []
    for finding in findings:
        should_reopen = (
            finding.finding_id in reconfirmed_finding_ids
            and finding.lifecycle is FindingLifecycle.OPEN
            and finding.review_state is ReviewState.SNOOZED
            and finding.snooze_until is not None
            and finding.snooze_until <= reopened_at
        )
        if not should_reopen:
            reopened.append(finding)
            continue
        reopened.append(
            replace(finding, review_state=ReviewState.NEW, snooze_until=None)
        )
        additions.append(
            ReviewRecord(
                finding_id=finding.finding_id,
                action=ReviewAction.REOPEN,
                actor="hamie",
                at=reopened_at,
                finding_content_revision=finding.content_revision,
                prior_state=ReviewState.SNOOZED,
                resulting_state=ReviewState.NEW,
                reason="Snooze expired and the condition was reconfirmed.",
            )
        )
    return tuple(reopened), (*reviews, *additions)[-500:]


def record_policy_reopens(
    previous: tuple[Finding, ...],
    reconciled: tuple[Finding, ...],
    reviews: tuple[ReviewRecord, ...],
    *,
    at: datetime,
) -> tuple[tuple[Finding, ...], tuple[ReviewRecord, ...]]:
    """Append audits for material-change and recurrence review resets."""
    reopened_at = require_utc(at, "at")
    prior_by_id = {finding.finding_id: finding for finding in previous}
    additions: list[ReviewRecord] = []
    for finding in reconciled:
        prior = prior_by_id.get(finding.finding_id)
        if (
            prior is None
            or prior.review_state is ReviewState.NEW
            or finding.review_state is not ReviewState.NEW
        ):
            continue
        recurred = prior.lifecycle is FindingLifecycle.RESOLVED
        changed = prior.material_digest != finding.material_digest
        if not (recurred or changed):
            continue
        additions.append(
            ReviewRecord(
                finding_id=finding.finding_id,
                action=ReviewAction.REOPEN,
                actor="hamie",
                at=reopened_at,
                finding_content_revision=finding.content_revision,
                prior_state=prior.review_state,
                resulting_state=ReviewState.NEW,
                reason=(
                    "The condition recurred after resolution."
                    if recurred
                    else "The finding changed materially and requires review."
                ),
            )
        )
    return reconciled, (*reviews, *additions)[-500:]


def reconcile_findings(
    current: tuple[Finding, ...],
    result: SupervisionResult,
    *,
    seen_at: datetime,
    scan_id: str,
) -> tuple[tuple[Finding, ...], ReconciliationCounts]:
    """Reconcile candidates without resolving uncovered subjects."""
    at = require_utc(seen_at, "seen_at")
    by_id = {item.finding_id: item for item in current}
    candidate_ids: set[str] = set()
    created = retained = resolved = unchanged = 0

    for candidate in result.findings:
        candidate_ids.add(candidate.finding_id)
        existing = by_id.get(candidate.finding_id)
        if existing is None:
            by_id[candidate.finding_id] = Finding.from_candidate(
                candidate,
                seen_at=at,
                scan_id=scan_id,
                coverage_state=result.coverage.state,
            )
            created += 1
            continue
        material_changed = existing.material_digest != candidate.material_digest
        lifecycle_changed = existing.lifecycle is FindingLifecycle.RESOLVED
        by_id[candidate.finding_id] = replace(
            existing,
            rule_version=candidate.rule_version,
            subject=candidate.subject,
            category=candidate.category,
            title_key=candidate.title_key,
            description_arguments=candidate.description_arguments,
            severity=candidate.severity,
            evidence=candidate.evidence,
            recommendation=candidate.recommendation,
            last_seen=at,
            occurrence_count=existing.occurrence_count + 1,
            latest_scan_id=scan_id,
            content_revision=(
                existing.content_revision + 1
                if material_changed
                else existing.content_revision
            ),
            material_digest=candidate.material_digest,
            lifecycle=FindingLifecycle.OPEN,
            review_state=(
                ReviewState.NEW
                if material_changed or lifecycle_changed
                else existing.review_state
            ),
            snooze_until=(
                None if material_changed or lifecycle_changed else existing.snooze_until
            ),
            coverage_state=result.coverage.state,
        )
        if material_changed or lifecycle_changed:
            retained += 1
        else:
            unchanged += 1

    conclusively_absent = set(result.coverage.covered_subjects) | set(
        result.coverage.excluded_subjects
    )
    for finding_id, existing in tuple(by_id.items()):
        if (
            existing.analyzer_id != result.coverage.analyzer_id
            or finding_id in candidate_ids
            or existing.lifecycle is FindingLifecycle.RESOLVED
            or existing.subject.source_id not in conclusively_absent
        ):
            continue
        by_id[finding_id] = replace(
            existing,
            latest_scan_id=scan_id,
            lifecycle=FindingLifecycle.RESOLVED,
            coverage_state=result.coverage.state,
        )
        resolved += 1

    return (
        tuple(sorted(by_id.values(), key=lambda item: item.finding_id)),
        ReconciliationCounts(created, retained, resolved, unchanged),
    )
