"""Canonical remediation plan domain model (HAMIE Phase 2B).

A ``RemediationPlan`` is the durable, deterministic, immutable record of
"exactly what would happen" if a human approves acting on one
``CanonicalRecommendation`` (see ``domain/recommendation.py``). Nothing in
this module executes anything -- it is the same pure, I/O-free discipline
as the rest of ``domain/`` (see ``domain/findings.py``,
``domain/recommendation.py``).

This is not an autonomous cleanup system. A plan is inert data until an
``ApprovalRecord`` (``domain/remediation_approval.py``) binds a human
decision to its exact ``plan_fingerprint``, and even then only the
execution coordinator (``application/remediation/coordinator.py``) --
never an LLM, never this module -- may act on it.

Phase 2B ships with a conservative action catalog
(``domain/remediation_catalog.py``): only non-destructive, no-real-backup
actions are ``execution_supported``. No real Home Assistant mutation
capability exists yet; the only executable adapters (see
``application/remediation/adapters.py``) touch HAMIE's own recommendation
metadata, produce inert patch/instruction artifacts, or (for testing only)
mutate an isolated fixture store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .common import canonical_json, require_non_empty, require_utc, stable_digest
from .findings import Confidence, Risk, RiskLevel
from .identity import SubjectIdentity

REMEDIATION_SCHEMA_VERSION = 1
REMEDIATION_FINGERPRINT_VERSION = 1

MAX_TEXT_LENGTH = 4_000
MAX_LIST_ITEMS = 64
MAX_LIST_ITEM_LENGTH = 1_000
MAX_ACTION_STEPS = 16


class RemediationPlanState(StrEnum):
    """Lifecycle state of one remediation plan."""

    DRAFT = "draft"
    READY_FOR_REVIEW = "ready_for_review"
    SNOOZED = "snoozed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTION_PENDING = "execution_pending"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    ROLLBACK_PENDING = "rollback_pending"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"
    INVALIDATED = "invalidated"


# States in which a plan is inert -- no execution, no pending approval
# action -- used by callers deciding whether a plan may still be shown as
# actionable in a review UI.
TERMINAL_PLAN_STATES = frozenset(
    {
        RemediationPlanState.REJECTED,
        RemediationPlanState.EXPIRED,
        RemediationPlanState.SUCCEEDED,
        RemediationPlanState.PARTIALLY_SUCCEEDED,
        RemediationPlanState.FAILED,
        RemediationPlanState.ROLLED_BACK,
        RemediationPlanState.ROLLBACK_FAILED,
        RemediationPlanState.INVALIDATED,
    }
)


class RollbackSupportStatus(StrEnum):
    """Whether a plan's completed steps can be reversed."""

    NOT_APPLICABLE = "not_applicable"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    PARTIAL = "partial"


