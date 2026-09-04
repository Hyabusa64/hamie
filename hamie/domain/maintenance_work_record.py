"""Durable maintenance work records -- the Review Queue's non-plan half.

``domain/maintenance_work_items.py`` groups non-actionable cleanup
decisions into an explained, in-memory ``MaintenanceWorkItem`` -- real,
but ephemeral: recomputed every ``hamie/cleanup/run`` call and never
persisted, so it vanishes the moment the response is rendered. That is
the exact gap the mission calls out: hundreds of maintenance issues
Clean Up genuinely found, discoverable only in the instant one WS
response is on screen.

This module is the durable counterpart. ``build_maintenance_work_record``
turns one ephemeral ``MaintenanceWorkItem`` into a
``MaintenanceWorkRecord`` with a stable, content-derived ID (hashing
only the group key, not the member count) so re-running Clean Up on
materially the same root cause upserts the existing record instead of
duplicating it -- the mission's own "duplicate Clean Up does not
duplicate equivalent queue items" invariant.

Pure and I/O-free, like every other ``domain/`` module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .cleanup_classifier import CleanupClassification
from .common import require_non_empty, stable_digest
from .maintenance_work_items import MaintenanceWorkItem

MAX_AFFECTED_ENTITY_IDS = 50


class WorkItemLifecycleState(StrEnum):
    """Every persisted maintenance work item's lifecycle state."""

    NEEDS_EVIDENCE = "needs_evidence"
    DEPENDENCY_BLOCKED = "dependency_blocked"
    AI_INVESTIGATION = "ai_investigation"
    MANUAL_REPAIR = "manual_repair"
    SNOOZED = "snoozed"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"


# User-set terminal/paused states a fresh Clean Up pass must never
# silently overwrite -- see ``merge_maintenance_work_records``.
USER_MANAGED_STATES = frozenset(
    {
        WorkItemLifecycleState.SNOOZED,
        WorkItemLifecycleState.COMPLETED,
    }
)


class MaintenanceDecision(StrEnum):
    """An explicit user decision recorded against one durable work item.

    KEEP -> WorkItemLifecycleState.COMPLETED (a USER_MANAGED_STATE --
    merge_maintenance_work_records will never let a future Clean Up pass
    silently overwrite it while the evidence fingerprint is unchanged;
    "Previously kept -- evidence changed" is the honest re-surfacing
    signal once it does).
    UNSURE -> WorkItemLifecycleState.NEEDS_EVIDENCE (explicitly requests
    re-investigation; not itself user-managed, so a future Clean Up pass
    or Gather Evidence may resolve it once new evidence arrives).
    """

    KEEP = "keep"
    UNSURE = "unsure"


DECISION_LIFECYCLE: dict[MaintenanceDecision, WorkItemLifecycleState] = {
    MaintenanceDecision.KEEP: WorkItemLifecycleState.COMPLETED,
    MaintenanceDecision.UNSURE: WorkItemLifecycleState.NEEDS_EVIDENCE,
}


_LIFECYCLE_BY_CLASSIFICATION: dict[CleanupClassification, WorkItemLifecycleState] = {
    CleanupClassification.MANUAL_REVIEW: WorkItemLifecycleState.MANUAL_REPAIR,
    CleanupClassification.BLOCKED_DEPENDENCY: WorkItemLifecycleState.DEPENDENCY_BLOCKED,
    CleanupClassification.BLOCKED_UNCERTAIN: WorkItemLifecycleState.NEEDS_EVIDENCE,
    CleanupClassification.PARENT_INTEGRATION_FAILURE: (
        WorkItemLifecycleState.AI_INVESTIGATION
    ),
}

# Classifications the mission explicitly exempts from durable queue
# work -- genuinely no-action states, never worth a persisted row.
DURABLE_CLASSIFICATIONS = frozenset(_LIFECYCLE_BY_CLASSIFICATION)


