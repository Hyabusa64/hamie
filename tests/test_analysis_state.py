"""What "All clear" is allowed to mean.

Production displayed, on one screen, all at once:

    412 incidents
    The selected findings' evidence is too large for the configured prompt size
    All clear

Each was rendered from real data. The contradiction came from deriving the
verdict from the wrong signal -- zero recommendations plus a *healthy* AI
connector -- when the provider was fine and the payload was too large.
"""

from __future__ import annotations

import pytest

from hamie.domain.analysis_state import (
    NON_AFFIRMATIVE_STATES,
    AnalysisInputs,
    AnalysisState,
    evaluate,
)

# The live numbers from the installation, 2026-08-27.
LIVE = AnalysisInputs(
    current_scan_id="b6858449ae9747f5a4fd2204fb6d8c44",
    analyzed_scan_id="b6858449ae9747f5a4fd2204fb6d8c44",
    eligible_total=1525,
    analyzed_total=94,
    groups_total=51,
    groups_analyzed=20,
    failed_groups=0,
    recommendation_total=0,
    high_priority_total=21,
    high_priority_unanalyzed=21,
    provider_status="healthy",
    ever_analyzed=True,
)

COMPLETE = AnalysisInputs(
    current_scan_id="scan-1",
    analyzed_scan_id="scan-1",
    eligible_total=40,
    analyzed_total=40,
    groups_total=6,
    groups_analyzed=6,
    recommendation_total=0,
    high_priority_total=2,
    high_priority_unanalyzed=0,
    provider_status="healthy",
    ever_analyzed=True,
)


def test_the_exact_production_contradiction_cannot_recur() -> None:
    status = evaluate(LIVE)
    assert status.all_clear_permitted is False
    assert status.state is AnalysisState.PARTIALLY_ANALYZED
    assert status.pending_total == 1431
    assert "high-priority" in status.reason


def test_all_clear_requires_full_coverage_of_the_current_scan() -> None:
    status = evaluate(COMPLETE)
    assert status.all_clear_permitted is True
    assert status.state is AnalysisState.COMPLETE
    assert status.pending_total == 0


@pytest.mark.parametrize(
    "override,expected",
    [
        ({"ever_analyzed": False}, AnalysisState.NOT_ANALYZED),
        ({"analysis_running": True}, AnalysisState.ANALYZING),
        ({"provider_status": "error"}, AnalysisState.PROVIDER_UNAVAILABLE),
        ({"provider_status": "degraded"}, AnalysisState.PROVIDER_UNAVAILABLE),
        ({"failed_groups": 6, "groups_analyzed": 0}, AnalysisState.FAILED),
        ({"analyzed_scan_id": "scan-0"}, AnalysisState.STALE),
        ({"analyzed_total": 30}, AnalysisState.PARTIALLY_ANALYZED),
        ({"groups_analyzed": 4}, AnalysisState.PARTIALLY_ANALYZED),
        ({"failed_groups": 1}, AnalysisState.PARTIALLY_ANALYZED),
        ({"high_priority_unanalyzed": 1}, AnalysisState.PARTIALLY_ANALYZED),
    ],
)
def test_every_incomplete_situation_forbids_all_clear(override, expected) -> None:
    from dataclasses import replace

    status = evaluate(replace(COMPLETE, **override))
    assert status.state is expected, status.reason
    assert status.all_clear_permitted is False
    assert status.state in NON_AFFIRMATIVE_STATES


def test_a_running_analysis_outranks_everything_else() -> None:
    from dataclasses import replace

    status = evaluate(replace(COMPLETE, analysis_running=True, provider_status="error"))
    assert status.state is AnalysisState.ANALYZING


def test_unanalyzed_high_priority_outranks_good_aggregate_coverage() -> None:
    """One unexamined safety defect matters more than 99% of examined noise."""
    from dataclasses import replace

    status = evaluate(
        replace(COMPLETE, eligible_total=1000, analyzed_total=1000, high_priority_unanalyzed=1)
    )
    assert status.all_clear_permitted is False
    assert "high-priority" in status.reason


def test_stale_analysis_is_not_all_clear_even_with_recommendations() -> None:
    from dataclasses import replace

    status = evaluate(
        replace(COMPLETE, recommendation_total=3, stale_recommendations=3)
    )
    assert status.state is AnalysisState.STALE
    assert status.all_clear_permitted is False


