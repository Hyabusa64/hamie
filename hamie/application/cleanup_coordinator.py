"""Central cleanup orchestrator.

The canonical, single pipeline: obtain current open findings -> build
real dependency evidence -> classify every unavailable-entity candidate
-> group safe candidates into deterministic batch proposals -> persist
them into Review Queue -> apply AI operating-mode policy (auto-approve
and auto-execute eligible ``safe_auto_fix`` batches; leave every other
classification for human review) -> return one summary.

This is the *only* place that wires the cleanup classifier
(``domain/cleanup_classifier.py``), the dependency reference scanner
(``infrastructure/dependency_source.py``), and the batch entity-disable
capability (``application/remediation/batch_entity_adapter.py``)
together. Frontend, AI, and Review Queue all reach cleanup through this
one path -- there is no second, duplicate cleanup pipeline.

Deliberately conservative about what it does *not* do: it never
triggers a full Home Assistant re-scan itself (HAMIE's own scan
pipeline is a separate, heavier subsystem the user or scheduler
triggers independently; the next scan naturally reconciles findings for
now-disabled entities, since a disabled entity is excluded by the
analyzer's own policy unless ``include_disabled_entities`` is set), and
it never classifies or acts on anything beyond the
``hamie.unavailable_entities`` analyzer's findings this release.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from ..domain.ai_control import AiOperatingMode, is_risk_class_auto_executable
from ..domain.cleanup_classifier import (
    CleanupCandidate,
    CleanupClassification,
    CleanupPolicy,
    EntityAvailabilitySignal,
    classify_cleanup_candidate,
    compute_parent_unavailable_ratios,
)
from ..domain.common import stable_digest
from ..domain.dependency_references import DependencyScanCoverage, build_reference_index
from ..domain.entity_batch import MAX_BATCH_ENTITIES
from ..domain.findings import FindingLifecycle, RiskLevel
from ..domain.maintenance_work_items import (
    MaintenanceWorkItem,
    group_into_maintenance_work_items,
)
from ..domain.maintenance_work_record import (
    DECISION_LIFECYCLE,
    MaintenanceDecision,
    MaintenanceWorkRecord,
    build_maintenance_work_record,
    merge_maintenance_work_records,
)
from ..domain.remediation import RemediationPlan
from ..infrastructure.dependency_source import capture_all_reference_sources
from ..infrastructure.ha_source import HomeAssistantOperationalSource
from . import ai_control_service
from .persistence import GenerationConflictError, PersistenceUnitOfWorkPort
from .remediation import service as remediation_service

CLEANUP_ANALYZER_ID = "hamie.unavailable_entities"
CLEANUP_ACTOR = "hamie.cleanup_coordinator"
MAX_WORK_ITEM_COMMIT_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class CleanupBatchOutcome:
    """The result of proposing (and possibly auto-executing) one batch."""

    batch_label: str
    entity_ids: tuple[str, ...]
    plan: RemediationPlan | None
    auto_executed: bool
    execution_succeeded: bool | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CleanupSummary:
    """The complete, decision-ready result of one cleanup pass."""

    total_findings_considered: int
    classification_counts: dict[str, int]
    non_actionable_reason_counts: dict[str, int]
    maintenance_work_items: tuple[MaintenanceWorkItem, ...]
    persisted_maintenance_work_items: tuple[MaintenanceWorkRecord, ...]
    safe_auto_fix_entity_ids: tuple[str, ...]
    safe_with_approval_entity_ids: tuple[str, ...]
    batches: tuple[CleanupBatchOutcome, ...]
    configured_ai_mode: str
    effective_ai_mode: str
    dependency_scanned_sources: tuple[str, ...]
    dependency_unscanned_sources: tuple[str, ...]

    @property
    def actionable_candidate_count(self) -> int:
        return len(self.safe_auto_fix_entity_ids) + len(
            self.safe_with_approval_entity_ids
        )

    @property
    def entities_auto_disabled(self) -> int:
        return sum(
            len(batch.entity_ids)
            for batch in self.batches
            if batch.auto_executed and batch.execution_succeeded
        )


def _csv_option(value: Any) -> tuple[str, ...]:
    if isinstance(value, list | tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return ()


def cleanup_policy_from_options(options: dict[str, Any]) -> CleanupPolicy:
    """Build a ``CleanupPolicy`` from stored config-entry options.

    Mirrors ``operations_service.py``'s own ``self._options.get(key,
    default)`` convention: an entry that predates the ``ai_control``
    section simply lacks these keys, so every default here matches the
    field's declared default in ``configuration.py`` exactly.
    """
    # float(), not int(): the shortest configurable option is "0.5" (12
    # hours) -- a fractional-day choice, not a bug.
    duration_days = float(options.get("minimum_unavailable_duration_days", "5"))
    return CleanupPolicy(
        minimum_unavailable_duration_seconds=int(duration_days * 86_400),
        minimum_confidence=options.get("minimum_ai_confidence", "medium"),
        dependency_coverage_requirement=options.get(
            "dependency_coverage_requirement", "complete"
        ),
        excluded_integrations=frozenset(
            _csv_option(options.get("cleanup_exclude_integrations", ""))
        ),
        excluded_devices=frozenset(
            _csv_option(options.get("cleanup_exclude_devices", ""))
        ),
        excluded_entity_domains=frozenset(
            _csv_option(options.get("cleanup_exclude_entity_domains", ""))
        ),
        excluded_entity_ids=frozenset(
            _csv_option(options.get("cleanup_exclude_entity_ids", ""))
        ),
        excluded_areas=frozenset(_csv_option(options.get("cleanup_exclude_areas", ""))),
    )


def _unavailable_seconds(finding: Any) -> int | None:
    for item in finding.evidence:
        if item.predicate == "hamie.entity.unavailable_seconds@1":
            value = item.value
            if isinstance(value, bool):
                return None
            if isinstance(value, int | float):
                return int(value)
    return None


def _chunk(values: tuple[str, ...], size: int) -> list[tuple[str, ...]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def _parent_ratio_signals(
    entity_by_id: dict[str, Any],
) -> tuple[EntityAvailabilitySignal, ...]:
    """Build one availability signal per *live* entity (not just findings).

    The device-outage ratio must reflect a device's entire entity
    population -- see ``EntityAvailabilitySignal``'s docstring -- so
    this reads every entity Home Assistant currently reports, not the
    (already-unavailable-by-construction) subset that becomes a
    ``CleanupCandidate``.
    """
    return tuple(
        EntityAvailabilitySignal(
            entity_id=record.entity_id,
            device_id=record.device_id,
            entity_category=record.entity_category,
            is_unavailable=record.state == "unavailable",
        )
        for record in entity_by_id.values()
    )


def _build_candidates(
    findings: tuple[Any, ...],
    entity_by_id: dict[str, Any],
    coverage: DependencyScanCoverage,
    reference_index: Any,
) -> list[CleanupCandidate]:
    prelim: list[CleanupCandidate] = []
    for finding in findings:
        entity_id = finding.subject.source_id
        record = entity_by_id.get(entity_id)
        if record is None:
            # The entity no longer exists in Home Assistant at all --
            # nothing to disable; treated as already_clean rather than
            # guessed at.
            prelim.append(
                CleanupCandidate(
                    entity_id=entity_id,
                    domain=entity_id.split(".")[0] if "." in entity_id else "unknown",
                    entity_category=None,
                    already_disabled=False,
                    unavailable_seconds=None,
                    dependency_coverage=coverage,
                    referenced_by_count=0,
                )
            )
            continue
        unavailable_seconds = (
            _unavailable_seconds(finding) if record.state == "unavailable" else None
        )
        prelim.append(
            CleanupCandidate(
                entity_id=entity_id,
                domain=record.domain,
                entity_category=record.entity_category,
                already_disabled=bool(record.disabled),
                unavailable_seconds=unavailable_seconds,
                dependency_coverage=coverage,
                referenced_by_count=len(reference_index.referenced_by(entity_id)),
                integration=record.platform,
                device_id=record.device_id,
            )
        )

    ratios = compute_parent_unavailable_ratios(_parent_ratio_signals(entity_by_id))
    final: list[CleanupCandidate] = []
    for candidate in prelim:
        ratio: float | None = None
        sibling_count = 0
        if candidate.device_id and f"device:{candidate.device_id}" in ratios:
            ratio, sibling_count = ratios[f"device:{candidate.device_id}"]
        final.append(
            replace(
                candidate,
                parent_unavailable_ratio=ratio,
                parent_sibling_count=sibling_count,
            )
        )
    return final


async def _persist_maintenance_work_items(
    repository: PersistenceUnitOfWorkPort,
    fresh_records: tuple[MaintenanceWorkRecord, ...],
    *,
    now: datetime,
    current_scan_id: str | None,
) -> tuple[MaintenanceWorkRecord, ...]:
    """Durably upsert this pass's non-actionable work, verified by reload.

    Mission invariant: ``hamie/cleanup/run`` must not report completion
    until every maintenance work item it found has either been
    persisted, or the pass has produced an explicit persistence
    failure -- this is why cleanup work items are committed as their
    own step here, verified by an immediate re-load, rather than left
    for a caller to assume succeeded.

    Also stamps ``last_cleanup_scan_id`` in the same commit -- the only
    signal that lets the frontend honestly distinguish "cleanup has
    never been run against the current evidence" from "cleanup ran and
    genuinely found zero safe candidates" (mission: never show a fake
    zero for "not yet analyzed").
    """
    for _attempt in range(MAX_WORK_ITEM_COMMIT_ATTEMPTS):
        state = await repository.async_load()
        merged = merge_maintenance_work_records(
            state.maintenance_work_items, fresh_records, now=now
        )
        try:
            await repository.async_commit(
                replace(
                    state,
                    maintenance_work_items=merged,
                    last_cleanup_scan_id=current_scan_id,
                    generation=state.generation + 1,
                ),
                expected_generation=state.generation,
            )
        except GenerationConflictError:
            continue
        verified = await repository.async_load()
        return verified.maintenance_work_items
    raise RuntimeError(
        "could not persist maintenance work items after "
        f"{MAX_WORK_ITEM_COMMIT_ATTEMPTS} attempts"
    )


class MaintenanceDecisionError(RuntimeError):
    """A stable, non-sensitive maintenance-decision failure category."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def async_decide_maintenance_work(
    repository: PersistenceUnitOfWorkPort,
    *,
    work_item_id: str,
    decision: MaintenanceDecision,
    now: datetime,
) -> MaintenanceWorkRecord:
    """Persist an explicit user Keep/Unsure decision against one durable
    maintenance work item, independent of the next Clean Up pass.

    The record's `evidence_fingerprint` is deliberately left unchanged --
    it is the signal a future Clean Up pass compares against to decide
    whether a kept item's underlying condition has materially changed
    (mission: "Previously kept -- evidence changed"), so this must never
    reset it merely because the user made a decision this instant.
    """
    new_state = DECISION_LIFECYCLE[decision]
    for _attempt in range(MAX_WORK_ITEM_COMMIT_ATTEMPTS):
        state = await repository.async_load()
        current = next(
            (
                item
                for item in state.maintenance_work_items
                if item.work_item_id == work_item_id
            ),
            None,
        )
        if current is None:
            raise MaintenanceDecisionError("maintenance_work_item_not_found")
        updated = replace(current, lifecycle_state=new_state, updated_at=now)
        merged = tuple(
            updated if item.work_item_id == work_item_id else item
            for item in state.maintenance_work_items
        )
        try:
            await repository.async_commit(
                replace(
                    state,
                    maintenance_work_items=merged,
                    generation=state.generation + 1,
                ),
                expected_generation=state.generation,
            )
        except GenerationConflictError:
            continue
        verified = await repository.async_load()
        return next(
            item
            for item in verified.maintenance_work_items
            if item.work_item_id == work_item_id
        )
    raise RuntimeError(
        "could not persist maintenance work decision after "
        f"{MAX_WORK_ITEM_COMMIT_ATTEMPTS} attempts"
    )


