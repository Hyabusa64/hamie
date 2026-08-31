"""Application facade for the AI Control acknowledgement lifecycle.

Mirrors ``application/remediation/service.py``'s own facade discipline:
this module is the only thing the presentation layer talks to for AI
Control acknowledgement, and it does nothing but load/mutate/persist
``RepositoryState`` via the same generation-guarded commit-with-retry
pattern every other write path in HAMIE already uses.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from ..domain.ai_control import (
    AI_CONTROL_ACKNOWLEDGEMENT_VERSION,
    AiControlAcknowledgement,
    AiOperatingMode,
    effective_ai_mode,
)
from .persistence import (
    GenerationConflictError,
    PersistenceUnitOfWorkPort,
    RepositoryState,
)

MAX_COMMIT_ATTEMPTS = 5


class AiControlServiceError(RuntimeError):
    """A stable, non-sensitive AI Control failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class AiControlStatus:
    """The complete, read-only AI Control status the UI needs."""

    configured_mode: AiOperatingMode
    effective_mode: AiOperatingMode
    acknowledgement: AiControlAcknowledgement | None
    acknowledgement_required: bool
    current_acknowledgement_version: int


async def _commit_with_retry(
    repository: PersistenceUnitOfWorkPort, mutate
) -> RepositoryState:
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
    raise AiControlServiceError(
        "ai_control_internal_error",
        "Could not save the AI Control acknowledgement; please try again.",
    )


def get_status(
    repository_state: RepositoryState, *, configured_mode_raw: str
) -> AiControlStatus:
    """Return the current AI Control status. Never mutates anything."""
    try:
        configured_mode = AiOperatingMode(configured_mode_raw)
    except ValueError:
        configured_mode = AiOperatingMode.OBSERVE
    acknowledgement = repository_state.ai_control_acknowledgement
    effective = effective_ai_mode(
        configured_mode=configured_mode, acknowledgement=acknowledgement
    )
    return AiControlStatus(
        configured_mode=configured_mode,
        effective_mode=effective,
        acknowledgement=acknowledgement,
        acknowledgement_required=(
            configured_mode is AiOperatingMode.AI_CONTROL
            and effective is not AiOperatingMode.AI_CONTROL
        ),
        current_acknowledgement_version=AI_CONTROL_ACKNOWLEDGEMENT_VERSION,
    )


async def async_acknowledge_ai_control(
    repository: PersistenceUnitOfWorkPort,
    *,
    actor: str,
    now: datetime,
) -> AiControlAcknowledgement:
    """Record one explicit AI Control acknowledgement.

    Never called except from the dedicated, exact-text-confirming
    WebSocket command (``presentation/ai_control_api.py``) -- there is
    no other path in HAMIE that can create this record.
    """
    acknowledgement = AiControlAcknowledgement(
        version=AI_CONTROL_ACKNOWLEDGEMENT_VERSION,
        acknowledged_at=now,
        acknowledged_by=actor,
    )

    def _mutate(current: RepositoryState) -> RepositoryState:
        return replace(
            current,
            ai_control_acknowledgement=acknowledgement,
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate)
    return acknowledgement


async def async_revoke_ai_control_acknowledgement(
    repository: PersistenceUnitOfWorkPort,
) -> None:
    """Clear a previously granted acknowledgement (e.g. an explicit opt-out).

    Idempotent: clearing an already-absent acknowledgement is a no-op.
    """

    def _mutate(current: RepositoryState) -> RepositoryState:
        if current.ai_control_acknowledgement is None:
            return current
        return replace(
            current,
            ai_control_acknowledgement=None,
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate)
