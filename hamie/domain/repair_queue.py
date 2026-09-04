"""The repair recommendation queue: "here are the 6 things worth fixing."

Repair-orchestration Phase 17. HAMIE's own real production numbers are
the reason this exists: 2,672 open findings at one real review, 1,399 of
them REVIEW_REQUIRED. A flat findings list at that scale is not a
recommendation, it's a wall. This module is the ranking/filtering layer
that turns "everything HAMIE has ever noticed" into "what's actually
worth a human's attention right now" -- ranked, and honest about which
tier each item is in.

Pure and I/O-free: it takes already-computed candidate records (plain
dicts describing one incident's repair status), never queries a live
incident store itself. The caller (application layer) is responsible
for building ``RepairQueueEntry`` records from whatever its own incident/
disposition types actually are -- this module deliberately does not
import ``application/incident_remediation.py``'s ``InvestigationDisposition``
or any other application-layer enum, to keep the dependency direction
domain <- application, never the reverse.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .common import require_non_empty

#: Recognised disposition strings, matching
#: ``application/incident_remediation.py``'s ``InvestigationDisposition``
#: values by convention (not by import). Kept as plain strings, not an
#: enum import, so this module has no dependency on the application
#: layer; ``RepairQueueEntry.__post_init__`` still validates against this
#: set so a typo or a future disposition addition is caught immediately
#: rather than silently mis-ranked.
KNOWN_DISPOSITIONS = frozenset(
    {
        "no_action",
        "insufficient_evidence",
        "external_action_required",
        "operator_decision_required",
        "repair_candidate",
        "blocked",
    }
)

#: Priority order, most urgent first. An incident whose priority is not
#: in this list is never silently dropped -- see ``_priority_rank``.
_PRIORITY_ORDER = ("p0", "p1", "p2", "p3", "info")


class RepairTier(StrEnum):
    """Which section of the queue an entry belongs in.

    Deliberately a small, fixed set independent of ``KNOWN_DISPOSITIONS``:
    several dispositions collapse into the same *actionability* tier
    (e.g. ``insufficient_evidence`` and ``external_action_required`` both
    mean "not HAMIE's to fix right now"), and the queue's whole purpose
    is presenting actionability, not raw disposition taxonomy.
    """

    READY_TO_APPROVE = "ready_to_approve"  # repair_candidate
    NEEDS_A_DECISION = "needs_a_decision"  # operator_decision_required
    NOT_YET_ACTIONABLE = "not_yet_actionable"  # insufficient_evidence, external_action_required
    NOT_HAMIES_TO_FIX = "not_hamies_to_fix"  # blocked, no_action


TIER_BY_DISPOSITION: dict[str, RepairTier] = {
    "repair_candidate": RepairTier.READY_TO_APPROVE,
    "operator_decision_required": RepairTier.NEEDS_A_DECISION,
    "insufficient_evidence": RepairTier.NOT_YET_ACTIONABLE,
    "external_action_required": RepairTier.NOT_YET_ACTIONABLE,
    "blocked": RepairTier.NOT_HAMIES_TO_FIX,
    "no_action": RepairTier.NOT_HAMIES_TO_FIX,
}


@dataclass(frozen=True, slots=True)
class RepairQueueEntry:
    """One incident's current repair status, ready to rank and present."""

    incident_id: str
    disposition: str
    priority: str
    root_cause: str
    confidence: float
    risk: str
    affected_objects: tuple[str, ...] = ()
    dry_run_available: bool = False
    approval_required: bool = True
    recommended_repair: str = ""

    def __post_init__(self) -> None:
        require_non_empty(self.incident_id, "incident_id")
        require_non_empty(self.root_cause, "root_cause")
        if self.disposition not in KNOWN_DISPOSITIONS:
            raise ValueError(f"unrecognised disposition: {self.disposition!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

    @property
    def tier(self) -> RepairTier:
        return TIER_BY_DISPOSITION[self.disposition]


def _priority_rank(priority: str) -> int:
    try:
        return _PRIORITY_ORDER.index(priority)
    except ValueError:
        # An unrecognised priority is never silently sorted as if it were
        # the lowest urgency -- it is treated as at least as urgent as
        # the worst *known* priority, so a labeling gap can never hide an
        # incident at the bottom of the queue.
        return len(_PRIORITY_ORDER) - 1


def rank_queue(entries: tuple[RepairQueueEntry, ...]) -> tuple[RepairQueueEntry, ...]:
    """Order entries: tier first (most actionable first), then priority,
    then confidence (higher first), then incident_id for a stable order
    among ties.
    """
    tier_order = {
        RepairTier.READY_TO_APPROVE: 0,
        RepairTier.NEEDS_A_DECISION: 1,
        RepairTier.NOT_YET_ACTIONABLE: 2,
        RepairTier.NOT_HAMIES_TO_FIX: 3,
    }
    return tuple(
        sorted(
            entries,
            key=lambda e: (
                tier_order[e.tier],
                _priority_rank(e.priority),
                -e.confidence,
                e.incident_id,
            ),
        )
    )


def top_recommendations(
    entries: tuple[RepairQueueEntry, ...], *, limit: int = 6
) -> tuple[RepairQueueEntry, ...]:
    """The queue's actual product: "here are the N things worth fixing."

    Only ``READY_TO_APPROVE`` and ``NEEDS_A_DECISION`` tiers are ever
    surfaced here -- an incident HAMIE has already determined it cannot
    act on (``NOT_YET_ACTIONABLE``, ``NOT_HAMIES_TO_FIX``) is never
    presented as something "worth fixing right now," regardless of how
    much room is left under ``limit``. A caller that wants the full
    picture uses ``rank_queue`` directly.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    actionable_tiers = (RepairTier.READY_TO_APPROVE, RepairTier.NEEDS_A_DECISION)
    ranked = rank_queue(entries)
    return tuple(entry for entry in ranked if entry.tier in actionable_tiers)[:limit]
