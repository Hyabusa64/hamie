"""Injectable adapters for HAMIE's narrow Home Assistant mutation allowlist."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

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


@dataclass(frozen=True, slots=True)
class EntityRegistrySnapshot:
    entity_id: str
    disabled_by: str | None
    config_entry_id: str | None
    entity_category: str | None


class HomeAssistantMutationPort(Protocol):
    async def config_entry_state(self, entry_id: str) -> str | None: ...
    async def reload_config_entry(self, entry_id: str) -> bool: ...
    async def entity_record(self, entity_id: str) -> EntityRegistrySnapshot | None: ...
    async def set_entity_disabled_by(
        self, entity_id: str, disabled_by: str | None
    ) -> None: ...
    async def entity_state_exists(self, entity_id: str) -> bool: ...


class UnavailableHomeAssistantMutationPort:
    """Fail-closed port used by metadata-only callers and foundation tests."""

    async def config_entry_state(self, entry_id: str) -> str | None:
        return None

    async def reload_config_entry(self, entry_id: str) -> bool:
        return False

    async def entity_record(self, entity_id: str) -> EntityRegistrySnapshot | None:
        return None

    async def set_entity_disabled_by(
        self, entity_id: str, disabled_by: str | None
    ) -> None:
        raise RuntimeError("Home Assistant mutation port is unavailable")

    async def entity_state_exists(self, entity_id: str) -> bool:
        return False


class HassHomeAssistantMutationPort:
    """Official Home Assistant config-entry and entity-registry API boundary."""

    def __init__(self, hass: Any) -> None:
        self._hass = hass

    async def config_entry_state(self, entry_id: str) -> str | None:
        entry = self._hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return None
        state = getattr(entry, "state", None)
        return str(getattr(state, "value", state)) if state is not None else "unknown"

    async def reload_config_entry(self, entry_id: str) -> bool:
        return bool(await self._hass.config_entries.async_reload(entry_id))

    async def entity_record(self, entity_id: str) -> EntityRegistrySnapshot | None:
        from homeassistant.helpers import entity_registry as er

        record = er.async_get(self._hass).async_get(entity_id)
        if record is None:
            return None
        disabled = getattr(record, "disabled_by", None)
        disabled_value = (
            str(getattr(disabled, "value", disabled)) if disabled is not None else None
        )
        category = getattr(record, "entity_category", None)
        category_value = (
            str(getattr(category, "value", category)) if category is not None else None
        )
        return EntityRegistrySnapshot(
            entity_id=entity_id,
            disabled_by=disabled_value,
            config_entry_id=getattr(record, "config_entry_id", None),
            entity_category=category_value,
        )

    async def set_entity_disabled_by(
        self, entity_id: str, disabled_by: str | None
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(self._hass)
        value = None if disabled_by is None else er.RegistryEntryDisabler(disabled_by)
        registry.async_update_entity(entity_id, disabled_by=value)

    async def entity_state_exists(self, entity_id: str) -> bool:
        return self._hass.states.get(entity_id) is not None


def _parameter(step: RemediationActionStep, name: str) -> str | None:
    return dict(step.parameters).get(name)


def _execution_failure(
    adapter_id: str,
    step: RemediationActionStep,
    context: RemediationAdapterContext,
    error: str,
) -> StepExecutionResult:
    return StepExecutionResult(
        step_index=step.step_index,
        adapter_id=adapter_id,
        adapter_version=1,
        attempt=1,
        mutation_occurred=False,
        succeeded=False,
        idempotency_key=f"{context.execution_id}:{step.step_index}:{adapter_id}",
        started_at=context.now,
        completed_at=context.now,
        error=error,
    )


class ConfigEntryReloadAdapter:
    adapter_id = "config_entry_reload_adapter"
    adapter_version = 1

    def __init__(self, port: HomeAssistantMutationPort) -> None:
        self._port = port

    async def validate(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterValidationResult:
        state = await self._port.config_entry_state(step.target.source_id)
        errors: list[str] = []
        if step.target.kind != "home_assistant.config_entry":
            errors.append("target is not a config entry")
        if state is None:
            errors.append("config entry does not exist")
        if state in {"setup_in_progress", "migration_in_progress"}:
            errors.append("config entry is already changing state")
        if _parameter(step, "current_failure") != "true":
            errors.append("current failure evidence is required")
        if _parameter(step, "cooldown_passed") != "true":
            errors.append("reload cooldown has not elapsed")
        return AdapterValidationResult(valid=not errors, errors=tuple(errors))

    async def preview(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterPreviewResult:
        state = await self._port.config_entry_state(step.target.source_id)
        return AdapterPreviewResult(
            rendered_before=state or "missing",
            rendered_after="reload once, then verify loaded state and entity recovery",
            warnings=("Reload may briefly interrupt entities from this config entry.",),
        )

    async def execute(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> StepExecutionResult:
        validation = await self.validate(step, context)
        if not validation.valid:
            return _execution_failure(
                self.adapter_id, step, context, "; ".join(validation.errors)
            )
        before = await self._port.config_entry_state(step.target.source_id)
        try:
            succeeded = await self._port.reload_config_entry(step.target.source_id)
        except Exception:
            return _execution_failure(
                self.adapter_id, step, context, "config-entry reload failed"
            )
        if not succeeded:
            return _execution_failure(
                self.adapter_id, step, context, "config-entry reload was not accepted"
            )
        after = await self._port.config_entry_state(step.target.source_id)
        return StepExecutionResult(
            step_index=step.step_index,
            adapter_id=self.adapter_id,
            adapter_version=1,
            attempt=1,
            mutation_occurred=True,
            succeeded=True,
            idempotency_key=f"{context.execution_id}:{step.step_index}:{self.adapter_id}",
            started_at=context.now,
            completed_at=context.now,
            observed_before_state=before,
            observed_after_state=after,
        )

    async def verify(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> VerificationResult:
        state = await self._port.config_entry_state(step.target.source_id)
        succeeded = execution_result.succeeded and state == "loaded"
        return VerificationResult(
            step_index=step.step_index,
            method=step.verification.method,
            expected_result="config entry loaded without setup failure",
            observed_result=state or "missing",
            succeeded=succeeded,
            confidence="high",
            checked_at=context.now,
            errors=() if succeeded else ("config entry did not reach loaded state",),
            user_visible_impact="config-entry entities may briefly reload",
            rollback_recommended=False,
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
            succeeded=False,
            completed_at=context.now,
            error="config-entry reload is not reversible",
        )


class EntityDisabledStateAdapter:
    adapter_version = 1

    def __init__(
        self,
        port: HomeAssistantMutationPort,
        *,
        adapter_id: str,
        desired_disabled_by: str | None,
    ) -> None:
        self._port = port
        self.adapter_id = adapter_id
        self._desired = desired_disabled_by

    async def validate(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterValidationResult:
        record = await self._port.entity_record(step.target.source_id)
        errors: list[str] = []
        if step.target.kind != "home_assistant.entity":
            errors.append("target is not an entity")
        if record is None:
            errors.append("entity registry record does not exist")
            return AdapterValidationResult(valid=False, errors=tuple(errors))
        if not record.config_entry_id:
            errors.append("backing config entry is missing")
        elif await self._port.config_entry_state(record.config_entry_id) is None:
            errors.append("backing config entry does not exist")
        if self._desired is None and record.disabled_by != "user":
            errors.append("entity is not user-disabled")
        if self._desired == "user":
            if record.disabled_by is not None:
                errors.append("entity is already disabled")
            required = {
                "persistent_unavailable": "true",
                "eligible_entity_category": "true",
                "dependency_coverage": "complete",
                "direct_reference_count": "0",
                "indirect_reference_count": "0",
                "unresolved_reference_count": "0",
            }
            for key, expected in required.items():
                if _parameter(step, key) != expected:
                    errors.append(f"{key} must equal {expected}")
        if not _parameter(step, "target_fingerprint"):
            errors.append("current target fingerprint is required")
        return AdapterValidationResult(valid=not errors, errors=tuple(errors))

    async def preview(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterPreviewResult:
        record = await self._port.entity_record(step.target.source_id)
        before = record.disabled_by if record else "missing"
        after = self._desired or "enabled"
        return AdapterPreviewResult(
            rendered_before=before or "enabled", rendered_after=after
        )

    async def execute(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> StepExecutionResult:
        validation = await self.validate(step, context)
        if not validation.valid:
            return _execution_failure(
                self.adapter_id, step, context, "; ".join(validation.errors)
            )
        record = await self._port.entity_record(step.target.source_id)
        assert record is not None
        before = record.disabled_by
        try:
            await self._port.set_entity_disabled_by(
                step.target.source_id, self._desired
            )
        except Exception:
            return _execution_failure(
                self.adapter_id, step, context, "entity-registry update failed"
            )
        return StepExecutionResult(
            step_index=step.step_index,
            adapter_id=self.adapter_id,
            adapter_version=1,
            attempt=1,
            mutation_occurred=True,
            succeeded=True,
            idempotency_key=f"{context.execution_id}:{step.step_index}:{self.adapter_id}",
            started_at=context.now,
            completed_at=context.now,
            observed_before_state=before or "enabled",
            observed_after_state=self._desired or "enabled",
            rollback_token=before or "enabled",
        )

    async def verify(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> VerificationResult:
        record = await self._port.entity_record(step.target.source_id)
        registry_matches = record is not None and record.disabled_by == self._desired
        state_exists = await self._port.entity_state_exists(step.target.source_id)
        succeeded = (
            execution_result.succeeded
            and registry_matches
            and (self._desired == "user" or state_exists)
        )
        observed = (
            "missing"
            if record is None
            else (
                f"disabled_by={record.disabled_by or 'none'}; "
                f"state_exists={state_exists}"
            )
        )
        return VerificationResult(
            step_index=step.step_index,
            method=step.verification.method,
            expected_result=(
                "entity registry user-disabled"
                if self._desired == "user"
                else "entity registry enabled and entity recreated"
            ),
            observed_result=observed,
            succeeded=succeeded,
            confidence="high",
            checked_at=context.now,
            errors=() if succeeded else ("entity postconditions were not satisfied",),
            user_visible_impact="only the exact entity registry record changed",
            rollback_recommended=not succeeded and execution_result.mutation_occurred,
        )

    async def rollback(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> RollbackStepResult:
        previous = execution_result.rollback_token
        if previous is None:
            return RollbackStepResult(
                reverses_step_index=step.step_index,
                adapter_id=self.adapter_id,
                succeeded=False,
                completed_at=context.now,
                error="exact previous disabled state was not recorded",
            )
        restored = None if previous == "enabled" else previous
        current_before = await self._port.entity_record(step.target.source_id)
        if current_before is None or current_before.disabled_by != self._desired:
            return RollbackStepResult(
                reverses_step_index=step.step_index,
                adapter_id=self.adapter_id,
                succeeded=False,
                completed_at=context.now,
                error="entity state changed since execution; rollback blocked",
            )
        try:
            await self._port.set_entity_disabled_by(step.target.source_id, restored)
            current = await self._port.entity_record(step.target.source_id)
        except Exception:
            return RollbackStepResult(
                reverses_step_index=step.step_index,
                adapter_id=self.adapter_id,
                succeeded=False,
                completed_at=context.now,
                error="entity-registry rollback failed",
            )
        succeeded = current is not None and current.disabled_by == restored
        return RollbackStepResult(
            reverses_step_index=step.step_index,
            adapter_id=self.adapter_id,
            succeeded=succeeded,
            completed_at=context.now,
            observed_state_after_rollback=restored or "enabled",
            error=None if succeeded else "previous disabled state was not restored",
        )


def home_assistant_adapters(
    hass: Any | None = None,
) -> dict[str, ConfigEntryReloadAdapter | EntityDisabledStateAdapter | Any]:
    from .batch_entity_adapter import DisableEntityBatchAdapter

    port: HomeAssistantMutationPort = (
        HassHomeAssistantMutationPort(hass)
        if hass is not None
        else UnavailableHomeAssistantMutationPort()
    )
    return {
        "config_entry_reload_adapter": ConfigEntryReloadAdapter(port),
        "enable_entity_adapter": EntityDisabledStateAdapter(
            port, adapter_id="enable_entity_adapter", desired_disabled_by=None
        ),
        "disable_unused_entity_adapter": EntityDisabledStateAdapter(
            port,
            adapter_id="disable_unused_entity_adapter",
            desired_disabled_by="user",
        ),
        "disable_entity_batch_adapter": DisableEntityBatchAdapter(port),
    }
