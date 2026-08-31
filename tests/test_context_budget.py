"""Context budgeting: never knowingly send an oversized request.

The numbers in these tests are measurements taken from the live installation
that produced

    The selected findings' evidence is too large for the configured prompt size

not invented bounds. The previous pipeline budgeted the findings list against
`maximum_input_characters` and then added the envelope, the coverage id list
and up to three full incident public_dicts on top.
"""

from __future__ import annotations

import json

import pytest

from hamie.domain.context_budget import (
    MAX_COMPACT_INCIDENT_CHARACTERS,
    MAX_PROVIDER_INCIDENTS,
    MINIMUM_EVIDENCE_ALLOWANCE,
    ContextBudget,
    compact_incident,
    fit_payload,
    payload_characters,
)

# Measured live, 2026-08-27, on the installation this was built for.
MEASURED_COVERAGE_ID_LIST_CHARACTERS = 3948
MEASURED_LARGEST_INCIDENT_CHARACTERS = 14124
MEASURED_WORST_CASE_PAYLOAD_CHARACTERS = 48737
CONFIGURED_BUDGET = 16000


def _incident(findings: int = 100, subjects: int = 100) -> dict:
    return {
        "incident_id": "inc_" + "a" * 32,
        "title": "Related entities are unavailable: " + "x" * 100,
        "root_cause": "y" * 400,
        "category": "availability",
        "priority": "p2",
        "evidence_status": "verified",
        "lifecycle": "new",
        "finding_ids": [f"hamie_{i:032x}" for i in range(findings)],
        "finding_count": findings,
        "affected_subject_ids": [f"entity:sensor.example_{i}" for i in range(subjects)],
        "affected_subject_count": subjects,
        "recommended_next_step": "z" * 300,
    }


# --------------------------------------------------------------- budget


def test_evidence_allowance_is_what_remains_after_overhead_and_reserve() -> None:
    budget = ContextBudget(
        maximum_characters=16000,
        response_reserve_characters=4096,
        overhead_characters=9237,
    )
    assert budget.evidence_allowance == 16000 - 4096 - 9237
    assert budget.viable


def test_allowance_never_goes_negative() -> None:
    budget = ContextBudget(
        maximum_characters=2000, response_reserve_characters=4096, overhead_characters=9000
    )
    assert budget.evidence_allowance == 0
    assert not budget.viable


def test_a_budget_too_small_to_carry_evidence_is_not_viable() -> None:
    budget = ContextBudget(
        maximum_characters=MINIMUM_EVIDENCE_ALLOWANCE + 99,
        response_reserve_characters=50,
        overhead_characters=50,
    )
    assert not budget.viable


def test_budget_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        ContextBudget(maximum_characters=0, response_reserve_characters=0, overhead_characters=0)
    with pytest.raises(ValueError):
        ContextBudget(
            maximum_characters=100, response_reserve_characters=-1, overhead_characters=0
        )


# ----------------------------------------------------- compact incident


def test_compact_incident_removes_the_two_fields_that_cost_14kb() -> None:
    full = _incident()
    assert payload_characters(full) > 7000
    compact = compact_incident(full)
    assert "finding_ids" not in compact
    assert "affected_subject_ids" not in compact
    assert payload_characters(compact) <= MAX_COMPACT_INCIDENT_CHARACTERS


def test_compact_incident_preserves_what_the_model_needs_to_decide() -> None:
    compact = compact_incident(_incident())
    assert compact["incident_id"].startswith("inc_")
    assert compact["priority"] == "p2"
    assert compact["evidence_status"] == "verified"
    assert compact["finding_count"] == 100
    assert compact["affected_subject_count"] == 100
    assert compact["detail_available_via_tool"] == "hamie_get_incident"


def test_compact_incident_says_when_it_truncated() -> None:
    compact = compact_incident(_incident(subjects=50))
    assert compact["subjects_truncated"] is True
    assert len(compact["representative_subjects"]) <= 5


def test_a_small_incident_is_not_marked_truncated() -> None:
    compact = compact_incident(_incident(findings=1, subjects=2))
    assert "subjects_truncated" not in compact
    assert len(compact["representative_subjects"]) == 2


def test_three_compact_incidents_cost_less_than_one_raw_one() -> None:
    raw = payload_characters(_incident())
    three = sum(payload_characters(compact_incident(_incident())) for _ in range(3))
    assert three < raw


# ------------------------------------------------------------- fitting


