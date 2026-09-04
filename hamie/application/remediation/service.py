"""Thin orchestration facade for the Phase 2B remediation engine (Phase 2C).

This module is the *only* thing the presentation layer
(``presentation/remediation_api.py``) talks to. It never reimplements
planning, preview, approval, locking, precondition verification,
execution, or rollback -- every one of those already exists in
``domain/remediation*.py`` and ``application/remediation/{adapters,
preconditions,locks,preview_service,coordinator}.py``; this module only
loads/persists ``RepositoryState``, calls those existing functions, and
translates outcomes into a small set of stable, typed results the
WebSocket layer can serialize.

Production adapter registry: deliberately excludes
``fixture_test_adapter`` -- the API surface must never be able to reach
the test-only adapter, matching its existing catalog/planner-level
gating (see docs/REMEDIATION_ENGINE.md §7).

Audit events use the same deterministic ``audit_id = f"aud_{stable_digest(
event, token)[:24]}"`` scheme already established in
``operations_service.py``: retrying the identical operation with the
identical token produces the identical audit_id, which
``_append_audit`` uses to silently deduplicate rather than double-record.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import uuid4

from ...domain.common import stable_digest
from ...domain.intelligence import MAX_AUDIT_RECORDS, AuditRecord
from ...domain.maintenance_work_record import MaintenanceWorkRecord
from ...domain.recommendation import (
    CanonicalRecommendation,
    RecommendationLifecycleState,
)
from ...domain.remediation import RemediationPlan, RemediationPlanState
from ...domain.remediation_approval import (
    ApprovalRecord,
    ApprovalScope,
    ApprovalState,
    revoke_approval,
)
from ...domain.remediation_execution import ExecutionRecord, RollbackRecord
from ...domain.remediation_planner import (
    PlanningRejection,
    plan_batch_disable_remediation,
    plan_llm_proposed_remediation,
    plan_remediation,
)
from ..persistence import (
    GenerationConflictError,
    PersistenceUnitOfWorkPort,
    RepositoryState,
)
from . import audit_events
from .adapters import (
    ManualActionAdapter,
    RecorderExclusionPatchAdapter,
    RemediationActionAdapter,
)
from .coordinator import (
    RollbackRejectedError,
)
from .coordinator import (
    async_execute_plan as _coordinator_execute,
)
from .coordinator import (
    async_rollback_execution as _coordinator_rollback,
)
from .file_adapters import (
    FilePolicyError,
    HassFileMutationPort,
    UnavailableFileMutationPort,
    file_mutation_adapter,
    resource_content_hash,
)
from .ha_adapters import home_assistant_adapters
from .preconditions import BackupProvider, NullBackupProvider
from .preview_service import (
    PreviewMismatchError,
    PreviewRunResult,
    async_run_preview,
)

MAX_COMMIT_ATTEMPTS = 5
DEFAULT_APPROVAL_LEASE = timedelta(hours=24)
DEFAULT_QUEUE_LIMIT = 50
MAX_QUEUE_LIMIT = 200


class RemediationServiceError(RuntimeError):
    """A stable, non-sensitive remediation API failure.

    Mirrors ``configuration.py``'s ``ConfigurationError`` -- the
    established project convention for a typed, code-carrying business
    error the presentation layer maps directly to
    ``connection.send_error(msg["id"], err.code, message)``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


def production_adapters(
    hass: object | None = None,
) -> dict[str, RemediationActionAdapter]:
    """Return the adapter registry the API/coordinator may use.

    Never includes ``fixture_test_adapter`` -- there is no path from
    this module back to a test-only mutation target.
    """
    adapters: dict[str, RemediationActionAdapter] = {
        "manual_action_adapter": ManualActionAdapter(),
        "recorder_exclusion_patch_adapter": RecorderExclusionPatchAdapter(),
        "file_mutation_adapter": file_mutation_adapter(hass),
    }
    adapters.update(home_assistant_adapters(hass))
    return adapters


def production_backup_provider() -> BackupProvider:
    """Return the backup provider the API/coordinator may use.

    ``NullBackupProvider`` is the only implementation Phase 2B/2C ships
    -- see docs/REMEDIATION_ENGINE.md §8. No real backup integration
    exists in this repository.
    """
    return NullBackupProvider()


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
    raise RemediationServiceError(
        "remediation_internal_error",
        "Could not save the remediation change; please try again.",
    )


def _find_recommendation(
    state: RepositoryState, recommendation_id: str
) -> CanonicalRecommendation | None:
    return next(
        (
            item
            for item in state.canonical_recommendations
            if item.recommendation_id == recommendation_id
        ),
        None,
    )


def _find_plan(
    state: RepositoryState, remediation_plan_id: str
) -> RemediationPlan | None:
    return next(
        (
            item
            for item in state.remediation_plans
            if item.remediation_plan_id == remediation_plan_id
        ),
        None,
    )


def _find_latest_plan_for_recommendation(
    state: RepositoryState, recommendation_id: str
) -> RemediationPlan | None:
    candidates = [
        item
        for item in state.remediation_plans
        if item.recommendation_id == recommendation_id
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.created_at)


def _find_approval(state: RepositoryState, approval_id: str) -> ApprovalRecord | None:
    return next(
        (
            item
            for item in state.remediation_approvals
            if item.approval_id == approval_id
        ),
        None,
    )


def _latest_approval_for_plan(
    state: RepositoryState, remediation_plan_id: str
) -> ApprovalRecord | None:
    candidates = [
        item
        for item in state.remediation_approvals
        if item.remediation_plan_id == remediation_plan_id
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.decided_at)


def _executions_for_plan(
    state: RepositoryState, remediation_plan_id: str
) -> tuple[ExecutionRecord, ...]:
    return tuple(
        sorted(
            (
                item
                for item in state.remediation_executions
                if item.remediation_plan_id == remediation_plan_id
            ),
            key=lambda item: item.started_at,
        )
    )


def _rollbacks_for_executions(
    state: RepositoryState, execution_ids: tuple[str, ...]
) -> tuple[RollbackRecord, ...]:
    return tuple(
        sorted(
            (
                item
                for item in state.remediation_rollbacks
                if item.execution_id in execution_ids
            ),
            key=lambda item: item.initiated_at,
        )
    )


def _audit(
    event: str,
    actor: str,
    target_ids: tuple[str, ...],
    details: tuple[tuple[str, str], ...],
    *,
    token: str,
    now: datetime,
) -> AuditRecord:
    return AuditRecord(
        audit_id=f"aud_{stable_digest(event, token)[:24]}",
        event=event,
        at=now,
        actor=actor,
        target_ids=target_ids,
        details=details,
    )