async def async_run_cleanup(
    repository: PersistenceUnitOfWorkPort,
    hass: Any,
    *,
    options: dict[str, Any],
    now: datetime,
    actor: str = CLEANUP_ACTOR,
) -> CleanupSummary:
    """Run the complete cleanup pipeline once and return its summary.

    Never raises for an ordinary classification/proposal outcome -- a
    per-batch failure (stale fingerprint, planning rejection, execution
    failure) is recorded on that batch's ``CleanupBatchOutcome.error``
    rather than aborting the whole pass; every other batch still
    completes.
    """
    state = await repository.async_load()
    open_findings = tuple(
        item
        for item in state.findings
        if item.analyzer_id == CLEANUP_ANALYZER_ID
        and item.lifecycle == FindingLifecycle.OPEN
    )

    source = HomeAssistantOperationalSource(hass)
    capture = await source.async_capture_entities()
    entity_by_id = {item.entity_id: item for item in capture.entities}

    reference_index = build_reference_index(await capture_all_reference_sources(hass))
    policy = cleanup_policy_from_options(options)
    candidates = _build_candidates(
        open_findings, entity_by_id, reference_index.coverage, reference_index
    )
    decisions = [classify_cleanup_candidate(item, policy) for item in candidates]
    work_items = group_into_maintenance_work_items(tuple(zip(candidates, decisions)))

    scan_id = open_findings[0].latest_scan_id if open_findings else "cleanup_pass"
    fresh_records = tuple(
        record
        for record in (
            build_maintenance_work_record(item, scan_id=scan_id, now=now)
            for item in work_items
        )
        if record is not None
    )
    current_scan_id = (
        state.evaluations[-1].identity.scan_id if state.evaluations else None
    )
    persisted_work_items = await _persist_maintenance_work_items(
        repository, fresh_records, now=now, current_scan_id=current_scan_id
    )

    counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    safe_auto_fix_ids: list[str] = []
    safe_with_approval_ids: list[str] = []
    for decision in decisions:
        key = decision.classification.value
        counts[key] = counts.get(key, 0) + 1
        if decision.classification is CleanupClassification.SAFE_AUTO_FIX:
            safe_auto_fix_ids.append(decision.entity_id)
        elif decision.classification is CleanupClassification.SAFE_WITH_APPROVAL:
            safe_with_approval_ids.append(decision.entity_id)
        else:
            reason_key = decision.reason_code.value
            reason_counts[reason_key] = reason_counts.get(reason_key, 0) + 1

    configured_mode_raw = options.get("ai_operating_mode", "observe")
    status = ai_control_service.get_status(
        state, configured_mode_raw=configured_mode_raw
    )
    effective_mode = status.effective_mode
    auto_low_risk = bool(options.get("ai_auto_execute_low_risk", True))
    auto_medium_risk = bool(options.get("ai_auto_execute_medium_risk", False))

    seed = stable_digest(
        now.isoformat(), *sorted(safe_auto_fix_ids), *sorted(safe_with_approval_ids)
    )
    batches: list[CleanupBatchOutcome] = []

    async def _propose(
        entity_ids: tuple[str, ...], label: str, *, allow_auto_execute: bool
    ) -> None:
        if not entity_ids:
            return
        for index, chunk in enumerate(_chunk(entity_ids, MAX_BATCH_ENTITIES)):
            batch_label = f"{label} ({index + 1})" if index else label
            token = f"cleanup:{seed[:16]}:{index}:{label}"
            try:
                plan = await remediation_service.async_create_batch_disable_plan(
                    repository,
                    chunk,
                    actor=actor,
                    idempotency_token=token,
                    now=now,
                    hass=hass,
                    batch_label=batch_label,
                )
            except remediation_service.RemediationServiceError as err:
                batches.append(
                    CleanupBatchOutcome(
                        batch_label=batch_label,
                        entity_ids=chunk,
                        plan=None,
                        auto_executed=False,
                        execution_succeeded=None,
                        error=err.message,
                    )
                )
                continue
            auto_executed = False
            execution_succeeded: bool | None = None
            error: str | None = None
            eligible = allow_auto_execute and is_risk_class_auto_executable(
                risk=RiskLevel.LOW,
                mode=effective_mode,
                auto_execute_low_risk_setting=auto_low_risk,
                auto_execute_medium_risk_setting=auto_medium_risk,
            )
            if eligible:
                try:
                    approval = await remediation_service.async_approve_plan(
                        repository,
                        plan.remediation_plan_id,
                        plan_fingerprint=plan.plan_fingerprint,
                        preview_digest=plan.preview_digest,  # type: ignore[arg-type]
                        actor=actor,
                        destructive_acknowledged=False,
                        backup_acknowledged=True,
                        warnings_acknowledged=(),
                        idempotency_token=f"{token}:approve",
                        now=now,
                        hass=hass,
                    )
                    execution = await remediation_service.async_execute_plan(
                        repository,
                        plan.remediation_plan_id,
                        approval_id=approval.approval_id,
                        actor=actor,
                        idempotency_token=f"{token}:execute",
                        now=now,
                        hass=hass,
                    )
                    auto_executed = True
                    execution_succeeded = execution.outcome.value == "succeeded"
                    if not execution_succeeded:
                        error = execution.error
                except (
                    Exception
                ) as err:  # narrow, non-sensitive: never surfaces a traceback
                    error = f"auto_execute_failed: {type(err).__name__}"
            batches.append(
                CleanupBatchOutcome(
                    batch_label=batch_label,
                    entity_ids=chunk,
                    plan=plan,
                    auto_executed=auto_executed,
                    execution_succeeded=execution_succeeded,
                    error=error,
                )
            )

    # Observe never mutates: allow_auto_execute is still gated a second
    # time inside is_risk_class_auto_executable (mode check first,
    # authoritative), so this outer flag is defense in depth, not the
    # only gate.
    await _propose(
        tuple(safe_auto_fix_ids),
        "Safe auto-fix cleanup",
        allow_auto_execute=effective_mode is not AiOperatingMode.OBSERVE,
    )
    # safe_with_approval is never auto-executed regardless of mode --
    # it always requires a human decision (domain/cleanup_classifier.py).
    await _propose(
        tuple(safe_with_approval_ids),
        "Cleanup requiring approval",
        allow_auto_execute=False,
    )

    return CleanupSummary(
        total_findings_considered=len(open_findings),
        classification_counts=counts,
        non_actionable_reason_counts=reason_counts,
        maintenance_work_items=work_items,
        persisted_maintenance_work_items=persisted_work_items,
        safe_auto_fix_entity_ids=tuple(safe_auto_fix_ids),
        safe_with_approval_entity_ids=tuple(safe_with_approval_ids),
        batches=tuple(batches),
        configured_ai_mode=status.configured_mode.value,
        effective_ai_mode=effective_mode.value,
        dependency_scanned_sources=reference_index.coverage.scanned_sources,
        dependency_unscanned_sources=reference_index.coverage.unscanned_sources,
    )


