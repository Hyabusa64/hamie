"""Incident validity is not incident repairability.

Live evidence that forced this distinction: all 22 active P1 incidents
returned `operator_decision_required` with zero repair candidates, and every
affected entity existed. Read as "false positives", that would have closed
the queue. Read correctly:

    sensor.master_bedroom_fan_reason     unavailable
    sensor.master_bedroom_fan_reason_2   "Bedroom vacant"

the old identity is retained and not serving while its successor carries the
state -- the exact duplicate/migration defect, still true. Rediscovery
disproved repairability, not validity.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hamie.domain.incident_reconciliation import (
    ACTIONABLE_VALIDITY,
    CATEGORY_RULES,
    CurrentValidity,
    ReconciliationObservation,
    reconcile,
)

NOW = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)


def _incident(category: str, *subjects: str) -> dict:
    return {
        "incident_id": "inc_test",
        "category": category,
        "root_cause": "test",
        "affected_subject_ids": [f"entity:{s}" for s in subjects],
    }


def _obs(states: dict, refs: dict | None = None, *, fresh: bool = True):
    return ReconciliationObservation(
        subject_states=states,
        config_references=refs or {},
        scan_id="scan-1" if fresh else None,
        observed_at=NOW if fresh else None,
        evidence_ids=("ev-1",),
    )


# ------------------------------------------------- duplicate_migration


def test_the_real_master_bedroom_case_stays_present() -> None:
    """The exact live shape. Closing this would discard a real defect."""
    result = reconcile(
        _incident("duplicate_migration",
                  "sensor.master_bedroom_fan_reason",
                  "sensor.master_bedroom_fan_reason_2"),
        _obs({
            "sensor.master_bedroom_fan_reason": "unavailable",
            "sensor.master_bedroom_fan_reason_2": "Bedroom vacant",
        }),
    )
    assert result.validity is CurrentValidity.STILL_PRESENT
    assert result.actionable is True
    assert "sensor.master_bedroom_fan_reason" in result.subjects_stale


def test_entity_existence_alone_never_closes_a_migration_incident() -> None:
    """Both present, but the old one is not serving."""
    result = reconcile(
        _incident("duplicate_migration", "sensor.old", "sensor.old_2"),
        _obs({"sensor.old": "unavailable", "sensor.old_2": "on"}),
    )
    assert result.validity is CurrentValidity.STILL_PRESENT


def test_an_absent_identity_keeps_a_migration_incident_present() -> None:
    result = reconcile(
        _incident("duplicate_migration", "sensor.gone", "sensor.gone_2"),
        _obs({"sensor.gone": None, "sensor.gone_2": "on"}, {"sensor.gone": 3}),
    )
    assert result.validity is CurrentValidity.STILL_PRESENT
    assert result.subjects_absent == ("sensor.gone",)


def test_lingering_references_keep_a_migration_incident_present() -> None:
    """Both healthy, but configuration still points at the duplicate."""
    result = reconcile(
        _incident("duplicate_migration", "sensor.a", "sensor.a_2"),
        _obs({"sensor.a": "on", "sensor.a_2": "on"}, {"sensor.a": 2}),
    )
    assert result.validity is CurrentValidity.STILL_PRESENT


def test_a_migration_incident_closes_only_when_healthy_and_unreferenced() -> None:
    result = reconcile(
        _incident("duplicate_migration", "sensor.a", "sensor.a_2"),
        _obs({"sensor.a": "on", "sensor.a_2": "on"}, {"sensor.a": 0, "sensor.a_2": 0}),
    )
    assert result.validity is CurrentValidity.NO_LONGER_PRESENT
    assert result.actionable is False


# ------------------------------------------------------- functional_bug


def test_a_self_reference_stays_present_while_the_config_expresses_it() -> None:
    """Both entities available and the defect is still real."""
    result = reconcile(
        _incident("functional_bug", "binary_sensor.mop_due", "binary_sensor.mop_due_2"),
        _obs({"binary_sensor.mop_due": "on", "binary_sensor.mop_due_2": "on"},
             {"binary_sensor.mop_due": 1}),
    )
    assert result.validity is CurrentValidity.STILL_PRESENT


def test_a_functional_bug_closes_when_the_config_no_longer_expresses_it() -> None:
    result = reconcile(
        _incident("functional_bug", "binary_sensor.mop_due"),
        _obs({"binary_sensor.mop_due": "on"}, {"binary_sensor.mop_due": 0}),
    )
    assert result.validity is CurrentValidity.NO_LONGER_PRESENT


def test_a_functional_bug_without_a_config_search_is_not_resolved() -> None:
    """Entity availability says nothing about a structural relationship."""
    result = reconcile(
        _incident("functional_bug", "binary_sensor.mop_due"),
        _obs({"binary_sensor.mop_due": "on"}, {}),
    )
    assert result.validity is CurrentValidity.INSUFFICIENT_EVIDENCE
    assert result.actionable is True


# ------------------------------------------------------------- hygiene


def test_hygiene_stays_present_while_a_writer_targets_a_stale_identity() -> None:
    result = reconcile(
        _incident("hygiene", "light.dining_light_2"),
        _obs({"light.dining_light_2": "unavailable"}, {"light.dining_light_2": 1}),
    )
    assert result.validity is CurrentValidity.STILL_PRESENT


def test_hygiene_closes_when_the_target_became_healthy() -> None:
    result = reconcile(
        _incident("hygiene", "light.dining_light_2"),
        _obs({"light.dining_light_2": "on"}, {"light.dining_light_2": 1}),
    )
    assert result.validity is CurrentValidity.NO_LONGER_PRESENT


def test_hygiene_closes_when_the_writer_is_gone() -> None:
    result = reconcile(
        _incident("hygiene", "light.dining_light_2"),
        _obs({"light.dining_light_2": "unavailable"}, {"light.dining_light_2": 0}),
    )
    assert result.validity is CurrentValidity.NO_LONGER_PRESENT


# ------------------------------------------------------------ fail-safe


def test_an_unknown_category_is_never_auto_closed() -> None:
    """Unknown means uncertain, not resolved."""
    result = reconcile(
        _incident("some_future_analyzer", "sensor.x"),
        _obs({"sensor.x": "on"}, {"sensor.x": 0}),
    )
    assert result.validity is CurrentValidity.MANUAL_REVIEW
    assert result.actionable is True
    assert result.rule == "unknown_category_fail_safe"


@pytest.mark.parametrize("category", sorted(CATEGORY_RULES))
def test_every_known_category_has_a_rule(category: str) -> None:
    assert callable(CATEGORY_RULES[category])


def test_an_incident_with_no_entity_subjects_goes_to_manual_review() -> None:
    result = reconcile(_incident("duplicate_migration"), _obs({}))
    assert result.validity is CurrentValidity.MANUAL_REVIEW


# ----------------------------------------------------------- freshness


def test_stale_evidence_cannot_establish_still_present() -> None:
    result = reconcile(
        _incident("duplicate_migration", "sensor.a"),
        _obs({"sensor.a": "unavailable"}, {"sensor.a": 1}, fresh=False),
    )
    assert result.validity is CurrentValidity.INSUFFICIENT_EVIDENCE


def test_stale_evidence_cannot_close_an_incident_either() -> None:
    result = reconcile(
        _incident("duplicate_migration", "sensor.a", "sensor.a_2"),
        _obs({"sensor.a": "on", "sensor.a_2": "on"}, {"sensor.a": 0}, fresh=False),
    )
    assert result.validity is not CurrentValidity.NO_LONGER_PRESENT
    assert result.validity is CurrentValidity.INSUFFICIENT_EVIDENCE


def test_a_verdict_records_the_evidence_that_produced_it() -> None:
    result = reconcile(
        _incident("duplicate_migration", "sensor.a"),
        _obs({"sensor.a": "unavailable"}, {"sensor.a": 1}),
    )
    data = result.as_dict()
    assert data["scan_id"] == "scan-1"
    assert data["observed_at"].startswith("2026-08-28")
    assert data["evidence_ids"] == ["ev-1"]
    assert data["rule"]


# ------------------------------------------- the two axes stay separate


def test_operator_decision_required_does_not_mean_the_incident_is_invalid() -> None:
    """Axis B says HAMIE cannot derive a repair. Axis A is untouched by that.

    This is the exact confusion the live data exposed: zero repair candidates
    across 22 P1s did not make any of them false positives.
    """
    from hamie.application.incident_remediation import InvestigationDisposition

    result = reconcile(
        _incident("duplicate_migration",
                  "sensor.master_bedroom_fan_reason",
                  "sensor.master_bedroom_fan_reason_2"),
        _obs({
            "sensor.master_bedroom_fan_reason": "unavailable",
            "sensor.master_bedroom_fan_reason_2": "Bedroom vacant",
        }),
    )
    repairability = InvestigationDisposition.OPERATOR_DECISION_REQUIRED
    assert result.validity is CurrentValidity.STILL_PRESENT
    assert result.actionable is True
    assert repairability is InvestigationDisposition.OPERATOR_DECISION_REQUIRED


def test_zero_repair_candidates_does_not_imply_zero_valid_incidents() -> None:
    incidents = [
        (_incident("duplicate_migration", "sensor.a", "sensor.a_2"),
         _obs({"sensor.a": "unavailable", "sensor.a_2": "on"})),
        (_incident("functional_bug", "binary_sensor.b"),
         _obs({"binary_sensor.b": "on"}, {"binary_sensor.b": 1})),
        (_incident("hygiene", "light.c"),
         _obs({"light.c": "unavailable"}, {"light.c": 1})),
    ]
    verdicts = [reconcile(i, o) for i, o in incidents]
    assert all(v.validity is CurrentValidity.STILL_PRESENT for v in verdicts)
    assert all(v.actionable for v in verdicts)


def test_reconciliation_never_invents_a_repairability_verdict() -> None:
    """This module answers one question and must not answer the other."""
    from hamie.domain import incident_reconciliation

    # Checked against the module's namespace rather than its text: the
    # docstring deliberately names InvestigationDisposition to say where
    # repairability lives, and prose is not a leak.
    exported = {name for name in dir(incident_reconciliation) if not name.startswith("_")}
    assert "InvestigationDisposition" not in exported
    assert not any("REPAIR" in name.upper() for name in exported)
    assert {v.value for v in CurrentValidity}.isdisjoint(
        {"repair_candidate", "operator_decision_required", "blocked"}
    )


def test_actionable_and_retired_sets_are_disjoint() -> None:
    from hamie.domain.incident_reconciliation import RETIRED_VALIDITY

    assert not (ACTIONABLE_VALIDITY & RETIRED_VALIDITY)
    assert len(ACTIONABLE_VALIDITY | RETIRED_VALIDITY) == len(list(CurrentValidity))


def test_an_unbound_reader_is_never_read_as_an_absent_entity() -> None:
    """Live defect: 12 incidents reported no_longer_present with no data.

    The readers were bound lazily inside a property nothing had touched, so a
    fresh restart left them unset. `None` from an unbound reader is
    indistinguishable from "the entity does not exist", and reconciliation
    produced confident verdicts from nothing. Absence of an observer is not
    observation.
    """
    import inspect

    from hamie.application import operations_service

    source = inspect.getsource(operations_service.MaintenanceOperationsService)
    assert "_world_readers_bound" in source
    assert "reconciliation_readers_unavailable" in source
    # The readers must raise rather than return a falsy default.
    reader_src = inspect.getsource(
        operations_service.MaintenanceOperationsService._world_entity_state
    )
    assert "raise RuntimeError" in reader_src
    assert "return None" not in reader_src.split("if reader is None")[1][:120]


def test_readers_are_bound_before_any_verdict_can_be_requested() -> None:
    import inspect

    from hamie.application import runtime

    source = inspect.getsource(runtime.HamieRuntime.async_initialize)
    assert "bind_world_readers" in source, "binding must happen at initialization"