def _append_audit(
    audits: tuple[AuditRecord, ...], record: AuditRecord
) -> tuple[AuditRecord, ...]:
    """Append one audit record, deduplicating by its deterministic ID.

    A retried operation with the same idempotency token produces the
    identical ``audit_id`` -- appending it again would be a duplicate,
    not a new event, so it is silently skipped rather than recorded
    twice.
    """
    if any(item.audit_id == record.audit_id for item in audits):
        return audits
    return (*audits, record)[-MAX_AUDIT_RECORDS:]


@dataclass(frozen=True, slots=True)
class QueueItem:
    """One row of the remediation review queue."""

    recommendation_id: str
    title: str
    category: str
    subtype: str
    action_type: str | None
    execution_supported: bool
    unsupported_reason: str | None
    confidence: str
    risk_level: str
    affected_object: str
    dependency_status: str
    estimated_impact: str
    status: str
    section: str
    plan_id: str | None
    plan_fingerprint: str | None
    snooze_until: datetime | None
    snooze_reason: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class QueueResult:
    items: tuple[QueueItem, ...]
    total: int
    offset: int
    limit: int
    section_counts: tuple[tuple[str, int], ...] = ()
    # Durable non-actionable maintenance work
    # (domain/maintenance_work_record.py's MaintenanceWorkRecord) --
    # deliberately a separate list rather than force-fit into
    # QueueItem, which models an executable-plan lifecycle
    # (approve/execute/rollback) these records never have.
    maintenance_work_items: tuple[MaintenanceWorkRecord, ...] = ()
    # The scan_id `hamie/cleanup/run` last completed a full classification
    # pass against (RepositoryState.last_cleanup_scan_id) -- compared by
    # the frontend against `hamie/explorer/overview`'s `last_scan_id` to
    # honestly distinguish "cleanup has never been run against the
    # current evidence" from "cleanup ran and genuinely found zero safe
    # candidates". None until the first successful cleanup run.
    last_cleanup_scan_id: str | None = None


_REPLAY_BLOCKED_PREFIX = "replay_blocked:"


def _meaningful_executions(
    executions: tuple[ExecutionRecord, ...],
) -> tuple[ExecutionRecord, ...]:
    """Drop coordinator-level replay-blocked stand-ins.

    A resent request with an already-used idempotency token (a dropped
    response and an automatic client retry, not a new user action)
    appends a synthetic ``FAILED`` record with an ``error`` starting
    ``"replay_blocked:"`` -- see coordinator.py's replay-protection
    step. It is real evidence, so it is never dropped from
    ``DetailResult``/``ExecutionStatusResult``, but it must never be
    treated as *the* execution outcome: doing so would let a benign
    retry of an already-succeeded execution flip the queue status from
    "verified" to "failed".
    """
    return tuple(
        item
        for item in executions
        if not (item.error or "").startswith(_REPLAY_BLOCKED_PREFIX)
    )


def _queue_status(
    recommendation: CanonicalRecommendation | None,
    plan: RemediationPlan | None,
    approval: ApprovalRecord | None,
    executions: tuple[ExecutionRecord, ...],
    rollbacks: tuple[RollbackRecord, ...],
    *,
    now: datetime,
) -> str:
    """Derive one human-facing status label from persisted state only.

    Never inferred from anything the frontend could have cached --
    always recomputed from the current plan/approval/execution/rollback
    records, so a stale client view can never show a status the backend
    does not agree with. ``recommendation`` is never actually read here
    (kept for signature symmetry with ``_queue_section``) -- ``None`` is
    how a batch-disable plan (never driven by a ``CanonicalRecommendation``,
    see ``async_create_batch_disable_plan``) reaches this function.
    """
    if plan is None:
        return "needs_review"
    if plan.state is RemediationPlanState.SNOOZED:
        return "snoozed"
    if plan.state is RemediationPlanState.INVALIDATED:
        return "blocked"
    if not plan.execution_supported:
        return "blocked"
    if rollbacks:
        latest_rollback = rollbacks[-1]
        if latest_rollback.outcome.value == "failed":
            return "rollback_failed"
        if latest_rollback.outcome.value == "succeeded":
            return "rolled_back"
    real_executions = _meaningful_executions(executions)
    if real_executions:
        latest = real_executions[-1]
        outcome = latest.outcome.value
        if outcome == "succeeded":
            return "verified"
        if outcome in {"failed", "partially_succeeded"}:
            return "failed"
        if outcome == "in_progress":
            return "executing"
    if approval is not None:
        if approval.state.value == "rejected":
            return "rejected"
        if approval.is_revoked:
            return "needs_review"
        if approval.is_valid_for(
            plan_fingerprint=plan.plan_fingerprint,
            preview_digest=plan.preview_digest or "",
            now=now,
        ):
            return "approved"
    return "needs_review"


QUEUE_SECTIONS = (
    "ready_for_review",
    "needs_more_evidence",
    "awaiting_backup",
    "awaiting_approval",
    "approved",
    "ready_to_execute",
    "executing",
    "verification_required",
    "verified",
    "failed",
    "rejected",
    "snoozed",
    "expired",
    "rollback_available",
)


def _queue_section(
    recommendation: CanonicalRecommendation | None,
    plan: RemediationPlan | None,
    approval: ApprovalRecord | None,
    executions: tuple[ExecutionRecord, ...],
    rollbacks: tuple[RollbackRecord, ...],
    *,
    now: datetime,
) -> str:
    """``recommendation=None`` is how a batch-disable plan reaches this
    function -- it always has ``execution_supported=True`` (the cleanup
    classifier already verified every member entity), so the one branch
    below that would otherwise need ``recommendation.dependency_analysis``
    is unreachable for a batch plan and never evaluates it.
    """
    if plan is not None and plan.state is RemediationPlanState.SNOOZED:
        return "snoozed"
    if (
        recommendation is not None
        and recommendation.lifecycle_state is RecommendationLifecycleState.SNOOZED
    ):
        return "snoozed"
    if plan is not None and plan.state is RemediationPlanState.INVALIDATED:
        return "needs_more_evidence"
    if plan is not None and (
        plan.state is RemediationPlanState.EXPIRED
        or (plan.expires_at is not None and plan.expires_at <= now)
    ):
        return "expired"
    if plan is None:
        return "ready_for_review"
    if not plan.execution_supported:
        return (
            "needs_more_evidence"
            if recommendation is not None
            and recommendation.dependency_analysis.status.value != "complete"
            else "failed"
        )
    if plan.requires_backup:
        return "awaiting_backup"
    real_executions = _meaningful_executions(executions)
    if real_executions:
        outcome = real_executions[-1].outcome.value
        if outcome == "in_progress":
            return "executing"
        if outcome == "succeeded":
            return "verified"
        if outcome in {"failed", "partially_succeeded"}:
            return (
                "rollback_available"
                if plan.rollback_plan.supported and not rollbacks
                else "failed"
            )
    if approval is not None and approval.state.value == "rejected":
        return "rejected"
    if approval is not None and approval.is_valid_for(
        plan_fingerprint=plan.plan_fingerprint,
        preview_digest=plan.preview_digest or "",
        now=now,
    ):
        return "ready_to_execute"
    if plan.preview_digest:
        return "awaiting_approval"
    return "ready_for_review"