class GatherEvidenceError(RuntimeError):
    """A gather-evidence request could not be honored."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class GatherEvidenceResult:
    """The outcome of re-checking one durable maintenance work item.

    Deliberately reuses the exact same classify -> persist pipeline
    ``async_run_cleanup`` already runs (proven idempotent -- re-running
    it on unchanged evidence upserts, never duplicates, batches or
    work items) rather than a second, narrower reclassification path:
    "what changed for this one item" is only ever answerable by
    re-deriving current classification for everyone in its root-cause
    group from live findings, which is precisely what a full pass
    already does correctly. The request itself is still scoped and
    fast -- HAMIE's entire dependency scan is a handful of bounded,
    already-fast collector calls, never a heavy multi-minute rescan.
    """

    request_id: str
    work_item_id: str
    started_at: datetime
    completed_at: datetime
    previous_lifecycle_state: str
    resolved: bool
    new_lifecycle_state: str | None
    new_classification: str | None
    still_missing: tuple[str, ...]
    created_plan_id: str | None
    collector_statuses: dict[str, str]


async def async_gather_evidence(
    repository: PersistenceUnitOfWorkPort,
    hass: Any,
    *,
    work_item_id: str,
    options: dict[str, Any],
    now: datetime,
    actor: str = CLEANUP_ACTOR,
) -> GatherEvidenceResult:
    """Re-check one durable maintenance work item's missing evidence.

    ``needs_evidence`` (and every other non-actionable lifecycle state)
    is an operational state, not a permanent label: this re-runs the
    full classify/dependency/persist pipeline once, then reports
    exactly what happened to the *one* item the caller asked about --
    resolved into an executable proposal, reclassified into a
    different non-actionable state with an updated reason, or
    genuinely still blocked on the same missing evidence, explicitly
    named.
    """
    request_id = f"gather_{uuid.uuid4().hex[:24]}"
    started_at = now
    state = await repository.async_load()
    target = next(
        (
            item
            for item in state.maintenance_work_items
            if item.work_item_id == work_item_id
        ),
        None,
    )
    if target is None:
        raise GatherEvidenceError(
            "work_item_not_found", f"no maintenance work item {work_item_id!r}"
        )
    previous_lifecycle_state = target.lifecycle_state.value

    summary = await async_run_cleanup(
        repository, hass, options=options, now=now, actor=actor
    )
    completed_at = now

    updated = next(
        (
            item
            for item in summary.persisted_maintenance_work_items
            if item.work_item_id == work_item_id
        ),
        None,
    )
    created_plan_id: str | None = None
    still_missing: tuple[str, ...] = ()
    if updated is not None:
        # Still durable non-actionable work -- possibly the same
        # classification (evidence genuinely still missing) or a
        # different one (e.g. dependency_coverage_incomplete ->
        # blocked_dependency once a real reference was actually found).
        resolved = False
        still_missing = updated.missing_evidence or (updated.dependency_status,)
        new_lifecycle_state = updated.lifecycle_state.value
        new_classification = updated.classification
    else:
        # No longer present in the durable set at all: either its
        # entities are now actionable (an executable batch was
        # created for them -- find it via sample-entity overlap) or
        # its root cause simply no longer reproduces (also a genuine
        # resolution, e.g. the entity became available again).
        resolved = True
        new_lifecycle_state = None
        new_classification = None
        for batch in summary.batches:
            if any(
                entity_id in target.affected_entity_ids
                for entity_id in batch.entity_ids
            ):
                created_plan_id = (
                    batch.plan.remediation_plan_id if batch.plan is not None else None
                )
                break

    return GatherEvidenceResult(
        request_id=request_id,
        work_item_id=work_item_id,
        started_at=started_at,
        completed_at=completed_at,
        previous_lifecycle_state=previous_lifecycle_state,
        resolved=resolved,
        new_lifecycle_state=new_lifecycle_state,
        new_classification=new_classification,
        still_missing=still_missing,
        created_plan_id=created_plan_id,
        collector_statuses={
            source: "succeeded" for source in summary.dependency_scanned_sources
        }
        | {source: "unavailable" for source in summary.dependency_unscanned_sources},
    )
