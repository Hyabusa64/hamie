"""Persistence repository/unit-of-work port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain.ai_control import AiControlAcknowledgement
from ..domain.capability import CapabilityResult
from ..domain.durable_baseline import AnalysisBaseline, RemediationBaseline
from ..domain.common import require_non_empty
from ..domain.evaluations import EvaluationRecord
from ..domain.findings import Finding
from ..domain.implementation_groups import ImplementationGroup
from ..domain.incidents import MAX_INCIDENTS, Incident
from ..domain.intelligence import (
    MAX_AUDIT_RECORDS,
    MAX_GROUPING_RULES,
    MAX_RECOMMENDATIONS,
    MAX_SUPPRESSION_RULES,
    AIRecommendation,
    AuditRecord,
    GroupingRule,
    SuppressionRule,
)
from ..domain.maintenance_work_record import MaintenanceWorkRecord
from ..domain.recommendation import (
    MAX_CANONICAL_RECOMMENDATIONS,
    CanonicalRecommendation,
)
from ..domain.remediation import RemediationPlan
from ..domain.remediation_approval import ApprovalRecord
from ..domain.remediation_execution import (
    ExecutionLockRecord,
    ExecutionRecord,
    ExecutionReplayToken,
    RollbackRecord,
)
from ..domain.reviews import ReviewRecord
from ..domain.successors import EntitySuccessorRelationship

MAX_REMEDIATION_PLANS = 256
MAX_REMEDIATION_APPROVALS = 512
MAX_REMEDIATION_EXECUTIONS = 512
MAX_REMEDIATION_ROLLBACKS = 256
MAX_REMEDIATION_LOCKS = 64
MAX_REMEDIATION_REPLAY_TOKENS = 512
MAX_MAINTENANCE_WORK_ITEMS = 2_000
MAX_ENTITY_SUCCESSORS = 2_000
MAX_IMPLEMENTATION_GROUPS = 500


class PersistenceError(RuntimeError):
    """Base stable persistence error."""


class GenerationConflictError(PersistenceError):
    """Stored generation changed before commit."""


class CorruptStoredStateError(PersistenceError):
    """Stored state failed schema or checksum validation."""


class UnsupportedStoredStateError(PersistenceError):
    """Stored state is newer than this HAMIE release."""


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """Bounded replay marker for an application command."""

    token: str
    command: str
    finding_id: str
    resulting_revision: int

    def __post_init__(self) -> None:
        require_non_empty(self.token, "idempotency token")
        require_non_empty(self.command, "idempotency command")
        require_non_empty(self.finding_id, "idempotency finding_id")
        if self.resulting_revision < 1:
            raise ValueError("idempotency resulting_revision must be positive")


@dataclass(frozen=True, slots=True)
class RepositoryState:
    """Complete canonical state committed as one Store document."""

    generation: int = 0
    findings: tuple[Finding, ...] = ()
    reviews: tuple[ReviewRecord, ...] = ()
    evaluations: tuple[EvaluationRecord, ...] = ()
    idempotency: tuple[IdempotencyRecord, ...] = ()
    projection_revision: int = 0
    migration_history: tuple[str, ...] = ()
    grouping_rules: tuple[GroupingRule, ...] = ()
    suppression_rules: tuple[SuppressionRule, ...] = ()
    audits: tuple[AuditRecord, ...] = ()
    recommendations: tuple[AIRecommendation, ...] = ()
    canonical_recommendations: tuple[CanonicalRecommendation, ...] = ()
    remediation_plans: tuple[RemediationPlan, ...] = ()
    remediation_approvals: tuple[ApprovalRecord, ...] = ()
    remediation_executions: tuple[ExecutionRecord, ...] = ()
    remediation_rollbacks: tuple[RollbackRecord, ...] = ()
    remediation_locks: tuple[ExecutionLockRecord, ...] = ()
    remediation_replay_tokens: tuple[ExecutionReplayToken, ...] = ()
    ai_control_acknowledgement: AiControlAcknowledgement | None = None
    maintenance_work_items: tuple[MaintenanceWorkRecord, ...] = ()
    entity_successors: tuple[EntitySuccessorRelationship, ...] = ()
    implementation_groups: tuple[ImplementationGroup, ...] = ()
    incidents: tuple[Incident, ...] = ()
    # The scan_id `hamie/cleanup/run` last completed a full classification
    # pass against -- the only way the frontend can honestly distinguish
    # "cleanup has never been run against the current evidence" from
    # "cleanup ran and genuinely found zero safe candidates" (see
    # cleanup_coordinator.py's async_run_cleanup). None until the first
    # successful cleanup run.
    last_cleanup_scan_id: str | None = None
    #: The most recent provider capability probe, bound to the exact
    #: configuration it measured (see domain/capability.py).
    capability: CapabilityResult | None = None
    #: What the last completed analysis covered, so coverage is not lost on
    #: restart while its recommendations survive (see domain/durable_baseline).
    analysis_baseline: AnalysisBaseline | None = None
    #: The world immediately before each approved repair, so an interrupted
    #: remediation can still be reconciled after a restart.
    remediation_baselines: tuple[RemediationBaseline, ...] = ()

    def __post_init__(self) -> None:
        if self.generation < 0 or self.projection_revision < 0:
            raise ValueError("repository generations cannot be negative")
        finding_ids = [item.finding_id for item in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("repository findings must have unique IDs")
        tokens = [item.token for item in self.idempotency]
        if len(tokens) != len(set(tokens)):
            raise ValueError("idempotency tokens must be unique")
        object.__setattr__(
            self,
            "findings",
            tuple(sorted(self.findings, key=lambda item: item.finding_id)),
        )
        if len(self.findings) > 10_000:
            raise ValueError("repository retains at most 10000 findings")
        if len(self.evaluations) > 5:
            raise ValueError("repository retains at most 5 evaluations")
        if len(self.reviews) > 500:
            raise ValueError("repository retains at most 500 reviews")
        if len(self.idempotency) > 128:
            raise ValueError("repository retains at most 128 idempotency records")
        if len(self.grouping_rules) > MAX_GROUPING_RULES:
            raise ValueError("repository grouping rule limit exceeded")
        if len(self.suppression_rules) > MAX_SUPPRESSION_RULES:
            raise ValueError("repository suppression rule limit exceeded")
        if len(self.audits) > MAX_AUDIT_RECORDS:
            raise ValueError("repository audit limit exceeded")
        if len(self.recommendations) > MAX_RECOMMENDATIONS:
            raise ValueError("repository recommendation limit exceeded")
        if len(self.canonical_recommendations) > MAX_CANONICAL_RECOMMENDATIONS:
            raise ValueError("repository canonical recommendation limit exceeded")
        canonical_ids = [
            item.recommendation_id for item in self.canonical_recommendations
        ]
        if len(canonical_ids) != len(set(canonical_ids)):
            raise ValueError("canonical recommendation IDs must be unique")
        canonical_fingerprints = [
            item.fingerprint for item in self.canonical_recommendations
        ]
        if len(canonical_fingerprints) != len(set(canonical_fingerprints)):
            raise ValueError("canonical recommendation fingerprints must be unique")
        for values, name in (
            (self.grouping_rules, "grouping rule"),
            (self.suppression_rules, "suppression rule"),
        ):
            ids = [item.rule_id for item in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"repository {name} IDs must be unique")
        if any(not item or item != item.strip() for item in self.migration_history):
            raise ValueError("migration history entries must be normalized")

        if len(self.remediation_plans) > MAX_REMEDIATION_PLANS:
            raise ValueError("repository remediation plan limit exceeded")
        plan_ids = [item.remediation_plan_id for item in self.remediation_plans]
        if len(plan_ids) != len(set(plan_ids)):
            raise ValueError("remediation plan IDs must be unique")
        plan_fingerprints = [item.plan_fingerprint for item in self.remediation_plans]
        if len(plan_fingerprints) != len(set(plan_fingerprints)):
            raise ValueError("remediation plan fingerprints must be unique")

        if len(self.remediation_approvals) > MAX_REMEDIATION_APPROVALS:
            raise ValueError("repository remediation approval limit exceeded")
        approval_ids = [item.approval_id for item in self.remediation_approvals]
        if len(approval_ids) != len(set(approval_ids)):
            raise ValueError("remediation approval IDs must be unique")

        if len(self.remediation_executions) > MAX_REMEDIATION_EXECUTIONS:
            raise ValueError("repository remediation execution limit exceeded")
        execution_ids = [item.execution_id for item in self.remediation_executions]
        if len(execution_ids) != len(set(execution_ids)):
            raise ValueError("remediation execution IDs must be unique")

        if len(self.remediation_rollbacks) > MAX_REMEDIATION_ROLLBACKS:
            raise ValueError("repository remediation rollback limit exceeded")
        rollback_ids = [item.rollback_id for item in self.remediation_rollbacks]
        if len(rollback_ids) != len(set(rollback_ids)):
            raise ValueError("remediation rollback IDs must be unique")

        if len(self.remediation_locks) > MAX_REMEDIATION_LOCKS:
            raise ValueError("repository remediation lock limit exceeded")
        lock_ids = [item.lock_id for item in self.remediation_locks]
        if len(lock_ids) != len(set(lock_ids)):
            raise ValueError("remediation lock IDs must be unique")

        if len(self.remediation_replay_tokens) > MAX_REMEDIATION_REPLAY_TOKENS:
            raise ValueError("repository remediation replay token limit exceeded")
        replay_tokens = [item.token for item in self.remediation_replay_tokens]
        if len(replay_tokens) != len(set(replay_tokens)):
            raise ValueError("remediation replay tokens must be unique")

        if len(self.maintenance_work_items) > MAX_MAINTENANCE_WORK_ITEMS:
            raise ValueError("repository maintenance work item limit exceeded")
        work_item_ids = [item.work_item_id for item in self.maintenance_work_items]
        if len(work_item_ids) != len(set(work_item_ids)):
            raise ValueError("maintenance work item IDs must be unique")

        if len(self.entity_successors) > MAX_ENTITY_SUCCESSORS:
            raise ValueError("repository entity successor limit exceeded")
        successor_fingerprints = [item.fingerprint for item in self.entity_successors]
        if len(successor_fingerprints) != len(set(successor_fingerprints)):
            raise ValueError("entity successor fingerprints must be unique")

        if len(self.implementation_groups) > MAX_IMPLEMENTATION_GROUPS:
            raise ValueError("repository implementation group limit exceeded")
        group_fingerprints = [item.fingerprint for item in self.implementation_groups]
        if len(group_fingerprints) != len(set(group_fingerprints)):
            raise ValueError("implementation group fingerprints must be unique")

        if len(self.incidents) > MAX_INCIDENTS:
            raise ValueError("repository incident limit exceeded")
        incident_ids = [item.incident_id for item in self.incidents]
        if len(incident_ids) != len(set(incident_ids)):
            raise ValueError("repository incident IDs must be unique")


class PersistenceUnitOfWorkPort(Protocol):
    """Single-document repository and optimistic unit-of-work boundary."""

    async def async_load(self) -> RepositoryState:
        """Load and validate current state."""

    async def async_commit(
        self, state: RepositoryState, *, expected_generation: int
    ) -> None:
        """Atomically replace one document if generation is unchanged."""

    async def async_remove(self) -> None:
        """Remove the repository document during config-entry removal."""
