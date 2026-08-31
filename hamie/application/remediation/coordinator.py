"""The remediation execution lifecycle (HAMIE Phase 2B).

Ties every other layer together -- planner output, approval binding,
locks, backup/precondition verification, adapters, post-action
verification, and rollback -- into one auditable sequence. This is the
only module in Phase 2B that actually calls an adapter's ``execute()``.

Every business-rule failure (missing plan, invalid approval, failed
precondition, adapter failure) produces a durable, persisted
``ExecutionRecord`` explaining exactly what happened -- never a raised
exception and never a silently dropped attempt. Only a genuine
programming defect (e.g. no adapter registered for a plan's
``adapter_id``) is allowed to raise, since that is a configuration bug
this module cannot recover from, not a normal outcome to record.

Simplifications explicit for Phase 2B (documented, not hidden): there is
no separate durable "execution started" checkpoint written before the
first step runs -- all Phase 2B adapters are fast and synchronous, so a
crash between "lock acquired" and "result persisted" simply leaves the
lock to expire on its lease and the attempt is retried fresh, rather
than being resumed mid-step. True step-by-step crash resumability, and
genuine multi-step ``PARTIALLY_SUCCEEDED`` plans (today's catalog only
ever plans one action step), are documented Phase 2C extension points
(see docs/REMEDIATION_ENGINE.md).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

from ...domain.recommendation import CanonicalRecommendation
from ...domain.remediation import (
    RemediationActionStep,
    RemediationPlan,
    RemediationPlanState,
)
from ...domain.remediation_approval import ApprovalRecord
from ...domain.remediation_execution import (
    ExecutionOutcome,
    ExecutionRecord,
    RollbackOutcome,
    RollbackRecord,
    RollbackStepResult,
    StepExecutionResult,
    VerificationResult,
)
from ..persistence import (
    GenerationConflictError,
    PersistenceUnitOfWorkPort,
    RepositoryState,
)
from .adapters import RemediationActionAdapter, RemediationAdapterContext
from .locks import (
    LockConflictError,
    async_acquire_lock,
    async_check_and_record_replay_token,
    async_release_lock,
)
from .preconditions import (
    BackupProvider,
    verify_backup_for_step,
    verify_preconditions,
)

_LOGGER = logging.getLogger(__name__)

MAX_COMMIT_ATTEMPTS = 5


class CoordinatorConfigurationError(RuntimeError):
    """A genuine defect (e.g. an unregistered adapter), not a business outcome."""


class RollbackRejectedError(RuntimeError):
    """A safe business rejection of an explicit rollback request."""


async def _commit_with_retry(
    repository: PersistenceUnitOfWorkPort,
    mutate,
) -> RepositoryState:
    """Load, apply ``mutate``, and commit, retrying on generation conflict."""
    for _attempt in range(MAX_COMMIT_ATTEMPTS):
        state = await repository.async_load()
        next_state = mutate(state)
        try:
            await repository.async_commit(
                next_state, expected_generation=state.generation
            )
            return next_state
        except GenerationConflictError:
            continue
    raise LockConflictError(
        "could not persist remediation state: repeated generation conflicts"
    )


def _blocked_record(
    *,
    execution_id: str,
    remediation_plan_id: str,
    plan_fingerprint: str,
    approval_id: str,
    installation_id: str,
    started_by: str,
    idempotency_token: str,
    now: datetime,
    reason: str,
) -> ExecutionRecord:
    return ExecutionRecord(
        execution_id=execution_id,
        remediation_plan_id=remediation_plan_id,
        plan_fingerprint=plan_fingerprint,
        approval_id=approval_id,
        installation_id=installation_id,
        started_at=now,
        started_by=started_by,
        idempotency_token=idempotency_token,
        outcome=ExecutionOutcome.FAILED,
        completed_at=now,
        error=reason,
    )


async def _persist_and_return(
    repository: PersistenceUnitOfWorkPort,
    *,
    plan: RemediationPlan | None,
    execution: ExecutionRecord,
    rollback: RollbackRecord | None = None,
) -> ExecutionRecord:
    """Append the execution (and optional rollback) record, update plan state.

    Additive only: the original plan is replaced (state/updated_at
    changes only, its identity/fingerprint never do), never deleted; the
    execution and rollback records are appended, never overwritten.
    """
    new_plan_state = {
        ExecutionOutcome.SUCCEEDED: RemediationPlanState.SUCCEEDED,
        ExecutionOutcome.PARTIALLY_SUCCEEDED: RemediationPlanState.PARTIALLY_SUCCEEDED,
        ExecutionOutcome.FAILED: RemediationPlanState.FAILED,
        ExecutionOutcome.ROLLED_BACK: RemediationPlanState.ROLLED_BACK,
        ExecutionOutcome.ROLLBACK_FAILED: RemediationPlanState.ROLLBACK_FAILED,
    }.get(execution.outcome)

    def _mutate(state: RepositoryState) -> RepositoryState:
        plans = state.remediation_plans
        if plan is not None and new_plan_state is not None:
            updated_plan = replace(
                plan,
                state=new_plan_state,
                updated_at=execution.completed_at or plan.created_at,
            )
            plans = tuple(
                updated_plan
                if item.remediation_plan_id == plan.remediation_plan_id
                else item
                for item in state.remediation_plans
            )
        executions = (*state.remediation_executions, execution)
        rollbacks = (
            (*state.remediation_rollbacks, rollback)
            if rollback is not None
            else state.remediation_rollbacks
        )
        return replace(
            state,
            remediation_plans=plans,
            remediation_executions=executions,
            remediation_rollbacks=rollbacks,
            generation=state.generation + 1,
        )

    await _commit_with_retry(repository, _mutate)
    return execution


async def _persist_explicit_rollback(
    repository: PersistenceUnitOfWorkPort,
    *,
    plan: RemediationPlan,
    rollback: RollbackRecord,
) -> RollbackRecord:
    """Append an explicit rollback and update only the plan lifecycle state."""
    plan_state = (
        RemediationPlanState.ROLLED_BACK
        if rollback.outcome is RollbackOutcome.SUCCEEDED
        else RemediationPlanState.ROLLBACK_FAILED
    )

    def _mutate(state: RepositoryState) -> RepositoryState:
        current = next(
            (
                item
                for item in state.remediation_plans
                if item.remediation_plan_id == plan.remediation_plan_id
            ),
            None,
        )
        if current is None or current.plan_fingerprint != plan.plan_fingerprint:
            raise RollbackRejectedError("plan_changed_before_rollback")
        if any(
            item.execution_id == rollback.execution_id
            for item in state.remediation_rollbacks
        ):
            raise RollbackRejectedError("rollback_already_recorded")
        updated = replace(
            current,
            state=plan_state,
            updated_at=rollback.completed_at or rollback.initiated_at,
        )
        return replace(
            state,
            remediation_plans=tuple(
                updated
                if item.remediation_plan_id == plan.remediation_plan_id
                else item
                for item in state.remediation_plans
            ),
            remediation_rollbacks=(*state.remediation_rollbacks, rollback),
            generation=state.generation + 1,
        )

    await _commit_with_retry(repository, _mutate)
    return rollback


async def async_rollback_execution(
    repository: PersistenceUnitOfWorkPort,
    *,
    remediation_plan_id: str,
    execution_id: str,
    rollback_id: str,
    idempotency_token: str,
    initiated_by: str,
    adapters: dict[str, RemediationActionAdapter],
    now: datetime,
) -> RollbackRecord:
    """Explicitly reverse one verified execution through declared handlers.

    The original execution evidence is immutable. The request is replay-protected,
    target-locked, bound to the same plan fingerprint, and rejected if any rollback
    has already been recorded for the execution.
    """
    state = await repository.async_load()
    plan = next(
        (
            item
            for item in state.remediation_plans
            if item.remediation_plan_id == remediation_plan_id
        ),
        None,
    )
    execution = next(
        (
            item
            for item in state.remediation_executions
            if item.execution_id == execution_id
            and item.remediation_plan_id == remediation_plan_id
        ),
        None,
    )
    if plan is None or execution is None:
        raise RollbackRejectedError("rollback_source_not_found")
    if execution.outcome is not ExecutionOutcome.SUCCEEDED:
        raise RollbackRejectedError("only_verified_execution_can_be_rolled_back")
    if execution.plan_fingerprint != plan.plan_fingerprint:
        raise RollbackRejectedError("plan_changed_since_execution")
    if not plan.rollback_plan.supported:
        raise RollbackRejectedError("rollback_not_supported")
    if (
        plan.rollback_plan.expires_at is not None
        and now >= plan.rollback_plan.expires_at
    ):
        raise RollbackRejectedError("rollback_expired")
    if any(item.execution_id == execution_id for item in state.remediation_rollbacks):
        raise RollbackRejectedError("rollback_already_recorded")

    is_new = await async_check_and_record_replay_token(
        repository,
        token=idempotency_token,
        remediation_plan_id=remediation_plan_id,
        plan_fingerprint=plan.plan_fingerprint,
        execution_id=rollback_id,
    )
    if not is_new:
        raise RollbackRejectedError("rollback_replay_blocked")

    completed = {
        item.step_index: item for item in execution.step_results if item.succeeded
    }
    reversible = [
        (step, completed[step.step_index])
        for step in plan.actions
        if step.reversible and step.step_index in completed
    ]
    if not reversible:
        raise RollbackRejectedError("no_completed_reversible_step")

    target_identity_key = plan.actions[0].target.identity_key
    lock = await async_acquire_lock(
        repository,
        remediation_plan_id=plan.remediation_plan_id,
        target_identity_key=target_identity_key,
        owner_execution_id=rollback_id,
        now=now,
    )
    try:
        context = RemediationAdapterContext(
            installation_id=plan.installation_id,
            now=now,
            execution_id=rollback_id,
        )
        rollback = await _run_rollback(
            reversible,
            adapters=adapters,
            context=context,
            execution_id=execution.execution_id,
            remediation_plan_id=plan.remediation_plan_id,
            initiated_by=initiated_by,
            now=now,
            rollback_id=rollback_id,
            reason="user requested rollback of a verified repair",
        )
        return await _persist_explicit_rollback(
            repository, plan=plan, rollback=rollback
        )
    finally:
        try:
            await async_release_lock(
                repository,
                lock_id=lock.lock_id,
                reason="rollback finished",
                now=now,
            )
        except LockConflictError:
            _LOGGER.warning(
                "HAMIE rollback lock %s could not be released; "
                "it will expire naturally",
                lock.lock_id,
                exc_info=True,
            )


async def async_execute_plan(
    repository: PersistenceUnitOfWorkPort,
    *,
    remediation_plan_id: str,
    approval_id: str,
    execution_id: str,
    idempotency_token: str,
    started_by: str,
    adapters: dict[str, RemediationActionAdapter],
    backup_provider: BackupProvider,
    now: datetime,
) -> ExecutionRecord:
    """Execute one approved remediation plan.

    See the module docstring for the complete lifecycle and its
    documented Phase 2B simplifications.
    """
    # 1. Replay protection -- a reused idempotency_token never re-runs
    # anything, regardless of whether the plan/approval below even exist.
    is_new = await async_check_and_record_replay_token(
        repository,
        token=idempotency_token,
        remediation_plan_id=remediation_plan_id,
        plan_fingerprint="pending",
        execution_id=execution_id,
    )
    if not is_new:
        execution = _blocked_record(
            execution_id=execution_id,
            remediation_plan_id=remediation_plan_id,
            plan_fingerprint="pending",
            approval_id=approval_id,
            installation_id="unknown",
            started_by=started_by,
            idempotency_token=idempotency_token,
            now=now,
            reason="replay_blocked: idempotency_token already used",
        )
        return await _persist_and_return(repository, plan=None, execution=execution)

    # 2. Load plan.
    state = await repository.async_load()
    plan = next(
        (
            item
            for item in state.remediation_plans
            if item.remediation_plan_id == remediation_plan_id
        ),
        None,
    )
    if plan is None:
        execution = _blocked_record(
            execution_id=execution_id,
            remediation_plan_id=remediation_plan_id,
            plan_fingerprint="unknown",
            approval_id=approval_id,
            installation_id="unknown",
            started_by=started_by,
            idempotency_token=idempotency_token,
            now=now,
            reason="plan_not_found",
        )
        return await _persist_and_return(repository, plan=None, execution=execution)

    def _block(reason: str) -> ExecutionRecord:
        return _blocked_record(
            execution_id=execution_id,
            remediation_plan_id=plan.remediation_plan_id,
            plan_fingerprint=plan.plan_fingerprint,
            approval_id=approval_id,
            installation_id=plan.installation_id,
            started_by=started_by,
            idempotency_token=idempotency_token,
            now=now,
            reason=reason,
        )

    # 3. Validate plan state.
    if plan.state not in (
        RemediationPlanState.APPROVED,
        RemediationPlanState.EXECUTION_PENDING,
    ):
        return await _persist_and_return(
            repository,
            plan=plan,
            execution=_block(f"plan_not_approved: state is {plan.state.value}"),
        )
    if not plan.execution_supported:
        return await _persist_and_return(
            repository, plan=plan, execution=_block("plan_not_execution_supported")
        )
    if plan.expires_at is not None and now >= plan.expires_at:
        return await _persist_and_return(
            repository, plan=plan, execution=_block("plan_expired")
        )

    # 4. Load approval.
    approval = next(
        (
            item
            for item in state.remediation_approvals
            if item.approval_id == approval_id
        ),
        None,
    )
    if approval is None:
        return await _persist_and_return(
            repository, plan=plan, execution=_block("approval_not_found")
        )

    # 5. Verify approval binding to the exact plan fingerprint and preview.
    if not approval.is_valid_for(
        plan_fingerprint=plan.plan_fingerprint,
        preview_digest=plan.preview_digest or "",
        now=now,
    ):
        return await _persist_and_return(
            repository,
            plan=plan,
            execution=_block(
                "approval_invalid: expired, revoked, rejected, or mismatched"
            ),
        )

    # 6. Acquire locks -- deliberately ahead of the backup/precondition
    # checks below (earlier than the plain checklist order) to close the
    # time-of-check-to-time-of-use gap between checking and acting.
    target_identity_key = plan.actions[0].target.identity_key
    try:
        lock = await async_acquire_lock(
            repository,
            remediation_plan_id=plan.remediation_plan_id,
            target_identity_key=target_identity_key,
            owner_execution_id=execution_id,
            now=now,
        )
    except LockConflictError as err:
        return await _persist_and_return(
            repository, plan=plan, execution=_block(f"execution_blocked: {err}")
        )

    try:
        return await _execute_locked(
            repository,
            plan=plan,
            approval=approval,
            execution_id=execution_id,
            idempotency_token=idempotency_token,
            started_by=started_by,
            adapters=adapters,
            backup_provider=backup_provider,
            now=now,
        )
    finally:
        # A failure to release the lock is a distinct, secondary problem
        # that must never mask the already-computed (and, by this point,
        # already-persisted) primary result -- catch and log it rather
        # than letting it propagate and override a real success or
        # failure outcome. The lock still stops blocking once its lease
        # naturally expires (see locks.py's is_held_at).
        try:
            await async_release_lock(
                repository, lock_id=lock.lock_id, reason="execution finished", now=now
            )
        except LockConflictError:
            _LOGGER.warning(
                "HAMIE remediation lock %s could not be released; it "
                "will expire naturally on its lease",
                lock.lock_id,
                exc_info=True,
            )


async def _execute_locked(
    repository: PersistenceUnitOfWorkPort,
    *,
    plan: RemediationPlan,
    approval: ApprovalRecord,
    execution_id: str,
    idempotency_token: str,
    started_by: str,
    adapters: dict[str, RemediationActionAdapter],
    backup_provider: BackupProvider,
    now: datetime,
) -> ExecutionRecord:
    """Run backup/precondition checks, execute, verify, and roll back.

    Everything here calls out to code this module does not control (a
    backup provider, an adapter) -- any unexpected exception from that
    external code is caught and turned into a persisted, redacted
    ``FAILED`` ``ExecutionRecord`` rather than propagating raw, so a
    failure this class of never leaves the coordinator's own promise
    (a durable record explaining exactly what happened) unfulfilled. A
    ``CoordinatorConfigurationError`` is a genuine defect in *this*
    module's own setup (e.g. a missing adapter registration), not an
    external failure, and is deliberately re-raised unchanged.
    """

    def _block(reason: str) -> ExecutionRecord:
        return _blocked_record(
            execution_id=execution_id,
            remediation_plan_id=plan.remediation_plan_id,
            plan_fingerprint=plan.plan_fingerprint,
            approval_id=approval.approval_id,
            installation_id=plan.installation_id,
            started_by=started_by,
            idempotency_token=idempotency_token,
            now=now,
            reason=reason,
        )

    state = await repository.async_load()
    current_recommendation = next(
        (
            item
            for item in state.canonical_recommendations
            if item.recommendation_id == plan.recommendation_id
        ),
        None,
    )

    try:
        return await _run_execution(
            repository,
            plan=plan,
            approval=approval,
            execution_id=execution_id,
            idempotency_token=idempotency_token,
            started_by=started_by,
            adapters=adapters,
            backup_provider=backup_provider,
            current_recommendation=current_recommendation,
            now=now,
        )
    except CoordinatorConfigurationError:
        raise
    except Exception as err:
        return await _persist_and_return(
            repository,
            plan=plan,
            execution=_block(f"unexpected_error: {type(err).__name__}: {err}"),
        )


async def _run_execution(
    repository: PersistenceUnitOfWorkPort,
    *,
    plan: RemediationPlan,
    approval: ApprovalRecord,
    execution_id: str,
    idempotency_token: str,
    started_by: str,
    adapters: dict[str, RemediationActionAdapter],
    backup_provider: BackupProvider,
    current_recommendation: CanonicalRecommendation | None,
    now: datetime,
) -> ExecutionRecord:
    def _block(reason: str) -> ExecutionRecord:
        return _blocked_record(
            execution_id=execution_id,
            remediation_plan_id=plan.remediation_plan_id,
            plan_fingerprint=plan.plan_fingerprint,
            approval_id=approval.approval_id,
            installation_id=plan.installation_id,
            started_by=started_by,
            idempotency_token=idempotency_token,
            now=now,
            reason=reason,
        )

    # 7. Verify backup for every step that requires it.
    backup_results = [
        await verify_backup_for_step(step, provider=backup_provider, now=now)
        for step in plan.actions
    ]
    backup_ok = all(item.passes for item in backup_results)

    # 8. Full precondition report, now that the lock is held.
    report = verify_preconditions(
        plan=plan,
        current_recommendation=current_recommendation,
        approval=approval,
        lock_held=True,
        adapter_available=all(step.adapter_id in adapters for step in plan.actions),
        backup_result=backup_results[0],
        now=now,
    )
    if not backup_ok or not report.all_passed:
        reasons = ", ".join(item.detail for item in report.failures)
        return await _persist_and_return(
            repository,
            plan=plan,
            execution=_block(f"precondition_failed: {reasons or 'backup unavailable'}"),
        )

    # 9-11. Execute steps in order, verifying each immediately; stop on
    # the first failure (fail-fast -- never silently retries a
    # destructive action).
    step_results: list[StepExecutionResult] = []
    verification_results: list[VerificationResult] = []
    context = RemediationAdapterContext(
        installation_id=plan.installation_id, now=now, execution_id=execution_id
    )
    failed = False
    for step in plan.actions:
        adapter = adapters.get(step.adapter_id)
        if adapter is None:
            raise CoordinatorConfigurationError(
                f"no adapter registered for {step.adapter_id}"
            )
        exec_result = await adapter.execute(step, context)
        step_results.append(exec_result)
        if not exec_result.succeeded:
            failed = True
            break
        verify_result = await adapter.verify(step, exec_result, context)
        verification_results.append(verify_result)
        if not verify_result.succeeded:
            failed = True
            break

    all_succeeded = (
        not failed
        and len(step_results) == len(plan.actions)
        and all(item.succeeded for item in step_results)
        and len(verification_results) == len(plan.actions)
        and all(item.succeeded for item in verification_results)
    )

    # 13-15. Roll back completed reversible steps, in reverse order, when
    # something failed.
    rollback_record: RollbackRecord | None = None
    if failed:
        pairs = zip(plan.actions, step_results, strict=False)
        completed_reversible: list[
            tuple[RemediationActionStep, StepExecutionResult]
        ] = [
            (step, result)
            for step, result in pairs
            if result.succeeded and step.reversible
        ]
        if completed_reversible:
            rollback_record = await _run_rollback(
                completed_reversible,
                adapters=adapters,
                context=context,
                execution_id=execution_id,
                remediation_plan_id=plan.remediation_plan_id,
                initiated_by=started_by,
                now=now,
            )

    outcome = _determine_outcome(
        all_succeeded=all_succeeded, rollback_record=rollback_record
    )
    error = None
    if outcome is ExecutionOutcome.FAILED:
        failing_step = next((item for item in step_results if not item.succeeded), None)
        failing_verification = next(
            (item for item in verification_results if not item.succeeded), None
        )
        if failing_step is not None:
            error = failing_step.error
        elif failing_verification is not None:
            error = "post-action verification did not succeed"
        else:
            error = "execution did not complete"

    execution = ExecutionRecord(
        execution_id=execution_id,
        remediation_plan_id=plan.remediation_plan_id,
        plan_fingerprint=plan.plan_fingerprint,
        approval_id=approval.approval_id,
        installation_id=plan.installation_id,
        started_at=now,
        started_by=started_by,
        idempotency_token=idempotency_token,
        outcome=outcome,
        step_results=tuple(step_results),
        verification_results=tuple(verification_results),
        completed_at=now,
        error=error,
    )
    return await _persist_and_return(
        repository, plan=plan, execution=execution, rollback=rollback_record
    )


def _determine_outcome(
    *, all_succeeded: bool, rollback_record: RollbackRecord | None
) -> ExecutionOutcome:
    if all_succeeded:
        return ExecutionOutcome.SUCCEEDED
    if rollback_record is not None:
        if rollback_record.outcome is RollbackOutcome.SUCCEEDED:
            return ExecutionOutcome.ROLLED_BACK
        return ExecutionOutcome.ROLLBACK_FAILED
    return ExecutionOutcome.FAILED


async def _run_rollback(
    completed_reversible: list[tuple[RemediationActionStep, StepExecutionResult]],
    *,
    adapters: dict[str, RemediationActionAdapter],
    context: RemediationAdapterContext,
    execution_id: str,
    remediation_plan_id: str,
    initiated_by: str,
    now: datetime,
    rollback_id: str | None = None,
    reason: str = "a subsequent step failed; reversing completed reversible steps",
) -> RollbackRecord:
    rollback_step_results: list[RollbackStepResult] = []
    # Reverse completed reversible steps only, in reverse execution order.
    for step, exec_result in reversed(completed_reversible):
        adapter = adapters.get(step.adapter_id)
        if adapter is None:
            rollback_step_results.append(
                RollbackStepResult(
                    reverses_step_index=step.step_index,
                    adapter_id=step.adapter_id,
                    succeeded=False,
                    completed_at=now,
                    error="rollback adapter is unavailable",
                )
            )
            continue
        try:
            result = await adapter.rollback(step, exec_result, context)
        except Exception:
            result = RollbackStepResult(
                reverses_step_index=step.step_index,
                adapter_id=step.adapter_id,
                succeeded=False,
                completed_at=now,
                error="rollback handler failed",
            )
        rollback_step_results.append(result)
    all_succeeded = bool(rollback_step_results) and all(
        item.succeeded for item in rollback_step_results
    )
    outcome = RollbackOutcome.SUCCEEDED if all_succeeded else RollbackOutcome.FAILED
    return RollbackRecord(
        rollback_id=rollback_id or f"rb_{execution_id}",
        execution_id=execution_id,
        remediation_plan_id=remediation_plan_id,
        initiated_at=now,
        initiated_by=initiated_by,
        reason=reason,
        outcome=outcome,
        step_results=tuple(rollback_step_results),
        completed_at=now,
    )
