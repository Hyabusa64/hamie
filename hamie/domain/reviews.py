"""HAMIE-owned review state and audit values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .common import require_non_empty, require_utc

MAX_REVIEW_REASON_LENGTH = 500


class ReviewState(StrEnum):
    """Stable local review states."""

    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    SNOOZED = "snoozed"
    RETAINED = "retained"
    DISMISSED = "dismissed"


class ReviewAction(StrEnum):
    """Supported local review actions."""

    ACKNOWLEDGE = "acknowledge"
    SNOOZE = "snooze"
    RETAIN = "retain"
    DISMISS = "dismiss"
    REOPEN = "reopen"


ACTION_STATE = {
    ReviewAction.ACKNOWLEDGE: ReviewState.ACKNOWLEDGED,
    ReviewAction.SNOOZE: ReviewState.SNOOZED,
    ReviewAction.RETAIN: ReviewState.RETAINED,
    ReviewAction.DISMISS: ReviewState.DISMISSED,
    ReviewAction.REOPEN: ReviewState.NEW,
}

ALLOWED_PRIOR_STATES = {
    ReviewAction.ACKNOWLEDGE: frozenset({ReviewState.NEW}),
    ReviewAction.SNOOZE: frozenset(
        {ReviewState.NEW, ReviewState.ACKNOWLEDGED, ReviewState.RETAINED}
    ),
    ReviewAction.RETAIN: frozenset({ReviewState.NEW, ReviewState.ACKNOWLEDGED}),
    ReviewAction.DISMISS: frozenset(
        {
            ReviewState.NEW,
            ReviewState.ACKNOWLEDGED,
            ReviewState.SNOOZED,
            ReviewState.RETAINED,
        }
    ),
    ReviewAction.REOPEN: frozenset(
        {
            ReviewState.ACKNOWLEDGED,
            ReviewState.SNOOZED,
            ReviewState.RETAINED,
            ReviewState.DISMISSED,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    """One immutable review transition."""

    finding_id: str
    action: ReviewAction
    actor: str
    at: datetime
    finding_content_revision: int
    prior_state: ReviewState
    resulting_state: ReviewState
    reason: str | None = None
    snooze_until: datetime | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.finding_id, "finding_id")
        require_non_empty(self.actor, "actor")
        object.__setattr__(self, "at", require_utc(self.at, "at"))
        if self.finding_content_revision < 1:
            raise ValueError("finding_content_revision must be positive")
        if self.resulting_state is not ACTION_STATE[self.action]:
            raise ValueError("resulting state does not match review action")
        if self.prior_state not in ALLOWED_PRIOR_STATES[self.action]:
            raise ValueError("review action is not valid from prior state")
        if self.reason is not None:
            reason = self.reason.strip()
            if not reason or len(reason) > MAX_REVIEW_REASON_LENGTH:
                raise ValueError("reason must be bounded and non-empty")
            object.__setattr__(self, "reason", reason)
        if self.action is ReviewAction.SNOOZE:
            if self.snooze_until is None:
                raise ValueError("snooze requires snooze_until")
            snooze_until = require_utc(self.snooze_until, "snooze_until")
            if snooze_until <= self.at:
                raise ValueError("snooze_until must be after review time")
            object.__setattr__(self, "snooze_until", snooze_until)
        elif self.snooze_until is not None:
            raise ValueError("only snooze may set snooze_until")
