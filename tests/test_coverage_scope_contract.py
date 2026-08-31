"""One field name, one scope -- wherever it is read.

Live defect: a mixed run reported `groups_analyzed: 2` inside the analyze
response's embedded coverage block while the authoritative analysis state
correctly reported 1 achieved and 1 failed. Both were "right" under their own
local meaning, which is exactly the problem: the embedded block is the set of
planned batches, and it borrowed the names the authoritative state uses for
achieved installation-scope counts. A correct store with a misleading API
still generates false bug reports.

The contract pinned here: request-scope fields carry request-scope names, and
no name means one thing in the response and another in the state.
"""

from __future__ import annotations

from hamie.domain.analysis_state import AnalysisInputs, evaluate
from hamie.domain.intelligence import AIAnalysisCoverage

#: Names owned exclusively by the authoritative analysis state.
INSTALLATION_SCOPE_NAMES = frozenset(
    {"groups_total", "groups_analyzed", "analyzed_total", "eligible_total",
     "failed_groups", "pending_total"}
)


def _coverage(selected=3, groups=2, skipped=1):
    return AIAnalysisCoverage(
        eligible_total=selected + skipped,
        selected_finding_ids=tuple(f"f{i}" for i in range(selected)),
        skipped_finding_ids=tuple(f"s{i}" for i in range(skipped)),
        total_findings=1000,
        root_cause_group_ids=tuple(f"grp_{i}" for i in range(groups)),
        analyzed_group_ids=tuple(f"grp_{i}" for i in range(groups)),
    )


def test_embedded_coverage_declares_its_scope():
    assert _coverage().public_dict()["scope"] == "request"


def test_embedded_coverage_never_reuses_installation_scope_names():
    keys = set(_coverage().public_dict())
    collisions = keys & INSTALLATION_SCOPE_NAMES
    assert not collisions, f"request-scope block reuses state names: {collisions}"


def test_provider_view_never_reuses_installation_scope_names():
    keys = set(_coverage().provider_dict())
    assert not (keys & INSTALLATION_SCOPE_NAMES)


def test_the_exact_mixed_run_that_exposed_the_collision():
    # Two groups selected, one succeeded. The response says "2 selected";
    # the state says "1 analyzed, 1 failed". Both true, neither ambiguous.
    response = _coverage(selected=2, groups=2, skipped=0).public_dict()
    state = evaluate(
        AnalysisInputs(
            groups_total=57, groups_analyzed=1, failed_groups=1,
            request_groups_total=2, request_groups_analyzed=1,
            eligible_total=2, analyzed_total=1,
        )
    ).as_dict()
    assert response["request_groups_selected"] == 2
    assert state["groups_analyzed"] == 1
    assert state["failed_groups"] == 1
    assert state["request_groups_total"] == 2
    # The old defect in one line: no shared name may disagree.
    for name in set(response) & set(state):
        assert response[name] == state[name], (
            f"{name!r} means different things in the response and the state"
        )


def test_selected_total_duplicate_is_gone():
    # analyzed_total in this block was literally len(selected_finding_ids) --
    # a duplicate of selected_total wearing an authoritative name.
    data = _coverage().public_dict()
    assert "analyzed_total" not in data
    assert data["request_selected_total"] == 3


def test_installation_total_keeps_its_name_because_it_is_global():
    assert _coverage().public_dict()["total_findings"] == 1000


def test_a_smaller_request_does_not_shrink_installation_scope():
    one = evaluate(AnalysisInputs(groups_total=57, request_groups_total=1)).as_dict()
    five = evaluate(AnalysisInputs(groups_total=57, request_groups_total=5)).as_dict()
    assert one["groups_total"] == five["groups_total"] == 57
    assert one["request_groups_total"] == 1
    assert five["request_groups_total"] == 5
