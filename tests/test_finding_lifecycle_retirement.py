"""Absence from analyzer output is not evidence of resolution.

`reconcile_findings` retires a finding only when the responsible analyzer
COVERED its subject in a fresh run and then did not emit a finding for it.
That gate had no direct test coverage, and three whole-collection analyzers
could never satisfy it:

* `duplicate_migration` emitted a finding for EVERY group it covered --
  including the benign LIKELY_DISTINCT_ENTITIES classification -- so
  "covered but clean" was unreachable by construction, and its condition_key
  is a constant, so all five classifications of a group share one finding id.
* `abandoned_bugfix_fork` added a member to covered_subjects only alongside
  that member's own finding, so a fork that was cleaned up stopped being
  covered at the exact moment it stopped being a defect.
* `automation_migration_residue` reported "examined, found no residue" as
  *uncovered*, making a fixed group look like one that was never examined.

Live evidence for the gap: 147 `unavailable_entities` findings had reached
`resolved`; `duplicate_migration`, `abandoned_bugfix_fork` and
`automation_migration_residue` had **zero** between them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hamie.analysis.supervisor import SupervisionResult
from hamie.application.reconciliation import reconcile_findings
from hamie.domain.evaluations import CoverageAssessment, CoverageState
from hamie.domain.dependencies import DependencyAssessment, DependencyCoverage
from hamie.domain.findings import (
    CandidateFinding,
    Confidence,
    ConfidenceFactor,
    ConfidenceLevel,
    EvidenceItem,
    Finding,
    FindingLifecycle,
    FindingSeverity,
    Recommendation,
    RecommendationKind,
    Risk,
    RiskLevel,
    SubjectIdentity,
)

NOW = datetime(2026, 8, 29, tzinfo=UTC)
ANALYZER = "hamie.duplicate_migration"
SUBJECT = "sensor.thing"


def _subject(source_id: str = SUBJECT) -> SubjectIdentity:
    return SubjectIdentity(
        durable_id=source_id,
        kind="hamie.duplicate_group",
        source_instance="test",
        source_id=source_id,
    )


def _candidate(source_id: str = SUBJECT, condition: str = "cond") -> CandidateFinding:
    subject = _subject(source_id)
    evidence = (
        EvidenceItem(
            subject=subject,
            predicate="test.predicate@1",
            value="present",
            observed_at=NOW,
            source_id="test-source",
            source_revision="rev-1",
        ),
    )
    return CandidateFinding(
        analyzer_id=ANALYZER,
        rule_version="1.0.0",
        condition_key=condition,
        subject=subject,
        category="duplicate_migration",
        title_key="test.title",
        description_arguments=(("k", "v"),),
        severity=FindingSeverity.WARNING,
        evidence=evidence,
        recommendation=Recommendation(
            kind=RecommendationKind.INVESTIGATE,
            action="Look at it.",
            rationale="test rationale",
            evidence=evidence,
            confidence=Confidence(
                level=ConfidenceLevel.HIGH,
                factors=(ConfidenceFactor(code="t", effect=10, rationale="test"),),
                rule_revision="1.0.0",
            ),
            dependency_assessment=DependencyAssessment(
                subject=subject,
                required_capabilities=(),
                used_capabilities=(),
                coverage=DependencyCoverage.COMPLETE,
                rationale="test dependency rationale",
            ),
            risk=Risk(
                likelihood=RiskLevel.LOW,
                impact=RiskLevel.LOW,
                reversible=True,
                affected_scope="test",
                overall=RiskLevel.LOW,
                rationale="test risk rationale",
            ),
            analyzer_id=ANALYZER,
            rule_revision="1.0.0",
        ),
    )


def _existing(source_id: str = SUBJECT, condition: str = "cond") -> Finding:
    return Finding.from_candidate(
        _candidate(source_id, condition),
        seen_at=NOW,
        scan_id="scan-1",
        coverage_state=CoverageState.COMPLETE,
    )


def _result(
    *,
    findings: tuple[CandidateFinding, ...] = (),
    covered: tuple[str, ...] = (),
    uncovered: tuple[str, ...] = (),
    excluded: tuple[str, ...] = (),
    state: CoverageState = CoverageState.COMPLETE,
) -> SupervisionResult:
    return SupervisionResult(
        findings=findings,
        coverage=CoverageAssessment(
            analyzer_id=ANALYZER,
            policy_version="1.0.0",
            state=state,
            requested_subjects=tuple(sorted({*covered, *uncovered, *excluded})),
            covered_subjects=covered,
            excluded_subjects=excluded,
            uncovered_subjects=uncovered,
        ),
        partitions_processed=1,
        partitions_skipped=0,
        analyzer_duration_ms=1,
        concurrency_used=1,
    )


def _reconcile(existing, result):
    return reconcile_findings((existing,), result, seen_at=NOW, scan_id="scan-2")


# ------------------------------------------------- conclusively disproven


def test_covered_and_not_emitted_resolves():
    """The one state that means "freshly disproven"."""
    findings, counts = _reconcile(_existing(), _result(covered=(SUBJECT,)))
    assert findings[0].lifecycle is FindingLifecycle.RESOLVED
    assert counts.resolved == 1


def test_excluded_subject_also_resolves():
    # Deliberately excluded by policy is still an authoritative evaluation.
    findings, _ = _reconcile(_existing(), _result(excluded=(SUBJECT,)))
    assert findings[0].lifecycle is FindingLifecycle.RESOLVED


# ------------------------------------------------------- NOT observed
#
# Every case below is "the finding was not emitted", and none of them are
# evidence that the defect is gone.


def test_not_observed_and_not_covered_stays_open():
    findings, counts = _reconcile(_existing(), _result(covered=("sensor.other",)))
    assert findings[0].lifecycle is FindingLifecycle.OPEN
    assert counts.resolved == 0


def test_uncovered_subject_never_resolves():
    # A run that reports gaps is PARTIAL by domain invariant; the subject it
    # could not evaluate must survive it untouched.
    findings, _ = _reconcile(
        _existing(), _result(uncovered=(SUBJECT,), state=CoverageState.PARTIAL)
    )
    assert findings[0].lifecycle is FindingLifecycle.OPEN


def test_analyzer_that_produced_nothing_at_all_resolves_nothing():
    # A failed or unrun analyzer covers nothing, so it can disprove nothing.
    findings, counts = _reconcile(_existing(), _result())
    assert findings[0].lifecycle is FindingLifecycle.OPEN
    assert counts.resolved == 0


def test_partial_coverage_still_requires_the_subject_to_be_covered():
    findings, _ = _reconcile(
        _existing(),
        _result(covered=("sensor.other",), uncovered=(SUBJECT,),
                state=CoverageState.PARTIAL),
    )
    assert findings[0].lifecycle is FindingLifecycle.OPEN


def test_a_different_analyzer_can_never_retire_this_finding():
    result = _result(covered=(SUBJECT,))
    other = SupervisionResult(
        findings=(),
        coverage=CoverageAssessment(
            analyzer_id="hamie.unavailable_entities",
            policy_version="1.0.0",
            state=CoverageState.COMPLETE,
            requested_subjects=(SUBJECT,),
            covered_subjects=(SUBJECT,),
        ),
        partitions_processed=1, partitions_skipped=0,
        analyzer_duration_ms=1, concurrency_used=1,
    )
    findings, _ = _reconcile(_existing(), other)
    assert findings[0].lifecycle is FindingLifecycle.OPEN
    # ...but its own analyzer still can.
    findings, _ = _reconcile(_existing(), result)
    assert findings[0].lifecycle is FindingLifecycle.RESOLVED


# ------------------------------------------------------- still present


def test_reemitted_finding_stays_open():
    findings, counts = _reconcile(
        _existing(), _result(findings=(_candidate(),), covered=(SUBJECT,))
    )
    assert findings[0].lifecycle is FindingLifecycle.OPEN
    assert counts.resolved == 0


def test_one_subject_resolves_while_another_stays_open():
    present, gone = _existing("sensor.present"), _existing("sensor.gone")
    result = _result(
        findings=(_candidate("sensor.present"),),
        covered=("sensor.present", "sensor.gone"),
    )
    findings, counts = reconcile_findings(
        (present, gone), result, seen_at=NOW, scan_id="scan-2"
    )
    by_id = {f.subject.source_id: f for f in findings}
    assert by_id["sensor.present"].lifecycle is FindingLifecycle.OPEN
    assert by_id["sensor.gone"].lifecycle is FindingLifecycle.RESOLVED
    assert counts.resolved == 1


def test_an_already_resolved_finding_is_not_resolved_twice():
    from dataclasses import replace

    resolved = replace(_existing(), lifecycle=FindingLifecycle.RESOLVED)
    findings, counts = _reconcile(resolved, _result(covered=(SUBJECT,)))
    assert counts.resolved == 0


def test_recurrence_reopens_a_resolved_finding():
    from dataclasses import replace

    resolved = replace(_existing(), lifecycle=FindingLifecycle.RESOLVED)
    findings, _ = _reconcile(
        resolved, _result(findings=(_candidate(),), covered=(SUBJECT,))
    )
    assert findings[0].lifecycle is FindingLifecycle.OPEN


def test_review_state_is_not_lifecycle_truth():
    """Dismissing something must not repair it."""
    from dataclasses import replace

    from hamie.domain.reviews import ReviewState

    dismissed = replace(_existing(), review_state=ReviewState.DISMISSED)
    findings, _ = _reconcile(
        dismissed, _result(findings=(_candidate(),), covered=(SUBJECT,))
    )
    assert findings[0].lifecycle is FindingLifecycle.OPEN
