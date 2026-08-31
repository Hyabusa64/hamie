"""Truthful analysis state: what "All clear" is allowed to mean.

Production showed the Recommendations page reporting, simultaneously:

    412 incidents
    The selected findings' evidence is too large for the configured prompt size
    All clear

Every one of those was rendered from real data. The contradiction came from
deriving "All clear" from the wrong signal: zero recommendations, plus an AI
connector whose status was *healthy* -- because the provider was fine, the
payload was too large. The question the UI needs answered is not "is the
provider broken?" but "did analysis actually cover the scope, and does zero
recommendations mean nothing is wrong or that nothing was looked at?"

So the gate lives here, deterministically, once. The frontend reads
`all_clear_permitted` rather than re-deriving it, because a second
implementation of this rule is a second chance to get it wrong -- and the
failure mode is telling someone their house is fine when HAMIE never looked.

Pure and I/O-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AnalysisState(StrEnum):
    """Where AI analysis stands for the current scan."""

    NOT_ANALYZED = "not_analyzed"
    ANALYZING = "analyzing"
    PARTIALLY_ANALYZED = "partially_analyzed"
    COMPLETE = "complete"
    FAILED = "failed"
    STALE = "stale"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


#: States in which zero recommendations cannot be read as good news.
NON_AFFIRMATIVE_STATES = frozenset(
    {
        AnalysisState.NOT_ANALYZED,
        AnalysisState.ANALYZING,
        AnalysisState.PARTIALLY_ANALYZED,
        AnalysisState.FAILED,
        AnalysisState.STALE,
        AnalysisState.PROVIDER_UNAVAILABLE,
    }
)


@dataclass(frozen=True, slots=True)
class AnalysisInputs:
    """Everything the gate is allowed to consider. All deterministic."""

    #: The scan currently reflected by the projection.
    current_scan_id: str | None = None
    #: The scan the most recent completed analysis ran against.
    analyzed_scan_id: str | None = None
    #: Findings eligible for analysis in the current scan.
    eligible_total: int = 0
    #: Findings actually included in a completed analysis.
    analyzed_total: int = 0
    #: INSTALLATION SCOPE: every root-cause group the current scan detected.
    #: Must not shrink because the most recent analysis request was small.
    #: Live defect this comment exists for: immediately after a 3-group
    #: request this read 3, and after a restart the same installation read
    #: 57, because one branch reported request scope and the others reported
    #: installation scope. A metric whose meaning depends on whether Home
    #: Assistant has rebooted is worse than no metric.
    groups_total: int = 0
    #: INSTALLATION SCOPE: groups covered by the last completed analysis.
    groups_analyzed: int = 0
    #: Groups whose provider call failed in the last run.
    failed_groups: int = 0
    #: REQUEST SCOPE: groups the most recent bounded request selected and
    #: analyzed. Deliberately separate fields -- these may legitimately be
    #: smaller than the installation totals above.
    request_groups_total: int = 0
    request_groups_analyzed: int = 0
    #: Recommendations currently held, and how many are stale.
    recommendation_total: int = 0
    stale_recommendations: int = 0
    #: Active P0/P1 incidents, and how many have no analysis covering them.
    high_priority_total: int = 0
    high_priority_unanalyzed: int = 0
    #: Provider health as the connector reports it.
    provider_status: str = "unknown"
    #: An analysis run is in flight.
    analysis_running: bool = False
    #: Analysis has never been requested on this installation.
    ever_analyzed: bool = False


@dataclass(frozen=True, slots=True)
class AnalysisStatus:
    """The single authoritative answer, plus the counts that justify it."""

    state: AnalysisState
    all_clear_permitted: bool
    reason: str
    pending_total: int
    inputs: AnalysisInputs

    def as_dict(self) -> dict[str, Any]:
        data = self.inputs
        return {
            "state": self.state.value,
            "all_clear_permitted": self.all_clear_permitted,
            "reason": self.reason,
            "current_scan_id": data.current_scan_id,
            "analyzed_scan_id": data.analyzed_scan_id,
            "eligible_total": data.eligible_total,
            "analyzed_total": data.analyzed_total,
            "pending_total": self.pending_total,
            "groups_total": data.groups_total,
            "groups_analyzed": data.groups_analyzed,
            "failed_groups": data.failed_groups,
            "request_groups_total": data.request_groups_total,
            "request_groups_analyzed": data.request_groups_analyzed,
            "recommendation_total": data.recommendation_total,
            "stale_recommendations": data.stale_recommendations,
            "high_priority_total": data.high_priority_total,
            "high_priority_unanalyzed": data.high_priority_unanalyzed,
            "provider_status": data.provider_status,
            "analysis_running": data.analysis_running,
        }


def evaluate(inputs: AnalysisInputs) -> AnalysisStatus:
    """Decide the analysis state and whether "All clear" is honest.

    Ordered so the most misleading situations are caught first. Every branch
    that returns `all_clear_permitted=False` does so because a reader would
    otherwise conclude something HAMIE has not established.
    """
    pending = max(0, inputs.eligible_total - inputs.analyzed_total)

    def _status(state: AnalysisState, permitted: bool, reason: str) -> AnalysisStatus:
        return AnalysisStatus(state, permitted, reason, pending, inputs)

    if inputs.analysis_running:
        return _status(
            AnalysisState.ANALYZING, False, "analysis is currently running"
        )

    if not inputs.ever_analyzed:
        return _status(
            AnalysisState.NOT_ANALYZED,
            False,
            "AI analysis has not been run against this installation",
        )

    if inputs.provider_status in ("error", "degraded"):
        return _status(
            AnalysisState.PROVIDER_UNAVAILABLE,
            False,
            f"the AI provider is {inputs.provider_status}",
        )

    # A run where every attempted group failed produced no information at all.
    if inputs.failed_groups and inputs.groups_analyzed == 0:
        return _status(
            AnalysisState.FAILED,
            False,
            f"all {inputs.failed_groups} analyzed group(s) failed",
        )

    if (
        inputs.analyzed_scan_id
        and inputs.current_scan_id
        and inputs.analyzed_scan_id != inputs.current_scan_id
    ):
        return _status(
            AnalysisState.STALE,
            False,
            "the current scan is newer than the last completed analysis",
        )

    # Unanalyzed P0/P1 outranks aggregate coverage: one unexamined safety
    # defect matters more than a high percentage of examined noise.
    if inputs.high_priority_unanalyzed:
        return _status(
            AnalysisState.PARTIALLY_ANALYZED,
            False,
            f"{inputs.high_priority_unanalyzed} high-priority incident(s) "
            "have not been analyzed",
        )

    if pending or inputs.failed_groups or (
        inputs.groups_total and inputs.groups_analyzed < inputs.groups_total
    ):
        detail = []
        if pending:
            detail.append(f"{pending} of {inputs.eligible_total} findings not analyzed")
        if inputs.groups_total and inputs.groups_analyzed < inputs.groups_total:
            detail.append(
                f"{inputs.groups_total - inputs.groups_analyzed} of "
                f"{inputs.groups_total} root-cause groups not analyzed"
            )
        if inputs.failed_groups:
            detail.append(f"{inputs.failed_groups} group(s) failed")
        return _status(
            AnalysisState.PARTIALLY_ANALYZED, False, "; ".join(detail)
        )

    if inputs.stale_recommendations and inputs.stale_recommendations == (
        inputs.recommendation_total
    ):
        return _status(
            AnalysisState.STALE,
            False,
            "every held recommendation is stale relative to the current scan",
        )

    return _status(
        AnalysisState.COMPLETE,
        True,
        "analysis covered every eligible finding in the current scan",
    )
