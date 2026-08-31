"""Batch entity-disable adapter (mission Part 8/22) -- the primary
"Disable unused entities" bulk cleanup capability.

Wraps the exact same ``HomeAssistantMutationPort``
``ha_adapters.py``'s single-entity ``EntityDisabledStateAdapter``
already uses -- no separate, duplicated entity-registry mutation path.
The batch is treated as one atomic unit:

- **Fail-closed staleness precondition** (mission Phase 7 precedent):
  ``execute`` recomputes a single fingerprint over every member
  entity's current ``disabled_by`` state and refuses to run unless it
  matches the plan-time ``expected_before_digest`` parameter exactly.
- **All-or-nothing**: if any entity fails to disable partway through,
  every entity this attempt already changed is restored before
  reporting the step as failed -- there is no code path that leaves
  the batch in a half-mutated state.
- **Local rollback**: on success, the exact prior ``disabled_by`` value
  of every member entity is carried forward as the step's
  ``rollback_token`` (compact ``entity_id=value`` lines, bounded by
  ``domain/entity_batch.py``'s ``MAX_BATCH_ENTITIES``), so a later
  rollback restores every entity's exact previous state.
"""

from __future__ import annotations

import contextlib
import hashlib
from typing import Any, Protocol

from ...domain.entity_batch import decode_entity_id_batch
from ...domain.remediation import RemediationActionStep
from ...domain.remediation_execution import (
    RollbackStepResult,
    StepExecutionResult,
    VerificationResult,
)
from .adapters import (
    AdapterPreviewResult,
    AdapterValidationResult,
    RemediationAdapterContext,
)


class EntityMutationPort(Protocol):
    """The narrow entity-registry boundary this adapter needs.

    Deliberately not imported from ``ha_adapters.py``'s
    ``HomeAssistantMutationPort`` -- that module needs to import this
    adapter to register it in ``home_assistant_adapters()``, so sharing
    the Protocol class here would create an import cycle. Any real
    implementation of ``HomeAssistantMutationPort`` (structurally a
    superset of this) already satisfies this Protocol.
    """

    async def entity_record(self, entity_id: str) -> Any: ...

    async def set_entity_disabled_by(
        self, entity_id: str, disabled_by: str | None
    ) -> None: ...


MAX_SUMMARY_CHARS = 4_000
DISABLED_BY_VALUE = "user"


def _fingerprint(states: dict[str, str | None]) -> str:
    parts = sorted(f"{entity_id}={value or ''}" for entity_id, value in states.items())
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _encode_state_summary(states: dict[str, str | None]) -> str:
    lines = [
        f"{entity_id}={value or ''}" for entity_id, value in sorted(states.items())
    ]
    text = "\n".join(lines)
    if len(text) > MAX_SUMMARY_CHARS:
        raise ValueError("batch state summary exceeds the storable bound")
    return text


def _decode_state_summary(text: str) -> dict[str, str | None]:
    states: dict[str, str | None] = {}
    for line in text.split("\n"):
        if not line:
            continue
        entity_id, _, value = line.partition("=")
        states[entity_id] = value or None
    return states


def _idempotency_key(
    step: RemediationActionStep, context: RemediationAdapterContext
) -> str:
    return f"{context.execution_id}:{step.step_index}:{step.adapter_id}"