def test_some_stale_recommendations_do_not_block_a_fully_covered_scan() -> None:
    from dataclasses import replace

    status = evaluate(replace(COMPLETE, recommendation_total=3, stale_recommendations=1))
    assert status.all_clear_permitted is True


def test_reason_is_always_populated() -> None:
    from dataclasses import replace

    for override in ({}, {"ever_analyzed": False}, {"provider_status": "error"},
                     {"analyzed_total": 1}, {"analyzed_scan_id": "other"}):
        status = evaluate(replace(COMPLETE, **override))
        assert status.reason, override


def test_serialized_status_carries_the_counts_that_justify_it() -> None:
    data = evaluate(LIVE).as_dict()
    assert data["state"] == "partially_analyzed"
    assert data["all_clear_permitted"] is False
    assert data["eligible_total"] == 1525
    assert data["analyzed_total"] == 94
    assert data["pending_total"] == 1431
    assert data["groups_total"] == 51
    assert data["groups_analyzed"] == 20
    assert data["high_priority_unanalyzed"] == 21
    assert data["provider_status"] == "healthy"
    assert data["current_scan_id"] == LIVE.current_scan_id


def test_zero_findings_and_zero_incidents_is_genuinely_all_clear() -> None:
    status = evaluate(
        AnalysisInputs(
            current_scan_id="scan-1",
            analyzed_scan_id="scan-1",
            eligible_total=0,
            analyzed_total=0,
            groups_total=0,
            groups_analyzed=0,
            provider_status="healthy",
            ever_analyzed=True,
        )
    )
    assert status.all_clear_permitted is True


def test_a_never_run_provider_that_is_merely_disabled_is_not_all_clear() -> None:
    """Zero recommendations because nobody asked is not evidence of health."""
    status = evaluate(
        AnalysisInputs(
            current_scan_id="scan-1",
            eligible_total=1525,
            provider_status="disabled",
            ever_analyzed=False,
        )
    )
    assert status.state is AnalysisState.NOT_ANALYZED
    assert status.all_clear_permitted is False


def test_a_failed_group_is_not_reported_as_analyzed() -> None:
    """Live, a 16-finding group that failed still reported 'analyzed 3/16'.

    Planned coverage is not achieved coverage. Counting a model failure as
    progress is the exact way an installation comes to look partly examined
    when nothing was examined at all.
    """
    from dataclasses import replace

    status = evaluate(
        replace(
            COMPLETE,
            eligible_total=16,
            analyzed_total=0,
            groups_total=1,
            groups_analyzed=0,
            failed_groups=1,
        )
    )
    assert status.all_clear_permitted is False
    assert status.pending_total == 16
    assert status.state is AnalysisState.FAILED


def test_a_run_where_every_group_failed_reports_zero_analyzed() -> None:
    """Live, a run whose only group failed reported 'analyzed 1/16, failed 0'.

    When every group fails, the request re-raises before the commit path, so
    a failure list assigned only on success stayed empty and coverage fell
    back to reporting planned work. Total failure is the case most likely to
    be misread as progress, so it is the one that must be exact.
    """
    import inspect

    from hamie.application import operations_service

    source = inspect.getsource(operations_service)
    marker = "self._last_ai_failed_group_ids = tuple(failed_group_ids)"
    # Assigned in the per-group handler AND after the loop: the handler copy
    # is what survives a total failure, which re-raises before the loop ends.
    assert source.count(marker) >= 2, (
        "failure must be recorded inside the handler, not only after the loop"
    )
    append_at = source.index("failed_group_ids.append(group_id)")
    assert source.index(marker) > append_at, "recorded before the failure is known"


def test_total_failure_state_is_not_partially_analyzed() -> None:
    from dataclasses import replace

    status = evaluate(
        replace(COMPLETE, eligible_total=16, analyzed_total=0,
                groups_total=1, groups_analyzed=0, failed_groups=1)
    )
    assert status.state is AnalysisState.FAILED
    assert status.all_clear_permitted is False


# ------------------------------------------------- mixed-outcome coverage


