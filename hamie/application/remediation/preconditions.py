"""Backup and precondition verification (HAMIE Phase 2B).

No real backup provider integration exists in this repository today --
verified directly (full-repo ``grep -ri backup`` finds only HAMIE's own
Store-document migration checkpoint mechanism and an unenforced
declarative ``backup_required`` flag on ``CanonicalRecommendation``; see
``docs/REMEDIATION_ENGINE.md``). This module never fabricates backup
integrity: ``NullBackupProvider`` is the only provider Phase 2B ships,
and it always reports verification as unavailable -- never an assumed
pass -- so any step that declares ``required_backup=REQUIRED`` is
provably always blocked until a real provider is added in a later phase.

Precondition checks beyond backup (recommendation still active, target
identity unchanged, dependency digest unchanged, approval valid, lock
held, adapter available) are pure comparisons over already-fetched state
-- this module performs no repository I/O itself; the execution
coordinator (``coordinator.py``) is responsible for fetching current
state and passing it in, keeping this layer independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from ...domain.recommendation import (
    CanonicalRecommendation,
    RecommendationLifecycleState,
)
from ...domain.remediation import (
    BackupRequirement,
    RemediationActionStep,
    RemediationPlan,
)
from ...domain.remediation_approval import ApprovalRecord


class BackupCompletionStatus(StrEnum):
    """Whether a backup covering the target actually finished."""

    UNAVAILABLE = "unavailable"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class BackupIntegrityStatus(StrEnum):
    """Whether a completed backup was verified as restorable."""

    UNKNOWN = "unknown"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BackupPreparationResult:
    """Sanitized result for create/poll/linkage operations."""

    provider_available: bool
    accepted: bool
    completion_status: BackupCompletionStatus
    backup_identifier: str | None = None
    proposal_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class BackupVerificationResult:
    """An honest record of backup status -- never a fabricated pass."""

    required: bool
    provider: str
    completion_status: BackupCompletionStatus
    integrity_status: BackupIntegrityStatus
    backup_identifier: str | None = None
    backup_timestamp: datetime | None = None
    backup_scope: tuple[str, ...] = ()
    age_seconds: float | None = None
    target_coverage: tuple[str, ...] = ()
    verification_method: str = "none@1"
    errors: tuple[str, ...] = ()
    expires_at: datetime | None = None

    @property
    def passes(self) -> bool:
        """Return whether this result clears a required-backup precondition."""
        if not self.required:
            return True
        return (
            self.completion_status is BackupCompletionStatus.COMPLETE
            and self.integrity_status is BackupIntegrityStatus.VERIFIED
        )


class BackupProvider(Protocol):
    """Narrow fail-closed backup lifecycle required by remediation."""

    async def async_available(self) -> bool: ...

    async def async_create(
        self,
        *,
        proposal_id: str,
        name: str,
        target_identity_keys: tuple[str, ...],
        now: datetime,
    ) -> BackupPreparationResult: ...

    async def async_poll(
        self, *, backup_identifier: str, proposal_id: str, now: datetime
    ) -> BackupPreparationResult: ...

    async def async_verify_linkage(
        self, *, backup_identifier: str, proposal_id: str, now: datetime
    ) -> BackupPreparationResult: ...

    async def async_verify(
        self, *, target_identity_key: str, now: datetime
    ) -> BackupVerificationResult: ...


class NullBackupProvider:
    """The only backup provider Phase 2B ships: honestly absent.

    Not a placeholder pending wiring -- this *is* what "no backup
    integration exists" looks like represented truthfully.
    """

    async def async_available(self) -> bool:
        """Report that no usable provider is configured."""
        return False

    def _unavailable(self, proposal_id: str) -> BackupPreparationResult:
        return BackupPreparationResult(
            provider_available=False,
            accepted=False,
            completion_status=BackupCompletionStatus.UNAVAILABLE,
            proposal_id=proposal_id,
            error_code="backup_provider_unavailable",
        )

    async def async_create(
        self,
        *,
        proposal_id: str,
        name: str,
        target_identity_keys: tuple[str, ...],
        now: datetime,
    ) -> BackupPreparationResult:
        """Refuse creation without generating a fake identifier."""
        return self._unavailable(proposal_id)

    async def async_poll(
        self, *, backup_identifier: str, proposal_id: str, now: datetime
    ) -> BackupPreparationResult:
        """Refuse polling because no backup could have been created."""
        return self._unavailable(proposal_id)

    async def async_verify_linkage(
        self, *, backup_identifier: str, proposal_id: str, now: datetime
    ) -> BackupPreparationResult:
        """Refuse linkage verification without provider evidence."""
        return self._unavailable(proposal_id)

    async def async_verify(
        self, *, target_identity_key: str, now: datetime
    ) -> BackupVerificationResult:
        return BackupVerificationResult(
            required=True,
            provider="none",
            completion_status=BackupCompletionStatus.UNAVAILABLE,
            integrity_status=BackupIntegrityStatus.UNKNOWN,
            errors=("no backup provider is configured",),
        )


async def verify_backup_for_step(
    step: RemediationActionStep, *, provider: BackupProvider, now: datetime
) -> BackupVerificationResult:
    """Return backup status for one step, honestly, never fabricated."""
    if step.required_backup is not BackupRequirement.REQUIRED:
        return BackupVerificationResult(
            required=False,
            provider="not_required",
            completion_status=BackupCompletionStatus.UNAVAILABLE,
            integrity_status=BackupIntegrityStatus.UNKNOWN,
        )
    return await provider.async_verify(
        target_identity_key=step.target.identity_key, now=now
    )


@dataclass(frozen=True, slots=True)
class PreconditionCheck:
    """One named pass/fail precondition result."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PreconditionReport:
    """The complete set of precondition checks for one execution attempt."""

    checks: tuple[PreconditionCheck, ...]

    @property
    def all_passed(self) -> bool:
        return all(item.passed for item in self.checks)

    @property
    def failures(self) -> tuple[PreconditionCheck, ...]:
        return tuple(item for item in self.checks if not item.passed)


