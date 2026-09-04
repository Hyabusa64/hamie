"""Recovery must actually READ the durable record back.

`reconcile_interrupted_remediation` existed, was correct, and was fully unit
tested -- and nothing in the shipped integration ever called it. Checkpoints
were written on every boundary and reloaded on every restart, then ignored, so
an interrupted repair stayed interrupted in silence. Truth nobody reads proves
nothing, which is the same failure class as not writing it at all.

These tests pin the entry point rather than the decision table (that is
tests/test_remediation_recovery.py's job): the lifecycle must classify an
incomplete baseline from the real files, must record the verdict where an
operator can retrieve it, and must not write while doing so.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hamie.application.remediation_lifecycle import RemediationLifecycle
from tests.test_checkpoint_durability import _CountingFileGateway, _Rig


def _sha256_of(path: str) -> str:
    import hashlib

    with open(path, encoding="utf-8") as fh:
        return hashlib.sha256(fh.read().encode("utf-8")).hexdigest()


def _lifecycle(rig: _Rig) -> RemediationLifecycle:
    return rig.lifecycle


async def _baselines_from_a_completed_run(rig: _Rig):
    """Run a real repair and return whatever it durably recorded."""
    await rig.execute()
    return tuple(rig.gate.baselines)


@pytest.mark.asyncio
async def test_recovery_classifies_an_incomplete_baseline_and_writes_nothing() -> None:
    rig = _Rig(file_gateway=_CountingFileGateway)
    await rig.execute()
    incomplete = [b for b in rig.gate.baselines if not b.complete]
    assert incomplete, "the run recorded no checkpoint to recover from"

    rig.files.writes.clear()
    decisions = await _lifecycle(rig).async_recover_interrupted(incomplete[:1])

    assert len(decisions) == 1
    assert decisions[0]["outcome"]
    assert decisions[0]["incident_id"] == incomplete[0].incident_id
    # Classification only: recovery never touches configuration.
    assert rig.files.writes == []


@pytest.mark.asyncio
async def test_recovery_verdict_is_retrievable_by_incident_and_plan() -> None:
    rig = _Rig(file_gateway=_CountingFileGateway)
    await rig.execute()
    incomplete = [b for b in rig.gate.baselines if not b.complete][:1]
    await _lifecycle(rig).async_recover_interrupted(incomplete)

    baseline = incomplete[0]
    by_incident = _lifecycle(rig).recovery_record(baseline.incident_id)
    by_plan = _lifecycle(rig).recovery_record(baseline.plan_identity)
    assert by_incident is not None and by_plan is not None
    assert by_incident == by_plan
    assert len(_lifecycle(rig).recovery_records()) >= 1


@pytest.mark.asyncio
async def test_completed_baselines_are_not_reclassified() -> None:
    rig = _Rig(file_gateway=_CountingFileGateway)
    await rig.execute()
    complete = [b for b in rig.gate.baselines if b.complete]
    if not complete:
        pytest.skip("this run recorded no completed baseline")
    assert await _lifecycle(rig).async_recover_interrupted(complete) == ()


@pytest.mark.asyncio
async def test_no_baselines_is_not_an_error() -> None:
    rig = _Rig(file_gateway=_CountingFileGateway)
    assert await _lifecycle(rig).async_recover_interrupted(()) == ()


@pytest.mark.asyncio
async def test_terminal_recovery_retires_the_baseline() -> None:
    """A finished repair must stop being reclassified on every restart.

    Retention deliberately exempts incomplete baselines from pruning, so a
    baseline left incomplete after a terminal verdict is reclassified forever
    and never removed -- the store grows without bound and the operator's
    "interrupted repairs" list never empties.
    """
    from hamie.application.remediation_lifecycle import (
        BASELINE_SCHEMA_VERSION,
        RemediationBaseline,
    )

    rig = _Rig(file_gateway=_CountingFileGateway)
    plan = await rig.plan()
    baseline = RemediationBaseline(
        schema_version=BASELINE_SCHEMA_VERSION,
        plan_identity=plan.plan_identity,
        incident_id=plan.incident_id,
        captured_at=datetime.now(UTC),
        pre_repair_scan_id="scan-pre",
        active_incident_ids=(),
        incident_finding_ids=(),
        stage="backup_created",
        complete=False,
        backup_complete=True,
        protection_verdict=plan.protection_verdict,
        file_states=tuple(
            (item.path, item.pre_hash, "") for item in plan.locations
        ),
    )
    rig.gate.incident_list = []          # the incident is gone entirely
    rig.gate.baselines.clear()

    decisions = await _lifecycle(rig).async_recover_interrupted([baseline])
    assert decisions[0]["outcome"] == "incident_no_longer_present"

    retired = [b for b in rig.gate.baselines if b.complete]
    assert retired, "a terminal recovery left its baseline incomplete"
    assert retired[0].plan_identity == plan.plan_identity


@pytest.mark.asyncio
async def test_non_terminal_recovery_keeps_the_baseline_visible() -> None:
    rig = _Rig(file_gateway=_CountingFileGateway)
    await rig.execute()
    incomplete = [b for b in rig.gate.baselines if not b.complete][:1]
    assert incomplete
    rig.gate.baselines.clear()
    await _lifecycle(rig).async_recover_interrupted(incomplete)
    assert not any(b.complete for b in rig.gate.baselines)
