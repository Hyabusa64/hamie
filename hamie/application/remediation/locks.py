"""Restart-safe execution locking and replay protection (HAMIE Phase 2B).

Locks and replay tokens are persisted inside the same generation-guarded
``RepositoryState`` document everything else lives in (see
``application/persistence.py``) -- never held only in memory, so a
process restart mid-execution cannot silently forget a lock was held.
Acquisition uses the exact same optimistic-concurrency pattern as every
other repository write: load, compute ``next_state``, commit with
``expected_generation``, and on ``GenerationConflictError`` retry a
bounded number of times before failing closed -- never assuming
acquisition succeeded when ownership is uncertain.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from ...domain.common import stable_digest
from ...domain.remediation_execution import ExecutionLockRecord, ExecutionReplayToken
from ..persistence import (
    MAX_REMEDIATION_REPLAY_TOKENS,
    GenerationConflictError,
    PersistenceUnitOfWorkPort,
)

DEFAULT_LEASE = timedelta(minutes=10)
MAX_ACQUIRE_ATTEMPTS = 5


class LockConflictError(RuntimeError):
    """A lock or replay token could not be acquired/recorded.

    Raised both for a genuine conflict (something else holds the lock,
    or this token was already used) and for repeated uncertainty
    (persistent ``GenerationConflictError`` retries exhausted) -- in
    both cases the caller must treat the attempt as failed, never as
    "probably succeeded."
    """


async def async_acquire_lock(
    repository: PersistenceUnitOfWorkPort,
    *,
    remediation_plan_id: str,
    target_identity_key: str,
    owner_execution_id: str,
    now: datetime,
    lease: timedelta = DEFAULT_LEASE,
) -> ExecutionLockRecord:
    """Acquire an exclusive, persisted lock on one (plan, target) pair.

    Blocks concurrent execution of the same plan, concurrent mutation of
    the same target, and overlapping batch actions on the same object --
    a still-held lock on *either* dimension is a conflict.
    """
    for _attempt in range(MAX_ACQUIRE_ATTEMPTS):
        state = await repository.async_load()
        conflicting = [
            lock
            for lock in state.remediation_locks
            if lock.is_held_at(now)
            and (
                lock.remediation_plan_id == remediation_plan_id
                or lock.target_identity_key == target_identity_key
            )
        ]
        if conflicting:
            raise LockConflictError(
                f"a lock is already held for plan={remediation_plan_id} "
                f"or target={target_identity_key}"
            )
        lock_id = (
            "lock_"
            + stable_digest(
                remediation_plan_id,
                target_identity_key,
                owner_execution_id,
                now.isoformat(),
            )[:24]
        )
        new_lock = ExecutionLockRecord(
            lock_id=lock_id,
            remediation_plan_id=remediation_plan_id,
            target_identity_key=target_identity_key,
            owner_execution_id=owner_execution_id,
            acquired_at=now,
            expires_at=now + lease,
        )
        # Drop expired/released locks to keep the bounded collection from
        # filling with dead entries -- never drops a still-held lock.
        retained = tuple(
            lock for lock in state.remediation_locks if lock.is_held_at(now)
        )
        next_state = replace(
            state,
            remediation_locks=(*retained, new_lock),
            generation=state.generation + 1,
        )
        try:
            await repository.async_commit(
                next_state, expected_generation=state.generation
            )
            return new_lock
        except GenerationConflictError:
            continue
    raise LockConflictError(
        "could not acquire lock: repeated generation conflicts, ownership uncertain"
    )


async def async_release_lock(
    repository: PersistenceUnitOfWorkPort,
    *,
    lock_id: str,
    reason: str,
    now: datetime,
) -> None:
    """Release a held lock. Idempotent: releasing twice is a no-op."""
    for _attempt in range(MAX_ACQUIRE_ATTEMPTS):
        state = await repository.async_load()
        target = next(
            (lock for lock in state.remediation_locks if lock.lock_id == lock_id),
            None,
        )
        if target is None or target.released_at is not None:
            return
        released = replace(target, released_at=now, release_reason=reason)
        next_locks = tuple(
            released if lock.lock_id == lock_id else lock
            for lock in state.remediation_locks
        )
        next_state = replace(
            state, remediation_locks=next_locks, generation=state.generation + 1
        )
        try:
            await repository.async_commit(
                next_state, expected_generation=state.generation
            )
            return
        except GenerationConflictError:
            continue
    raise LockConflictError(
        f"could not release lock {lock_id}: repeated generation conflicts"
    )


def is_lock_held(
    repository_locks: tuple[ExecutionLockRecord, ...],
    *,
    lock_id: str,
    now: datetime,
) -> bool:
    """Pure helper: whether a specific lock is currently held."""
    return any(
        lock.lock_id == lock_id and lock.is_held_at(now) for lock in repository_locks
    )


async def async_check_and_record_replay_token(
    repository: PersistenceUnitOfWorkPort,
    *,
    token: str,
    remediation_plan_id: str,
    plan_fingerprint: str,
    execution_id: str,
) -> bool:
    """Record ``token`` if new; return ``False`` if this is a replay.

    Bounded and trimmed like ``IdempotencyRecord``
    (``application/persistence.py``) -- the oldest tokens are dropped
    first once the collection is full, never a still-relevant one.
    """
    for _attempt in range(MAX_ACQUIRE_ATTEMPTS):
        state = await repository.async_load()
        if any(item.token == token for item in state.remediation_replay_tokens):
            return False
        new_token = ExecutionReplayToken(
            token=token,
            remediation_plan_id=remediation_plan_id,
            plan_fingerprint=plan_fingerprint,
            execution_id=execution_id,
        )
        trimmed = (*state.remediation_replay_tokens, new_token)[
            -MAX_REMEDIATION_REPLAY_TOKENS:
        ]
        next_state = replace(
            state,
            remediation_replay_tokens=trimmed,
            generation=state.generation + 1,
        )
        try:
            await repository.async_commit(
                next_state, expected_generation=state.generation
            )
            return True
        except GenerationConflictError:
            continue
    raise LockConflictError(
        f"could not record replay token {token}: repeated generation conflicts"
    )