def test_a_payload_inside_budget_is_returned_untouched() -> None:
    payload = {"findings": [{"id": 1}], "incidents": [{"incident_id": "x"}]}
    result = fit_payload(payload, 10_000)
    assert result.within_budget and not result.truncated
    assert result.payload == payload


def test_advisory_incident_context_is_dropped_before_evidence() -> None:
    payload = {
        "findings": [{"id": i, "text": "f" * 50} for i in range(5)],
        "incidents": [compact_incident(_incident()) for _ in range(3)],
    }
    limit = payload_characters({"findings": payload["findings"], "incidents": []}) + 80
    result = fit_payload(payload, limit)
    assert result.within_budget
    assert result.dropped_incidents and result.dropped_findings == 0
    assert result.payload["incidents"] == []
    assert result.payload["incident_context_dropped"] is True
    assert len(result.payload["findings"]) == 5, "evidence must survive advisory context"


def test_truncation_is_always_reported_never_silent() -> None:
    payload = {"findings": [{"id": i, "text": "f" * 200} for i in range(40)], "incidents": []}
    result = fit_payload(payload, 2_000)
    assert result.truncated
    assert result.dropped_findings > 0
    assert result.payload["evidence_truncated"] is True
    assert result.payload["evidence_dropped_count"] == result.dropped_findings


def test_an_unfittable_payload_is_refused_not_sent_empty() -> None:
    """A request with no evidence left is not a request worth making."""
    payload = {"findings": [{"id": 1, "text": "f" * 5000}], "incidents": []}
    result = fit_payload(payload, 100)
    assert not result.within_budget
    assert result.payload.get("findings") == []


def test_fitting_is_deterministic() -> None:
    payload = {"findings": [{"id": i, "text": "f" * 120} for i in range(30)], "incidents": []}
    first = fit_payload(dict(payload), 3_000)
    second = fit_payload(dict(payload), 3_000)
    assert first.payload == second.payload
    assert first.dropped_findings == second.dropped_findings


# ------------------------------------------- the measured regression


def test_the_measured_worst_case_now_fits() -> None:
    """The exact shape that produced evidence_payload_too_large in production."""
    incidents = [compact_incident(_incident()) for _ in range(MAX_PROVIDER_INCIDENTS)]
    coverage_counts = {
        "eligible_total": 1525,
        "selected_total": 94,
        "skipped_total": 1431,
        "groups_analyzed": 20,
        "groups_skipped": 31,
        "coverage": "partial",
    }
    budget = ContextBudget(
        maximum_characters=CONFIGURED_BUDGET,
        response_reserve_characters=4096,
        overhead_characters=payload_characters(incidents) + payload_characters(coverage_counts) + 400,
    )
    assert budget.viable, "the budget must still leave room for evidence"

    payload = {
        "schema_version": 1,
        "findings": [{"finding_id": f"hamie_{i:032x}", "evidence": "e" * 60} for i in range(20)],
        "incidents": incidents,
        "coverage": coverage_counts,
    }
    result = fit_payload(payload, CONFIGURED_BUDGET - 4096)
    assert result.within_budget
    assert result.characters < CONFIGURED_BUDGET
    # And decisively better than what was measured before the change.
    assert result.characters < MEASURED_WORST_CASE_PAYLOAD_CHARACTERS / 3


def test_coverage_id_list_is_no_longer_part_of_provider_context() -> None:
    """3,948 characters of identifiers, in every per-group request."""
    from hamie.domain.intelligence import AIAnalysisCoverage

    coverage = AIAnalysisCoverage(
        eligible_total=1525,
        selected_finding_ids=tuple(f"hamie_{i:032x}" for i in range(94)),
        skipped_finding_ids=tuple(f"hamie_{i:032x}" for i in range(94, 1525)),
        total_findings=1525,
        root_cause_group_ids=tuple(f"grp_{i}" for i in range(51)),
        analyzed_group_ids=tuple(f"grp_{i}" for i in range(20)),
    )
    public = coverage.public_dict()
    provider = coverage.provider_dict()

    assert "selected_finding_ids" in public, "the operator view keeps the ids"
    assert len(json.dumps(public["selected_finding_ids"])) > 3000

    assert "selected_finding_ids" not in provider
    assert provider["request_selected_total"] == 94
    assert provider["request_groups_skipped"] == 31
    assert provider["coverage"] == "partial"
    assert payload_characters(provider) < 400
