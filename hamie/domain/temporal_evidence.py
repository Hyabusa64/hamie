"""Temporal (history/statistics) evidence classification (mission Part 3d).

Answers "how long has this entity actually been unavailable, and how
confident can HAMIE be in a claim like '>30 days'?" -- distinct from,
and deliberately more conservative than, ``unavailable_seconds`` alone
(``domain/cleanup_classifier.py``'s existing signal, which only ever
reflects the *current* state-machine's ``last_changed``, not a
recorder-backed history query).

The live installation's actual recorder configuration was verified
read-only as part of this task (``ssh ha "grep -n 'recorder:' -A15
/config/configuration.yaml"``): an external MariaDB recorder with
``purge_keep_days: 7``. A 7-day raw retention window can **never**, by
itself, prove a >30-day claim -- ``classify_temporal_evidence`` below
enforces this as a hard invariant, not a policy choice: no combination
of inputs can produce ``CONFIRMED_UNAVAILABLE_GT_30D`` when the only
evidence offered is younger than the claimed duration.

Home Assistant's long-term statistics (``homeassistant.components.
recorder.statistics``) *do* separately retain aggregated (not raw)
data indefinitely, which is the one honest path to a real >30-day
claim on a 7-day raw-purge installation -- but this module cannot call
into that live API (see ``RecorderHistorySourcePort`` below): there is
no live Home Assistant Python process available in this task (see the
mission's absolute constraints) to run or test
``homeassistant.components.recorder``'s actual history/statistics
helper functions against. This is a genuine, structural, currently
unfillable gap -- ``infrastructure/ha_source.py`` and
``infrastructure/dependency_source.py`` have no code path into the
recorder at all today, and building one blind, with no live process to
validate the real HA statistics API surface against, would risk
fabricating a capability HAMIE does not actually have. What *is* done
here, at the interface/contract level, matching the rest of this
codebase's "every source is captured defensively, capability
absence/failure is reported honestly, never silently assumed" pattern
(see ``dependency_source.py``'s module docstring): a ``Protocol`` any
future live recorder adapter would implement, and a pure classifier
that turns whatever evidence *is* available into one of four honest
outcomes, never fabricating confidence the evidence does not support.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

THIRTY_DAYS_SECONDS = 30 * 24 * 60 * 60


class TemporalEvidenceStatus(StrEnum):
    """Every temporal-evidence question lands in exactly one of these."""

    CONFIRMED_UNAVAILABLE_GT_30D = "confirmed_unavailable_gt_30d"
    INSUFFICIENT_HISTORY_TO_PROVE_30D = "insufficient_history_to_prove_30d"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class TemporalEvidence:
    """Bounded, honestly-sourced history/statistics evidence for one entity.

    Every field is optional/``None``-able on purpose: a caller with
    only today's live-recorder raw-purge window (this installation:
    7 days) supplies ``raw_history_available_seconds`` and leaves the
    long-term-statistics fields ``None`` -- ``classify_temporal_evidence``
    is required to treat that honestly rather than inferring a longer
    window ever existed.
    """

    # How far back the *raw* recorder history actually reaches for this
    # entity, in seconds -- bounded above by the installation's
    # ``purge_keep_days`` regardless of how long the entity has
    # theoretically existed (a fresh purge always wins).
    raw_history_available_seconds: int | None = None
    # Seconds the entity has been continuously unavailable *within* the
    # raw history window above (never longer than
    # raw_history_available_seconds -- enforced below).
    raw_unavailable_seconds: int | None = None
    # Whether long-term statistics (HA's separate, indefinitely-retained
    # aggregate table) were actually queried and confirm continuous
    # unavailability back to a specific point. None = not queried/not
    # available (the honest default on every installation until a live
    # recorder adapter exists -- see the module docstring).
    long_term_statistics_confirm_unavailable_seconds: int | None = None
    # Whether any signal (a live state change event, a statistics row
    # showing activity) contradicts a "continuously unavailable" claim
    # within the claimed window.
    contradicting_activity_found: bool = False

    def __post_init__(self) -> None:
        for name in (
            "raw_history_available_seconds",
            "raw_unavailable_seconds",
            "long_term_statistics_confirm_unavailable_seconds",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")
        if (
            self.raw_history_available_seconds is not None
            and self.raw_unavailable_seconds is not None
            and self.raw_unavailable_seconds > self.raw_history_available_seconds
        ):
            raise ValueError(
                "raw_unavailable_seconds cannot exceed raw_history_available_seconds"
            )


def classify_temporal_evidence(
    evidence: TemporalEvidence,
    *,
    claim_threshold_seconds: int = THIRTY_DAYS_SECONDS,
    applicable: bool = True,
) -> TemporalEvidenceStatus:
    """Classify what a duration claim (default: 30 days) can honestly say.

    Structural guarantee: ``CONFIRMED_UNAVAILABLE_GT_30D`` is only ever
    returned when *some* evidence field's covered window is itself at
    least ``claim_threshold_seconds`` long -- there is no code path
    that lets a shorter window (e.g. a 7-day raw-purge installation
    with no long-term-statistics evidence supplied) produce it. This is
    verified directly by this function's own logic, not merely
    documented: every branch below checks the window length before
    ever returning the CONFIRMED status.
    """
    if not applicable:
        return TemporalEvidenceStatus.NOT_APPLICABLE
    if evidence.contradicting_activity_found:
        return TemporalEvidenceStatus.CONTRADICTORY_EVIDENCE

    # Long-term statistics are the only source ever allowed to prove a
    # window longer than the raw-history retention -- and even then,
    # only when the confirmed span itself reaches the threshold.
    lt_seconds = evidence.long_term_statistics_confirm_unavailable_seconds
    if lt_seconds is not None and lt_seconds >= claim_threshold_seconds:
        return TemporalEvidenceStatus.CONFIRMED_UNAVAILABLE_GT_30D

    raw_available = evidence.raw_history_available_seconds
    raw_unavailable = evidence.raw_unavailable_seconds
    if (
        raw_available is not None
        and raw_unavailable is not None
        # The raw window itself must cover the full claimed duration --
        # a 7-day (604,800s) raw-purge window can never satisfy a
        # 30-day (2,592,000s) threshold no matter what
        # raw_unavailable_seconds says, because "unavailable for the
        # entire 7 days we can see" is not evidence about day 8 through
        # 30.
        and raw_available >= claim_threshold_seconds
        and raw_unavailable >= claim_threshold_seconds
    ):
        return TemporalEvidenceStatus.CONFIRMED_UNAVAILABLE_GT_30D

    return TemporalEvidenceStatus.INSUFFICIENT_HISTORY_TO_PROVE_30D


class RecorderHistorySourcePort(Protocol):
    """The live recorder capability HAMIE would need to fill this gap.

    NOT implemented against a real Home Assistant process anywhere in
    this codebase -- see the module docstring. Declared here, matching
    ``application/ports.py``'s existing ``OperationalSourcePort``
    shape, purely as the contract a future live adapter (built and
    tested inside an actual running HA instance, which this task does
    not have access to) would satisfy, so that day's implementation
    slots into ``classify_temporal_evidence`` above via
    ``TemporalEvidence`` without this module changing at all.
    """

    async def async_raw_history_available_seconds(self, entity_id: str) -> int | None:
        """Return how far back raw recorder history reaches for this entity."""

    async def async_long_term_statistics_unavailable_seconds(
        self, entity_id: str
    ) -> int | None:
        """Return the longest continuous unavailable span long-term stats confirm."""
