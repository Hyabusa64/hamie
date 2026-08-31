"""Group non-actionable cleanup decisions into a visible maintenance workload.

Every classification the cleanup classifier can produce for a candidate
that is *not* immediately actionable (``safe_auto_fix``/
``safe_with_approval``) still represents real information HAMIE
discovered about the user's Home Assistant installation -- a device
that seems to be failing, entities a dependency scan found real
references for, entities whose dependency coverage is incomplete, and
so on. Counting these and then discarding them (the pre-existing
behaviour: ``classification_counts`` incremented, nothing else) makes
a large, evidence-backed maintenance workload invisible -- the exact
"509 findings, 0 actionable proposals" production symptom this module
exists to fix.

Pure and I/O-free, like every other ``domain/`` module: takes already-
classified ``(CleanupCandidate, CleanupDecision)`` pairs and groups
them by root cause (device, when known) and classification into a
small number of ``MaintenanceWorkItem`` records, each carrying a
human-actionable ``next_action``. Never executes anything itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cleanup_classifier import (
    ACTIONABLE_CLASSIFICATIONS,
    CleanupCandidate,
    CleanupClassification,
    CleanupDecision,
)

MAX_SAMPLE_ENTITY_IDS = 5

# One human next-action per classification -- deliberately specific
# enough to tell the user what would actually help, matching mission's
# explicit "not 'Gather more evidence' with no button that does
# anything" requirement. `action_id` is the machine-readable hook a
# frontend button binds to; not every one has a wired executor yet, but
# the label and grouping are real and correct regardless.
_NEXT_ACTION_BY_CLASSIFICATION: dict[CleanupClassification, tuple[str, str]] = {
    CleanupClassification.MANUAL_REVIEW: (
        "review_manually",
        "Review manually",
    ),
    CleanupClassification.BLOCKED_DEPENDENCY: (
        "view_dependencies",
        "View dependencies",
    ),
    CleanupClassification.BLOCKED_UNCERTAIN: (
        "gather_evidence",
        "Gather evidence",
    ),
    CleanupClassification.TRANSIENT_ISSUE: (
        "wait_and_rescan",
        "Wait and rescan later",
    ),
    CleanupClassification.PARENT_INTEGRATION_FAILURE: (
        "investigate_integration",
        "Investigate integration/device",
    ),
    CleanupClassification.EXPECTED_BEHAVIOR: (
        "no_action_needed",
        "No action needed",
    ),
    CleanupClassification.ALREADY_CLEAN: (
        "no_action_needed",
        "No action needed",
    ),
}


@dataclass(frozen=True, slots=True)
class MaintenanceWorkItem:
    """One grouped, explained bucket of non-actionable cleanup findings."""

    group_key: str
    classification: CleanupClassification
    reason_code: str
    entity_count: int
    sample_entity_ids: tuple[str, ...]
    reason: str
    next_action_id: str
    next_action_label: str
    device_id: str | None
    integration: str | None


def _group_key(candidate: CleanupCandidate, decision: CleanupDecision) -> str:
    if decision.classification is CleanupClassification.PARENT_INTEGRATION_FAILURE:
        if candidate.device_id:
            return f"{decision.classification.value}:device:{candidate.device_id}"
        if candidate.integration:
            return (
                f"{decision.classification.value}:integration:{candidate.integration}"
            )
    return f"{decision.classification.value}:{decision.reason_code.value}"


def group_into_maintenance_work_items(
    pairs: tuple[tuple[CleanupCandidate, CleanupDecision], ...],
) -> tuple[MaintenanceWorkItem, ...]:
    """Group every non-actionable decision into a small, explained workload.

    Actionable decisions (``safe_auto_fix``/``safe_with_approval``) are
    excluded -- those already get a real, executable batch proposal via
    the coordinator's own batch-disable path; this function is only for
    everything that path silently used to drop.
    """
    groups: dict[str, list[tuple[CleanupCandidate, CleanupDecision]]] = {}
    for candidate, decision in pairs:
        if decision.classification in ACTIONABLE_CLASSIFICATIONS:
            continue
        groups.setdefault(_group_key(candidate, decision), []).append(
            (candidate, decision)
        )

    items: list[MaintenanceWorkItem] = []
    for key, members in groups.items():
        _, first_decision = members[0]
        first_candidate = members[0][0]
        action_id, action_label = _NEXT_ACTION_BY_CLASSIFICATION.get(
            first_decision.classification, ("review_manually", "Review manually")
        )
        items.append(
            MaintenanceWorkItem(
                group_key=key,
                classification=first_decision.classification,
                reason_code=first_decision.reason_code.value,
                entity_count=len(members),
                sample_entity_ids=tuple(
                    candidate.entity_id
                    for candidate, _ in members[:MAX_SAMPLE_ENTITY_IDS]
                ),
                reason=first_decision.reason,
                next_action_id=action_id,
                next_action_label=action_label,
                device_id=first_candidate.device_id,
                integration=first_candidate.integration,
            )
        )
    items.sort(key=lambda item: item.entity_count, reverse=True)
    return tuple(items)