def verify_preconditions(
    *,
    plan: RemediationPlan,
    current_recommendation: CanonicalRecommendation | None,
    approval: ApprovalRecord | None,
    lock_held: bool,
    adapter_available: bool,
    backup_result: BackupVerificationResult,
    now: datetime,
) -> PreconditionReport:
    """Fail-closed precondition evaluation before execution may proceed.

    Every check defaults to failing when its input is missing or
    uncertain -- an absent recommendation, a missing approval, or an
    unheld lock is never treated as "probably fine."

    A batch-disable plan (``domain/remediation_planner.py``'s
    ``plan_batch_disable_remediation``) is never built from a
    ``CanonicalRecommendation`` at all -- its candidates come from the
    cleanup classification engine, not one recommendation -- so the
    three recommendation-derived checks below do not apply to it and
    are reported as trivially passing rather than failing closed on an
    absence that was never expected in the first place. Every other
    plan type is completely unaffected: a genuinely missing or stale
    recommendation still fails closed exactly as before.
    """
    is_batch_plan = (
        bool(plan.actions) and plan.actions[0].target.kind == "hamie.entity_batch"
    )
    checks: list[PreconditionCheck] = []

    checks.append(
        PreconditionCheck(
            name="recommendation_active",
            passed=(
                is_batch_plan
                or (
                    current_recommendation is not None
                    and current_recommendation.lifecycle_state
                    is RecommendationLifecycleState.ACTIVE
                )
            ),
            detail=(
                "not applicable to a batch-disable plan"
                if is_batch_plan
                else "recommendation is active"
                if current_recommendation is not None
                and current_recommendation.lifecycle_state
                is RecommendationLifecycleState.ACTIVE
                else "recommendation is missing or no longer active"
            ),
        )
    )
    revision_unchanged = is_batch_plan or (
        current_recommendation is not None
        and current_recommendation.content_revision == plan.recommendation_revision
    )
    checks.append(
        PreconditionCheck(
            name="recommendation_revision_unchanged",
            passed=revision_unchanged,
            detail=(
                "not applicable to a batch-disable plan"
                if is_batch_plan
                else "recommendation revision matches the plan"
                if revision_unchanged
                else "recommendation revision changed since planning"
            ),
        )
    )
    target_unchanged = is_batch_plan or (
        current_recommendation is not None
        and current_recommendation.affected_object.identity_key
        == plan.actions[0].target.identity_key
        and not current_recommendation.affected_object.tombstoned
    )
    checks.append(
        PreconditionCheck(
            name="target_identity_unchanged",
            passed=target_unchanged,
            detail=(
                "not applicable to a batch-disable plan"
                if is_batch_plan
                else "target identity matches the plan"
                if target_unchanged
                else "target identity changed or is tombstoned"
            ),
        )
    )
    approval_valid = approval is not None and approval.is_valid_for(
        plan_fingerprint=plan.plan_fingerprint,
        preview_digest=plan.preview_digest or "",
        now=now,
    )
    checks.append(
        PreconditionCheck(
            name="approval_valid",
            passed=approval_valid,
            detail=(
                "approval is valid for this exact plan fingerprint"
                if approval_valid
                else "approval is missing, expired, revoked, or bound to a "
                "different plan/preview"
            ),
        )
    )
    checks.append(
        PreconditionCheck(
            name="lock_acquired",
            passed=lock_held,
            detail="execution lock held" if lock_held else "execution lock not held",
        )
    )
    checks.append(
        PreconditionCheck(
            name="adapter_available",
            passed=adapter_available,
            detail=(
                "adapter is registered"
                if adapter_available
                else "no adapter is registered for this plan's action_type"
            ),
        )
    )
    checks.append(
        PreconditionCheck(
            name="backup_valid",
            passed=backup_result.passes,
            detail=(
                "backup verified or not required"
                if backup_result.passes
                else "a required backup could not be verified"
            ),
        )
    )
    checks.append(
        PreconditionCheck(
            name="plan_not_expired",
            passed=plan.expires_at is None or now < plan.expires_at,
            detail=(
                "plan has not expired"
                if plan.expires_at is None or now < plan.expires_at
                else "plan has expired"
            ),
        )
    )
    return PreconditionReport(checks=tuple(checks))
