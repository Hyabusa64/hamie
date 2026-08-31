"""Explicit, plan-bound approval records (HAMIE Phase 2B).

An ``ApprovalRecord`` is the durable evidence of exactly one human
decision about exactly one ``RemediationPlan``, identified by its
immutable ``plan_fingerprint``. Nothing infers approval from a
recommendation's review state, and nothing lets an approval outlive the
exact plan it was granted for -- if the plan changes (new evidence, new
dependencies, a different recommendation revision), its fingerprint
changes, and any existing approval simply no longer matches anything.

"Approve All" never exists as a single blanket token: a batch decision
is always N individual ``ApprovalRecord``s, one per ``plan_fingerprint``,
sharing only a ``batch_id`` for correlation (see
``application/remediation/coordinator.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .common import require_non_empty, require_utc

MAX_TEXT_LENGTH = 4_000
MAX_WARNINGS = 32


class ApprovalState(StrEnum):
    """The outcome of one human review decision."""

    GRANTED = "granted"
    REJECTED = "rejected"


class ApprovalScope(StrEnum):
    """What an approval covers."""

    SINGLE = "single"
    BATCH = "batch"


def _require_bounded(
    value: str, field_name: str, *, max_length: int = MAX_TEXT_LENGTH
) -> str:
    require_non_empty(value, field_name)
    if len(value) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    return value


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """One durable, plan-fingerprint-bound human decision.

    ``revoked_at``/``revoked_by``/``revocation_reason`` are the one
    additive mutation permitted after creation (via ``dataclasses.replace``
    in the application layer) -- everything else about a granted or
    rejected decision is fixed forever, matching the "immutable after
    completion except additive audit fields" persistence rule.
    """

    approval_id: str
    remediation_plan_id: str
    plan_fingerprint: str
    preview_digest: str
    recommendation_id: str
    recommendation_revision: int
    installation_id: str
    approved_by: str
    decided_at: datetime
    state: ApprovalState
    expires_at: datetime | None = None
    scope: ApprovalScope = ApprovalScope.SINGLE
    batch_id: str | None = None
    destructive_acknowledged: bool = False
    backup_acknowledged: bool = False
    warnings_acknowledged: tuple[str, ...] = ()
    rejection_reason: str | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.approval_id, "approval_id"),
            (self.remediation_plan_id, "remediation_plan_id"),
            (self.plan_fingerprint, "plan_fingerprint"),
            (self.preview_digest, "preview_digest"),
            (self.recommendation_id, "recommendation_id"),
            (self.installation_id, "installation_id"),
            (self.approved_by, "approved_by"),
        ):
            _require_bounded(value, name, max_length=512)
        if self.recommendation_revision < 1:
            raise ValueError("recommendation_revision must be positive")
        object.__setattr__(
            self, "decided_at", require_utc(self.decided_at, "decided_at")
        )
        if self.expires_at is not None:
            expires = require_utc(self.expires_at, "expires_at")
            if expires <= self.decided_at:
                raise ValueError("expires_at must be after decided_at")
            object.__setattr__(self, "expires_at", expires)
        object.__setattr__(
            self,
            "warnings_acknowledged",
            tuple(dict.fromkeys(self.warnings_acknowledged)),
        )
        if len(self.warnings_acknowledged) > MAX_WARNINGS:
            raise ValueError(f"warnings_acknowledged exceeds {MAX_WARNINGS} entries")

        if self.scope is ApprovalScope.BATCH and not self.batch_id:
            raise ValueError("a batch-scoped approval requires batch_id")
        if self.scope is ApprovalScope.SINGLE and self.batch_id is not None:
            raise ValueError("a single-scoped approval cannot carry batch_id")

        if self.state is ApprovalState.REJECTED:
            if not self.rejection_reason:
                raise ValueError("a rejected approval requires rejection_reason")
            if self.expires_at is not None:
                raise ValueError("a rejected approval cannot carry expires_at")
            if self.destructive_acknowledged or self.backup_acknowledged:
                raise ValueError(
                    "a rejected approval cannot carry acknowledgement flags"
                )
        else:
            if self.rejection_reason is not None:
                raise ValueError(
                    "rejection_reason is only meaningful for a rejected approval"
                )

        # Revocation is only meaningful for a previously granted approval,
        # and it is all-or-nothing: every revocation field must be set
        # together, never partially.
        revocation_fields = (
            self.revoked_at,
            self.revoked_by,
            self.revocation_reason,
        )
        any_revocation_field = any(field is not None for field in revocation_fields)
        all_revocation_fields = all(field is not None for field in revocation_fields)
        if any_revocation_field and not all_revocation_fields:
            raise ValueError(
                "revoked_at, revoked_by, and revocation_reason must be set together"
            )
        if any_revocation_field and self.state is not ApprovalState.GRANTED:
            raise ValueError("only a granted approval can be revoked")
        if self.revoked_at is not None:
            revoked_at = require_utc(self.revoked_at, "revoked_at")
            if revoked_at < self.decided_at:
                raise ValueError("revoked_at cannot precede decided_at")
            object.__setattr__(self, "revoked_at", revoked_at)
            _require_bounded(self.revoked_by or "", "revoked_by", max_length=512)
            _require_bounded(self.revocation_reason or "", "revocation_reason")

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_valid_for(
        self, *, plan_fingerprint: str, preview_digest: str, now: datetime
    ) -> bool:
        """Return whether this approval currently authorizes execution.

        Binds to the *exact* ``plan_fingerprint`` and ``preview_digest``
        supplied -- an approval for any other plan, or for the same plan
        after its preview changed, is never valid. A rejected or revoked
        approval is never valid; an expired one is never valid past its
        ``expires_at``.
        """
        if self.state is not ApprovalState.GRANTED:
            return False
        if self.is_revoked:
            return False
        if self.plan_fingerprint != plan_fingerprint:
            return False
        if self.preview_digest != preview_digest:
            return False
        current = require_utc(now, "now")
        if self.expires_at is not None and current >= self.expires_at:
            return False
        return True


def revoke_approval(
    approval: ApprovalRecord, *, revoked_by: str, reason: str, now: datetime
) -> ApprovalRecord:
    """Return a new, revoked copy of a granted approval.

    The only supported additive mutation of an ``ApprovalRecord`` after
    creation -- everything else about it is fixed forever.
    """
    if approval.state is not ApprovalState.GRANTED:
        raise ValueError("only a granted approval can be revoked")
    if approval.is_revoked:
        raise ValueError("approval is already revoked")
    return replace(
        approval,
        revoked_at=require_utc(now, "now"),
        revoked_by=revoked_by,
        revocation_reason=reason,
    )
