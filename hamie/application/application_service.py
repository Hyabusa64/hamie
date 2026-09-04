"""Presentation-neutral finding query and review command service."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from ..analysis.analyzers.unavailable_entities import ANALYZER_ID
from ..domain.findings import Finding, FindingLifecycle
from ..domain.reviews import ACTION_STATE, ReviewAction, ReviewRecord
from .persistence import (
    IdempotencyRecord,
    PersistenceUnitOfWorkPort,
    RepositoryState,
)
from .ports import Clock
from .scan_coordinator import ProjectionPort, ScanCoordinator, ScanResult, SystemClock


class ApplicationError(RuntimeError):
    """Base stable application error."""


class FindingNotFoundError(ApplicationError):
    """Requested finding does not exist."""


class RevisionConflictError(ApplicationError):
    """Finding content changed before a review command."""


class IdempotencyConflictError(ApplicationError):
    """Idempotency token was already used for a different command."""


class InvalidReviewTransitionError(ApplicationError):
    """Review command is invalid for the current finding lifecycle."""


class StateTransitionPort(Protocol):
    """Optional post-commit lifecycle publication boundary."""

    async def async_state_committed(
        self, current: RepositoryState, committed: RepositoryState
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class FindingPage:
    """Bounded finding query result."""

    items: tuple[Finding, ...]
    total: int
    offset: int
    limit: int
    generation: int


class HamieApplicationService:
    """Stable internal API used by HA services, Repairs, and diagnostics."""

    def __init__(
        self,
        coordinator: ScanCoordinator,
        repository: PersistenceUnitOfWorkPort,
        projection: ProjectionPort,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._repository = repository
        self._projection = projection
        self._clock = clock or SystemClock()
        self._transition_listener: StateTransitionPort | None = None

    def set_transition_listener(self, listener: StateTransitionPort) -> None:
        """Attach finite post-commit publication without changing command logic."""
        self._transition_listener = listener

    async def async_start_full_evaluation(self) -> ScanResult:
        """Start or coalesce a full entity-state evaluation."""
        return await self._coordinator.async_request_scan(trigger="manual")

    async def async_query_findings(
        self,
        *,
        unavailable_only: bool = False,
        include_resolved: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> FindingPage:
        """Query canonical findings without exposing repositories."""
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("offset must be non-negative and limit must be 1..100")
        state = await self._repository.async_load()
        items = tuple(
            item
            for item in state.findings
            if (not unavailable_only or item.analyzer_id == ANALYZER_ID)
            and (include_resolved or item.lifecycle is FindingLifecycle.OPEN)
        )
        return FindingPage(
            items=items[offset : offset + limit],
            total=len(items),
            offset=offset,
            limit=limit,
            generation=state.generation,
        )

    async def async_get_finding(self, finding_id: str) -> Finding:
        """Retrieve one finding by stable ID."""
        state = await self._repository.async_load()
        return self._find(state, finding_id)

    async def async_acknowledge(
        self, finding_id: str, *, expected_revision: int, token: str, actor: str
    ) -> Finding:
        """Acknowledge a finding in HAMIE-owned state."""
        return await self._review(
            finding_id,
            ReviewAction.ACKNOWLEDGE,
            expected_revision=expected_revision,
            token=token,
            actor=actor,
        )

    async def async_snooze(
        self,
        finding_id: str,
        *,
        expected_revision: int,
        token: str,
        actor: str,
        snooze_until: datetime,
        reason: str | None = None,
    ) -> Finding:
        """Snooze a finding in HAMIE-owned state."""
        return await self._review(
            finding_id,
            ReviewAction.SNOOZE,
            expected_revision=expected_revision,
            token=token,
            actor=actor,
            snooze_until=snooze_until,
            reason=reason,
        )

    async def async_retain(
        self,
        finding_id: str,
        *,
        expected_revision: int,
        token: str,
        actor: str,
        reason: str | None = None,
    ) -> Finding:
        """Record a local decision to retain the subject."""
        return await self._review(
            finding_id,
            ReviewAction.RETAIN,
            expected_revision=expected_revision,
            token=token,
            actor=actor,
            reason=reason,
        )

    async def async_dismiss(
        self,
        finding_id: str,
        *,
        expected_revision: int,
        token: str,
        actor: str,
        reason: str | None = None,
    ) -> Finding:
        """Dismiss a finding locally without changing Home Assistant."""
        return await self._review(
            finding_id,
            ReviewAction.DISMISS,
            expected_revision=expected_revision,
            token=token,
            actor=actor,
            reason=reason,
        )

    async def _review(
        self,
        finding_id: str,
        action: ReviewAction,
        *,
        expected_revision: int,
        token: str,
        actor: str,
        reason: str | None = None,
        snooze_until: datetime | None = None,
    ) -> Finding:
        if not token or token != token.strip() or len(token) > 128:
            raise ValueError(
                "idempotency token must be normalized and at most 128 characters"
            )
        state = await self._repository.async_load()
        command = f"review:{action.value}"
        replay = next((item for item in state.idempotency if item.token == token), None)
        if replay is not None:
            if replay.command != command or replay.finding_id != finding_id:
                raise IdempotencyConflictError("idempotency token already used")
            return self._find(state, finding_id)
        finding = self._find(state, finding_id)
        if finding.lifecycle is not FindingLifecycle.OPEN:
            raise InvalidReviewTransitionError("resolved findings cannot be reviewed")
        if finding.content_revision != expected_revision:
            raise RevisionConflictError("finding content revision changed")
        at = self._clock.now()
        resulting_state = ACTION_STATE[action]
        review = ReviewRecord(
            finding_id=finding_id,
            action=action,
            actor=actor,
            at=at,
            finding_content_revision=finding.content_revision,
            prior_state=finding.review_state,
            resulting_state=resulting_state,
            reason=reason,
            snooze_until=snooze_until,
        )
        updated = replace(
            finding,
            review_state=resulting_state,
            snooze_until=(snooze_until if action is ReviewAction.SNOOZE else None),
        )
        findings = tuple(
            updated if item.finding_id == finding_id else item
            for item in state.findings
        )
        idempotency = (
            *state.idempotency,
            IdempotencyRecord(token, command, finding_id, finding.content_revision),
        )[-128:]
        next_state = replace(
            state,
            generation=state.generation + 1,
            findings=findings,
            reviews=(*state.reviews, review)[-500:],
            idempotency=idempotency,
            projection_revision=state.projection_revision + 1,
        )
        await self._repository.async_commit(
            next_state, expected_generation=state.generation
        )
        await self._projection.async_sync(next_state)
        if self._transition_listener is not None:
            try:
                await self._transition_listener.async_state_committed(state, next_state)
            except Exception:
                pass
        return updated

    @staticmethod
    def _find(state: RepositoryState, finding_id: str) -> Finding:
        try:
            return next(
                item for item in state.findings if item.finding_id == finding_id
            )
        except StopIteration as err:
            raise FindingNotFoundError(
                f"finding {finding_id!r} does not exist"
            ) from err