SNOOZE_ELIGIBLE_STATES = frozenset(
    {RemediationPlanState.DRAFT, RemediationPlanState.READY_FOR_REVIEW}
)


def _state_after_snooze(
    state: RepositoryState, plan: RemediationPlan, *, now: datetime
) -> RemediationPlanState:
    """Restore a snoozed plan only when its deterministic evidence is current."""
    if plan.expires_at is not None and plan.expires_at <= now:
        return RemediationPlanState.EXPIRED
    recommendation = _find_recommendation(state, plan.recommendation_id)
    if (
        recommendation is None
        or recommendation.lifecycle_state is not RecommendationLifecycleState.ACTIVE
    ):
        return RemediationPlanState.INVALIDATED
    current = plan_remediation(recommendation, now=now)
    if isinstance(current, PlanningRejection):
        return RemediationPlanState.INVALIDATED
    if current.plan_fingerprint != plan.plan_fingerprint:
        return RemediationPlanState.INVALIDATED
    return plan.snoozed_from_state or RemediationPlanState.READY_FOR_REVIEW


async def _expire_due_snoozes(
    repository: PersistenceUnitOfWorkPort, *, now: datetime
) -> None:
    """Resume elapsed Snoozes with audit evidence; never approve or execute."""
    initial = await repository.async_load()
    if not any(
        plan.state is RemediationPlanState.SNOOZED
        and plan.snooze_until is not None
        and plan.snooze_until <= now
        for plan in initial.remediation_plans
    ):
        return

    def _mutate(current: RepositoryState) -> RepositoryState:
        plans: list[RemediationPlan] = []
        audits = current.audits
        changed = False
        for plan in current.remediation_plans:
            if not (
                plan.state is RemediationPlanState.SNOOZED
                and plan.snooze_until is not None
                and plan.snooze_until <= now
            ):
                plans.append(plan)
                continue
            restored_state = _state_after_snooze(current, plan, now=now)
            restored = replace(plan, state=restored_state, updated_at=now)
            plans.append(restored)
            token = f"expiry:{plan.remediation_plan_id}:{plan.snooze_until.isoformat()}"
            audit = _audit(
                audit_events.PROPOSAL_SNOOZE_EXPIRED,
                "system:snooze_expiry",
                (plan.recommendation_id, plan.remediation_plan_id),
                (("restored_state", restored_state.value),),
                token=token,
                now=now,
            )
            audits = _append_audit(audits, audit)
            changed = True
        if not changed:
            return replace(current, generation=current.generation + 1)
        return replace(
            current,
            remediation_plans=tuple(plans),
            audits=audits,
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate)


async def async_list_queue(
    repository: PersistenceUnitOfWorkPort,
    *,
    category: str | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_QUEUE_LIMIT,
    now: datetime,
) -> QueueResult:
    """List queue rows, first restoring any elapsed proposal Snoozes."""
    await _expire_due_snoozes(repository, now=now)
    bounded_limit = max(1, min(limit, MAX_QUEUE_LIMIT))
    state = await repository.async_load()
    rows: list[QueueItem] = []
    section_counts = {section: 0 for section in QUEUE_SECTIONS}
    for recommendation in state.canonical_recommendations:
        if recommendation.lifecycle_state not in {
            RecommendationLifecycleState.ACTIVE,
            RecommendationLifecycleState.SNOOZED,
        }:
            continue
        plan = _find_latest_plan_for_recommendation(
            state, recommendation.recommendation_id
        )
        approval = (
            _latest_approval_for_plan(state, plan.remediation_plan_id) if plan else None
        )
        executions = (
            _executions_for_plan(state, plan.remediation_plan_id) if plan else ()
        )
        rollbacks = _rollbacks_for_executions(
            state, tuple(item.execution_id for item in executions)
        )
        row_status = _queue_status(
            recommendation, plan, approval, executions, rollbacks, now=now
        )
        row_section = _queue_section(
            recommendation, plan, approval, executions, rollbacks, now=now
        )
        if category is not None and recommendation.category != category:
            continue
        section_counts[row_section] += 1
        real_executions = _meaningful_executions(executions)
        if (
            plan is not None
            and plan.rollback_plan.supported
            and real_executions
            and real_executions[-1].outcome.value == "succeeded"
            and not rollbacks
        ):
            section_counts["rollback_available"] += 1
        if status is not None and row_status != status:
            continue
        rows.append(
            QueueItem(
                recommendation_id=recommendation.recommendation_id,
                title=recommendation.title,
                category=recommendation.category,
                subtype=recommendation.subtype,
                action_type=plan.actions[0].action_type if plan else None,
                execution_supported=plan.execution_supported if plan else True,
                unsupported_reason=plan.unsupported_reason if plan else None,
                confidence=recommendation.confidence.level.value,
                risk_level=recommendation.risk.risk.overall.value,
                affected_object=recommendation.affected_object.display_hint
                or recommendation.affected_object.source_id,
                dependency_status=recommendation.dependency_analysis.status.value,
                estimated_impact=(
                    plan.risk.expected_user_visible_impact
                    if plan
                    else "not yet planned"
                ),
                status=row_status,
                section=row_section,
                plan_id=plan.remediation_plan_id if plan else None,
                plan_fingerprint=plan.plan_fingerprint if plan else None,
                snooze_until=plan.snooze_until if plan else None,
                snooze_reason=plan.snooze_reason if plan else None,
                updated_at=(
                    (plan.updated_at or plan.created_at)
                    if plan
                    else recommendation.updated_at
                ),
            )
        )

    # Batch-disable plans (application/cleanup_coordinator.py's Clean Up
    # pipeline) are never driven by a CanonicalRecommendation at all --
    # see async_create_batch_disable_plan's own docstring -- so the loop
    # above, which only ever iterates state.canonical_recommendations,
    # structurally cannot see them. Without this second pass every batch
    # Clean Up proposes (the actual "Actionable proposals" / "Pending
    # approvals" a user expects to see after running Clean Up) is
    # invisible to the Review Queue no matter how many safe candidates
    # the classifier found -- confirmed as the real mechanism behind the
    # "509 findings, 0 actionable proposals" production symptom.
    canonical_ids = {item.recommendation_id for item in state.canonical_recommendations}
    for plan in state.remediation_plans:
        if not plan.actions or plan.actions[0].target.kind != "hamie.entity_batch":
            continue
        if plan.recommendation_id in canonical_ids:
            continue
        approval = _latest_approval_for_plan(state, plan.remediation_plan_id)
        executions = _executions_for_plan(state, plan.remediation_plan_id)
        rollbacks = _rollbacks_for_executions(
            state, tuple(item.execution_id for item in executions)
        )
        row_status = _queue_status(None, plan, approval, executions, rollbacks, now=now)
        row_section = _queue_section(
            None, plan, approval, executions, rollbacks, now=now
        )
        if category is not None and category != "cleanup_batch":
            continue
        section_counts[row_section] += 1
        real_executions = _meaningful_executions(executions)
        if (
            plan.rollback_plan.supported
            and real_executions
            and real_executions[-1].outcome.value == "succeeded"
            and not rollbacks
        ):
            section_counts["rollback_available"] += 1
        if status is not None and row_status != status:
            continue
        target = plan.actions[0].target
        rows.append(
            QueueItem(
                recommendation_id=plan.remediation_plan_id,
                title=target.display_hint or target.source_id,
                category="cleanup_batch",
                subtype=plan.actions[0].action_type,
                action_type=plan.actions[0].action_type,
                execution_supported=plan.execution_supported,
                unsupported_reason=plan.unsupported_reason,
                confidence=plan.risk.confidence.level.value,
                risk_level=plan.risk.risk.overall.value,
                affected_object=target.display_hint or target.source_id,
                dependency_status="complete",
                estimated_impact=plan.risk.expected_user_visible_impact,
                status=row_status,
                section=row_section,
                plan_id=plan.remediation_plan_id,
                plan_fingerprint=plan.plan_fingerprint,
                snooze_until=plan.snooze_until,
                snooze_reason=plan.snooze_reason,
                updated_at=plan.updated_at or plan.created_at,
            )
        )

    rows.sort(key=lambda item: item.updated_at, reverse=True)
    total = len(rows)
    page = tuple(rows[offset : offset + bounded_limit])
    return QueueResult(
        items=page,
        total=total,
        offset=offset,
        limit=bounded_limit,
        section_counts=tuple(section_counts.items()),
        maintenance_work_items=state.maintenance_work_items,
        last_cleanup_scan_id=state.last_cleanup_scan_id,
    )


