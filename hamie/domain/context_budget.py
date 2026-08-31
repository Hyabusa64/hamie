"""Deterministic context budgeting for provider requests.

Measured on this installation before it was written. The previous pipeline
applied the configured `maximum_input_characters` budget to the FINDINGS list
only, then added everything else on top:

    findings (budgeted)              16,000 chars
    + coverage.selected_finding_ids   3,948 chars   -- every id, in EVERY
                                                       per-group request
    + up to three incident public_dicts, largest measured 14,124 chars each,
      because Incident.public_dict carries finding_ids[:100] and
      affected_subject_ids[:100]
    ---------------------------------------------------
    worst case observed              48,737 chars = 3.0x the budget

which is where `evidence_payload_too_large` came from. Raising the configured
maximum would not have fixed it: the overhead scales with how many groups the
run analyzes and how large the incidents are, so a bigger number just moves
the cliff.

Two rules here:

1. **Budget the whole request, not the interesting part of it.** The
   allowance handed to the evidence planner is what is left after the
   envelope, the instructions and the response reserve are subtracted.
2. **Send accounting as counts, evidence as evidence.** A list of 94 finding
   ids tells the model nothing it can act on; it is coverage bookkeeping for
   the operator. Identifiers the model may want are retrievable through the
   bounded HAMIE investigation tools instead of being pushed into every
   prompt.

Pure and I/O-free, like the rest of `domain/`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

#: Below this, an evidence allowance cannot carry even one useful finding.
MINIMUM_EVIDENCE_ALLOWANCE = 500

#: What a compact incident summary is allowed to cost. Chosen so three of
#: them plus the envelope stay far inside a small local model's context.
MAX_COMPACT_INCIDENT_CHARACTERS = 900

#: Incidents attached as context to one provider request. Three was the
#: previous behaviour and remains right: enough to relate a group to its
#: root causes, few enough that the compact summaries stay cheap.
MAX_PROVIDER_INCIDENTS = 3

#: Representative subjects kept per incident. The full list is retrievable
#: through hamie_get_incident when the model actually needs it.
MAX_REPRESENTATIVE_SUBJECTS = 5


def payload_characters(payload: Any) -> int:
    """Deterministic size of a payload as it will be serialized."""
    return len(json.dumps(payload, sort_keys=True, default=str))


def _clip(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def compact_incident(incident: dict[str, Any]) -> dict[str, Any]:
    """A bounded incident summary for provider context.

    Deliberately drops `finding_ids` and `affected_subject_ids`, which are
    the two fields that made a single incident cost 14 KB. Counts and a few
    representative subjects carry the same meaning for a model deciding what
    to investigate next, and the full lists remain one bounded tool call away.
    """
    subjects = list(incident.get("affected_subject_ids") or ())
    summary = {
        "incident_id": incident.get("incident_id"),
        "title": _clip(incident.get("title"), 160),
        "root_cause": _clip(incident.get("root_cause"), 300),
        "category": incident.get("category"),
        "priority": incident.get("priority"),
        "evidence_status": incident.get("evidence_status"),
        "lifecycle": incident.get("lifecycle"),
        "finding_count": incident.get("finding_count", len(incident.get("finding_ids") or ())),
        "affected_subject_count": incident.get("affected_subject_count", len(subjects)),
        "representative_subjects": subjects[:MAX_REPRESENTATIVE_SUBJECTS],
        "recommended_next_step": _clip(incident.get("recommended_next_step"), 200),
        "detail_available_via_tool": "hamie_get_incident",
    }
    if len(subjects) > MAX_REPRESENTATIVE_SUBJECTS:
        summary["subjects_truncated"] = True

    # Shrink prose before evidence. root_cause and recommended_next_step are
    # restatements the model can also get from the incident itself, whereas a
    # representative subject is a concrete identifier it can investigate --
    # trimming those first would trade the useful part for the narration.
    for field, limit in (
        ("recommended_next_step", 120),
        ("root_cause", 180),
        ("title", 100),
        ("root_cause", 100),
    ):
        if payload_characters(summary) <= MAX_COMPACT_INCIDENT_CHARACTERS:
            return summary
        summary[field] = _clip(summary[field], limit)

    while (
        payload_characters(summary) > MAX_COMPACT_INCIDENT_CHARACTERS
        and summary["representative_subjects"]
    ):
        summary["representative_subjects"] = summary["representative_subjects"][:-1]
        summary["subjects_truncated"] = True
    return summary


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """What a single provider request may cost, and what is left for evidence."""

    maximum_characters: int
    #: Held back so the model has room to answer inside its context window.
    response_reserve_characters: int
    #: Everything that is not evidence: envelope, instructions, coverage
    #: counts, compact incident context.
    overhead_characters: int

    def __post_init__(self) -> None:
        if self.maximum_characters < 1:
            raise ValueError("maximum_characters must be positive")
        if self.response_reserve_characters < 0 or self.overhead_characters < 0:
            raise ValueError("budget reserves cannot be negative")

    @property
    def evidence_allowance(self) -> int:
        """Characters the evidence planner may actually spend."""
        return max(
            0,
            self.maximum_characters
            - self.response_reserve_characters
            - self.overhead_characters,
        )

    @property
    def viable(self) -> bool:
        return self.evidence_allowance >= MINIMUM_EVIDENCE_ALLOWANCE

    def as_dict(self) -> dict[str, Any]:
        return {
            "maximum_characters": self.maximum_characters,
            "response_reserve_characters": self.response_reserve_characters,
            "overhead_characters": self.overhead_characters,
            "evidence_allowance": self.evidence_allowance,
            "viable": self.viable,
        }


@dataclass(frozen=True, slots=True)
class FitResult:
    """Outcome of forcing a payload inside its budget."""

    payload: dict[str, Any]
    characters: int
    within_budget: bool
    dropped_incidents: bool = False
    dropped_findings: int = 0

    @property
    def truncated(self) -> bool:
        return self.dropped_incidents or bool(self.dropped_findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "characters": self.characters,
            "within_budget": self.within_budget,
            "truncated": self.truncated,
            "dropped_incidents": self.dropped_incidents,
            "dropped_findings": self.dropped_findings,
        }


def fit_payload(payload: dict[str, Any], maximum_characters: int) -> FitResult:
    """Force one assembled payload inside its budget, deterministically.

    Shrinks in a fixed order -- advisory incident context first, then
    evidence from the tail -- so the same input always produces the same
    request. Every reduction is reported: a request that quietly dropped
    half its evidence and returned a confident answer is worse than one
    that says it was truncated.

    Never returns an oversized payload silently; `within_budget` is False
    when even an empty evidence list does not fit, and the caller must
    refuse rather than send.
    """
    working = dict(payload)
    dropped_incidents = False
    dropped_findings = 0

    size = payload_characters(working)
    if size <= maximum_characters:
        return FitResult(working, size, True)

    if working.get("incidents"):
        working["incidents"] = []
        working["incident_context_dropped"] = True
        dropped_incidents = True
        size = payload_characters(working)
        if size <= maximum_characters:
            return FitResult(working, size, True, True, 0)

    findings = list(working.get("findings") or ())
    while findings and size > maximum_characters:
        findings.pop()
        dropped_findings += 1
        working["findings"] = findings
        working["evidence_truncated"] = True
        working["evidence_dropped_count"] = dropped_findings
        size = payload_characters(working)

    return FitResult(
        working,
        size,
        size <= maximum_characters and bool(findings),
        dropped_incidents,
        dropped_findings,
    )