def test_mixed_success_failure_and_skipped_accounting() -> None:
    """Coverage has had two real bugs; a single-success case proves nothing.

    The accounting invariant this pins, documented rather than forced:

        eligible = analyzed + skipped

    Findings in a FAILED group are not a third bucket -- they were selected,
    attempted, and rejected, so they return to the pending population and are
    counted in `skipped`. `failed_groups` counts GROUPS, not findings, which
    is why the arithmetic is over findings on one side and groups on the
    other.
    """
    from dataclasses import replace

    # 3 groups: one succeeded (5 findings), one failed (4), one never
    # attempted because the run was bounded (6). 15 eligible in total.
    status = evaluate(
        replace(
            COMPLETE,
            eligible_total=15,
            analyzed_total=5,
            groups_total=3,
            groups_analyzed=1,
            failed_groups=1,
            high_priority_unanalyzed=0,
        )
    )
    assert status.pending_total == 10, "failed + unattempted findings stay pending"
    assert status.state is AnalysisState.PARTIALLY_ANALYZED
    assert status.all_clear_permitted is False
    data = status.as_dict()
    assert data["analyzed_total"] == 5
    assert data["failed_groups"] == 1
    assert data["groups_analyzed"] == 1
    assert data["groups_total"] == 3
    assert data["eligible_total"] == data["analyzed_total"] + data["pending_total"]


def test_a_failed_group_never_contributes_to_analyzed() -> None:
    from dataclasses import replace

    succeeded_only = evaluate(
        replace(COMPLETE, eligible_total=9, analyzed_total=5,
                groups_total=2, groups_analyzed=1, failed_groups=0)
    )
    with_a_failure = evaluate(
        replace(COMPLETE, eligible_total=9, analyzed_total=5,
                groups_total=2, groups_analyzed=1, failed_groups=1)
    )
    assert succeeded_only.inputs.analyzed_total == with_a_failure.inputs.analyzed_total
    assert with_a_failure.all_clear_permitted is False


def test_skipped_findings_are_pending_not_analyzed_and_not_failed() -> None:
    """Bounding must never silently remove findings from the population."""
    from dataclasses import replace

    status = evaluate(
        replace(COMPLETE, eligible_total=30, analyzed_total=20,
                groups_total=2, groups_analyzed=2, failed_groups=0,
                high_priority_unanalyzed=0)
    )
    assert status.pending_total == 10
    assert status.state is AnalysisState.PARTIALLY_ANALYZED
    assert status.all_clear_permitted is False


def test_all_clear_only_when_nothing_failed_and_nothing_pends() -> None:
    from dataclasses import replace

    assert evaluate(COMPLETE).all_clear_permitted is True
    for override in (
        {"failed_groups": 1},
        {"analyzed_total": COMPLETE.eligible_total - 1},
        {"groups_analyzed": COMPLETE.groups_total - 1},
    ):
        assert evaluate(replace(COMPLETE, **override)).all_clear_permitted is False


# ----------------------------------------------------- scope separation
#
# Live defect: immediately after a 3-group bounded request the API reported
# groups_total=3, and after a restart the same unchanged installation reported
# groups_total=57 -- one branch computed request scope, the others computed
# installation scope. A metric that changes meaning depending on whether Home
# Assistant has rebooted becomes debugging folklore.


def test_installation_and_request_group_scopes_are_separate_fields():
    status = evaluate(
        AnalysisInputs(
            current_scan_id="s1",
            analyzed_scan_id="s1",
            eligible_total=50,
            analyzed_total=3,
            groups_total=57,
            groups_analyzed=3,
            request_groups_total=3,
            request_groups_analyzed=3,
        )
    )
    data = status.as_dict()
    assert data["groups_total"] == 57
    assert data["request_groups_total"] == 3
    assert data["groups_analyzed"] == 3
    assert data["request_groups_analyzed"] == 3


def test_installation_total_is_not_reduced_by_a_small_request():
    small = evaluate(
        AnalysisInputs(groups_total=57, groups_analyzed=1, request_groups_total=1,
                       request_groups_analyzed=1, eligible_total=9, analyzed_total=1)
    ).as_dict()
    large = evaluate(
        AnalysisInputs(groups_total=57, groups_analyzed=20, request_groups_total=20,
                       request_groups_analyzed=20, eligible_total=50, analyzed_total=20)
    ).as_dict()
    assert small["groups_total"] == large["groups_total"] == 57
    assert small["request_groups_total"] != large["request_groups_total"]


def test_request_scope_defaults_to_zero_when_nothing_was_requested():
    data = evaluate(AnalysisInputs(groups_total=57)).as_dict()
    assert data["groups_total"] == 57
    assert data["request_groups_total"] == 0
    assert data["request_groups_analyzed"] == 0
