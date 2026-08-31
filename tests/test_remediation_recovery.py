"""Interrupted remediation: recover from current evidence, never from memory.

`remediation_baselines = 0` had one cause: RemediationLifecycle held every
run in an in-memory dict and never touched the repository, so a restart
between mutation and reconciliation lost the entire truth of an in-flight
repair.

The rule these tests enforce is that the persisted stage is a hint about what
was *attempted* and never evidence of what happened. A process that died
immediately after recording "write_began" may or may not have written
anything, and the only way to know is to hash the files that exist now.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hamie.domain.durable_baseline import (
    BASELINE_SCHEMA_VERSION,
    NO_MUTATION_OUTCOMES,
    RESUMABLE_OUTCOMES,
    RecoveryObservation,
    RecoveryOutcome,
    RemediationBaseline,
    decode_remediation_baseline,
    encode_remediation_baseline,
    reconcile_interrupted_remediation,
)

NOW = datetime(2026, 8, 28, 7, 0, tzinfo=UTC)
PLAN = "plan-identity-aaaa"
PRE_A, POST_A = "hash-pre-a", "hash-post-a"
PRE_B, POST_B = "hash-pre-b", "hash-post-b"


def _baseline(**kw) -> RemediationBaseline:
    base = dict(
        schema_version=BASELINE_SCHEMA_VERSION,
        plan_identity=PLAN,
        incident_id="inc-1",
        captured_at=NOW,
        pre_repair_scan_id="scan-pre",
        active_incident_ids=("inc-1",),
        incident_finding_ids=("f1",),
        protection_verdict="allowed",
        approval_id="appr-1",
        approved_by="home_assistant_user:abc",
        risk="config_mutation",
        file_states=(("/config/a.yaml", PRE_A, POST_A), ("/config/b.yaml", PRE_B, POST_B)),
        backup_paths=("/config/a.yaml.bak", "/config/b.yaml.bak"),
    )
    base.update(kw)
    return RemediationBaseline(**base)


def _obs(**kw) -> RecoveryObservation:
    base = dict(
        current_hashes={"/config/a.yaml": PRE_A, "/config/b.yaml": PRE_B},
        backups_present={"/config/a.yaml.bak": True, "/config/b.yaml.bak": True},
        incident_present=True,
        current_plan_identity=PLAN,
        current_protection_verdict="allowed",
    )
    base.update(kw)
    return RecoveryObservation(**base)


def _run(baseline, observation):
    return reconcile_interrupted_remediation(baseline, observation)


# ------------------------------------------------- scenarios A through I


def test_A_restart_before_mutation() -> None:
    d = _run(_baseline(), _obs())
    assert d.outcome is RecoveryOutcome.NOT_STARTED
    assert d.may_apply_mutation is True
    assert len(d.matched_pre) == 2


def test_B_restart_after_backup_before_write() -> None:
    d = _run(_baseline(backup_complete=True, stage="backup_created"), _obs())
    assert d.outcome is RecoveryOutcome.BACKUP_CREATED
    assert d.may_resume is True
    assert d.may_apply_mutation is True


def test_B_backup_recorded_but_missing_needs_review() -> None:
    """A recorded backup that is gone must not be assumed usable."""
    d = _run(
        _baseline(backup_complete=True),
        _obs(backups_present={"/config/a.yaml.bak": True, "/config/b.yaml.bak": False}),
    )
    assert d.outcome is RecoveryOutcome.MANUAL_REVIEW_REQUIRED
    assert d.may_apply_mutation is False


def test_C_restart_after_write_before_validation() -> None:
    d = _run(
        _baseline(write_began=True, write_complete=True, stage="write_applied"),
        _obs(current_hashes={"/config/a.yaml": POST_A, "/config/b.yaml": POST_B}),
    )
    assert d.outcome is RecoveryOutcome.POST_STATE_CONFIRMED
    assert d.may_resume is True
    assert d.may_apply_mutation is False, "must never write a second time"


def test_D_restart_after_validation_before_finalization() -> None:
    d = _run(
        _baseline(write_began=True, write_complete=True,
                  validation_began=True, validation_complete=True, validation_passed=True),
        _obs(current_hashes={"/config/a.yaml": POST_A, "/config/b.yaml": POST_B}),
    )
    assert d.outcome is RecoveryOutcome.VALIDATED_SUCCESS
    assert d.may_apply_mutation is False


def test_E_restart_during_rollback_files_restored() -> None:
    d = _run(
        _baseline(write_began=True, write_complete=True, rollback_began=True),
        _obs(),  # every file back at pre-state
    )
    assert d.outcome is RecoveryOutcome.ROLLED_BACK
    assert d.may_apply_mutation is False


def test_E_restart_during_rollback_files_not_restored() -> None:
    d = _run(
        _baseline(write_began=True, write_complete=True, rollback_began=True),
        _obs(current_hashes={"/config/a.yaml": POST_A, "/config/b.yaml": POST_B}),
    )
    assert d.outcome is RecoveryOutcome.ROLLBACK_REQUIRED
    assert d.may_apply_mutation is False


def test_F_external_divergence_refuses_continuation() -> None:
    d = _run(
        _baseline(write_began=True),
        _obs(current_hashes={"/config/a.yaml": "someone-else-edited-this",
                             "/config/b.yaml": PRE_B}),
    )
    assert d.outcome is RecoveryOutcome.DIVERGED
    assert d.may_apply_mutation is False
    assert d.may_resume is False


def test_F_unreadable_file_is_divergence_not_progress() -> None:
    d = _run(_baseline(), _obs(current_hashes={"/config/a.yaml": PRE_A}))
    assert d.outcome is RecoveryOutcome.DIVERGED


def test_G_incident_no_longer_present_stops_everything() -> None:
    d = _run(_baseline(backup_complete=True), _obs(incident_present=False))
    assert d.outcome is RecoveryOutcome.INCIDENT_NO_LONGER_PRESENT
    assert d.may_apply_mutation is False


def test_G_vanished_incident_outranks_a_perfectly_resumable_state() -> None:
    """Checked first because every other question is moot."""
    d = _run(
        _baseline(backup_complete=True, write_began=True),
        _obs(incident_present=False),
    )
    assert d.outcome is RecoveryOutcome.INCIDENT_NO_LONGER_PRESENT


def test_H_plan_digest_change_invalidates_approval() -> None:
    d = _run(_baseline(), _obs(current_plan_identity="plan-identity-CHANGED"))
    assert d.outcome is RecoveryOutcome.APPROVAL_INVALID
    assert d.may_apply_mutation is False


def test_H_underivable_plan_is_stale_not_resumable() -> None:
    d = _run(_baseline(), _obs(current_plan_identity=None))
    assert d.outcome is RecoveryOutcome.STALE_PLAN
    assert d.may_apply_mutation is False


def test_I_protected_effect_change_invalidates_prior_approval() -> None:
    d = _run(_baseline(), _obs(current_protection_verdict="blocked"))
    assert d.outcome is RecoveryOutcome.PROTECTED_EFFECT_CHANGED
    assert d.may_apply_mutation is False


# ------------------------------------------------------- the core rules


def test_partial_write_is_never_resumed_automatically() -> None:
    d = _run(
        _baseline(write_began=True),
        _obs(current_hashes={"/config/a.yaml": POST_A, "/config/b.yaml": PRE_B}),
    )
    assert d.outcome is RecoveryOutcome.RECOVERY_REQUIRED
    assert d.may_apply_mutation is False
    assert d.matched_post == ("/config/a.yaml",)
    assert d.matched_pre == ("/config/b.yaml",)


def test_a_recorded_write_that_never_landed_is_safe_to_retry() -> None:
    """Only because the files provably never changed."""
    d = _run(_baseline(write_began=True, write_complete=False), _obs())
    assert d.outcome is RecoveryOutcome.PRE_STATE_CONFIRMED
    assert d.may_apply_mutation is True


def test_the_recorded_stage_never_decides_the_outcome() -> None:
    """A stage claiming success cannot survive contradicting file hashes."""
    lying = _baseline(
        stage="validated_success", write_began=True, write_complete=True,
        validation_complete=True, validation_passed=True,
    )
    d = _run(lying, _obs())  # files are actually at pre-state
    assert d.outcome is not RecoveryOutcome.VALIDATED_SUCCESS
    assert d.outcome is RecoveryOutcome.PRE_STATE_CONFIRMED


def test_resumable_and_no_mutation_overlap_only_where_intended() -> None:
    """POST_STATE_CONFIRMED is the one state that resumes without writing.

    The work left is validation, not mutation, so it is both resumable and
    forbidden from applying the change again.
    """
    assert RESUMABLE_OUTCOMES & NO_MUTATION_OUTCOMES == {
        RecoveryOutcome.POST_STATE_CONFIRMED
    }


@pytest.mark.parametrize("outcome", sorted(NO_MUTATION_OUTCOMES))
def test_every_no_mutation_outcome_forbids_writing(outcome) -> None:
    """Exhaustive: no path through the classifier may permit a second write."""
    baselines = {
        RecoveryOutcome.POST_STATE_CONFIRMED: (
            _baseline(write_began=True, write_complete=True),
            _obs(current_hashes={"/config/a.yaml": POST_A, "/config/b.yaml": POST_B}),
        ),
        RecoveryOutcome.VALIDATED_SUCCESS: (
            _baseline(write_complete=True, validation_complete=True, validation_passed=True),
            _obs(current_hashes={"/config/a.yaml": POST_A, "/config/b.yaml": POST_B}),
        ),
        RecoveryOutcome.ROLLED_BACK: (_baseline(rollback_began=True), _obs()),
        RecoveryOutcome.DIVERGED: (_baseline(), _obs(current_hashes={"/config/a.yaml": "x", "/config/b.yaml": PRE_B})),
        RecoveryOutcome.STALE_PLAN: (_baseline(), _obs(current_plan_identity=None)),
        RecoveryOutcome.APPROVAL_INVALID: (_baseline(), _obs(current_plan_identity="other")),
        RecoveryOutcome.INCIDENT_NO_LONGER_PRESENT: (_baseline(), _obs(incident_present=False)),
        RecoveryOutcome.PROTECTED_EFFECT_CHANGED: (_baseline(), _obs(current_protection_verdict="blocked")),
        RecoveryOutcome.RECOVERY_REQUIRED: (
            _baseline(write_began=True),
            _obs(current_hashes={"/config/a.yaml": POST_A, "/config/b.yaml": PRE_B}),
        ),
        RecoveryOutcome.MANUAL_REVIEW_REQUIRED: (
            _baseline(backup_complete=True),
            _obs(backups_present={"/config/a.yaml.bak": False}),
        ),
        RecoveryOutcome.ROLLBACK_REQUIRED: (
            _baseline(write_began=True, write_complete=True, rollback_began=True),
            _obs(current_hashes={"/config/a.yaml": POST_A, "/config/b.yaml": POST_B}),
        ),
        RecoveryOutcome.MATERIAL_RETIRED: (
            _baseline(write_began=True, write_complete=True),
            _obs(
                current_hashes={},
                paths_confirmed_absent=frozenset({"/config/a.yaml", "/config/b.yaml"}),
                material_reader_available=True,
                material_referenced=False,
                incident_present=False,
                evidence_scan_id="scan-now",
            ),
        ),
    }
    baseline, observation = baselines[outcome]
    decision = _run(baseline, observation)
    assert decision.outcome is outcome
    assert decision.may_apply_mutation is False


# ------------------------------------------------------------ durability


def test_recovery_fields_round_trip_through_storage() -> None:
    original = _baseline(
        write_began=True, write_complete=True, backup_complete=True,
        validation_began=True, validation_complete=True, validation_passed=False,
        rollback_began=True, rollback_complete=True, rollback_verified=True,
        transaction_id="txn-9",
    )
    restored = decode_remediation_baseline(encode_remediation_baseline(original))
    assert restored.file_states == original.file_states
    assert restored.backup_paths == original.backup_paths
    assert restored.validation_passed is False
    assert restored.rollback_verified is True
    assert restored.approval_id == "appr-1"
    assert restored.transaction_id == "txn-9"


def test_a_baseline_written_before_the_new_fields_still_decodes() -> None:
    """Additive-optional: older records must not become unreadable."""
    raw = encode_remediation_baseline(_baseline())
    for key in ("file_states", "backup_paths", "write_began", "validation_passed",
                "approval_id", "transaction_id", "rollback_verified"):
        raw.pop(key, None)
    restored = decode_remediation_baseline(raw)
    assert restored.plan_identity == PLAN
    assert restored.file_states == ()
    assert restored.validation_passed is None


# ------------------------------------------------- lifecycle persistence


@pytest.mark.asyncio
async def test_the_lifecycle_persists_a_baseline_at_every_boundary() -> None:
    """The defect was that it persisted at none of them.

    RemediationLifecycle held every run in an in-memory dict and never
    touched the repository, so remediation_baselines stayed 0 and an
    interrupted repair lost its entire truth on restart.
    """
    import inspect

    from hamie.application import remediation_lifecycle

    source = inspect.getsource(remediation_lifecycle)
    for stage in (
        '"pre_state_confirmed"',
        '"backup_created"',
        '"write_began"',
        '"write_applied"',
        '"validation_complete"',
        '"rollback_began"',
        '"rollback_complete"',
    ):
        assert f"stage={stage}" in source, f"missing checkpoint at {stage}"


def test_the_write_checkpoint_precedes_the_write() -> None:
    """A process dying mid-write must leave evidence a write was attempted."""
    import inspect

    from hamie.application import remediation_lifecycle

    source = inspect.getsource(remediation_lifecycle)
    checkpoint = source.index('stage="write_began"')
    apply_call = source.index("async_apply_locations(", checkpoint)
    assert checkpoint < apply_call


def test_a_checkpoint_failure_does_not_abort_the_repair() -> None:
    """Losing a checkpoint is bad; abandoning a half-written repair is worse."""
    import inspect

    from hamie.application.remediation_lifecycle import RemediationLifecycle

    source = inspect.getsource(RemediationLifecycle._async_checkpoint)
    assert "except Exception" in source
    assert "_LOGGER.warning" in source


# --------------------------------------------------------------- live defect
#
# Found on a real interrupted repair, not by reading the code. A repair that
# was interrupted between the write and validation reported STALE_PLAN: once
# the stale reference is rewritten it is no longer in configuration, so the
# plan cannot be re-derived -- the plan becomes underivable BECAUSE the write
# succeeded. Asking about the approval before reading the bytes turned a
# completed mutation into a stale approval and refused to finish validating
# it, leaving the mutation applied, unvalidated and unreconciled.


def test_written_repair_is_post_state_even_when_the_plan_cannot_be_rederived():
    d = _run(
        _baseline(write_began=True, write_complete=True),
        _obs(current_hashes={"/config/a.yaml": POST_A, "/config/b.yaml": POST_B}, current_plan_identity=None),
    )
    assert d.outcome is RecoveryOutcome.POST_STATE_CONFIRMED
    assert not d.may_apply_mutation


def test_written_repair_is_not_reported_as_approval_invalid():
    d = _run(
        _baseline(write_began=True, write_complete=True),
        _obs(
            current_hashes={"/config/a.yaml": POST_A, "/config/b.yaml": POST_B},
            current_plan_identity="a-different-identity",
        ),
    )
    assert d.outcome is RecoveryOutcome.POST_STATE_CONFIRMED


def test_written_repair_is_not_reported_as_incident_resolved():
    # The incident being gone after a successful write is the repair working,
    # not a reason to forget the write happened and still owes validation.
    d = _run(
        _baseline(write_began=True, write_complete=True),
        _obs(current_hashes={"/config/a.yaml": POST_A, "/config/b.yaml": POST_B}, incident_present=False),
    )
    assert d.outcome is RecoveryOutcome.POST_STATE_CONFIRMED


def test_divergence_outranks_a_re_derivable_approval():
    # Unsafe continuation must win over any approval question.
    d = _run(
        _baseline(write_began=True),
        _obs(
            current_hashes={"/config/a.yaml": "unexpected", "/config/b.yaml": PRE_B},
            current_plan_identity=None,
        ),
    )
    assert d.outcome is RecoveryOutcome.DIVERGED
    assert not d.may_apply_mutation


def test_pre_state_still_answers_approval_questions_first():
    # The reorder must NOT stop guarding a repair that could still write.
    d = _run(
        _baseline(backup_complete=True),
        _obs(current_hashes={"/config/a.yaml": PRE_A, "/config/b.yaml": PRE_B}, incident_present=False),
    )
    assert d.outcome is RecoveryOutcome.INCIDENT_NO_LONGER_PRESENT


def test_protected_effect_change_is_reachable_despite_identity_change():
    # plan_identity folds in protection_verdict, so a changed verdict ALWAYS
    # changes the identity too. Checking identity first made this outcome
    # unreachable in the deployed system: an operator was told "the plan
    # changed" when the truth was "protected infrastructure is now in scope".
    d = _run(
        _baseline(),
        _obs(current_plan_identity="identity-changed-too",
             current_protection_verdict="blocked"),
    )
    assert d.outcome is RecoveryOutcome.PROTECTED_EFFECT_CHANGED
    assert not d.may_apply_mutation


def test_identity_change_alone_is_still_approval_invalid():
    d = _run(_baseline(), _obs(current_plan_identity="identity-changed-only"))
    assert d.outcome is RecoveryOutcome.APPROVAL_INVALID


# ------------------------------------------------- material retirement
#
# Live defect: the lifecycle fixture's own cleanup deleted the files a
# completed transaction had targeted. Current state then matched neither
# pre_hash nor post_hash, so reconciliation returned DIVERGED forever, and
# retention deliberately exempts incomplete baselines from pruning -- the
# record became immortal and was reclassified on every restart. Infinite
# retention is right for genuine unresolved divergence; it is wrong for a
# target that was deliberately and verifiably removed.


def _retired_obs(**kw):
    base = dict(
        current_hashes={},
        paths_confirmed_absent=frozenset({"/config/a.yaml", "/config/b.yaml"}),
        material_reader_available=True,
        material_referenced=False,
        incident_present=False,
        evidence_scan_id="scan-now",
    )
    base.update(kw)
    return _obs(**base)


def test_material_retired_when_every_target_is_provably_gone():
    d = _run(_baseline(write_began=True, write_complete=True), _retired_obs())
    assert d.outcome is RecoveryOutcome.MATERIAL_RETIRED
    assert not d.may_apply_mutation
    assert not d.may_resume


def test_existing_target_with_unexpected_hash_stays_diverged():
    d = _run(
        _baseline(write_began=True),
        _obs(current_hashes={"/config/a.yaml": "surprise", "/config/b.yaml": PRE_B}),
    )
    assert d.outcome is RecoveryOutcome.DIVERGED


def test_partial_removal_is_never_retired():
    # One gone, one still present and divergent: remediation or rollback could
    # still overwrite the survivor, so DIVERGED must win.
    d = _run(
        _baseline(write_began=True),
        _retired_obs(
            paths_confirmed_absent=frozenset({"/config/a.yaml"}),
            current_hashes={"/config/b.yaml": "surprise"},
        ),
    )
    assert d.outcome is RecoveryOutcome.DIVERGED


def test_absent_files_but_incident_still_active_is_not_retired():
    d = _run(_baseline(write_began=True), _retired_obs(incident_present=True))
    assert d.outcome is not RecoveryOutcome.MATERIAL_RETIRED


def test_absent_files_but_config_still_references_material_is_not_retired():
    d = _run(_baseline(write_began=True), _retired_obs(material_referenced=True))
    assert d.outcome is not RecoveryOutcome.MATERIAL_RETIRED


def test_unavailable_filesystem_reader_never_reads_as_removal():
    # The exact failure class that already produced one wrong live verdict:
    # missing infrastructure must fail as itself, not as a domain fact.
    d = _run(_baseline(write_began=True), _retired_obs(material_reader_available=False))
    assert d.outcome is RecoveryOutcome.DIVERGED


def test_retirement_requires_freshness_evidence():
    d = _run(_baseline(write_began=True), _retired_obs(evidence_scan_id=""))
    assert d.outcome is not RecoveryOutcome.MATERIAL_RETIRED


def test_retired_material_is_terminal_and_prunable():
    from hamie.domain.durable_baseline import TERMINAL_RECOVERY_OUTCOMES

    assert RecoveryOutcome.MATERIAL_RETIRED in TERMINAL_RECOVERY_OUTCOMES


def test_reappearing_target_after_retirement_is_handled_as_current_state():
    # A historical retired baseline stays historical; a baseline still asked
    # about while its files exist again is judged on those files, not on the
    # earlier retirement.
    d = _run(
        _baseline(write_began=True),
        _retired_obs(paths_confirmed_absent=frozenset(),
                     current_hashes={"/config/a.yaml": PRE_A, "/config/b.yaml": PRE_B}),
    )
    assert d.outcome is not RecoveryOutcome.MATERIAL_RETIRED