@dataclass(frozen=True, slots=True)
class DetailResult:
    recommendation: CanonicalRecommendation
    plan: RemediationPlan | None
    approval: ApprovalRecord | None
    executions: tuple[ExecutionRecord, ...]
    rollbacks: tuple[RollbackRecord, ...]
    status: str


async def async_get_detail(
    repository: PersistenceUnitOfWorkPort, recommendation_id: str, *, now: datetime
) -> DetailResult:
    """Return current detail after restoring any elapsed proposal Snooze."""
    await _expire_due_snoozes(repository, now=now)
    state = await repository.async_load()
    recommendation = _find_recommendation(state, recommendation_id)
    if recommendation is None:
        raise RemediationServiceError(
            "remediation_not_found", "That recommendation could not be found."
        )
    plan = _find_latest_plan_for_recommendation(state, recommendation_id)
    approval = (
        _latest_approval_for_plan(state, plan.remediation_plan_id) if plan else None
    )
    executions = _executions_for_plan(state, plan.remediation_plan_id) if plan else ()
    rollbacks = _rollbacks_for_executions(
        state, tuple(item.execution_id for item in executions)
    )
    status = _queue_status(
        recommendation, plan, approval, executions, rollbacks, now=now
    )
    return DetailResult(
        recommendation=recommendation,
        plan=plan,
        approval=approval,
        executions=executions,
        rollbacks=rollbacks,
        status=status,
    )


async def _plan_from_llm_proposal(
    recommendation: CanonicalRecommendation, *, now: datetime, hass: object | None
) -> RemediationPlan | PlanningRejection | None:
    """Attempt the LLM-proposed planning path for one recommendation.

    Returns ``None`` when the recommendation carries no proposal at all
    (the ordinary case) -- distinct from a ``PlanningRejection``, which
    means a proposal was present but policy declined it. Callers must
    treat both ``None`` and a rejection the same way: fall back to the
    normal deterministic ``plan_remediation`` path without failing plan
    creation, per mission Phase 15 ("keep the underlying recommendation
    if valid, discard/reject the executable action").
    """
    proposal = recommendation.llm_proposed_action
    if proposal is None:
        return None
    port = (
        HassFileMutationPort(hass)
        if hass is not None
        else UnavailableFileMutationPort()
    )
    try:
        expected_before_hash = await resource_content_hash(port, proposal.resource_id)
    except FilePolicyError as err:
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code=f"llm_proposal_{err.code}",
            message=err.message,
        )
    return plan_llm_proposed_remediation(
        recommendation,
        proposal,
        expected_before_hash=expected_before_hash,
        now=now,
    )


async def async_create_plan(
    repository: PersistenceUnitOfWorkPort,
    recommendation_id: str,
    *,
    actor: str,
    idempotency_token: str,
    now: datetime,
    hass: object | None = None,
) -> RemediationPlan:
    """Create or refresh a deterministic plan for one recommendation.

    Never executes anything. Raises ``remediation_unsupported`` if the
    planner itself declines (see ``PlanningRejection``), never silently
    returning a partial or fabricated plan.

    If the recommendation carries a validated LLM-proposed action (see
    ``domain/llm_proposal.py``), that path is tried first
    (``plan_llm_proposed_remediation``); a policy rejection there falls
    back to the ordinary deterministic ``plan_remediation`` path rather
    than failing plan creation outright -- the underlying recommendation
    is never lost because its proposed action was invalid.
    """
    state = await repository.async_load()
    recommendation = _find_recommendation(state, recommendation_id)
    if recommendation is None:
        raise RemediationServiceError(
            "remediation_not_found", "That recommendation could not be found."
        )
    proposal_outcome = await _plan_from_llm_proposal(recommendation, now=now, hass=hass)
    proposal_rejection: PlanningRejection | None = None
    if isinstance(proposal_outcome, RemediationPlan):
        plan = proposal_outcome
    else:
        if isinstance(proposal_outcome, PlanningRejection):
            proposal_rejection = proposal_outcome
        outcome = plan_remediation(recommendation, now=now)
        if isinstance(outcome, PlanningRejection):
            raise RemediationServiceError("remediation_unsupported", outcome.message)
        plan = outcome

    def _mutate(current: RepositoryState) -> RepositoryState:
        existing = _find_plan(current, plan.remediation_plan_id)
        if existing is not None:
            # Identical deterministic plan already persisted -- nothing
            # to add, but still safe/idempotent to "recreate".
            plans = current.remediation_plans
        else:
            plans = (*current.remediation_plans, plan)
        audits = current.audits
        if proposal_rejection is not None:
            audits = _append_audit(
                audits,
                _audit(
                    audit_events.LLM_PROPOSAL_REJECTED,
                    actor,
                    (recommendation_id,),
                    (
                        ("reason_code", proposal_rejection.reason_code),
                        ("message", proposal_rejection.message[:200]),
                    ),
                    token=f"{idempotency_token}:llm_proposal_rejected",
                    now=now,
                ),
            )
        elif plan.actions and plan.actions[0].adapter_id == "file_mutation_adapter":
            audits = _append_audit(
                audits,
                _audit(
                    audit_events.LLM_PROPOSAL_ACCEPTED,
                    actor,
                    (recommendation_id, plan.remediation_plan_id),
                    (),
                    token=f"{idempotency_token}:llm_proposal_accepted",
                    now=now,
                ),
            )
        audit = _audit(
            audit_events.PLAN_CREATED,
            actor,
            (recommendation_id, plan.remediation_plan_id),
            (("plan_fingerprint", plan.plan_fingerprint[:16]),),
            token=idempotency_token,
            now=now,
        )
        return replace(
            current,
            remediation_plans=plans,
            audits=_append_audit(audits, audit),
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate)
    return plan


