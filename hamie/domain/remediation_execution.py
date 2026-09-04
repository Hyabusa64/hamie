"""Execution, verification, rollback, and lock domain records (Phase 2B).

Pure data, no I/O: these are the durable, structured *outcomes* the
execution coordinator (``application/remediation/coordinator.py``)
records as it works through a ``RemediationPlan`` -- distinct from the
plan itself (the deterministic proposal) and from the adapter Protocol
(``application/remediation/adapters.py``, the thing that actually
produces these results by talking to a target).

Execution cannot be marked succeeded merely because an adapter call
returned without raising: every step's ``StepExecutionResult`` is paired
with its own ``VerificationResult``, and only a successful verification
lets a step count as done.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .common import require_non_empty, require_utc

MAX_TEXT_LENGTH = 4_000
MAX_LIST_ITEMS = 32


class ExecutionOutcome(StrEnum):
    """Overall outcome of one execution attempt."""

    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


class RollbackOutcome(StrEnum):
    """Overall outcome of one rollback attempt."""

    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class RemediationOutcome(StrEnum):
    """Did the repair actually solve the problem it was created for?

    Deliberately NOT an extension of ``ExecutionOutcome`` above, which
    answers a strictly narrower question: "did the mutation attempt run
    and verify its own steps?". A mutation can succeed, validate, and
    still leave the original root cause exactly where it was -- so
    ``ExecutionOutcome.SUCCEEDED`` and ``RemediationOutcome.RESOLVED``
    are different claims and folding them into one enum would let the
    weaker one masquerade as the stronger. ``ROLLED_BACK`` /
    ``ROLLBACK_FAILED`` appear in both for the same reason a rollback is
    visible at both layers; the names match on purpose.

    Only ``RESOLVED`` is success, and only deterministic post-repair
    evidence -- a genuinely fresh scan plus finding/incident
    reconciliation, regression checks and protected-invariant re-checks
    -- may produce it. Uncertainty becomes ``INCONCLUSIVE``, never
    success.
    """

    RESOLVED = "resolved"
    STILL_PRESENT = "still_present"
    REGRESSED = "regressed"
    VALIDATION_FAILED = "validation_failed"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"
    INCONCLUSIVE = "inconclusive"
    BLOCKED = "blocked"


#: Every outcome that leaves the incident unresolved. Membership is the
#: single source of truth for "may this incident be closed?" -- callers
#: must never test ``!= RESOLVED`` themselves and drift from it.
UNRESOLVED_REMEDIATION_OUTCOMES = frozenset(
    outcome for outcome in RemediationOutcome if outcome is not RemediationOutcome.RESOLVED
)

#: Outcomes that require operator attention rather than a retry.
ESCALATING_REMEDIATION_OUTCOMES = frozenset(
    {
        RemediationOutcome.REGRESSED,
        RemediationOutcome.ROLLBACK_FAILED,
    }
)


def _require_bounded(
    value: str, field_name: str, *, max_length: int = MAX_TEXT_LENGTH
) -> str:
    require_non_empty(value, field_name)
    if len(value) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    return value


def _bounded_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    deduped = tuple(dict.fromkeys(values))
    if len(deduped) > MAX_LIST_ITEMS:
        raise ValueError(f"{field_name} exceeds {MAX_LIST_ITEMS} items")
    if any(not item or len(item) > 1_000 for item in deduped):
        raise ValueError(f"{field_name} items must be bounded non-empty strings")
    return deduped


_SECRET_VALUE_PATTERN = re.compile(
    r"(password|secret|token|api[_-]?key|authorization)\s*[:=]\s*\S+"
    r"|bearer\s+\S+",
    re.IGNORECASE,
)


def _redact(value: str | None) -> str | None:
    """Best-effort redaction for freeform adapter error text.

    Adapters must never produce secret-bearing text in the first place
    (see ``application/remediation/adapters.py``); this is a defensive
    second layer, not the primary control.

    Deliberately narrower than a bare substring check on words like
    "token": this repository's own idempotency/replay machinery uses
    "token" as an ordinary identifier name in legitimate, non-secret
    business-reason text (e.g. "idempotency_token already used"). Only a
    recognized secret keyword immediately followed by ``key=value`` or
    ``key: value`` syntax, or a bare ``Bearer <value>``, is treated as an
    actual embedded secret.
    """
    if value is None:
        return None
    if _SECRET_VALUE_PATTERN.search(value):
        return "[redacted: error text withheld, may contain sensitive data]"
    return value


@dataclass(frozen=True, slots=True)
class StepExecutionResult:
    """The structured, versioned outcome of running one adapter's ``execute``."""

    step_index: int
    adapter_id: str
    adapter_version: int
    attempt: int
    mutation_occurred: bool
    succeeded: bool
    idempotency_key: str
    started_at: datetime
    completed_at: datetime
    observed_before_state: str | None = None
    observed_after_state: str | None = None
    rollback_token: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.step_index < 0:
            raise ValueError("step_index cannot be negative")
        if self.attempt < 1:
            raise ValueError("attempt must be positive")
        _require_bounded(self.adapter_id, "adapter_id", max_length=256)
        _require_bounded(self.idempotency_key, "idempotency_key", max_length=256)
        started = require_utc(self.started_at, "started_at")
        completed = require_utc(self.completed_at, "completed_at")
        if completed < started:
            raise ValueError("completed_at cannot precede started_at")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "completed_at", completed)
        object.__setattr__(self, "error", _redact(self.error))
        if self.succeeded and self.error:
            raise ValueError("a succeeded step result cannot carry an error")
        if not self.succeeded and not self.error:
            raise ValueError("a failed step result requires an error")
        for value, name in (
            (self.observed_before_state, "observed_before_state"),
            (self.observed_after_state, "observed_after_state"),
        ):
            if value is not None and len(value) > MAX_TEXT_LENGTH:
                raise ValueError(f"{name} exceeds {MAX_TEXT_LENGTH} characters")


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Deterministic post-action verification outcome for one step."""

    step_index: int
    method: str
    expected_result: str
    observed_result: str
    succeeded: bool
    confidence: str
    checked_at: datetime
    incomplete_checks: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    user_visible_impact: str = "unknown"
    rollback_recommended: bool = False

    def __post_init__(self) -> None:
        if self.step_index < 0:
            raise ValueError("step_index cannot be negative")
        _require_bounded(self.method, "method", max_length=256)
        _require_bounded(self.expected_result, "expected_result")
        _require_bounded(self.observed_result, "observed_result")
        _require_bounded(self.user_visible_impact, "user_visible_impact")
        if self.confidence not in {"low", "medium", "high"}:
            raise ValueError("confidence must be low, medium, or high")
        object.__setattr__(
            self, "checked_at", require_utc(self.checked_at, "checked_at")
        )
        object.__setattr__(
            self,
            "incomplete_checks",
            _bounded_tuple(self.incomplete_checks, "incomplete_checks"),
        )
        object.__setattr__(
            self, "errors", tuple(_redact(item) or item for item in self.errors)
        )
        object.__setattr__(self, "errors", _bounded_tuple(self.errors, "errors"))
        if self.succeeded and (self.errors or self.rollback_recommended):
            raise ValueError(
                "a succeeded verification cannot carry errors or recommend rollback"
            )
        # Execution cannot be marked succeeded merely because an adapter
        # returned without exception -- a verification with incomplete
        # checks can never itself claim success.
        if self.succeeded and self.incomplete_checks:
            raise ValueError(
                "a verification with incomplete checks cannot be marked succeeded"
            )


@dataclass(frozen=True, slots=True)
class ExecutionReplayToken:
    """Bounded replay marker preventing a duplicate execution attempt.

    Mirrors ``application/persistence.py``'s ``IdempotencyRecord`` shape
    deliberately -- domain/ cannot import the application layer, so this
    is a structurally identical, independently defined type.
    """

    token: str
    remediation_plan_id: str
    plan_fingerprint: str
    execution_id: str

    def __post_init__(self) -> None:
        _require_bounded(self.token, "token", max_length=256)
        _require_bounded(self.remediation_plan_id, "remediation_plan_id")
        _require_bounded(self.plan_fingerprint, "plan_fingerprint")
        _require_bounded(self.execution_id, "execution_id")


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """The complete, durable record of one execution attempt."""

    execution_id: str
    remediation_plan_id: str
    plan_fingerprint: str
    approval_id: str
    installation_id: str
    started_at: datetime
    started_by: str
    idempotency_token: str
    outcome: ExecutionOutcome
    step_results: tuple[StepExecutionResult, ...] = ()
    verification_results: tuple[VerificationResult, ...] = ()
    completed_at: datetime | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.execution_id, "execution_id"),
            (self.remediation_plan_id, "remediation_plan_id"),
            (self.plan_fingerprint, "plan_fingerprint"),
            (self.approval_id, "approval_id"),
            (self.installation_id, "installation_id"),
            (self.started_by, "started_by"),
            (self.idempotency_token, "idempotency_token"),
        ):
            _require_bounded(value, name, max_length=512)
        object.__setattr__(
            self, "started_at", require_utc(self.started_at, "started_at")
        )
        if self.completed_at is not None:
            completed = require_utc(self.completed_at, "completed_at")
            if completed < self.started_at:
                raise ValueError("completed_at cannot precede started_at")
            object.__setattr__(self, "completed_at", completed)
        object.__setattr__(
            self,
            "step_results",
            tuple(sorted(self.step_results, key=lambda item: item.step_index)),
        )
        object.__setattr__(
            self,
            "verification_results",
            tuple(sorted(self.verification_results, key=lambda item: item.step_index)),
        )
        object.__setattr__(self, "error", _redact(self.error))
        if self.outcome is ExecutionOutcome.IN_PROGRESS:
            if self.completed_at is not None:
                raise ValueError("an in-progress execution cannot have completed_at")
        elif self.completed_at is None:
            raise ValueError("a finished execution requires completed_at")
        if self.outcome is ExecutionOutcome.SUCCEEDED:
            all_steps_succeeded = all(item.succeeded for item in self.step_results)
            all_verified = all(item.succeeded for item in self.verification_results)
            if not (
                self.step_results
                and all_steps_succeeded
                and self.verification_results
                and all_verified
            ):
                raise ValueError(
                    "an execution cannot be marked succeeded unless every step "
                    "executed and every step was independently verified"
                )
        if self.outcome is ExecutionOutcome.FAILED and not self.error:
            raise ValueError("a failed execution requires an error")

    @property
    def is_terminal(self) -> bool:
        return self.outcome is not ExecutionOutcome.IN_PROGRESS


@dataclass(frozen=True, slots=True)
class RollbackStepResult:
    """The outcome of reversing exactly one previously-executed step."""

    reverses_step_index: int
    adapter_id: str
    succeeded: bool
    completed_at: datetime
    observed_state_after_rollback: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.reverses_step_index < 0:
            raise ValueError("reverses_step_index cannot be negative")
        _require_bounded(self.adapter_id, "adapter_id", max_length=256)
        object.__setattr__(
            self, "completed_at", require_utc(self.completed_at, "completed_at")
        )
        object.__setattr__(self, "error", _redact(self.error))
        if self.succeeded and self.error:
            raise ValueError("a succeeded rollback step cannot carry an error")
        if not self.succeeded and not self.error:
            raise ValueError("a failed rollback step requires an error")


@dataclass(frozen=True, slots=True)
class RollbackRecord:
    """The complete, durable record of one rollback attempt.

    Never replaces or deletes the original ``ExecutionRecord`` it
    reverses -- both are retained, so the full history (what ran, then
    what was undone) stays reconstructable.
    """

    rollback_id: str
    execution_id: str
    remediation_plan_id: str
    initiated_at: datetime
    initiated_by: str
    reason: str
    outcome: RollbackOutcome
    step_results: tuple[RollbackStepResult, ...] = ()
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.rollback_id, "rollback_id"),
            (self.execution_id, "execution_id"),
            (self.remediation_plan_id, "remediation_plan_id"),
            (self.initiated_by, "initiated_by"),
        ):
            _require_bounded(value, name, max_length=512)
        _require_bounded(self.reason, "reason")
        object.__setattr__(
            self, "initiated_at", require_utc(self.initiated_at, "initiated_at")
        )
        if self.completed_at is not None:
            completed = require_utc(self.completed_at, "completed_at")
            if completed < self.initiated_at:
                raise ValueError("completed_at cannot precede initiated_at")
            object.__setattr__(self, "completed_at", completed)
        object.__setattr__(
            self,
            "step_results",
            tuple(
                sorted(
                    self.step_results,
                    key=lambda item: item.reverses_step_index,
                    reverse=True,
                )
            ),
        )
        if self.outcome is RollbackOutcome.IN_PROGRESS:
            if self.completed_at is not None:
                raise ValueError("an in-progress rollback cannot have completed_at")
        elif self.completed_at is None:
            raise ValueError("a finished rollback requires completed_at")
        # Rollback failure must produce ROLLBACK_FAILED (here: FAILED),
        # never be silently reported as the execution's own outcome --
        # this record's outcome is the sole source of truth for that.
        if self.outcome is RollbackOutcome.SUCCEEDED:
            if not self.step_results or not all(
                item.succeeded for item in self.step_results
            ):
                raise ValueError(
                    "a rollback cannot be marked succeeded unless every "
                    "rollback step succeeded"
                )
        if self.outcome is RollbackOutcome.FAILED and all(
            item.succeeded for item in self.step_results
        ):
            raise ValueError(
                "a rollback marked failed must have at least one failed step"
            )


@dataclass(frozen=True, slots=True)
class ExecutionLockRecord:
    """A restart-safe, persisted lock on one plan/target pair.

    Acquired before execution begins and released (never deleted) when
    execution or rollback finishes -- ``release_reason`` distinguishes a
    normal release from a stale/expired one the coordinator had to break.
    """

    lock_id: str
    remediation_plan_id: str
    target_identity_key: str
    owner_execution_id: str
    acquired_at: datetime
    expires_at: datetime
    released_at: datetime | None = None
    release_reason: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.lock_id, "lock_id"),
            (self.remediation_plan_id, "remediation_plan_id"),
            (self.target_identity_key, "target_identity_key"),
            (self.owner_execution_id, "owner_execution_id"),
        ):
            _require_bounded(value, name, max_length=512)
        acquired = require_utc(self.acquired_at, "acquired_at")
        expires = require_utc(self.expires_at, "expires_at")
        if expires <= acquired:
            raise ValueError("expires_at must be after acquired_at")
        object.__setattr__(self, "acquired_at", acquired)
        object.__setattr__(self, "expires_at", expires)
        if self.released_at is not None:
            released = require_utc(self.released_at, "released_at")
            if released < acquired:
                raise ValueError("released_at cannot precede acquired_at")
            object.__setattr__(self, "released_at", released)
            if not self.release_reason:
                raise ValueError("a released lock requires release_reason")
        elif self.release_reason is not None:
            raise ValueError("release_reason is only meaningful for a released lock")

    def is_held_at(self, now: datetime) -> bool:
        """Return whether this lock is still exclusive at ``now``."""
        current = require_utc(now, "now")
        if self.released_at is not None:
            return False
        return current < self.expires_at
