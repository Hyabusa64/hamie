"""Narrow, typed remediation action adapters (HAMIE Phase 2B).

Every adapter implements ``RemediationActionAdapter`` with five distinct
methods -- ``validate``, ``preview``, ``execute``, ``verify``,
``rollback`` -- and no adapter may hide a mutation inside ``validate``
or ``preview``: only ``execute`` ever changes anything, and only after
the execution coordinator (``coordinator.py``) has confirmed a valid,
unexpired, unrevoked approval bound to the exact plan being run.

Two adapters ship in Phase 2B:

- ``ManualActionAdapter`` -- marks a recommendation for human follow-up.
  Its only "mutation" is the structured execution record itself; there
  is no external system of record to toggle.
- ``RecorderExclusionPatchAdapter`` -- generates a proposed recorder
  exclusion YAML patch as inert text, returned inside the execution
  result. It never writes to a file or to Home Assistant's
  configuration; the patch is an artifact for a human to review and
  apply themselves.
- ``FixtureTestAdapter`` -- mutates an isolated, injected in-memory (or
  temporary-file-backed) fixture store. This is a genuine, fully working
  adapter used to exercise the complete plan/approve/execute/verify/
  rollback lifecycle in tests. **It is not a production Home Assistant
  adapter** -- the action catalog restricts it to
  ``hamie.test_fixture`` targets, and this module additionally refuses
  to run it against anything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ...domain.common import require_non_empty
from ...domain.remediation import RemediationActionStep
from ...domain.remediation_execution import (
    RollbackStepResult,
    StepExecutionResult,
    VerificationResult,
)

MAX_ARTIFACT_LENGTH = 4_000


class AdapterError(RuntimeError):
    """Raised only for a programming/contract violation, never a normal failure.

    Ordinary adapter failures (a step that legitimately did not succeed)
    are reported as a *result* (``StepExecutionResult(succeeded=False, ...)``),
    never as a raised exception -- this mirrors ``PlanningRejection`` in
    ``domain/remediation_planner.py``.
    """


@dataclass(frozen=True, slots=True)
class RemediationAdapterContext:
    """The bounded, secret-free context every adapter call receives."""

    installation_id: str
    now: datetime
    execution_id: str

    def __post_init__(self) -> None:
        require_non_empty(self.installation_id, "installation_id")
        require_non_empty(self.execution_id, "execution_id")


@dataclass(frozen=True, slots=True)
class AdapterValidationResult:
    """The outcome of ``validate`` -- never mutates anything."""

    valid: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AdapterPreviewResult:
    """The outcome of ``preview`` -- never mutates anything.

    ``rendered_before``/``rendered_after`` are display-only, adapter-
    rendered text for a human reviewer; they are never part of any
    fingerprint (see ``compute_structural_preview_digest``, which only
    covers the deterministic structural fields already on the plan).
    """

    rendered_before: str | None
    rendered_after: str
    warnings: tuple[str, ...] = ()


class RemediationActionAdapter(Protocol):
    """The narrow contract every remediation action adapter must satisfy."""

    adapter_id: str
    adapter_version: int

    async def validate(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterValidationResult:
        """Check preconditions. Never mutates anything."""

    async def preview(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterPreviewResult:
        """Render what would happen. Never mutates anything."""

    async def execute(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> StepExecutionResult:
        """Perform the action exactly once. The only method that may mutate."""

    async def verify(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> VerificationResult:
        """Deterministically confirm the action actually worked."""

    async def rollback(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> RollbackStepResult:
        """Reverse a previously executed step. Never silently retries."""


def _idempotency_key(
    step: RemediationActionStep, context: RemediationAdapterContext
) -> str:
    return f"{context.execution_id}:{step.step_index}:{step.adapter_id}"


class ManualActionAdapter:
    """Marks a recommendation for human follow-up.

    The only observable "mutation" is the structured execution record
    itself -- HAMIE has no separate manual-marks system of record in
    Phase 2B, so there is nothing else to touch, and therefore nothing
    else that could drift out of sync with the record.
    """

    adapter_id = "manual_action_adapter"
    adapter_version = 1

    async def validate(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterValidationResult:
        if step.adapter_id != self.adapter_id:
            return AdapterValidationResult(
                valid=False, errors=("step is not routed to this adapter",)
            )
        return AdapterValidationResult(valid=True)

    async def preview(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterPreviewResult:
        return AdapterPreviewResult(
            rendered_before="not marked",
            rendered_after="marked for manual remediation",
        )

    async def execute(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> StepExecutionResult:
        started = context.now
        return StepExecutionResult(
            step_index=step.step_index,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            attempt=1,
            mutation_occurred=True,
            succeeded=True,
            idempotency_key=_idempotency_key(step, context),
            started_at=started,
            completed_at=started,
            observed_before_state="not marked",
            observed_after_state="marked for manual remediation",
            rollback_token=f"unmark:{step.target.identity_key}",
        )

    async def verify(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> VerificationResult:
        succeeded = (
            execution_result.succeeded
            and execution_result.observed_after_state == "marked for manual remediation"
        )
        return VerificationResult(
            step_index=step.step_index,
            method=step.verification.method,
            expected_result="marked for manual remediation",
            observed_result=execution_result.observed_after_state or "unknown",
            succeeded=succeeded,
            confidence="high",
            checked_at=context.now,
            user_visible_impact="none",
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
                error="no rollback_token was recorded for this execution",
            )
        return RollbackStepResult(
            reverses_step_index=step.step_index,
            adapter_id=self.adapter_id,
            succeeded=True,
            completed_at=context.now,
            observed_state_after_rollback="not marked",
        )


class RecorderExclusionPatchAdapter:
    """Generates a proposed recorder exclusion YAML patch as inert text.

    Never writes a file and never touches Home Assistant configuration:
    the patch is the artifact, captured entirely inside the structured
    execution result (``observed_after_state``), for a human to copy and
    apply themselves.
    """

    adapter_id = "recorder_exclusion_patch_adapter"
    adapter_version = 1

    async def validate(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterValidationResult:
        if step.target.kind != "home_assistant.entity":
            return AdapterValidationResult(
                valid=False,
                errors=(f"unsupported target kind: {step.target.kind}",),
            )
        return AdapterValidationResult(valid=True)

    def _render_patch(self, step: RemediationActionStep) -> str:
        entity_id = step.target.source_id
        patch = f"recorder:\n  exclude:\n    entities:\n      - {entity_id}"
        return patch[:MAX_ARTIFACT_LENGTH].strip()

    async def preview(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterPreviewResult:
        return AdapterPreviewResult(
            rendered_before=None,
            rendered_after=self._render_patch(step),
            warnings=(
                "this patch is not applied automatically; copy it into "
                "configuration.yaml yourself and restart Home Assistant",
            ),
        )

    async def execute(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> StepExecutionResult:
        validation = await self.validate(step, context)
        started = context.now
        if not validation.valid:
            return StepExecutionResult(
                step_index=step.step_index,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                attempt=1,
                mutation_occurred=False,
                succeeded=False,
                idempotency_key=_idempotency_key(step, context),
                started_at=started,
                completed_at=started,
                error="; ".join(validation.errors) or "validation failed",
            )
        patch = self._render_patch(step)
        return StepExecutionResult(
            step_index=step.step_index,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            attempt=1,
            mutation_occurred=True,
            succeeded=True,
            idempotency_key=_idempotency_key(step, context),
            started_at=started,
            completed_at=started,
            observed_before_state="no patch artifact",
            observed_after_state=patch,
            rollback_token=f"discard_patch:{step.target.identity_key}",
        )

    async def verify(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> VerificationResult:
        expected = self._render_patch(step)
        observed = execution_result.observed_after_state or ""
        succeeded = execution_result.succeeded and observed == expected
        return VerificationResult(
            step_index=step.step_index,
            method=step.verification.method,
            expected_result=expected,
            observed_result=observed,
            succeeded=succeeded,
            confidence="high",
            checked_at=context.now,
            user_visible_impact="none",
        )

    async def rollback(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> RollbackStepResult:
        return RollbackStepResult(
            reverses_step_index=step.step_index,
            adapter_id=self.adapter_id,
            succeeded=True,
            completed_at=context.now,
            observed_state_after_rollback="patch artifact discarded",
        )


class FixtureStore(Protocol):
    """An isolated, non-production key/value store for test execution."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str) -> None: ...