class DataLossRisk(StrEnum):
    """Expected data-loss risk of executing a plan."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IdempotencyClassification(StrEnum):
    """How an action step behaves when applied more than once."""

    PURE_IDEMPOTENT = "pure_idempotent"
    IDEMPOTENT_WITH_SIDE_EFFECT = "idempotent_with_side_effect"
    NOT_IDEMPOTENT = "not_idempotent"


class BackupRequirement(StrEnum):
    """Whether a step requires a verified backup before it may execute."""

    NOT_REQUIRED = "not_required"
    REQUIRED = "required"


def _require_bounded(
    value: str, field_name: str, *, max_length: int = MAX_TEXT_LENGTH
) -> str:
    require_non_empty(value, field_name)
    if len(value) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    return value


def _bounded_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    deduped = tuple(dict.fromkeys(values))
    if len(deduped) > MAX_LIST_ITEMS:
        raise ValueError(f"{field_name} exceeds {MAX_LIST_ITEMS} items")
    if any(not item or len(item) > MAX_LIST_ITEM_LENGTH for item in deduped):
        raise ValueError(f"{field_name} items must be bounded non-empty strings")
    return deduped


def _bounded_params(
    values: tuple[tuple[str, str], ...], field_name: str
) -> tuple[tuple[str, str], ...]:
    normalized = tuple(sorted(dict(values).items()))
    if len(normalized) > MAX_LIST_ITEMS:
        raise ValueError(f"{field_name} exceeds {MAX_LIST_ITEMS} entries")
    for key, value in normalized:
        if not key or len(key) > 256:
            raise ValueError(f"{field_name} keys must be bounded non-empty strings")
        if len(value) > MAX_LIST_ITEM_LENGTH:
            raise ValueError(f"{field_name} values exceed {MAX_LIST_ITEM_LENGTH} chars")
    return normalized


@dataclass(frozen=True, slots=True)
class RemediationRollbackStep:
    """How to reverse exactly one already-executed action step."""

    reverses_step_index: int
    action_type: str
    adapter_id: str
    parameters: tuple[tuple[str, str], ...]
    verification_description: str

    def __post_init__(self) -> None:
        if self.reverses_step_index < 0:
            raise ValueError("reverses_step_index cannot be negative")
        _require_bounded(self.action_type, "rollback action_type", max_length=256)
        _require_bounded(self.adapter_id, "rollback adapter_id", max_length=256)
        _require_bounded(self.verification_description, "rollback verification")
        object.__setattr__(
            self, "parameters", _bounded_params(self.parameters, "rollback parameters")
        )


@dataclass(frozen=True, slots=True)
class RollbackPlan:
    """Aggregate rollback capability and plan for one remediation plan."""

    supported: bool
    steps: tuple[RemediationRollbackStep, ...] = ()
    required_data_tokens: tuple[str, ...] = ()
    risk: RiskLevel = RiskLevel.LOW
    preconditions: tuple[str, ...] = ()
    verification: str = "no rollback verification defined"
    limitations: tuple[str, ...] = ()
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_bounded(self.verification, "rollback verification")
        object.__setattr__(
            self,
            "required_data_tokens",
            _bounded_tuple(self.required_data_tokens, "required_data_tokens"),
        )
        object.__setattr__(
            self, "preconditions", _bounded_tuple(self.preconditions, "preconditions")
        )
        object.__setattr__(
            self, "limitations", _bounded_tuple(self.limitations, "limitations")
        )
        object.__setattr__(
            self,
            "steps",
            tuple(sorted(self.steps, key=lambda item: item.reverses_step_index)),
        )
        if self.expires_at is not None:
            object.__setattr__(
                self, "expires_at", require_utc(self.expires_at, "rollback expires_at")
            )
        # rollback_supported cannot be true without concrete rollback steps.
        if self.supported and not self.steps:
            raise ValueError("rollback_supported requires at least one rollback step")
        if not self.supported and self.steps:
            raise ValueError(
                "rollback steps were provided but rollback is marked unsupported"
            )


@dataclass(frozen=True, slots=True)
class RemediationVerificationSpec:
    """The deterministic check that proves one action step actually worked.

    Distinct from ``VerificationResult`` (``domain/remediation_execution.py``,
    the recorded *outcome* of running this check) -- this is the plan-time
    *specification* of what will be checked, fixed at planning time so it
    is part of the plan's identity.
    """

    method: str
    expected_outcome_description: str
    checks_before_state: bool = True

    def __post_init__(self) -> None:
        _require_bounded(self.method, "verification method", max_length=256)
        if "@" not in self.method:
            raise ValueError("verification method must include a schema version")
        _require_bounded(
            self.expected_outcome_description, "verification expected_outcome"
        )


@dataclass(frozen=True, slots=True)
class RemediationActionStep:
    """One ordered, immutable, deterministic step of a remediation plan."""

    step_index: int
    action_type: str
    action_version: int
    target: SubjectIdentity
    adapter_id: str
    adapter_version: int
    parameters: tuple[tuple[str, str], ...]
    expected_change_description: str
    destructive: bool
    idempotency: IdempotencyClassification
    reversible: bool
    verification: RemediationVerificationSpec
    required_backup: BackupRequirement
    rollback_step: RemediationRollbackStep | None = None
    timeout_seconds: int = 30
    max_attempts: int = 1
    required_privileges: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.step_index < 0:
            raise ValueError("step_index cannot be negative")
        if self.action_version < 1:
            raise ValueError("action_version must be positive")
        if self.adapter_version < 1:
            raise ValueError("adapter_version must be positive")
        _require_bounded(self.action_type, "action_type", max_length=256)
        _require_bounded(self.adapter_id, "adapter_id", max_length=256)
        _require_bounded(self.expected_change_description, "expected_change")
        object.__setattr__(
            self, "parameters", _bounded_params(self.parameters, "action parameters")
        )
        object.__setattr__(
            self,
            "required_privileges",
            _bounded_tuple(self.required_privileges, "required_privileges"),
        )
        if self.timeout_seconds < 1 or self.timeout_seconds > 3_600:
            raise ValueError("timeout_seconds must be between 1 and 3600")
        if self.max_attempts < 1 or self.max_attempts > 3:
            raise ValueError("max_attempts must be between 1 and 3")
        # A destructive step must never be silently retried.
        if self.destructive and self.max_attempts != 1:
            raise ValueError("a destructive action step cannot have max_attempts > 1")
        # A reversible step MAY still lack its own rollback_step (e.g. it
        # is trivially reversible by re-running the forward action) --
        # the plan-level RollbackPlan is the authoritative claim. An
        # irreversible step, however, must never carry a fabricated one.
        if not self.reversible and self.rollback_step is not None:
            raise ValueError("an irreversible action step cannot carry a rollback step")
        if self.rollback_step is not None:
            expected_index = self.rollback_step.reverses_step_index
            if expected_index != self.step_index:
                raise ValueError(
                    "a step's own rollback_step must reverse that same step_index"
                )


@dataclass(frozen=True, slots=True)
class RemediationDependencySnapshot:
    """Frozen dependency/evidence state a plan was built against.

    Deliberately distinct from ``recommendation.DependencyAnalysisResult``:
    that type is per-recommendation and mutable across reconciliation
    passes; this is a point-in-time digest captured once, at planning
    time, and never updated in place -- any change invalidates the plan's
    fingerprint (and therefore any approval) rather than being merged.
    """

    dependency_digest: str
    evidence_digest: str
    sources_checked: tuple[str, ...] = ()
    unavailable_sources: tuple[str, ...] = ()
    unresolved_dependencies: tuple[str, ...] = ()
    blocking_dependencies: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_bounded(self.dependency_digest, "dependency_digest", max_length=128)
        _require_bounded(self.evidence_digest, "evidence_digest", max_length=128)
        for field_name in (
            "sources_checked",
            "unavailable_sources",
            "unresolved_dependencies",
            "blocking_dependencies",
            "preconditions",
            "assumptions",
            "warnings",
        ):
            object.__setattr__(
                self, field_name, _bounded_tuple(getattr(self, field_name), field_name)
            )


@dataclass(frozen=True, slots=True)
class RemediationRiskAssessment:
    """Composed risk classification for one remediation plan."""

    risk: Risk
    destructive: bool
    reversible: bool
    rollback_support: RollbackSupportStatus
    expected_user_visible_impact: str
    expected_service_interruption: str
    expected_data_loss_risk: DataLossRisk
    confidence: Confidence
    risk_rationale: str

    def __post_init__(self) -> None:
        _require_bounded(
            self.expected_user_visible_impact, "expected_user_visible_impact"
        )
        _require_bounded(
            self.expected_service_interruption, "expected_service_interruption"
        )
        _require_bounded(self.risk_rationale, "risk_rationale")
        if self.destructive and self.expected_data_loss_risk is DataLossRisk.NONE:
            raise ValueError(
                "a destructive plan cannot claim zero expected data-loss risk"
            )


def compute_structural_preview_digest(
    actions: tuple[RemediationActionStep, ...],
) -> str:
    """Return a deterministic digest of exactly what a plan would do.

    Pure and I/O-free: covers only the same tamper-evident structural
    facts already embedded in each action step (target, adapter,
    parameters, expected-change description) -- never adapter-rendered
    before/after content, which is display-only and produced separately
    by ``application/remediation/preview_service.py``. This is the value
    ``ApprovalRecord.preview_digest`` binds to, so an approval can never
    be reused if what the plan would actually do changes.
    """
    parts = tuple(
        (
            step.step_index,
            step.action_type,
            step.target.identity_key,
            step.adapter_id,
            step.parameters,
            step.expected_change_description,
        )
        for step in actions
    )
    return stable_digest(canonical_json([str(part) for part in parts]))


def compute_remediation_plan_fingerprint(
    *,
    recommendation_id: str,
    recommendation_fingerprint: str,
    recommendation_revision: int,
    installation_id: str,
    planner_version: str,
    actions: tuple[RemediationActionStep, ...],
    dependency_snapshot: RemediationDependencySnapshot,
    risk: RemediationRiskAssessment,
    requires_backup: bool,
) -> str:
    """Return the deterministic identity of one remediation plan.

    Excludes every volatile input: timestamps, generated prose, UI
    labels, random identifiers, approval metadata, execution results,
    and logging metadata. Two calls with the same recommendation
    identity/revision, installation, planner version, ordered action
    definitions (including adapter versions, normalized targets and
    parameters), dependency/evidence digests, risk classification, and
    backup policy always produce the same fingerprint.
    """
    action_key = tuple(
        (
            step.step_index,
            step.action_type,
            step.action_version,
            step.target.identity_key,
            step.adapter_id,
            step.adapter_version,
            step.parameters,
            step.destructive,
            step.idempotency.value,
            step.reversible,
            step.verification.method,
            step.required_backup.value,
        )
        for step in actions
    )
    return stable_digest(
        REMEDIATION_FINGERPRINT_VERSION,
        recommendation_id,
        recommendation_fingerprint,
        recommendation_revision,
        installation_id,
        planner_version,
        canonical_json([str(part) for part in action_key]),
        dependency_snapshot.dependency_digest,
        dependency_snapshot.evidence_digest,
        risk.risk.overall.value,
        risk.destructive,
        risk.rollback_support.value,
        risk.expected_data_loss_risk.value,
        requires_backup,
    )


@dataclass(frozen=True, slots=True)
class RemediationPlan:
    """Complete durable, deterministic, non-executing remediation plan."""

    remediation_plan_id: str
    plan_fingerprint: str
    fingerprint_version: int
    schema_version: int
    recommendation_id: str
    recommendation_fingerprint: str
    recommendation_revision: int
    installation_id: str
    created_at: datetime
    created_by: str
    planner_version: str
    state: RemediationPlanState
    actions: tuple[RemediationActionStep, ...]
    dependency_snapshot: RemediationDependencySnapshot
    risk: RemediationRiskAssessment
    rollback_plan: RollbackPlan
    execution_supported: bool
    unsupported_reason: str | None = None
    expires_at: datetime | None = None
    requires_backup: bool = False
    requires_manual_confirmation: bool = True
    approval_scope: str = "single"
    batch_compatible: bool = False
    preview_digest: str | None = None
    updated_at: datetime | None = None
    snoozed_at: datetime | None = None
    snoozed_by: str | None = None
    snooze_until: datetime | None = None
    snooze_reason: str | None = None
    snoozed_from_state: RemediationPlanState | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.remediation_plan_id, "remediation_plan_id"),
            (self.plan_fingerprint, "plan_fingerprint"),
            (self.recommendation_id, "recommendation_id"),
            (self.recommendation_fingerprint, "recommendation_fingerprint"),
            (self.installation_id, "installation_id"),
            (self.created_by, "created_by"),
            (self.planner_version, "planner_version"),
        ):
            _require_bounded(value, name, max_length=512)
        if self.schema_version != REMEDIATION_SCHEMA_VERSION:
            raise ValueError("unsupported remediation plan schema version")
        if self.fingerprint_version != REMEDIATION_FINGERPRINT_VERSION:
            raise ValueError("unsupported remediation plan fingerprint version")
        if self.recommendation_revision < 1:
            raise ValueError("recommendation_revision must be positive")
        created = require_utc(self.created_at, "created_at")
        object.__setattr__(self, "created_at", created)
        if self.updated_at is not None:
            updated = require_utc(self.updated_at, "updated_at")
            if updated < created:
                raise ValueError("updated_at cannot precede created_at")
            object.__setattr__(self, "updated_at", updated)
        if self.expires_at is not None:
            object.__setattr__(
                self, "expires_at", require_utc(self.expires_at, "expires_at")
            )
        if self.snoozed_at is not None:
            object.__setattr__(
                self, "snoozed_at", require_utc(self.snoozed_at, "snoozed_at")
            )
        if self.snooze_until is not None:
            object.__setattr__(
                self, "snooze_until", require_utc(self.snooze_until, "snooze_until")
            )
        if self.snoozed_by is not None:
            _require_bounded(self.snoozed_by, "snoozed_by", max_length=512)
        if self.snooze_reason is not None:
            _require_bounded(self.snooze_reason, "snooze_reason", max_length=500)
        snooze_identity = (
            self.snoozed_at,
            self.snoozed_by,
            self.snooze_until,
            self.snoozed_from_state,
        )
        if self.state is RemediationPlanState.SNOOZED:
            if any(value is None for value in snooze_identity):
                raise ValueError("a snoozed plan requires complete snooze metadata")
            assert self.snoozed_at is not None
            assert self.snooze_until is not None
            if self.snoozed_from_state not in {
                RemediationPlanState.DRAFT,
                RemediationPlanState.READY_FOR_REVIEW,
            }:
                raise ValueError(
                    "a snoozed plan must preserve a reviewable prior state"
                )
            if self.snooze_until <= self.snoozed_at:
                raise ValueError("snooze_until must be later than snoozed_at")
        if not self.actions:
            raise ValueError("a remediation plan requires at least one action step")
        if len(self.actions) > MAX_ACTION_STEPS:
            raise ValueError(
                f"a remediation plan allows at most {MAX_ACTION_STEPS} steps"
            )
        ordered = tuple(sorted(self.actions, key=lambda item: item.step_index))
        if tuple(item.step_index for item in ordered) != tuple(range(len(ordered))):
            raise ValueError("action step_index values must be a dense 0..n-1 sequence")
        object.__setattr__(self, "actions", ordered)

        expected_fingerprint = compute_remediation_plan_fingerprint(
            recommendation_id=self.recommendation_id,
            recommendation_fingerprint=self.recommendation_fingerprint,
            recommendation_revision=self.recommendation_revision,
            installation_id=self.installation_id,
            planner_version=self.planner_version,
            actions=self.actions,
            dependency_snapshot=self.dependency_snapshot,
            risk=self.risk,
            requires_backup=self.requires_backup,
        )
        if self.plan_fingerprint != expected_fingerprint:
            raise ValueError("plan_fingerprint does not match its declared inputs")

        # execution_supported must be false for any step whose adapter is
        # not marked executable; the planner is the only place that
        # decides this, but the plan re-asserts it here defensively.
        if not self.execution_supported and not self.unsupported_reason:
            raise ValueError(
                "execution_supported=false requires a non-empty unsupported_reason"
            )
        if self.execution_supported and self.unsupported_reason:
            raise ValueError(
                "unsupported_reason must be empty when execution_supported is true"
            )

        destructive_steps = any(step.destructive for step in self.actions)
        if destructive_steps and not self.risk.destructive:
            raise ValueError(
                "a plan containing a destructive step must have risk.destructive=true"
            )
        # Destructive plans require explicit dependency safety: no
        # blocking or unresolved dependencies, and every source that was
        # supposed to be checked was actually reachable.
        if destructive_steps:
            snapshot = self.dependency_snapshot
            if snapshot.blocking_dependencies or snapshot.unresolved_dependencies:
                raise ValueError(
                    "a destructive plan cannot have blocking or unresolved dependencies"
                )
            if snapshot.unavailable_sources:
                raise ValueError(
                    "a destructive plan requires every dependency source to "
                    "have been reachable"
                )
        # Destructive plans require backup verification unless every
        # destructive step explicitly declares it does not need one
        # (e.g. it only affects HAMIE's own inert artifacts, never real
        # Home Assistant state). Any step -- destructive or not -- that
        # declares it needs a backup must be reflected at the plan level.
        any_step_needs_backup = any(
            step.required_backup is BackupRequirement.REQUIRED for step in self.actions
        )
        if any_step_needs_backup and not self.requires_backup:
            raise ValueError(
                "a step requiring backup must be reflected in plan.requires_backup"
            )

        # rollback_supported cannot be true without a concrete rollback
        # plan (RollbackPlan itself enforces steps<->supported coupling;
        # this cross-checks the plan-level risk classification agrees).
        rollback_claims_supported = self.rollback_plan.supported
        risk_claims_supported = (
            self.risk.rollback_support is RollbackSupportStatus.SUPPORTED
        )
        if rollback_claims_supported != risk_claims_supported:
            raise ValueError(
                "rollback_plan.supported must agree with risk.rollback_support"
            )
        if self.rollback_plan.supported:
            reversed_indices = {
                item.reverses_step_index for item in self.rollback_plan.steps
            }
            reversible_indices = {
                step.step_index for step in self.actions if step.reversible
            }
            if not reversed_indices <= reversible_indices:
                raise ValueError(
                    "rollback_plan cannot reverse a step that is not reversible"
                )

        # Irreversible destructive steps must be identified before
        # approval and are never execution_supported in Phase 2B.
        irreversible_destructive = any(
            step.destructive and not step.reversible for step in self.actions
        )
        if irreversible_destructive and self.execution_supported:
            raise ValueError(
                "a plan with an irreversible destructive step cannot be "
                "execution_supported in Phase 2B"
            )

        if self.approval_scope not in {"single", "batch"}:
            raise ValueError("approval_scope must be 'single' or 'batch'")
        # A plan cannot be reviewable, approvable, or executable without a
        # preview a human (or an approval record) can bind to -- DRAFT is
        # the only state a preview-less plan may exist in.
        preview_optional = self.state is RemediationPlanState.DRAFT or (
            self.state is RemediationPlanState.SNOOZED
            and self.snoozed_from_state is RemediationPlanState.DRAFT
        )
        if not preview_optional:
            if self.preview_digest is None:
                raise ValueError("a plan outside DRAFT state requires a preview_digest")
        if self.preview_digest is not None:
            _require_bounded(self.preview_digest, "preview_digest", max_length=128)
            expected_preview_digest = compute_structural_preview_digest(self.actions)
            if self.preview_digest != expected_preview_digest:
                raise ValueError("preview_digest does not match its declared actions")

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_PLAN_STATES

    @property
    def is_destructive(self) -> bool:
        return self.risk.destructive


def build_plan_fingerprint_only(
    *,
    recommendation_id: str,
    recommendation_fingerprint: str,
    recommendation_revision: int,
    installation_id: str,
    planner_version: str,
    actions: tuple[RemediationActionStep, ...],
    dependency_snapshot: RemediationDependencySnapshot,
    risk: RemediationRiskAssessment,
    requires_backup: bool,
) -> str:
    """Compute a plan fingerprint without constructing a ``RemediationPlan``.

    The planner (``domain/remediation_planner.py``) uses this to decide
    the plan's identity before it has every other required field
    (state, timestamps, ids) filled in.
    """
    return compute_remediation_plan_fingerprint(
        recommendation_id=recommendation_id,
        recommendation_fingerprint=recommendation_fingerprint,
        recommendation_revision=recommendation_revision,
        installation_id=installation_id,
        planner_version=planner_version,
        actions=actions,
        dependency_snapshot=dependency_snapshot,
        risk=risk,
        requires_backup=requires_backup,
    )
