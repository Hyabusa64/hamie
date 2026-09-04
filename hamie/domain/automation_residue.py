"""Automation ID migration-residue temporal classification (mission
Part 2, Analyzer 4).

Formalizes what this session's manual investigation did by hand for the
``automation.*`` migration-leftover cases: an old registry entity whose
YAML ``id:`` genuinely no longer exists anywhere in current source,
paired with a live, current sibling automation that *does* still have
its definition -- plus an honest temporal claim about whether the old
automation is truly dormant.

**Genuine, disclosed infrastructure gap**: this module's tri-state
tagging (``PROVEN``/``SUPPORTED``/``INSUFFICIENT_HISTORY``, the exact
vocabulary the mission specifies) can **never** return ``PROVEN`` in
this codebase today. Proving "this automation has never fired" needs a
real trigger/event-count signal -- Home Assistant's
``automation_triggered`` Logbook/event history, or the automation
entity's own ``last_triggered`` state attribute persisted across
restarts. Neither exists anywhere in HAMIE's infrastructure: the
already-built ``infrastructure/recorder_source.py`` only ever queries
``get_significant_states``/``statistics_during_period``, both of which
answer "did this entity's *state value* change" -- an automation
entity's state stays ``"on"``/``"off"`` regardless of how many times it
fires, so neither call can ever observe a trigger. Building a new
``automation_triggered`` event-table reader blind, with no live Home
Assistant process reachable from this task to validate the exact query
shape against, would risk fabricating a capability HAMIE does not
actually have -- the identical judgment call
``domain/temporal_evidence.py``'s own module docstring already made and
documented for a related gap ("this is a genuine, structural, currently
unfillable gap"). This module makes the same call, explicitly, rather
than shipping a silently-approximate "PROVEN" that isn't backed by real
trigger evidence.

Pure and I/O-free, like every other ``domain/`` module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .common import require_non_empty


class AutomationResidueTemporalTag(StrEnum):
    """Every automation-residue temporal claim lands in exactly one of
    these. ``PROVEN`` exists in this vocabulary for forward-compatibility
    (a future live ``automation_triggered`` event reader could populate
    it) but ``classify_automation_residue_temporal_evidence`` below
    never returns it today -- see module docstring."""

    PROVEN = "proven"
    SUPPORTED = "supported"
    INSUFFICIENT_HISTORY = "insufficient_history"


@dataclass(frozen=True, slots=True)
class AutomationResidueEvidence:
    """One confirmed automation-domain migration-residue candidate."""

    group_key: str
    old_automation_entity_id: str
    live_automation_entity_id: str
    temporal_tag: AutomationResidueTemporalTag
    zero_references_confirmed: bool

    def __post_init__(self) -> None:
        for value, name in (
            (self.group_key, "group_key"),
            (self.old_automation_entity_id, "old_automation_entity_id"),
            (self.live_automation_entity_id, "live_automation_entity_id"),
        ):
            require_non_empty(value, name)


def classify_automation_residue_temporal_evidence(
    *, zero_references_confirmed: bool, reference_scan_attempted: bool
) -> AutomationResidueTemporalTag:
    """Classify the temporal-confidence tier for one residue candidate.

    Never ``PROVEN`` -- see module docstring. ``SUPPORTED`` requires a
    reference scan to have actually run and confirmed zero references
    anywhere (structural corroboration beyond "source definition is
    missing" alone); anything less (no scan attempted, or a scan that
    could not reach a clean zero-reference answer) is
    ``INSUFFICIENT_HISTORY`` -- explicitly never a claim of "dead,"
    matching the mission's own caution against inferring dormancy from
    thin evidence.
    """
    if reference_scan_attempted and zero_references_confirmed:
        return AutomationResidueTemporalTag.SUPPORTED
    return AutomationResidueTemporalTag.INSUFFICIENT_HISTORY