async def async_create_batch_disable_plan(
    repository: PersistenceUnitOfWorkPort,
    entity_ids: tuple[str, ...],
    *,
    actor: str,
    idempotency_token: str,
    now: datetime,
    hass: object,
    batch_label: str = "cleanup batch",
    installation_id: str = "hamie",
) -> RemediationPlan:
    """Create a deterministic batch-disable plan for a set of entity ids.

    The batch-cleanup counterpart to ``async_create_plan`` -- not driven
    by a ``CanonicalRecommendation`` at all (its candidates come from
    ``application/cleanup_coordinator.py``'s classification pass, already
    filtered to safe entities). Computes the live fingerprint via
    ``compute_batch_fingerprint`` (I/O, application layer) then delegates
    to ``plan_batch_disable_remediation`` (pure, domain layer).
    """
    from .batch_entity_adapter import compute_batch_fingerprint

    expected_before_digest = await compute_batch_fingerprint(hass, entity_ids)
    outcome = plan_batch_disable_remediation(
        entity_ids=entity_ids,
        expected_before_digest=expected_before_digest,
        installation_id=installation_id,
        now=now,
        batch_label=batch_label,
    )
    if isinstance(outcome, PlanningRejection):
        raise RemediationServiceError("remediation_unsupported", outcome.message)
    plan = outcome

    def _mutate(current: RepositoryState) -> RepositoryState:
        existing = _find_plan(current, plan.remediation_plan_id)
        plans = (
            current.remediation_plans
            if existing is not None
            else (
                *current.remediation_plans,
                plan,
            )
        )
        audit = _audit(
            audit_events.PLAN_CREATED,
            actor,
            (batch_label, plan.remediation_plan_id),
            (
                ("plan_fingerprint", plan.plan_fingerprint[:16]),
                ("entity_count", str(len(entity_ids))),
            ),
            token=idempotency_token,
            now=now,
        )
        return replace(
            current,
            remediation_plans=plans,
            audits=_append_audit(current.audits, audit),
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate)
    return plan


async def async_snooze_plan(
    repository: PersistenceUnitOfWorkPort,
    remediation_plan_id: str,
    *,
    actor: str,
    snooze_until: datetime,
    reason: str | None,
    idempotency_token: str,
    now: datetime,
) -> RemediationPlan:
    """Snooze one reviewable proposal without approving or executing it."""
    if snooze_until.utcoffset() is None:
        raise RemediationServiceError(
            "remediation_snooze_invalid", "The Snooze time must include a timezone."
        )
    if snooze_until <= now or snooze_until > now + timedelta(days=30):
        raise RemediationServiceError(
            "remediation_snooze_invalid",
            "Choose a Snooze time after now and no more than 30 days away.",
        )
    state = await repository.async_load()
    plan = _find_plan(state, remediation_plan_id)
    if plan is None:
        raise RemediationServiceError(
            "remediation_not_found", "That remediation plan could not be found."
        )
    audit = _audit(
        audit_events.PROPOSAL_SNOOZED,
        actor,
        (plan.recommendation_id, plan.remediation_plan_id),
        (
            ("snooze_until", snooze_until.isoformat()),
            ("reason", (reason or "")[:200]),
            ("prior_state", plan.state.value),
        ),
        token=idempotency_token,
        now=now,
    )
    if any(item.audit_id == audit.audit_id for item in state.audits):
        return plan
    if plan.state not in SNOOZE_ELIGIBLE_STATES:
        raise RemediationServiceError(
            "remediation_snooze_invalid",
            "Only a proposal awaiting review, evidence, backup, or approval "
            "can be snoozed.",
        )
    if _executions_for_plan(state, remediation_plan_id):
        raise RemediationServiceError(
            "remediation_snooze_invalid",
            "A proposal with execution history cannot be snoozed.",
        )
    if any(
        item.remediation_plan_id == remediation_plan_id and item.released_at is None
        for item in state.remediation_locks
    ):
        raise RemediationServiceError(
            "remediation_snooze_invalid",
            "This proposal has a running operation and cannot be snoozed.",
        )
    snoozed = replace(
        plan,
        state=RemediationPlanState.SNOOZED,
        updated_at=now,
        snoozed_at=now,
        snoozed_by=actor,
        snooze_until=snooze_until,
        snooze_reason=reason or None,
        snoozed_from_state=plan.state,
    )

    def _mutate(current: RepositoryState) -> RepositoryState:
        duplicate = any(item.audit_id == audit.audit_id for item in current.audits)
        plans = current.remediation_plans
        audits = current.audits
        if not duplicate:
            plans = tuple(
                snoozed if item.remediation_plan_id == remediation_plan_id else item
                for item in current.remediation_plans
            )
            audits = _append_audit(audits, audit)
        return replace(
            current,
            remediation_plans=plans,
            audits=audits,
            generation=current.generation + 1,
        )

    committed = await _commit_with_retry(repository, _mutate)
    return _find_plan(committed, remediation_plan_id) or snoozed


async def async_resume_plan(
    repository: PersistenceUnitOfWorkPort,
    remediation_plan_id: str,
    *,
    actor: str,
    idempotency_token: str,
    now: datetime,
) -> RemediationPlan:
    """Resume one Snooze without restoring or creating approval authority."""
    state = await repository.async_load()
    plan = _find_plan(state, remediation_plan_id)
    if plan is None:
        raise RemediationServiceError(
            "remediation_not_found", "That remediation plan could not be found."
        )
    audit = _audit(
        audit_events.PROPOSAL_RESUMED,
        actor,
        (plan.recommendation_id, plan.remediation_plan_id),
        (),
        token=idempotency_token,
        now=now,
    )
    if any(item.audit_id == audit.audit_id for item in state.audits):
        return plan
    if plan.state is not RemediationPlanState.SNOOZED:
        raise RemediationServiceError(
            "remediation_snooze_invalid", "Only a snoozed proposal can be resumed."
        )
    restored_state = _state_after_snooze(state, plan, now=now)
    resumed = replace(plan, state=restored_state, updated_at=now)
    audit = _audit(
        audit_events.PROPOSAL_RESUMED,
        actor,
        (plan.recommendation_id, plan.remediation_plan_id),
        (("restored_state", restored_state.value),),
        token=idempotency_token,
        now=now,
    )

    def _mutate(current: RepositoryState) -> RepositoryState:
        duplicate = any(item.audit_id == audit.audit_id for item in current.audits)
        plans = current.remediation_plans
        audits = current.audits
        if not duplicate:
            plans = tuple(
                resumed if item.remediation_plan_id == remediation_plan_id else item
                for item in current.remediation_plans
            )
            audits = _append_audit(audits, audit)
        return replace(
            current,
            remediation_plans=plans,
            audits=audits,
            generation=current.generation + 1,
        )

    committed = await _commit_with_retry(repository, _mutate)
    return _find_plan(committed, remediation_plan_id) or resumed


