"""Repair-orchestration usage metrics (Phase 22).

The one metric this module exists to make possible:
``manual_escalation_rate`` -- the fraction of investigated incidents
that still needed a Claude escalation packet
(``domain/escalation.py``). HAMIE's repair-orchestration layer is
working precisely to the extent this number goes down over time; a
larger raw count of playbooks or tools proves nothing on its own.

Pure and I/O-free: takes an already-assembled snapshot of incident
outcomes (plain records, not live queries or application-layer types --
same dependency-direction discipline as ``repair_queue.py``) and computes
aggregate counts and rates. Never fabricates a rate from zero
denominator data -- see ``RepairMetrics.manual_escalation_rate``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .repair_queue import KNOWN_DISPOSITIONS, RepairTier, TIER_BY_DISPOSITION


@dataclass(frozen=True, slots=True)
class RemediationOutcomeRecord:
    """One completed (or attempted) remediation's terminal outcome.

    ``outcome`` mirrors ``application/remediation_execution.py``'s
    ``RemediationOutcome`` values by convention, as a plain string --
    see ``repair_queue.py``'s module docstring for why this module never
    imports application-layer enums directly.
    """

    incident_id: str
    outcome: str  # "resolved" | "still_present" | "regressed" | "validation_failed" | "rolled_back" | "rollback_failed"


@dataclass(frozen=True, slots=True)
class IncidentSnapshot:
    """One incident's current status, for aggregate metrics purposes."""

    incident_id: str
    disposition: str
    investigated: bool
    escalated_to_claude: bool
    seconds_to_investigation: float | None = None
    seconds_to_repair: float | None = None

    def __post_init__(self) -> None:
        if self.disposition not in KNOWN_DISPOSITIONS:
            raise ValueError(f"unrecognised disposition: {self.disposition!r}")
        if not self.investigated and self.escalated_to_claude:
            raise ValueError("an un-investigated incident cannot already be escalated")


@dataclass(frozen=True, slots=True)
class RepairMetrics:
    """Aggregate counts and rates over one snapshot of incidents/repairs."""

    active_incidents: int
    investigated_incidents: int
    repair_candidates: int
    operator_decision_incidents: int
    unsupported_incidents: int
    successful_repairs: int
    failed_repairs: int
    rolled_back_repairs: int
    mean_seconds_to_investigation: float | None
    mean_seconds_to_repair: float | None
    manual_escalations: int
    manual_escalation_rate: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "active_incidents": self.active_incidents,
            "investigated_incidents": self.investigated_incidents,
            "repair_candidates": self.repair_candidates,
            "operator_decision_incidents": self.operator_decision_incidents,
            "unsupported_incidents": self.unsupported_incidents,
            "successful_repairs": self.successful_repairs,
            "failed_repairs": self.failed_repairs,
            "rolled_back_repairs": self.rolled_back_repairs,
            "mean_seconds_to_investigation": self.mean_seconds_to_investigation,
            "mean_seconds_to_repair": self.mean_seconds_to_repair,
            "manual_escalations": self.manual_escalations,
            "manual_escalation_rate": self.manual_escalation_rate,
        }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def compute_repair_metrics(
    incidents: tuple[IncidentSnapshot, ...],
    outcomes: tuple[RemediationOutcomeRecord, ...] = (),
) -> RepairMetrics:
    """Compute the Phase 22 metric set from a snapshot.

    ``manual_escalation_rate`` is the fraction of *investigated*
    incidents (not all active incidents -- an un-investigated incident
    was never a candidate for escalation in the first place) that were
    escalated. Returns ``None``, never ``0.0``, when zero incidents were
    investigated: a rate of zero would falsely claim "HAMIE is resolving
    everything," when the honest fact is "nothing was measured yet."
    """
    investigated = [i for i in incidents if i.investigated]
    escalated = [i for i in investigated if i.escalated_to_claude]

    unsupported_tiers = (RepairTier.NOT_YET_ACTIONABLE, RepairTier.NOT_HAMIES_TO_FIX)
    repair_candidates = sum(
        1 for i in incidents if TIER_BY_DISPOSITION[i.disposition] is RepairTier.READY_TO_APPROVE
    )
    operator_decision = sum(
        1 for i in incidents if TIER_BY_DISPOSITION[i.disposition] is RepairTier.NEEDS_A_DECISION
    )
    unsupported = sum(1 for i in incidents if TIER_BY_DISPOSITION[i.disposition] in unsupported_tiers)

    investigation_times = [
        i.seconds_to_investigation for i in incidents if i.seconds_to_investigation is not None
    ]
    repair_times = [i.seconds_to_repair for i in incidents if i.seconds_to_repair is not None]

    successful = sum(1 for o in outcomes if o.outcome == "resolved")
    failed = sum(1 for o in outcomes if o.outcome in ("still_present", "regressed", "validation_failed"))
    rolled_back = sum(1 for o in outcomes if o.outcome in ("rolled_back", "rollback_failed"))

    return RepairMetrics(
        active_incidents=len(incidents),
        investigated_incidents=len(investigated),
        repair_candidates=repair_candidates,
        operator_decision_incidents=operator_decision,
        unsupported_incidents=unsupported,
        successful_repairs=successful,
        failed_repairs=failed,
        rolled_back_repairs=rolled_back,
        mean_seconds_to_investigation=_mean(investigation_times),
        mean_seconds_to_repair=_mean(repair_times),
        manual_escalations=len(escalated),
        manual_escalation_rate=(len(escalated) / len(investigated)) if investigated else None,
    )
