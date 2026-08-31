"""Absence of durable recovery evidence is not permission to mutate.

The previous policy logged and continued at every checkpoint, including
`write_began`. That knowingly creates the one state HAMIE cannot classify
after a restart: files possibly changed, with no durable record that anything
was attempted. A partially written tree then reads as external divergence
with no attribution to the repair that caused it.

These tests count actual filesystem writes. The invariant is not "an error was
logged" -- it is that the bytes on disk never changed.
"""

from __future__ import annotations

import pytest

from hamie.application.remediation_lifecycle import (
    NO_FURTHER_MUTATION_CHECKPOINTS,
    REQUIRED_CHECKPOINTS,
    CheckpointDurabilityError,
    LifecycleStage,
    RemediationLifecycle,
)
from hamie.application.remediation_tools import FileGateway
from hamie.domain.remediation_execution import RemediationOutcome

from tests.test_remediation_lifecycle import (  # reuse the proven harness
    OLD,
    _Rig,
    ACTOR,
    INCIDENT_ID,
)


class _CountingFileGateway(FileGateway):
    """Counts real writes. The only measurement that matters here."""

    writes: list[str] = []

    def __init__(self, policy=None) -> None:
        super().__init__(policy)
        self.writes = []

    def write(self, path: str, content: str) -> None:
        self.writes.append(path)
        super().write(path, content)

    def restore(self, path: str, backup_path: str) -> str:
        self.writes.append(f"restore:{path}")
        return super().restore(path, backup_path)


class _Saver:
    """A baseline saver that fails at exactly one stage."""

    def __init__(self, fail_stage: str | None, error: Exception | None = None) -> None:
        self.fail_stage = fail_stage
        self.error = error or OSError("store unavailable")
        self.saved: list[str] = []

    async def __call__(self, baseline) -> None:
        if baseline.stage == self.fail_stage:
            raise self.error
        self.saved.append(baseline.stage)


def _rig_with(saver, file_gateway=_CountingFileGateway) -> _Rig:
    rig = _Rig(file_gateway=file_gateway)
    gateway = rig.gate.gateway()
    from dataclasses import replace as dc_replace

    rig.lifecycle = RemediationLifecycle(
        rig.world.gateway(),
        dc_replace(gateway, save_remediation_baseline=saver),
        rig.executor,
    )
    return rig


# ------------------------------------------------ required boundaries


@pytest.mark.parametrize("stage", sorted(REQUIRED_CHECKPOINTS - {"rollback_began"}))
@pytest.mark.asyncio
async def test_a_failed_required_checkpoint_writes_nothing(stage: str) -> None:
    saver = _Saver(stage)
    rig = _rig_with(saver)
    original = {n: rig.text(n) for n in ("a.yaml", "b.yaml")}

    result = await rig.execute()

    assert result.outcome is RemediationOutcome.BLOCKED, stage
    assert rig.files.writes == [], f"{stage}: mutated despite no durable record"
    assert {n: rig.text(n) for n in ("a.yaml", "b.yaml")} == original
    assert rig.occurrences(OLD) == 3


@pytest.mark.asyncio
async def test_write_began_failure_is_the_refusal_that_matters() -> None:
    """The single record that a write was attempted."""
    rig = _rig_with(_Saver("write_began"))
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.BLOCKED
    assert result.stage is LifecycleStage.MUTATION
    assert "refusing to mutate" in result.reason
    assert rig.files.writes == []


@pytest.mark.asyncio
async def test_missing_persistence_infrastructure_also_fails_closed() -> None:
    """No saver configured is missing infrastructure, not permission."""
    from dataclasses import replace as dc_replace

    rig = _Rig(file_gateway=_CountingFileGateway)
    rig.lifecycle = RemediationLifecycle(
        rig.world.gateway(),
        dc_replace(rig.gate.gateway(), save_remediation_baseline=None),
        rig.executor,
    )
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.BLOCKED
    assert rig.files.writes == []


@pytest.mark.parametrize(
    "error",
    [
        OSError("disk full"),
        TimeoutError("store timed out"),
        ValueError("serialization failed"),
        RuntimeError("generation conflict"),
    ],
)
@pytest.mark.asyncio
async def test_every_failure_mode_is_treated_as_not_persisted(error) -> None:
    """Unknown is never collapsed into success."""
    rig = _rig_with(_Saver("write_began", error))
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.BLOCKED
    assert rig.files.writes == []


# ------------------------------------------- post-write boundary


@pytest.mark.asyncio
async def test_write_applied_failure_does_not_write_again() -> None:
    """The write already happened. Do not write again to fix bookkeeping."""
    rig = _rig_with(_Saver("write_applied"))
    result = await rig.execute()

    writes = [w for w in rig.files.writes if not w.startswith("restore:")]
    assert len(writes) == 2, "exactly one write per affected file, never more"
    assert rig.occurrences(OLD) == 0, "the mutation itself completed"
    assert result.outcome is not RemediationOutcome.BLOCKED
    assert "write_applied" in NO_FURTHER_MUTATION_CHECKPOINTS


@pytest.mark.asyncio
async def test_a_best_effort_checkpoint_failure_does_not_abort_the_repair() -> None:
    rig = _rig_with(_Saver("validation_complete"))
    rig.resolve_after_scan()
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.RESOLVED
    assert "validation_complete" not in REQUIRED_CHECKPOINTS


# ------------------------------------------------- rollback boundary


@pytest.mark.asyncio
async def test_rollback_is_refused_when_its_intent_cannot_be_recorded() -> None:
    """Without the record, restored files read as 'never written'.

    That would permit re-applying the repair that just failed validation.
    """
    rig = _rig_with(_Saver("rollback_began"))
    rig.ha.config_plan = [True, False, True]  # pre-valid, post-invalid
    result = await rig.execute()

    assert result.outcome is RemediationOutcome.ROLLBACK_FAILED
    assert result.rollback["applicable"] is False
    assert result.rollback["restoration_proven"] is False
    restores = [w for w in rig.files.writes if w.startswith("restore:")]
    assert restores == [], "rolled back without a durable record of intent"


@pytest.mark.asyncio
async def test_rollback_complete_failure_does_not_roll_back_twice() -> None:
    rig = _rig_with(_Saver("rollback_complete"))
    rig.ha.config_plan = [True, False, True]
    result = await rig.execute()
    restores = [w for w in rig.files.writes if w.startswith("restore:")]
    assert len(restores) == 2, "one restore per written file, never more"
    assert result.outcome is RemediationOutcome.ROLLED_BACK


# --------------------------------------------------- the invariants


@pytest.mark.asyncio
async def test_a_successful_run_records_every_required_checkpoint() -> None:
    saver = _Saver(None)
    rig = _rig_with(saver)
    rig.resolve_after_scan()
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.RESOLVED
    for stage in REQUIRED_CHECKPOINTS - {"rollback_began"}:
        assert stage in saver.saved, f"{stage} was never persisted"


def test_required_and_best_effort_sets_are_disjoint() -> None:
    assert not (REQUIRED_CHECKPOINTS & NO_FURTHER_MUTATION_CHECKPOINTS)


def test_write_began_is_required() -> None:
    """Pinned separately: this is the boundary the whole policy exists for."""
    assert "write_began" in REQUIRED_CHECKPOINTS


def test_checkpoint_error_names_the_stage_and_cause() -> None:
    err = CheckpointDurabilityError("write_began", "OSError: disk full")
    assert err.stage == "write_began"
    assert "disk full" in str(err)