@dataclass(frozen=True, slots=True)
class MaintenanceWorkRecord:
    """One durable, queryable Review Queue row for non-actionable cleanup work."""

    work_item_id: str
    source_scan_id: str
    source_group_key: str
    classification: str
    lifecycle_state: WorkItemLifecycleState
    affected_entity_ids: tuple[str, ...]
    entity_count: int
    title: str
    reason: str
    dependency_status: str
    missing_evidence: tuple[str, ...]
    recommended_capability_id: str | None
    risk: str
    confidence: str
    created_at: datetime
    updated_at: datetime
    evidence_fingerprint: str
    target_fingerprint: str | None = None
    ai_provenance: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.work_item_id, "work_item_id")
        require_non_empty(self.source_group_key, "source_group_key")
        require_non_empty(self.classification, "classification")
        require_non_empty(self.title, "title")
        require_non_empty(self.reason, "reason")
        require_non_empty(self.evidence_fingerprint, "evidence_fingerprint")
        if self.entity_count < 0:
            raise ValueError("entity_count cannot be negative")
        if len(self.affected_entity_ids) > MAX_AFFECTED_ENTITY_IDS:
            raise ValueError(
                f"affected_entity_ids exceeds {MAX_AFFECTED_ENTITY_IDS} bound"
            )


def _work_item_id(group_key: str) -> str:
    return f"work_{stable_digest('maintenance_work_item', group_key)[:24]}"


def build_maintenance_work_record(
    item: MaintenanceWorkItem, *, scan_id: str, now: datetime
) -> MaintenanceWorkRecord | None:
    """Build one durable record from an ephemeral grouped work item.

    Returns ``None`` for a classification the mission exempts from
    durable queue work (transient/expected/already-clean/actionable) --
    the caller filters on this rather than raising, since "this
    classification is not durable work" is an ordinary outcome, not an
    error.
    """
    lifecycle = _LIFECYCLE_BY_CLASSIFICATION.get(item.classification)
    if lifecycle is None:
        return None
    return MaintenanceWorkRecord(
        work_item_id=_work_item_id(item.group_key),
        source_scan_id=scan_id,
        source_group_key=item.group_key,
        classification=item.classification.value,
        lifecycle_state=lifecycle,
        affected_entity_ids=item.sample_entity_ids,
        entity_count=item.entity_count,
        title=item.next_action_label,
        reason=item.reason,
        dependency_status=item.reason_code,
        missing_evidence=(
            (item.reason_code,)
            if item.classification is CleanupClassification.BLOCKED_UNCERTAIN
            else ()
        ),
        recommended_capability_id=None,
        risk="low",
        confidence="high",
        created_at=now,
        updated_at=now,
        evidence_fingerprint=stable_digest(
            item.group_key, item.reason_code, *sorted(item.sample_entity_ids)
        ),
    )


def merge_maintenance_work_records(
    existing: tuple[MaintenanceWorkRecord, ...],
    fresh: tuple[MaintenanceWorkRecord, ...],
    *,
    now: datetime,
) -> tuple[MaintenanceWorkRecord, ...]:
    """Upsert this Clean Up pass's durable work into the persisted set.

    - A fresh record whose ID matches an existing one currently in a
      user-managed state (snoozed/completed) is dropped in favor of the
      existing one -- a user's decision must never be silently
      overwritten by a routine re-scan.
    - A fresh record whose ID matches an existing one in any other
      state replaces it, refreshing ``updated_at`` only when the
      evidence fingerprint actually changed.
    - An existing record whose ID does not appear in ``fresh`` at all
      means this pass no longer finds that root cause -- it is dropped
      (resolved), *unless* it is user-managed, which is preserved
      regardless of whether the current pass still reproduces it.
    """
    fresh_by_id = {item.work_item_id: item for item in fresh}
    existing_by_id = {item.work_item_id: item for item in existing}
    merged: dict[str, MaintenanceWorkRecord] = {}

    for work_item_id, current in existing_by_id.items():
        if current.lifecycle_state in USER_MANAGED_STATES:
            merged[work_item_id] = current

    for work_item_id, incoming in fresh_by_id.items():
        if work_item_id in merged:
            continue
        prior = existing_by_id.get(work_item_id)
        if (
            prior is not None
            and prior.evidence_fingerprint == incoming.evidence_fingerprint
        ):
            merged[work_item_id] = replace_created_at(incoming, prior.created_at)
        else:
            merged[work_item_id] = incoming

    return tuple(sorted(merged.values(), key=lambda item: item.work_item_id))


def replace_created_at(
    record: MaintenanceWorkRecord, created_at: datetime
) -> MaintenanceWorkRecord:
    """Preserve a record's original ``created_at`` across an unchanged re-run."""
    if record.created_at == created_at:
        return record
    from dataclasses import replace as _replace

    return _replace(record, created_at=created_at, updated_at=record.updated_at)