class InMemoryFixtureStore:
    """A dependency-free in-memory ``FixtureStore`` for tests."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._values: dict[str, str] = dict(initial or {})

    async def get(self, key: str) -> str | None:
        return self._values.get(key)

    async def set(self, key: str, value: str) -> None:
        self._values[key] = value

    def snapshot(self) -> dict[str, str]:
        return dict(self._values)


class FixtureTestAdapter:
    """Mutates an isolated fixture store. **Test/dev use only.**

    Never selectable by the recommendation-driven planner
    (``domain/remediation_planner.py``'s ``plan_remediation``) and
    restricted by the action catalog to ``hamie.test_fixture`` targets;
    this adapter additionally refuses to run against any other target
    kind as a second, independent guard.
    """

    adapter_id = "fixture_test_adapter"
    adapter_version = 1

    def __init__(self, store: FixtureStore) -> None:
        self._store = store

    def _parameter(self, step: RemediationActionStep, key: str) -> str | None:
        return dict(step.parameters).get(key)

    async def validate(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterValidationResult:
        if step.target.kind != "hamie.test_fixture":
            return AdapterValidationResult(
                valid=False,
                errors=(
                    "fixture_test_adapter refuses any target kind other "
                    "than hamie.test_fixture",
                ),
            )
        if self._parameter(step, "fixture_key") is None:
            return AdapterValidationResult(
                valid=False, errors=("missing fixture_key parameter",)
            )
        return AdapterValidationResult(valid=True)

    async def preview(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterPreviewResult:
        key = self._parameter(step, "fixture_key") or ""
        current = await self._store.get(key)
        target_value = self._parameter(step, "fixture_value") or ""
        return AdapterPreviewResult(
            rendered_before=current,
            rendered_after=target_value,
        )

    async def execute(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> StepExecutionResult:
        validation = await self.validate(step, context)
        started = context.now
        if not validation.valid:
            return StepExecutionResult(
                step_index=step.step_index,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                attempt=1,
                mutation_occurred=False,
                succeeded=False,
                idempotency_key=_idempotency_key(step, context),
                started_at=started,
                completed_at=started,
                error="; ".join(validation.errors) or "validation failed",
            )
        key = self._parameter(step, "fixture_key")
        new_value = self._parameter(step, "fixture_value") or ""
        assert key is not None  # validated above
        before = await self._store.get(key)
        await self._store.set(key, new_value)
        return StepExecutionResult(
            step_index=step.step_index,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            attempt=1,
            mutation_occurred=True,
            succeeded=True,
            idempotency_key=_idempotency_key(step, context),
            started_at=started,
            completed_at=started,
            observed_before_state=before,
            observed_after_state=new_value,
            rollback_token=before or "",
        )

    async def verify(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> VerificationResult:
        key = self._parameter(step, "fixture_key") or ""
        current = await self._store.get(key)
        expected = self._parameter(step, "fixture_value") or ""
        succeeded = execution_result.succeeded and current == expected
        return VerificationResult(
            step_index=step.step_index,
            method=step.verification.method,
            expected_result=expected,
            observed_result=current or "",
            succeeded=succeeded,
            confidence="high",
            checked_at=context.now,
            user_visible_impact="none",
        )

    async def rollback(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> RollbackStepResult:
        key = self._parameter(step, "fixture_key")
        if key is None or execution_result.rollback_token is None:
            return RollbackStepResult(
                reverses_step_index=step.step_index,
                adapter_id=self.adapter_id,
                succeeded=False,
                completed_at=context.now,
                error="no rollback data was recorded for this execution",
            )
        await self._store.set(key, execution_result.rollback_token)
        restored = await self._store.get(key)
        return RollbackStepResult(
            reverses_step_index=step.step_index,
            adapter_id=self.adapter_id,
            succeeded=restored == execution_result.rollback_token,
            completed_at=context.now,
            observed_state_after_rollback=restored,
        )


ADAPTER_REGISTRY_KEYS = (
    "manual_action_adapter",
    "recorder_exclusion_patch_adapter",
    "fixture_test_adapter",
)
