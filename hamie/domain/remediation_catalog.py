"""Deterministic remediation action catalog (HAMIE Phase 2B).

The capability registry is the single source of truth the planner
(``remediation_planner.py``) consults to decide whether, and how, one
``CanonicalRecommendation`` can become an executable
``RemediationPlan`` step. It is intentionally small and conservative:

- Every ``execution_supported=True`` production entry is non-destructive,
  requires no real backup, and is fully testable without live Home Assistant.
  Home Assistant adapters live in ``application/remediation/ha_adapters.py``;
  HAMIE-local adapters live in ``application/remediation/adapters.py``.
- Every entry HAMIE does *not* yet support -- including the obviously
  destructive actions a maintenance tool would eventually want
  (deleting entities/devices, removing integrations, editing recorder
  config or secrets, restarting, mutating an external n8n
  workflow) -- is still a first-class catalog entry with an explicit
  ``unsupported_reason``, never a silent omission.

Adding a new supported action means adding a new, reviewed
``ActionCatalogEntry`` here *and* a matching adapter -- the planner
refuses anything not listed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .common import require_non_empty
from .findings import RiskLevel
from .remediation import BackupRequirement, IdempotencyClassification

CATALOG_VERSION = 1

# An empty ``supported_target_kinds`` tuple means "any SubjectIdentity.kind
# is accepted" -- used only by actions that never inspect or touch the
# target's real state (e.g. marking something for manual follow-up).
ANY_TARGET_KIND: tuple[str, ...] = ()


class DependencyRequirement(StrEnum):
    """How complete dependency analysis must be before this action plans."""

    NOT_REQUIRED = "not_required"
    COMPLETE_REQUIRED = "complete_required"


@dataclass(frozen=True, slots=True)
class ActionCatalogEntry:
    """One deterministic, versioned action definition."""

    action_type: str
    version: int
    supported_target_kinds: tuple[str, ...]
    risk_class: RiskLevel
    destructive: bool
    reversible: bool
    dependency_requirement: DependencyRequirement
    required_backup: BackupRequirement
    preview_capable: bool
    execution_supported: bool
    rollback_capable: bool
    verification_method: str
    required_privileges: tuple[str, ...]
    idempotency: IdempotencyClassification
    timeout_seconds: int
    adapter_id: str | None = None
    supported_home_assistant_versions: tuple[str, ...] = ()
    unsupported_reason: str | None = None
    required_evidence: tuple[str, ...] = ()
    user_facing_templates: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.action_type, "action_type")
        if self.version < 1:
            raise ValueError("action version must be positive")
        if self.timeout_seconds < 1 or self.timeout_seconds > 3_600:
            raise ValueError("timeout_seconds must be between 1 and 3600")
        if self.execution_supported:
            if not self.adapter_id:
                raise ValueError("an execution_supported action requires adapter_id")
            if self.unsupported_reason:
                raise ValueError(
                    "an execution_supported action cannot carry unsupported_reason"
                )
        else:
            if not self.unsupported_reason:
                raise ValueError(
                    "an unsupported action requires a non-empty unsupported_reason"
                )
        if self.rollback_capable and not self.reversible:
            raise ValueError("an irreversible action cannot be rollback_capable")
        if self.destructive and self.dependency_requirement != (
            DependencyRequirement.COMPLETE_REQUIRED
        ):
            raise ValueError(
                "a destructive action must require complete dependency analysis"
            )
        if "@" not in self.verification_method:
            raise ValueError("verification_method must include a schema version")

    @property
    def capability_id(self) -> str:
        return self.action_type

    @property
    def target_types(self) -> tuple[str, ...]:
        return self.supported_target_kinds

    @property
    def risk(self) -> RiskLevel:
        return self.risk_class

    @property
    def supported(self) -> bool:
        return self.execution_supported

    @property
    def backup_requirement(self) -> BackupRequirement:
        return self.required_backup

    @property
    def dry_run_support(self) -> bool:
        return self.preview_capable

    @property
    def rollback_support(self) -> bool:
        return self.rollback_capable

    @property
    def executor(self) -> str | None:
        return self.adapter_id

    @property
    def verifier(self) -> str:
        return self.verification_method

    @property
    def rollback_handler(self) -> str | None:
        return self.adapter_id if self.rollback_capable else None

    def supports_target_kind(self, kind: str) -> bool:
        if not self.supported_target_kinds:
            return True
        return kind in self.supported_target_kinds


_SUPPORTED_ENTRIES: tuple[ActionCatalogEntry, ...] = (
    ActionCatalogEntry(
        action_type="hamie.mark_for_manual_remediation",
        version=1,
        supported_target_kinds=ANY_TARGET_KIND,
        risk_class=RiskLevel.LOW,
        destructive=False,
        reversible=True,
        dependency_requirement=DependencyRequirement.NOT_REQUIRED,
        required_backup=BackupRequirement.NOT_REQUIRED,
        preview_capable=True,
        execution_supported=True,
        rollback_capable=True,
        verification_method="manual_flag.check@1",
        required_privileges=(),
        idempotency=IdempotencyClassification.PURE_IDEMPOTENT,
        timeout_seconds=10,
        adapter_id="manual_action_adapter",
    ),
    ActionCatalogEntry(
        action_type="hamie.generate_recorder_exclusion_patch",
        version=1,
        supported_target_kinds=("home_assistant.entity",),
        risk_class=RiskLevel.LOW,
        destructive=False,
        reversible=True,
        dependency_requirement=DependencyRequirement.NOT_REQUIRED,
        required_backup=BackupRequirement.NOT_REQUIRED,
        preview_capable=True,
        execution_supported=True,
        rollback_capable=True,
        verification_method="patch_artifact.check@1",
        required_privileges=(),
        idempotency=IdempotencyClassification.PURE_IDEMPOTENT,
        timeout_seconds=10,
        adapter_id="recorder_exclusion_patch_adapter",
    ),
    ActionCatalogEntry(
        action_type="hamie.annotate_maintenance_notes",
        version=1,
        # Never a real Home Assistant object -- the target is HAMIE's own
        # editable resource identity (domain/remediation_resources.py),
        # resolved to a concrete, allowlisted, HAMIE-owned file only by
        # application/remediation/file_policy.py at execute time.
        supported_target_kinds=("hamie.editable_resource",),
        risk_class=RiskLevel.LOW,
        destructive=False,
        reversible=True,
        dependency_requirement=DependencyRequirement.NOT_REQUIRED,
        required_backup=BackupRequirement.NOT_REQUIRED,
        preview_capable=True,
        execution_supported=True,
        rollback_capable=True,
        verification_method="editable_resource.content_hash_matches@1",
        required_privileges=(),
        idempotency=IdempotencyClassification.IDEMPOTENT_WITH_SIDE_EFFECT,
        timeout_seconds=15,
        adapter_id="file_mutation_adapter",
        required_evidence=(
            "at least one HAMIE-supplied evidence id",
            "resource on the reviewed editable-resource allowlist",
            "current target content fingerprint",
        ),
        user_facing_templates=(
            ("action", "Update HAMIE maintenance notes ({target_id})"),
            (
                "verification",
                "Confirm the maintenance notes file now contains exactly "
                "the proposed value",
            ),
        ),
    ),
    ActionCatalogEntry(
        action_type="hamie.test_fixture_mutation",
        version=1,
        # Deliberately restricted to a target kind that can never be a
        # real Home Assistant subject -- this action_type must never be
        # selectable against anything but HAMIE's own test fixtures.
        supported_target_kinds=("hamie.test_fixture",),
        risk_class=RiskLevel.LOW,
        destructive=False,
        reversible=True,
        dependency_requirement=DependencyRequirement.NOT_REQUIRED,
        required_backup=BackupRequirement.NOT_REQUIRED,
        preview_capable=True,
        execution_supported=True,
        rollback_capable=True,
        verification_method="fixture_store.check@1",
        required_privileges=(),
        idempotency=IdempotencyClassification.IDEMPOTENT_WITH_SIDE_EFFECT,
        timeout_seconds=10,
        adapter_id="fixture_test_adapter",
    ),
    ActionCatalogEntry(
        action_type="reload_config_entry",
        version=1,
        supported_target_kinds=("home_assistant.config_entry",),
        risk_class=RiskLevel.MEDIUM,
        destructive=False,
        reversible=False,
        dependency_requirement=DependencyRequirement.NOT_REQUIRED,
        required_backup=BackupRequirement.NOT_REQUIRED,
        preview_capable=True,
        execution_supported=True,
        rollback_capable=False,
        verification_method="config_entry.loaded_without_setup_failure@1",
        required_privileges=("config_entries.reload",),
        idempotency=IdempotencyClassification.NOT_IDEMPOTENT,
        timeout_seconds=30,
        adapter_id="config_entry_reload_adapter",
        required_evidence=(
            "exact config entry identity",
            "current failure evidence",
            "no setup, reload, or migration in progress",
            "cooldown elapsed",
        ),
        user_facing_templates=(
            ("action", "Reload config entry {target_id}"),
            (
                "verification",
                "Confirm the config entry loaded and expected entities recovered",
            ),
        ),
    ),
    ActionCatalogEntry(
        action_type="enable_entity",
        version=1,
        supported_target_kinds=("home_assistant.entity",),
        risk_class=RiskLevel.LOW,
        destructive=False,
        reversible=True,
        dependency_requirement=DependencyRequirement.NOT_REQUIRED,
        required_backup=BackupRequirement.NOT_REQUIRED,
        preview_capable=True,
        execution_supported=True,
        rollback_capable=True,
        verification_method="entity_registry.enabled_and_entity_scheduled@1",
        required_privileges=("entity_registry.write",),
        idempotency=IdempotencyClassification.IDEMPOTENT_WITH_SIDE_EFFECT,
        timeout_seconds=30,
        adapter_id="enable_entity_adapter",
        required_evidence=(
            "exact entity registry identity",
            "user-disabled state",
            "current target fingerprint",
        ),
        user_facing_templates=(
            ("action", "Enable entity {target_id}"),
            (
                "verification",
                "Confirm registry enabled and entity recreation is scheduled",
            ),
        ),
    ),
    ActionCatalogEntry(
        action_type="disable_entity_batch",
        version=1,
        # A synthetic batch target, never a single real Home Assistant
        # entity -- domain/entity_batch.py's encoded parameters name the
        # actual member entity ids; see
        # application/remediation/batch_entity_adapter.py.
        supported_target_kinds=("hamie.entity_batch",),
        risk_class=RiskLevel.LOW,
        destructive=False,
        reversible=True,
        dependency_requirement=DependencyRequirement.NOT_REQUIRED,
        required_backup=BackupRequirement.NOT_REQUIRED,
        preview_capable=True,
        execution_supported=True,
        rollback_capable=True,
        verification_method="entity_batch.all_disabled_or_reported@1",
        required_privileges=("entity_registry.write",),
        idempotency=IdempotencyClassification.IDEMPOTENT_WITH_SIDE_EFFECT,
        timeout_seconds=120,
        adapter_id="disable_entity_batch_adapter",
        required_evidence=(
            "each member entity classified safe_auto_fix or "
            "safe_with_approval by the cleanup classifier",
            "each member entity's dependency coverage requirement satisfied",
            "each member entity's current disabled_by fingerprint",
        ),
        user_facing_templates=(
            ("action", "Disable {target_id} unused entities"),
            (
                "verification",
                "Confirm every member entity is now disabled or its "
                "specific failure is reported",
            ),
        ),
    ),
    ActionCatalogEntry(
        action_type="disable_unused_entity",
        version=1,
        supported_target_kinds=("home_assistant.entity",),
        risk_class=RiskLevel.MEDIUM,
        destructive=False,
        reversible=True,
        dependency_requirement=DependencyRequirement.COMPLETE_REQUIRED,
        required_backup=BackupRequirement.NOT_REQUIRED,
        preview_capable=True,
        execution_supported=True,
        rollback_capable=True,
        verification_method="entity_registry.user_disabled_without_collateral_change@1",
        required_privileges=("entity_registry.write",),
        idempotency=IdempotencyClassification.IDEMPOTENT_WITH_SIDE_EFFECT,
        timeout_seconds=30,
        adapter_id="disable_unused_entity_adapter",
        required_evidence=(
            "persistent unavailability",
            "optional, configuration, diagnostic, or feature entity",
            "complete dependency coverage",
            "no direct, indirect, or unresolved references",
            "current target fingerprint",
        ),
        user_facing_templates=(
            ("action", "Disable unused entity {target_id}"),
            ("verification", "Confirm only the exact target became user-disabled"),
        ),
    ),
)

_UNSUPPORTED_ENTRIES: tuple[ActionCatalogEntry, ...] = (
    ActionCatalogEntry(
        action_type="home_assistant.delete_entity",
        version=1,
        supported_target_kinds=("home_assistant.entity",),
        risk_class=RiskLevel.HIGH,
        destructive=True,
        reversible=False,
        dependency_requirement=DependencyRequirement.COMPLETE_REQUIRED,
        required_backup=BackupRequirement.REQUIRED,
        preview_capable=False,
        execution_supported=False,
        rollback_capable=False,
        verification_method="unsupported@1",
        required_privileges=("entity_registry.write",),
        idempotency=IdempotencyClassification.NOT_IDEMPOTENT,
        timeout_seconds=30,
        unsupported_reason=(
            "No real backup provider, rollback path, or live-tested adapter "
            "exists; entity deletion is irreversible through HAMIE."
        ),
    ),
    ActionCatalogEntry(
        action_type="home_assistant.delete_device",
        version=1,
        supported_target_kinds=("home_assistant.device",),
        risk_class=RiskLevel.HIGH,
        destructive=True,
        reversible=False,
        dependency_requirement=DependencyRequirement.COMPLETE_REQUIRED,
        required_backup=BackupRequirement.REQUIRED,
        preview_capable=False,
        execution_supported=False,
        rollback_capable=False,
        verification_method="unsupported@1",
        required_privileges=("device_registry.write",),
        idempotency=IdempotencyClassification.NOT_IDEMPOTENT,
        timeout_seconds=30,
        unsupported_reason=(
            "No real backup provider, rollback path, or live-tested adapter "
            "exists; device deletion is irreversible through HAMIE."
        ),
    ),
    ActionCatalogEntry(
        action_type="home_assistant.remove_integration",
        version=1,
        supported_target_kinds=("home_assistant.config_entry",),
        risk_class=RiskLevel.HIGH,
        destructive=True,
        reversible=False,
        dependency_requirement=DependencyRequirement.COMPLETE_REQUIRED,
        required_backup=BackupRequirement.REQUIRED,
        preview_capable=False,
        execution_supported=False,
        rollback_capable=False,
        verification_method="unsupported@1",
        required_privileges=("config_entries.write",),
        idempotency=IdempotencyClassification.NOT_IDEMPOTENT,
        timeout_seconds=30,
        unsupported_reason=(
            "Removing an integration can cascade into unrelated entities, "
            "automations, and devices; no safe scoped adapter exists."
        ),
    ),
    ActionCatalogEntry(
        action_type="home_assistant.delete_automation",
        version=1,
        supported_target_kinds=("home_assistant.automation",),
        risk_class=RiskLevel.HIGH,
        destructive=True,
        reversible=False,
        dependency_requirement=DependencyRequirement.COMPLETE_REQUIRED,
        required_backup=BackupRequirement.REQUIRED,
        preview_capable=False,
        execution_supported=False,
        rollback_capable=False,
        verification_method="unsupported@1",
        required_privileges=("automation.write",),
        idempotency=IdempotencyClassification.NOT_IDEMPOTENT,
        timeout_seconds=30,
        unsupported_reason=(
            "No real backup provider or rollback path exists; automation "
            "deletion is irreversible through HAMIE."
        ),
    ),
    ActionCatalogEntry(
        action_type="home_assistant.modify_dashboard",
        version=1,
        supported_target_kinds=("home_assistant.dashboard",),
        risk_class=RiskLevel.MEDIUM,
        destructive=True,
        reversible=False,
        dependency_requirement=DependencyRequirement.COMPLETE_REQUIRED,
        required_backup=BackupRequirement.REQUIRED,
        preview_capable=False,
        execution_supported=False,
        rollback_capable=False,
        verification_method="unsupported@1",
        required_privileges=("dashboard.write",),
        idempotency=IdempotencyClassification.NOT_IDEMPOTENT,
        timeout_seconds=30,
        unsupported_reason="No adapter, preview, or rollback path exists yet.",
    ),
    ActionCatalogEntry(
        action_type="home_assistant.modify_recorder_config",
        version=1,
        supported_target_kinds=("home_assistant.config_entry",),
        risk_class=RiskLevel.HIGH,
        destructive=True,
        reversible=False,
        dependency_requirement=DependencyRequirement.COMPLETE_REQUIRED,
        required_backup=BackupRequirement.REQUIRED,
        preview_capable=False,
        execution_supported=False,
        rollback_capable=False,
        verification_method="unsupported@1",
        required_privileges=("recorder.write",),
        idempotency=IdempotencyClassification.NOT_IDEMPOTENT,
        timeout_seconds=30,
        unsupported_reason=(
            "Recorder configuration affects history/statistics retention "
            "globally; Phase 2B only generates a proposed patch for human "
            "application, never applies one directly."
        ),
    ),
    ActionCatalogEntry(
        action_type="home_assistant.edit_secrets",
        version=1,
        supported_target_kinds=("home_assistant.config_entry",),
        risk_class=RiskLevel.HIGH,
        destructive=True,
        reversible=False,
        dependency_requirement=DependencyRequirement.COMPLETE_REQUIRED,
        required_backup=BackupRequirement.REQUIRED,
        preview_capable=False,
        execution_supported=False,
        rollback_capable=False,
        verification_method="unsupported@1",
        required_privileges=("secrets.write",),
        idempotency=IdempotencyClassification.NOT_IDEMPOTENT,
        timeout_seconds=30,
        unsupported_reason=(
            "HAMIE never reads or writes secrets; permanently out of scope."
        ),
    ),
    ActionCatalogEntry(
        action_type="home_assistant.restart",
        version=1,
        supported_target_kinds=("home_assistant.core",),
        risk_class=RiskLevel.HIGH,
        destructive=True,
        reversible=False,
        dependency_requirement=DependencyRequirement.COMPLETE_REQUIRED,
        required_backup=BackupRequirement.REQUIRED,
        preview_capable=False,
        execution_supported=False,
        rollback_capable=False,
        verification_method="unsupported@1",
        required_privileges=("core.restart",),
        idempotency=IdempotencyClassification.NOT_IDEMPOTENT,
        timeout_seconds=30,
        unsupported_reason=(
            "Restarting Home Assistant is explicitly out of scope for the "
            "remediation engine; it interrupts every running automation."
        ),
    ),
    ActionCatalogEntry(
        action_type="home_assistant.reload_integration",
        version=1,
        supported_target_kinds=("home_assistant.config_entry",),
        risk_class=RiskLevel.MEDIUM,
        destructive=True,
        reversible=False,
        dependency_requirement=DependencyRequirement.COMPLETE_REQUIRED,
        required_backup=BackupRequirement.REQUIRED,
        preview_capable=False,
        execution_supported=False,
        rollback_capable=False,
        verification_method="unsupported@1",
        required_privileges=("config_entries.reload",),
        idempotency=IdempotencyClassification.NOT_IDEMPOTENT,
        timeout_seconds=30,
        unsupported_reason=(
            "No safe, tested rollback path exists if a reload leaves an "
            "integration in a broken state."
        ),
    ),
    ActionCatalogEntry(
        action_type="n8n.modify_workflow",
        version=1,
        supported_target_kinds=("n8n.workflow",),
        risk_class=RiskLevel.HIGH,
        destructive=True,
        reversible=False,
        dependency_requirement=DependencyRequirement.COMPLETE_REQUIRED,
        required_backup=BackupRequirement.REQUIRED,
        preview_capable=False,
        execution_supported=False,
        rollback_capable=False,
        verification_method="unsupported@1",
        required_privileges=("n8n.workflow.write",),
        idempotency=IdempotencyClassification.NOT_IDEMPOTENT,
        timeout_seconds=30,
        unsupported_reason=(
            "n8n workflows are an external system HAMIE only reads from; "
            "HAMIE has no authority to mutate a user's automation platform."
        ),
    ),
)

ACTION_CATALOG: dict[str, ActionCatalogEntry] = {
    entry.action_type: entry for entry in (*_SUPPORTED_ENTRIES, *_UNSUPPORTED_ENTRIES)
}

if len(ACTION_CATALOG) != len(_SUPPORTED_ENTRIES) + len(_UNSUPPORTED_ENTRIES):
    raise RuntimeError("duplicate action_type in the remediation action catalog")


def get_catalog_entry(action_type: str) -> ActionCatalogEntry | None:
    """Return the catalog entry for ``action_type``, or ``None`` if unknown."""
    return ACTION_CATALOG.get(action_type)