async def async_generate_preview(
    repository: PersistenceUnitOfWorkPort,
    remediation_plan_id: str,
    *,
    actor: str,
    idempotency_token: str,
    now: datetime,
    hass: object | None = None,
) -> PreviewRunResult:
    """Render a plan's preview. Never mutates Home Assistant."""
    state = await repository.async_load()
    plan = _find_plan(state, remediation_plan_id)
    if plan is None:
        raise RemediationServiceError(
            "remediation_not_found", "That remediation plan could not be found."
        )
    try:
        preview = await async_run_preview(
            plan,
            adapters=production_adapters(hass),
            now=now,
            execution_id=f"preview_{idempotency_token}",
        )
    except PreviewMismatchError as err:
        raise RemediationServiceError("remediation_plan_stale", str(err)) from err
    except KeyError as err:
        raise RemediationServiceError(
            "remediation_unsupported",
            "No adapter is registered for this plan's action.",
        ) from err

    def _mutate(current: RepositoryState) -> RepositoryState:
        audit = _audit(
            audit_events.PREVIEW_GENERATED,
            actor,
            (plan.recommendation_id, plan.remediation_plan_id),
            (("preview_digest", preview.preview_digest[:16]),),
            token=idempotency_token,
            now=now,
        )
        return replace(
            current,
            audits=_append_audit(current.audits, audit),
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate)
    return preview


async def _recompute_current_plan_for_staleness_check(
    state: RepositoryState, plan: RemediationPlan, *, now: datetime, hass: object | None
) -> RemediationPlan | PlanningRejection | None:
    """Recompute what planning this exact plan's inputs would produce today.

    Three plan sources exist, and each needs its own re-derivation path
    -- using only ``plan_remediation`` here would wrongly declare an
    LLM-proposed or batch-disable plan stale on every approval attempt,
    since neither is what plain ``plan_remediation`` would ever produce
    for the same recommendation:

    - A plan with no resolvable ``CanonicalRecommendation`` (batch-disable
      plans use a synthetic ``recommendation_id`` label, never a real
      recommendation) has nothing to re-derive against; the persisted
      plan's own immutability plus the exact fingerprint/preview-digest
      match already checked by the caller is the only staleness
      guarantee that applies, so this returns ``None`` and the caller's
      fingerprint/preview check alone governs.
    - A plan built from an LLM-proposed action is re-verified via
      ``_plan_from_llm_proposal`` first, mirroring exactly what
      ``async_create_plan`` tried at creation time.
    - Every other plan is re-verified via the ordinary ``plan_remediation``
      path, as before.
    """
    current_recommendation = _find_recommendation(state, plan.recommendation_id)
    if current_recommendation is None:
        return None
    proposal_outcome = await _plan_from_llm_proposal(
        current_recommendation, now=now, hass=hass
    )
    if proposal_outcome is not None:
        return proposal_outcome
    return plan_remediation(current_recommendation, now=now)


async def async_approve_plan(
    repository: PersistenceUnitOfWorkPort,
    remediation_plan_id: str,
    *,
    plan_fingerprint: str,
    preview_digest: str,
    actor: str,
    destructive_acknowledged: bool,
    backup_acknowledged: bool,
    warnings_acknowledged: tuple[str, ...],
    idempotency_token: str,
    now: datetime,
    hass: object | None = None,
) -> ApprovalRecord:
    """Grant approval bound to the exact plan fingerprint and preview digest.

    The client-supplied ``plan_fingerprint``/``preview_digest`` are never
    trusted for the binding itself -- they are only what the client
    claims it is looking at. The approval is always created against the
    server's own current persisted plan; if the client's copy has
    drifted (stale plan or stale preview), this raises rather than
    silently approving something the human never actually reviewed.
    """
    state = await repository.async_load()
    plan = _find_plan(state, remediation_plan_id)
    if plan is None:
        raise RemediationServiceError(
            "remediation_not_found", "That remediation plan could not be found."
        )
    if plan.state in {
        RemediationPlanState.SNOOZED,
        RemediationPlanState.INVALIDATED,
    }:
        raise RemediationServiceError(
            "remediation_plan_stale",
            "Resume and refresh this proposal before approval.",
        )
    if not plan.execution_supported:
        raise RemediationServiceError(
            "remediation_unsupported",
            plan.unsupported_reason or "This action is not supported.",
        )
    current_plan = await _recompute_current_plan_for_staleness_check(
        state, plan, now=now, hass=hass
    )
    if current_plan is not None and (
        isinstance(current_plan, PlanningRejection)
        or current_plan.plan_fingerprint != plan.plan_fingerprint
    ):
        raise RemediationServiceError(
            "remediation_plan_stale",
            "The proposal evidence changed. Refresh the proposal before approval.",
        )
    if plan.plan_fingerprint != plan_fingerprint:
        raise RemediationServiceError(
            "remediation_plan_stale",
            "This plan has changed since it was last reviewed. Refresh and try again.",
        )
    if plan.preview_digest is None or plan.preview_digest != preview_digest:
        raise RemediationServiceError(
            "remediation_preview_stale",
            "Generate a fresh preview before approving.",
        )
    if plan.expires_at is not None and now >= plan.expires_at:
        raise RemediationServiceError(
            "remediation_plan_stale", "This plan has expired. Create a new one."
        )
    if plan.risk.destructive and not destructive_acknowledged:
        raise RemediationServiceError(
            "remediation_approval_invalid",
            "Destructive actions require explicit acknowledgement.",
        )
    if plan.requires_backup:
        backup_provider = production_backup_provider()
        if not await backup_provider.async_available():
            raise RemediationServiceError(
                "remediation_backup_unavailable",
                "A supported backup provider must be configured before this "
                "proposal can be approved.",
            )
        if not backup_acknowledged:
            raise RemediationServiceError(
                "remediation_approval_invalid",
                "This action requires backup acknowledgement.",
            )

    approval = ApprovalRecord(
        approval_id=(
            f"appr_{stable_digest(remediation_plan_id, idempotency_token)[:24]}"
        ),
        remediation_plan_id=plan.remediation_plan_id,
        plan_fingerprint=plan.plan_fingerprint,
        preview_digest=plan.preview_digest,
        recommendation_id=plan.recommendation_id,
        recommendation_revision=plan.recommendation_revision,
        installation_id=plan.installation_id,
        approved_by=actor,
        decided_at=now,
        state=ApprovalState.GRANTED,
        expires_at=now + DEFAULT_APPROVAL_LEASE,
        scope=ApprovalScope.SINGLE,
        destructive_acknowledged=destructive_acknowledged,
        backup_acknowledged=backup_acknowledged,
        warnings_acknowledged=warnings_acknowledged,
    )
    approved_plan = replace(plan, state=RemediationPlanState.APPROVED, updated_at=now)

    def _mutate(current: RepositoryState) -> RepositoryState:
        existing = _find_approval(current, approval.approval_id)
        approvals = (
            current.remediation_approvals
            if existing is not None
            else (
                *current.remediation_approvals,
                approval,
            )
        )
        plans = tuple(
            approved_plan
            if item.remediation_plan_id == plan.remediation_plan_id
            else item
            for item in current.remediation_plans
        )
        audit = _audit(
            audit_events.APPROVAL_GRANTED,
            actor,
            (plan.recommendation_id, plan.remediation_plan_id, approval.approval_id),
            (("plan_fingerprint", plan.plan_fingerprint[:16]),),
            token=idempotency_token,
            now=now,
        )
        return replace(
            current,
            remediation_approvals=approvals,
            remediation_plans=plans,
            audits=_append_audit(current.audits, audit),
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate)
    return approval