class DisableEntityBatchAdapter:
    adapter_id = "disable_entity_batch_adapter"
    adapter_version = 1

    def __init__(self, port: EntityMutationPort) -> None:
        self._port = port

    def _entity_ids(self, step: RemediationActionStep) -> tuple[str, ...]:
        return decode_entity_id_batch(step.parameters)

    async def _current_states(
        self, entity_ids: tuple[str, ...]
    ) -> dict[str, str | None]:
        states: dict[str, str | None] = {}
        for entity_id in entity_ids:
            record = await self._port.entity_record(entity_id)
            states[entity_id] = record.disabled_by if record is not None else None
        return states

    def _failure(
        self,
        step: RemediationActionStep,
        context: RemediationAdapterContext,
        started_at: Any,
        error: str,
    ) -> StepExecutionResult:
        return StepExecutionResult(
            step_index=step.step_index,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            attempt=1,
            mutation_occurred=False,
            succeeded=False,
            idempotency_key=_idempotency_key(step, context),
            started_at=started_at,
            completed_at=context.now,
            error=error,
        )

    async def validate(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterValidationResult:
        if step.target.kind != "hamie.entity_batch":
            return AdapterValidationResult(
                valid=False, errors=(f"unsupported target kind: {step.target.kind}",)
            )
        try:
            entity_ids = self._entity_ids(step)
        except ValueError as err:
            return AdapterValidationResult(valid=False, errors=(str(err),))
        if not entity_ids:
            return AdapterValidationResult(
                valid=False, errors=("batch contains no entities",)
            )
        if "expected_before_digest" not in dict(step.parameters):
            return AdapterValidationResult(
                valid=False, errors=("missing expected_before_digest parameter",)
            )
        return AdapterValidationResult(valid=True)

    async def preview(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterPreviewResult:
        entity_ids = self._entity_ids(step)
        states = await self._current_states(entity_ids)
        before = ", ".join(
            f"{entity_id} ({value or 'enabled'})"
            for entity_id, value in sorted(states.items())
        )[:MAX_SUMMARY_CHARS]
        after = f"{len(entity_ids)} entities disabled (disabled_by={DISABLED_BY_VALUE})"
        return AdapterPreviewResult(
            rendered_before=before or "(none)", rendered_after=after
        )

    async def execute(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> StepExecutionResult:
        started = context.now
        validation = await self.validate(step, context)
        if not validation.valid:
            return self._failure(
                step, context, started, "; ".join(validation.errors) or "invalid"
            )
        entity_ids = self._entity_ids(step)
        params = dict(step.parameters)
        current_states = await self._current_states(entity_ids)
        if _fingerprint(current_states) != params["expected_before_digest"]:
            return self._failure(
                step,
                context,
                started,
                "stale_target_fingerprint: one or more batch member entities "
                "changed since this plan was created",
            )

        changed: list[str] = []
        failed_entity: str | None = None
        failed_reason: str | None = None
        for entity_id in entity_ids:
            try:
                await self._port.set_entity_disabled_by(entity_id, DISABLED_BY_VALUE)
                changed.append(entity_id)
            except Exception as err:
                failed_entity = entity_id
                failed_reason = type(err).__name__
                break

        if failed_entity is not None:
            # All-or-nothing: restore everything this attempt already
            # changed before reporting failure -- never leave a
            # half-mutated batch.
            for entity_id in changed:
                with contextlib.suppress(Exception):
                    await self._port.set_entity_disabled_by(
                        entity_id, current_states[entity_id]
                    )
            return self._failure(
                step,
                context,
                started,
                f"batch_partial_failure: {failed_entity} failed "
                f"({failed_reason}); {len(changed)} entity change(s) were "
                "automatically rolled back",
            )

        return StepExecutionResult(
            step_index=step.step_index,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            attempt=1,
            mutation_occurred=True,
            succeeded=True,
            idempotency_key=_idempotency_key(step, context),
            started_at=started,
            completed_at=context.now,
            observed_before_state=_encode_state_summary(current_states),
            observed_after_state=f"{len(changed)} entities disabled",
            rollback_token=_encode_state_summary(current_states),
        )

    async def verify(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> VerificationResult:
        entity_ids = self._entity_ids(step)
        current_states = await self._current_states(entity_ids)
        disabled_count = sum(
            1 for value in current_states.values() if value == DISABLED_BY_VALUE
        )
        all_disabled = disabled_count == len(entity_ids)
        succeeded = execution_result.succeeded and all_disabled
        return VerificationResult(
            step_index=step.step_index,
            method=step.verification.method,
            expected_result=f"{len(entity_ids)} entities disabled",
            observed_result=f"{disabled_count} of {len(entity_ids)} disabled",
            succeeded=succeeded,
            confidence="high",
            checked_at=context.now,
            user_visible_impact=f"{len(entity_ids)} entities removed from active use",
            errors=() if succeeded else ("not every batch member entity is disabled",),
        )

    async def rollback(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> RollbackStepResult:
        if execution_result.rollback_token is None:
            return RollbackStepResult(
                reverses_step_index=step.step_index,
                adapter_id=self.adapter_id,
                succeeded=False,
                completed_at=context.now,
                error="no rollback data was recorded for this execution",
            )
        prior_states = _decode_state_summary(execution_result.rollback_token)
        restored: list[str] = []
        failed: list[str] = []
        for entity_id, prior_value in prior_states.items():
            try:
                await self._port.set_entity_disabled_by(entity_id, prior_value)
                restored.append(entity_id)
            except Exception:
                failed.append(entity_id)
        succeeded = not failed
        return RollbackStepResult(
            reverses_step_index=step.step_index,
            adapter_id=self.adapter_id,
            succeeded=succeeded,
            completed_at=context.now,
            observed_state_after_rollback=(
                f"{len(restored)} entities restored"
                if succeeded
                else f"{len(restored)} restored, {len(failed)} failed"
            ),
            error=(
                None
                if succeeded
                else f"{len(failed)} entities failed to roll back: {sorted(failed)[:5]}"
            ),
        )


async def compute_batch_fingerprint(hass: Any, entity_ids: tuple[str, ...]) -> str:
    """Return the current-state fingerprint for a candidate batch.

    Used by the application layer (``application/cleanup_coordinator.py``)
    at plan-creation time to fill in
    ``plan_batch_disable_remediation``'s ``expected_before_digest`` --
    the domain planner itself never performs I/O, so this fetch must
    happen here, outside ``domain/``. Local import avoids a module
    import cycle with ``ha_adapters.py`` (which itself imports this
    module to register ``DisableEntityBatchAdapter``).
    """
    from .ha_adapters import HassHomeAssistantMutationPort

    port = HassHomeAssistantMutationPort(hass)
    states: dict[str, str | None] = {}
    for entity_id in entity_ids:
        record = await port.entity_record(entity_id)
        states[entity_id] = record.disabled_by if record is not None else None
    return _fingerprint(states)
