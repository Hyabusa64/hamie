"""File-mutation adapter for HAMIE-owned editable resources (Phase 3B).

The only adapter in HAMIE that writes to the filesystem at all. It
mutates exactly one class of target: a reviewed, allowlisted logical
resource (``domain/remediation_resources.py``), resolved to a real path
only through ``file_policy.py``'s traversal/symlink-safe resolution --
never a path supplied directly by a plan, a proposal, or the model.

Safety properties, all enforced here or in the modules this adapter
calls:

- **Evidence- and policy-gated upstream**: a plan can only reach this
  adapter via ``domain/remediation_planner.py``'s
  ``plan_llm_proposed_remediation``, which itself only accepts a
  proposal ``domain/remediation_llm_proposal.py`` already validated
  against the editable-resource allowlist and HAMIE's own supplied
  evidence ids.
- **Fail-closed staleness precondition** (mission Phase 7): ``execute``
  recomputes the current file's SHA-256 and refuses to write unless it
  matches the plan-time ``expected_before_hash`` parameter exactly.
- **Atomic write** (mission Phase 10): every write goes through
  ``file_policy.atomic_write_bytes`` -- temp file, fsync, atomic
  rename, never an in-place partial write.
- **Local rollback, not a full Home Assistant backup**: the exact
  original file bytes are captured before every write and carried as
  the step's own ``rollback_token`` (the same mechanism
  ``FixtureTestAdapter`` already uses in
  ``application/remediation/adapters.py``), bounded by
  ``domain/remediation_execution.py``'s existing text-length limits.
  This is deliberately independent of ``BackupProvider``
  (``preconditions.py``), which remains honestly absent -- see
  ``docs/REMEDIATION_ENGINE.md`` §8/§18.
- **HAMIE-owned format only** (mission Phase 11): content is read and
  written exclusively through
  ``domain/maintenance_notes_format.py``'s closed, hand-rolled grammar.
  Content that does not match it exactly is never guessed at or
  partially repaired -- the step simply fails.

Extending this to a second editable resource requires, in order: a
reviewed ``EditableResourceDefinition``
(``domain/remediation_resources.py``), a format module able to prove
round-trip safety for that exact resource (mission Phase 11), and a
matching branch here (or a new adapter) -- never a generic "write
whatever bytes were given" path.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ...domain.maintenance_notes_format import (
    MaintenanceNotesFormatError,
    empty_notes_content,
    parse_notes,
    render_notes,
)
from ...domain.remediation import RemediationActionStep
from ...domain.remediation_execution import (
    RollbackStepResult,
    StepExecutionResult,
    VerificationResult,
)
from ...domain.remediation_resources import EditableResourceDefinition
from .adapters import (
    AdapterPreviewResult,
    AdapterValidationResult,
    RemediationAdapterContext,
)
from .file_policy import (
    FilePolicyError,
    atomic_write_bytes,
    read_current_bytes,
    resolve_editable_resource_path,
)

REQUIRED_PARAMETERS = (
    "resource_id",
    "operation_key",
    "operation_value",
    "expected_before_hash",
)


def content_hash(content: bytes | None) -> str:
    """Return the deterministic fingerprint used for the staleness precondition."""
    return hashlib.sha256(content or b"").hexdigest()


@dataclass(frozen=True, slots=True)
class _Loaded:
    resource: EditableResourceDefinition
    path: Path
    current_bytes: bytes | None


class FileMutationPort(Protocol):
    """The narrow, injectable filesystem boundary this adapter uses."""

    async def resolve_and_read(self, resource_id: str) -> _Loaded: ...

    async def atomic_write(self, path: Path, content: bytes) -> None: ...


class UnavailableFileMutationPort:
    """Fail-closed port used when no Home Assistant config directory is known."""

    async def resolve_and_read(self, resource_id: str) -> _Loaded:
        raise FilePolicyError(
            "file_mutation_unavailable", "no Home Assistant config directory is known"
        )

    async def atomic_write(self, path: Path, content: bytes) -> None:
        raise FilePolicyError(
            "file_mutation_unavailable", "no Home Assistant config directory is known"
        )


class HassFileMutationPort:
    """Real filesystem port bound to one Home Assistant config directory.

    All blocking filesystem calls run through
    ``hass.async_add_executor_job``, matching Home Assistant's own rule
    that blocking I/O must never run directly on the event loop.
    """

    def __init__(self, hass: Any) -> None:
        self._hass = hass
        self._config_root = Path(hass.config.path())

    async def resolve_and_read(self, resource_id: str) -> _Loaded:
        def _do() -> _Loaded:
            resource, path = resolve_editable_resource_path(
                self._config_root, resource_id
            )
            current = read_current_bytes(path)
            return _Loaded(resource=resource, path=path, current_bytes=current)

        return await self._hass.async_add_executor_job(_do)

    async def atomic_write(self, path: Path, content: bytes) -> None:
        await self._hass.async_add_executor_job(atomic_write_bytes, path, content)


class LocalFileMutationPort:
    """Direct-filesystem port for tests -- no Home Assistant instance required.

    Mirrors ``InMemoryFixtureStore`` (``application/remediation/adapters.py``):
    a genuine, fully working implementation of the same port used in
    production, bound to an arbitrary directory (a test's temp dir).
    """

    def __init__(self, config_root: Path) -> None:
        self._config_root = config_root

    async def resolve_and_read(self, resource_id: str) -> _Loaded:
        resource, path = resolve_editable_resource_path(self._config_root, resource_id)
        current = read_current_bytes(path)
        return _Loaded(resource=resource, path=path, current_bytes=current)

    async def atomic_write(self, path: Path, content: bytes) -> None:
        atomic_write_bytes(path, content)


def _idempotency_key(
    step: RemediationActionStep, context: RemediationAdapterContext
) -> str:
    return f"{context.execution_id}:{step.step_index}:{step.adapter_id}"


def _failure(
    step: RemediationActionStep,
    context: RemediationAdapterContext,
    *,
    started_at: Any,
    error: str,
) -> StepExecutionResult:
    return StepExecutionResult(
        step_index=step.step_index,
        adapter_id=FileMutationAdapter.adapter_id,
        adapter_version=FileMutationAdapter.adapter_version,
        attempt=1,
        mutation_occurred=False,
        succeeded=False,
        idempotency_key=_idempotency_key(step, context),
        started_at=started_at,
        completed_at=context.now,
        error=error,
    )


class FileMutationAdapter:
    """Applies exactly one validated ``yaml_set``-shaped operation to one
    reviewed editable resource, atomically, with a fail-closed staleness
    precondition and full local rollback."""

    adapter_id = "file_mutation_adapter"
    adapter_version = 1

    def __init__(self, port: FileMutationPort) -> None:
        self._port = port

    def _parameters(self, step: RemediationActionStep) -> dict[str, str]:
        return dict(step.parameters)

    async def _load(
        self, step: RemediationActionStep
    ) -> tuple[_Loaded | None, str | None]:
        params = self._parameters(step)
        resource_id = params.get("resource_id")
        if not resource_id:
            return None, "missing resource_id parameter"
        try:
            loaded = await self._port.resolve_and_read(resource_id)
        except FilePolicyError as err:
            return None, f"{err.code}: {err.message}"
        return loaded, None

    async def validate(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterValidationResult:
        if step.target.kind != "hamie.editable_resource":
            return AdapterValidationResult(
                valid=False, errors=(f"unsupported target kind: {step.target.kind}",)
            )
        params = self._parameters(step)
        missing = tuple(name for name in REQUIRED_PARAMETERS if name not in params)
        if missing:
            return AdapterValidationResult(
                valid=False,
                errors=tuple(f"missing {name} parameter" for name in missing),
            )
        loaded, error = await self._load(step)
        if error is not None or loaded is None:
            return AdapterValidationResult(valid=False, errors=(error or "unknown",))
        if not loaded.resource.allows_key(params["operation_key"]):
            return AdapterValidationResult(
                valid=False,
                errors=(f"key {params['operation_key']!r} is not permitted",),
            )
        return AdapterValidationResult(valid=True)

    def _current_notes(self, loaded: _Loaded) -> dict[str, str] | None:
        try:
            return (
                parse_notes(loaded.current_bytes.decode("utf-8"))
                if loaded.current_bytes is not None
                else {}
            )
        except (MaintenanceNotesFormatError, UnicodeDecodeError):
            return None

    async def preview(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> AdapterPreviewResult:
        loaded, error = await self._load(step)
        if error is not None or loaded is None:
            return AdapterPreviewResult(
                rendered_before=None, rendered_after="", warnings=(error or "unknown",)
            )
        current_notes = self._current_notes(loaded)
        if current_notes is None:
            return AdapterPreviewResult(
                rendered_before=None,
                rendered_after="",
                warnings=(
                    "the current file content does not match HAMIE's recognized "
                    "maintenance-notes format",
                ),
            )
        params = self._parameters(step)
        proposed_notes = dict(current_notes)
        proposed_notes[params["operation_key"]] = params["operation_value"]
        rendered_before = (
            render_notes(current_notes)
            if loaded.current_bytes is not None
            else empty_notes_content()
        )
        return AdapterPreviewResult(
            rendered_before=rendered_before, rendered_after=render_notes(proposed_notes)
        )

    async def execute(
        self, step: RemediationActionStep, context: RemediationAdapterContext
    ) -> StepExecutionResult:
        started = context.now
        validation = await self.validate(step, context)
        if not validation.valid:
            return _failure(
                step,
                context,
                started_at=started,
                error="; ".join(validation.errors) or "validation failed",
            )
        params = self._parameters(step)
        loaded, error = await self._load(step)
        if error is not None or loaded is None:
            return _failure(step, context, started_at=started, error=error or "unknown")
        current_hash = content_hash(loaded.current_bytes)
        expected_hash = params["expected_before_hash"]
        if current_hash != expected_hash:
            return _failure(
                step,
                context,
                started_at=started,
                error=(
                    "stale_target_fingerprint: the maintenance notes file changed "
                    "since this plan was created"
                ),
            )
        current_notes = self._current_notes(loaded)
        if current_notes is None:
            return _failure(
                step,
                context,
                started_at=started,
                error=(
                    "current file content does not match HAMIE's recognized "
                    "maintenance-notes format"
                ),
            )
        proposed_notes = dict(current_notes)
        proposed_notes[params["operation_key"]] = params["operation_value"]
        try:
            new_content = render_notes(proposed_notes).encode("utf-8")
        except ValueError as err:
            return _failure(step, context, started_at=started, error=str(err))
        if len(new_content) > loaded.resource.max_bytes:
            return _failure(
                step,
                context,
                started_at=started,
                error="proposed content exceeds the resource's maximum size",
            )
        original_text = (
            loaded.current_bytes.decode("utf-8")
            if loaded.current_bytes is not None
            else empty_notes_content()
        )
        new_text = new_content.decode("utf-8")
        # Idempotency (mission Phase 19): the exact proposed state is
        # already present -- never rewrite unnecessarily, and never
        # report a no-op as a mutation. rollback_token still carries the
        # (unchanged) original content so a later rollback of an
        # execution chain that includes this no-op step behaves exactly
        # like reversing a real write.
        if new_text == original_text:
            return StepExecutionResult(
                step_index=step.step_index,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                attempt=1,
                mutation_occurred=False,
                succeeded=True,
                idempotency_key=_idempotency_key(step, context),
                started_at=started,
                completed_at=context.now,
                observed_before_state=original_text,
                observed_after_state=new_text,
                rollback_token=original_text,
            )
        await self._port.atomic_write(loaded.path, new_content)
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
            observed_before_state=original_text,
            observed_after_state=new_text,
            rollback_token=original_text,
        )

    async def verify(
        self,
        step: RemediationActionStep,
        execution_result: StepExecutionResult,
        context: RemediationAdapterContext,
    ) -> VerificationResult:
        expected = execution_result.observed_after_state or ""
        loaded, error = await self._load(step)
        observed = (
            loaded.current_bytes.decode("utf-8")
            if loaded is not None and loaded.current_bytes is not None
            else ""
        )
        succeeded = (
            execution_result.succeeded and error is None and observed == expected
        )
        return VerificationResult(
            step_index=step.step_index,
            method=step.verification.method,
            # VerificationResult requires a normalized (no surrounding
            # whitespace) string -- the file content itself legitimately
            # ends with a trailing newline, so only the *display* value
            # here is stripped, never the actual file bytes.
            expected_result=expected.strip() or "(empty file)",
            observed_result=observed.strip() or "(empty file)",
            succeeded=succeeded,
            confidence="high",
            checked_at=context.now,
            user_visible_impact="none",
            errors=()
            if succeeded
            else (error or "file content did not match the expected result",),
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
        loaded, error = await self._load(step)
        if error is not None or loaded is None:
            return RollbackStepResult(
                reverses_step_index=step.step_index,
                adapter_id=self.adapter_id,
                succeeded=False,
                completed_at=context.now,
                error=error or "unknown",
            )
        original_content = execution_result.rollback_token.encode("utf-8")
        await self._port.atomic_write(loaded.path, original_content)
        restored, restore_error = await self._load(step)
        restored_text = (
            restored.current_bytes.decode("utf-8")
            if restored is not None and restored.current_bytes is not None
            else ""
        )
        succeeded = (
            restore_error is None and restored_text == execution_result.rollback_token
        )
        return RollbackStepResult(
            reverses_step_index=step.step_index,
            adapter_id=self.adapter_id,
            succeeded=succeeded,
            completed_at=context.now,
            observed_state_after_rollback=restored_text if succeeded else None,
            error=(
                None
                if succeeded
                else (
                    restore_error
                    or "rollback did not restore the exact original content"
                )
            ),
        )


async def resource_content_hash(port: FileMutationPort, resource_id: str) -> str:
    """Return the current content fingerprint for one editable resource.

    Used by the application layer (``service.py``) at plan-creation time
    to fill in ``plan_llm_proposed_remediation``'s ``expected_before_hash``
    -- the domain planner itself never performs I/O, so this fetch must
    happen here, outside ``domain/``.
    """
    loaded = await port.resolve_and_read(resource_id)
    return content_hash(loaded.current_bytes)


def file_mutation_adapter(hass: Any | None = None) -> FileMutationAdapter:
    """Return the production ``FileMutationAdapter``, bound to ``hass`` if given."""
    port: FileMutationPort = (
        HassFileMutationPort(hass)
        if hass is not None
        else UnavailableFileMutationPort()
    )
    return FileMutationAdapter(port)