async def async_reject_plan(
    repository: PersistenceUnitOfWorkPort,
    remediation_plan_id: str,
    *,
    actor: str,
    reason: str,
    idempotency_token: str,
    now: datetime,
) -> ApprovalRecord:
    """Record an explicit rejection. Never deletes historical evidence."""
    state = await repository.async_load()
    plan = _find_plan(state, remediation_plan_id)
    if plan is None:
        raise RemediationServiceError(
            "remediation_not_found", "That remediation plan could not be found."
        )
    approval = ApprovalRecord(
        approval_id=(
            f"appr_{stable_digest(remediation_plan_id, idempotency_token)[:24]}"
        ),
        remediation_plan_id=plan.remediation_plan_id,
        plan_fingerprint=plan.plan_fingerprint,
        preview_digest=plan.preview_digest or "not_previewed",
        recommendation_id=plan.recommendation_id,
        recommendation_revision=plan.recommendation_revision,
        installation_id=plan.installation_id,
        approved_by=actor,
        decided_at=now,
        state=ApprovalState.REJECTED,
        rejection_reason=reason,
    )
    rejected_plan = replace(plan, state=RemediationPlanState.REJECTED, updated_at=now)

    def _mutate(current: RepositoryState) -> RepositoryState:
        existing = _find_approval(current, approval.approval_id)
        approvals = (
            current.remediation_approvals
            if existing is not None
            else (
                *current.remediation_approvals,
                approval,
            )
        )
        plans = tuple(
            rejected_plan
            if item.remediation_plan_id == plan.remediation_plan_id
            else item
            for item in current.remediation_plans
        )
        audit = _audit(
            audit_events.APPROVAL_REJECTED,
            actor,
            (plan.recommendation_id, plan.remediation_plan_id, approval.approval_id),
            (("reason", reason[:200]),),
            token=idempotency_token,
            now=now,
        )
        return replace(
            current,
            remediation_approvals=approvals,
            remediation_plans=plans,
            audits=_append_audit(current.audits, audit),
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate)
    return approval


async def async_revoke_approval(
    repository: PersistenceUnitOfWorkPort,
    approval_id: str,
    *,
    actor: str,
    reason: str,
    idempotency_token: str,
    now: datetime,
) -> ApprovalRecord:
    """Revoke a previously granted approval. Preserves original evidence."""
    state = await repository.async_load()
    approval = _find_approval(state, approval_id)
    if approval is None:
        raise RemediationServiceError(
            "remediation_approval_missing", "That approval could not be found."
        )
    if approval.state is not ApprovalState.GRANTED or approval.is_revoked:
        raise RemediationServiceError(
            "remediation_approval_invalid",
            "Only a currently granted approval can be revoked.",
        )
    revoked = revoke_approval(approval, revoked_by=actor, reason=reason, now=now)
    plan = _find_plan(state, approval.remediation_plan_id)

    def _mutate(current: RepositoryState) -> RepositoryState:
        approvals = tuple(
            revoked if item.approval_id == approval_id else item
            for item in current.remediation_approvals
        )
        plans = current.remediation_plans
        if plan is not None:
            reverted = replace(
                plan, state=RemediationPlanState.READY_FOR_REVIEW, updated_at=now
            )
            target_id = plan.remediation_plan_id
            plans = tuple(
                reverted if item.remediation_plan_id == target_id else item
                for item in current.remediation_plans
            )
        audit = _audit(
            audit_events.APPROVAL_REVOKED,
            actor,
            (approval.recommendation_id, approval.remediation_plan_id, approval_id),
            (("reason", reason[:200]),),
            token=idempotency_token,
            now=now,
        )
        return replace(
            current,
            remediation_approvals=approvals,
            remediation_plans=plans,
            audits=_append_audit(current.audits, audit),
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate)
    return revoked


async def async_execute_plan(
    repository: PersistenceUnitOfWorkPort,
    remediation_plan_id: str,
    *,
    approval_id: str,
    actor: str,
    idempotency_token: str,
    now: datetime,
    hass: object | None = None,
) -> ExecutionRecord:
    """Execute one approved plan through the canonical coordinator only.

    Never exposes an adapter directly, never accepts client-supplied
    execution steps, and never reports success before the coordinator's
    own independent post-action verification has run -- this function
    is a pass-through to ``coordinator.async_execute_plan``, nothing more.
    """
    state = await repository.async_load()
    plan = _find_plan(state, remediation_plan_id)
    if plan is None:
        raise RemediationServiceError(
            "remediation_not_found", "That remediation plan could not be found."
        )
    approval = _find_approval(state, approval_id)
    if approval is None:
        raise RemediationServiceError(
            "remediation_approval_missing", "That approval could not be found."
        )

    # Deliberately *not* derived from idempotency_token: the coordinator
    # requires a fresh execution_id on every physical call, including a
    # retried one -- its own replay-blocked path still persists a
    # (blocked) ExecutionRecord, and RepositoryState requires every
    # execution_id to be globally unique. Replay protection itself is
    # what idempotency_token is for; the audit layer below separately
    # dedups by token so a retry never produces a duplicate audit event.
    execution_id = f"exec_{uuid4().hex[:24]}"

    def _mutate_requested(current: RepositoryState) -> RepositoryState:
        audit = _audit(
            audit_events.EXECUTION_STARTED,
            actor,
            (
                plan.recommendation_id,
                plan.remediation_plan_id,
                approval_id,
                execution_id,
            ),
            (),
            token=idempotency_token,
            now=now,
        )
        return replace(
            current,
            audits=_append_audit(current.audits, audit),
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate_requested)

    execution = await _coordinator_execute(
        repository,
        remediation_plan_id=remediation_plan_id,
        approval_id=approval_id,
        execution_id=execution_id,
        idempotency_token=idempotency_token,
        started_by=actor,
        adapters=production_adapters(hass),
        backup_provider=production_backup_provider(),
        now=now,
    )

    outcome_event = {
        "succeeded": audit_events.EXECUTION_SUCCEEDED,
        "partially_succeeded": audit_events.EXECUTION_PARTIALLY_SUCCEEDED,
        "failed": audit_events.EXECUTION_FAILED,
        "rolled_back": audit_events.ROLLBACK_SUCCEEDED,
        "rollback_failed": audit_events.ROLLBACK_FAILED,
    }.get(execution.outcome.value, audit_events.EXECUTION_FAILED)

    def _mutate_outcome(current: RepositoryState) -> RepositoryState:
        audit = _audit(
            outcome_event,
            actor,
            (plan.recommendation_id, plan.remediation_plan_id, execution_id),
            (("outcome", execution.outcome.value),),
            token=f"{idempotency_token}:outcome",
            now=now,
        )
        return replace(
            current,
            audits=_append_audit(current.audits, audit),
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate_outcome)
    return execution


