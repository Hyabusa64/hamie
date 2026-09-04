"""manual_escalation_rate is the metric this whole layer is judged by --
it must never be fabricated from a zero denominator, and must only ever
count incidents that were actually investigated.
"""

from __future__ import annotations

import pytest

from hamie.domain.repair_metrics import (
    IncidentSnapshot,
    RemediationOutcomeRecord,
    compute_repair_metrics,
)


def _incident(**overrides) -> IncidentSnapshot:
    defaults = dict(
        incident_id="inc_1",
        disposition="repair_candidate",
        investigated=True,
        escalated_to_claude=False,
    )
    defaults.update(overrides)
    return IncidentSnapshot(**defaults)


def test_un_investigated_incident_cannot_be_escalated() -> None:
    with pytest.raises(ValueError):
        _incident(investigated=False, escalated_to_claude=True)


def test_rejects_an_unrecognised_disposition() -> None:
    with pytest.raises(ValueError):
        _incident(disposition="not_a_real_disposition")


def test_empty_snapshot_reports_zero_counts_and_no_rate() -> None:
    metrics = compute_repair_metrics(())
    assert metrics.active_incidents == 0
    assert metrics.investigated_incidents == 0
    assert metrics.manual_escalation_rate is None


def test_manual_escalation_rate_is_none_not_zero_when_nothing_was_investigated() -> None:
    """A rate of 0.0 would falsely claim 'HAMIE resolved everything' --
    the honest answer is 'nothing was measured yet.'
    """
    incidents = (_incident(investigated=False, escalated_to_claude=False),)
    metrics = compute_repair_metrics(incidents)
    assert metrics.investigated_incidents == 0
    assert metrics.manual_escalation_rate is None


def test_manual_escalation_rate_is_computed_over_investigated_incidents_only() -> None:
    incidents = (
        _incident(incident_id="a", investigated=True, escalated_to_claude=True),
        _incident(incident_id="b", investigated=True, escalated_to_claude=False),
        _incident(incident_id="c", investigated=False, escalated_to_claude=False),
    )
    metrics = compute_repair_metrics(incidents)
    # 1 of 2 *investigated* incidents escalated -- the un-investigated
    # one must not inflate the denominator.
    assert metrics.investigated_incidents == 2
    assert metrics.manual_escalations == 1
    assert metrics.manual_escalation_rate == pytest.approx(0.5)


def test_manual_escalation_rate_is_zero_when_investigated_but_none_escalated() -> None:
    incidents = (
        _incident(incident_id="a", investigated=True, escalated_to_claude=False),
        _incident(incident_id="b", investigated=True, escalated_to_claude=False),
    )
    metrics = compute_repair_metrics(incidents)
    assert metrics.manual_escalation_rate == 0.0


def test_repair_candidates_and_operator_decisions_are_counted_by_tier() -> None:
    incidents = (
        _incident(incident_id="a", disposition="repair_candidate"),
        _incident(incident_id="b", disposition="repair_candidate"),
        _incident(incident_id="c", disposition="operator_decision_required"),
        _incident(incident_id="d", disposition="blocked"),
        _incident(incident_id="e", disposition="insufficient_evidence"),
    )
    metrics = compute_repair_metrics(incidents)
    assert metrics.repair_candidates == 2
    assert metrics.operator_decision_incidents == 1
    assert metrics.unsupported_incidents == 2  # blocked + insufficient_evidence


def test_mean_times_ignore_incidents_with_no_recorded_time() -> None:
    incidents = (
        _incident(incident_id="a", seconds_to_investigation=10.0),
        _incident(incident_id="b", seconds_to_investigation=None),
        _incident(incident_id="c", seconds_to_investigation=30.0),
    )
    metrics = compute_repair_metrics(incidents)
    assert metrics.mean_seconds_to_investigation == pytest.approx(20.0)


def test_mean_time_is_none_when_no_incident_recorded_one() -> None:
    metrics = compute_repair_metrics((_incident(seconds_to_investigation=None),))
    assert metrics.mean_seconds_to_investigation is None


def test_outcome_counts_classify_success_failure_and_rollback() -> None:
    outcomes = (
        RemediationOutcomeRecord(incident_id="a", outcome="resolved"),
        RemediationOutcomeRecord(incident_id="b", outcome="still_present"),
        RemediationOutcomeRecord(incident_id="c", outcome="regressed"),
        RemediationOutcomeRecord(incident_id="d", outcome="validation_failed"),
        RemediationOutcomeRecord(incident_id="e", outcome="rolled_back"),
        RemediationOutcomeRecord(incident_id="f", outcome="rollback_failed"),
    )
    metrics = compute_repair_metrics((), outcomes)
    assert metrics.successful_repairs == 1
    assert metrics.failed_repairs == 3
    assert metrics.rolled_back_repairs == 2


def test_as_dict_round_trips_every_field() -> None:
    metrics = compute_repair_metrics((_incident(),))
    as_dict = metrics.as_dict()
    assert as_dict["active_incidents"] == 1
    assert as_dict["investigated_incidents"] == 1
    assert "manual_escalation_rate" in as_dict
