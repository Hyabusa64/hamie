"""The gate-K interruption hook must be inert everywhere except the fixture.

An interruption mechanism that can reach production configuration is a
production defect, so these tests pin the refusals rather than the feature:
absent marker, production path, mixed paths, and unknown stage names all have
to return "" (run normally), and only an armed marker naming a real checkpoint
on an all-fixture plan may halt anything.
"""

from __future__ import annotations

import pytest

from hamie.application.remediation_lifecycle import (
    FIXTURE_HALT_MARKER,
    HALTABLE_CHECKPOINTS,
    REQUIRED_CHECKPOINTS,
    FixtureHalt,
    PlannedLocation,
    RepairPlan,
    read_fixture_halt_stage,
)


def _plan(*paths: str) -> RepairPlan:
    return RepairPlan(
        incident_id="inc_fixture",
        incident_root_cause="fixture",
        incident_material_digest="d" * 64,
        incident_priority="p1",
        incident_evidence_status="verified",
        intent_kind="replace_stale_entity_reference",
        old_entity="sensor.hamie_lifecycle_fixture_2",
        new_entity="sensor.hamie_lifecycle_fixture",
        locations=tuple(
            PlannedLocation(path=p, occurrences=1, pre_hash="a" * 64) for p in paths
        ),
        expected_occurrences=len(paths),
        risk="config_mutation",
        protection_verdict="allowed",
    )


FIXTURE_FILE = "/config/packages/hamie_lifecycle_fixture_refs.yaml"
PRODUCTION_FILE = "/config/automations.yaml"


def _arm(tmp_path, stage: str) -> str:
    (tmp_path / FIXTURE_HALT_MARKER).write_text(stage, encoding="utf-8")
    return str(tmp_path)


def test_disabled_when_no_marker_exists(tmp_path):
    assert read_fixture_halt_stage(_plan(FIXTURE_FILE), str(tmp_path)) == ""


def test_armed_marker_halts_a_fixture_only_plan(tmp_path):
    config_dir = _arm(tmp_path, "write_began")
    assert read_fixture_halt_stage(_plan(FIXTURE_FILE), config_dir) == "write_began"


@pytest.mark.parametrize(
    "paths",
    [
        (PRODUCTION_FILE,),
        (FIXTURE_FILE, PRODUCTION_FILE),
        (PRODUCTION_FILE, FIXTURE_FILE),
    ],
)
def test_never_halts_when_any_location_is_production(tmp_path, paths):
    config_dir = _arm(tmp_path, "write_began")
    assert read_fixture_halt_stage(_plan(*paths), config_dir) == ""


def test_empty_plan_is_never_haltable(tmp_path):
    config_dir = _arm(tmp_path, "write_began")
    assert read_fixture_halt_stage(_plan(), config_dir) == ""


@pytest.mark.parametrize("stage", ["", "   ", "resolved", "drop table", "COMPLETE"])
def test_unknown_stage_names_are_refused(tmp_path, stage):
    config_dir = _arm(tmp_path, stage)
    assert read_fixture_halt_stage(_plan(FIXTURE_FILE), config_dir) == ""


def test_every_required_checkpoint_is_haltable():
    # A boundary that cannot be interrupted cannot be proven to recover.
    assert REQUIRED_CHECKPOINTS <= HALTABLE_CHECKPOINTS


def test_halt_carries_its_stage():
    err = FixtureHalt("backup_created")
    assert err.stage == "backup_created"
    assert "backup_created" in str(err)