async def async_rollback_execution(
    repository: PersistenceUnitOfWorkPort,
    remediation_plan_id: str,
    *,
    execution_id: str,
    actor: str,
    idempotency_token: str,
    now: datetime,
    hass: object | None = None,
) -> RollbackRecord:
    """Rollback one verified reversible execution through the coordinator."""
    state = await repository.async_load()
    plan = _find_plan(state, remediation_plan_id)
    execution = next(
        (
            item
            for item in state.remediation_executions
            if item.execution_id == execution_id
            and item.remediation_plan_id == remediation_plan_id
        ),
        None,
    )
    if plan is None or execution is None:
        raise RemediationServiceError(
            "remediation_not_found", "That verified execution could not be found."
        )
    rollback_id = f"rb_{uuid4().hex[:24]}"

    def _mutate_started(current: RepositoryState) -> RepositoryState:
        audit = _audit(
            audit_events.ROLLBACK_STARTED,
            actor,
            (
                plan.recommendation_id,
                plan.remediation_plan_id,
                execution.execution_id,
                rollback_id,
            ),
            (),
            token=idempotency_token,
            now=now,
        )
        return replace(
            current,
            audits=_append_audit(current.audits, audit),
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate_started)
    try:
        rollback = await _coordinator_rollback(
            repository,
            remediation_plan_id=remediation_plan_id,
            execution_id=execution_id,
            rollback_id=rollback_id,
            idempotency_token=idempotency_token,
            initiated_by=actor,
            adapters=production_adapters(hass),
            now=now,
        )
    except RollbackRejectedError as err:

        def _mutate_rejected(current: RepositoryState) -> RepositoryState:
            audit = _audit(
                audit_events.ROLLBACK_FAILED,
                actor,
                (
                    plan.recommendation_id,
                    plan.remediation_plan_id,
                    execution.execution_id,
                    rollback_id,
                ),
                (("outcome", "rejected"),),
                token=f"{idempotency_token}:outcome",
                now=now,
            )
            return replace(
                current,
                audits=_append_audit(current.audits, audit),
                generation=current.generation + 1,
            )

        await _commit_with_retry(repository, _mutate_rejected)
        raise RemediationServiceError(
            "remediation_rollback_unavailable",
            f"This repair cannot be rolled back: {err}.",
        ) from err

    outcome_event = (
        audit_events.ROLLBACK_SUCCEEDED
        if rollback.outcome.value == "succeeded"
        else audit_events.ROLLBACK_FAILED
    )

    def _mutate_outcome(current: RepositoryState) -> RepositoryState:
        audit = _audit(
            outcome_event,
            actor,
            (
                plan.recommendation_id,
                plan.remediation_plan_id,
                execution.execution_id,
                rollback.rollback_id,
            ),
            (("outcome", rollback.outcome.value),),
            token=f"{idempotency_token}:outcome",
            now=now,
        )
        return replace(
            current,
            audits=_append_audit(current.audits, audit),
            generation=current.generation + 1,
        )

    await _commit_with_retry(repository, _mutate_outcome)
    return rollback


@dataclass(frozen=True, slots=True)
class ExecutionStatusResult:
    executions: tuple[ExecutionRecord, ...]
    rollbacks: tuple[RollbackRecord, ...]


async def async_get_execution_status(
    repository: PersistenceUnitOfWorkPort, remediation_plan_id: str
) -> ExecutionStatusResult:
    """Return persisted execution/rollback evidence. Read-only."""
    state = await repository.async_load()
    plan = _find_plan(state, remediation_plan_id)
    if plan is None:
        raise RemediationServiceError(
            "remediation_not_found", "That remediation plan could not be found."
        )
    executions = _executions_for_plan(state, remediation_plan_id)
    rollbacks = _rollbacks_for_executions(
        state, tuple(item.execution_id for item in executions)
    )
    return ExecutionStatusResult(executions=executions, rollbacks=rollbacks)


def get_capabilities() -> dict[str, object]:
    """Return a static, read-only capability summary. No secrets, no paths.

    "Supported" is never taken from catalog metadata alone -- an entry
    is only reported as supported if its ``adapter_id`` is also present
    in the real ``production_adapters()`` registry. This is what keeps
    the test-only ``fixture_test_adapter`` action out of the reported
    capability surface even though the catalog entry itself is marked
    ``execution_supported``.
    """
    from ...domain.remediation_catalog import ACTION_CATALOG

    available_adapters = production_adapters()
    supported = sorted(
        entry.action_type
        for entry in ACTION_CATALOG.values()
        if entry.execution_supported and entry.adapter_id in available_adapters
    )
    unsupported = sorted(
        (
            {
                "action_type": entry.action_type,
                "reason": (
                    entry.unsupported_reason
                    or "No production adapter is registered for this action."
                ),
            }
            for entry in ACTION_CATALOG.values()
            if not (
                entry.execution_supported and entry.adapter_id in available_adapters
            )
        ),
        key=lambda item: item["action_type"],
    )
    return {
        "supported_actions": supported,
        "unsupported_actions": unsupported,
        "backup_provider_available": False,
        "execution_available": True,
        "batch_execution_available": False,
        "known_limitations": (
            "No real backup provider is configured; any action requiring "
            "backup can never execute.",
            "Audit events are best-effort and may not cover every internal step.",
            "Execution is not resumable across a mid-execution process "
            "restart (it fails safe, but does not resume).",
        ),
    }
