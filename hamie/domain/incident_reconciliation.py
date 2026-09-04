"""Is this incident still real? -- asked separately from "can HAMIE fix it?".

A live investigation forced this module into existence. Every one of the 22
active P1 incidents produced `operator_decision_required` and zero repair
candidates, and it was tempting to read that as "these are false positives".
It is not. Checking the actual entities showed:

    sensor.master_bedroom_fan_reason        unavailable
    sensor.master_bedroom_fan_reason_2      "Bedroom vacant"

The old identity is retained and unavailable while its successor carries the
real state. That is exactly the duplicate/migration defect the incident
describes -- still true, still current. What deterministic rediscovery
disproved was *repairability*: you cannot derive a stale-reference
replacement when both identities exist in the registry. Those are different
questions, and an existence-based reconciliation would have closed a queue
full of real defects.

So this module answers ONE question -- current validity -- and deliberately
does not answer the other. Repairability already has a home in
application/incident_remediation.InvestigationDisposition and is not
duplicated here.

Two rules shape everything below:

1. **Category dispatch, never a generic existence check.** For a
   duplicate/migration defect the old entity existing is the problem, not
   evidence against it. For a self-referencing automation, entity existence
   is irrelevant entirely -- the defect lives in the configuration.
2. **Unknown means uncertain, not resolved.** A category without a rule is
   never auto-closed.

Pure and I/O-free; observations are gathered by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

RECONCILIATION_SCHEMA_VERSION = 1


class CurrentValidity(StrEnum):
    """Axis A: does fresh authoritative evidence show the defect NOW?

    Deliberately separate from IncidentLifecycle (durable user/scan
    decisions), from EvidenceStatus (how strong the evidence was when the
    finding was raised), and from InvestigationDisposition (whether a repair
    can be derived). Overloading any of those would reproduce the confusion
    this module exists to remove.
    """

    STILL_PRESENT = "still_present"
    NO_LONGER_PRESENT = "no_longer_present"
    NOT_A_PROBLEM = "not_a_problem"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    MANUAL_REVIEW = "manual_review"


#: Validity values that keep an incident in the actionable queue.
ACTIONABLE_VALIDITY = frozenset(
    {
        CurrentValidity.STILL_PRESENT,
        CurrentValidity.INSUFFICIENT_EVIDENCE,
        CurrentValidity.MANUAL_REVIEW,
    }
)

#: Validity values that may retire an incident from the active queue. Reached
#: only through a category rule with fresh evidence -- never by default.
RETIRED_VALIDITY = frozenset(
    {CurrentValidity.NO_LONGER_PRESENT, CurrentValidity.NOT_A_PROBLEM}
)

#: States that mean an entity identity is not currently serving.
STALE_STATES = frozenset({"unavailable", "unknown"})


@dataclass(frozen=True, slots=True)
class ReconciliationObservation:
    """Current, freshly-gathered facts about one incident's subjects.

    Everything here must come from the CURRENT scan and CURRENT config. A
    verdict built on a cached reverse-reference result or a previous scan's
    finding is exactly what this module refuses to accept.
    """

    #: entity_id -> current state string, or None when the entity is absent.
    subject_states: dict[str, str | None] = field(default_factory=dict)
    #: entity_id -> number of occurrences in ACTIVE configuration right now.
    config_references: dict[str, int] = field(default_factory=dict)
    #: The scan this observation belongs to. Absent means unprovable freshness.
    scan_id: str | None = None
    #: When the observation was taken.
    observed_at: datetime | None = None
    #: Evidence identifiers supporting the observation.
    evidence_ids: tuple[str, ...] = ()

    @property
    def is_fresh(self) -> bool:
        """Freshness is a property of the evidence, not of good intentions."""
        return bool(self.scan_id) and self.observed_at is not None


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    validity: CurrentValidity
    reason: str
    category: str
    rule: str
    subjects_absent: tuple[str, ...] = ()
    subjects_stale: tuple[str, ...] = ()
    referenced_subjects: tuple[str, ...] = ()
    scan_id: str | None = None
    observed_at: datetime | None = None
    evidence_ids: tuple[str, ...] = ()

    @property
    def actionable(self) -> bool:
        return self.validity in ACTIONABLE_VALIDITY

    @property
    def retired(self) -> bool:
        return self.validity in RETIRED_VALIDITY

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RECONCILIATION_SCHEMA_VERSION,
            "current_validity": self.validity.value,
            "actionable": self.actionable,
            "reason": self.reason,
            "category": self.category,
            "rule": self.rule,
            "subjects_absent": list(self.subjects_absent),
            "subjects_stale": list(self.subjects_stale),
            "referenced_subjects": list(self.referenced_subjects),
            "scan_id": self.scan_id,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "evidence_ids": list(self.evidence_ids[:20]),
        }


def _subjects(incident: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(item).split(":")[-1]
        for item in (incident.get("affected_subject_ids") or ())
        if "." in str(item)
    )


def _split(
    subjects: tuple[str, ...], observation: ReconciliationObservation
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """(absent, stale-but-present, referenced-in-current-config)."""
    absent, stale, referenced = [], [], []
    for entity_id in subjects:
        state = observation.subject_states.get(entity_id, "__unobserved__")
        if state is None:
            absent.append(entity_id)
        elif state != "__unobserved__" and str(state) in STALE_STATES:
            stale.append(entity_id)
        if observation.config_references.get(entity_id, 0) > 0:
            referenced.append(entity_id)
    return tuple(sorted(absent)), tuple(sorted(stale)), tuple(sorted(referenced))


def _result(validity, reason, category, rule, obs, absent=(), stale=(), refs=()):
    return ReconciliationResult(
        validity=validity, reason=reason, category=category, rule=rule,
        subjects_absent=absent, subjects_stale=stale, referenced_subjects=refs,
        scan_id=obs.scan_id, observed_at=obs.observed_at,
        evidence_ids=obs.evidence_ids,
    )


# ---------------------------------------------------------------------------
# Category rules
# ---------------------------------------------------------------------------


def _duplicate_migration(incident, observation, subjects):
    """Old identity retained and not serving, while references persist.

    Existence of the old entity is the DEFECT, not evidence against it. This
    is the rule the live data forced: master_bedroom_fan_reason is present
    and unavailable while _2 carries the state, and closing that on "both
    entities exist" would have discarded a real migration defect.
    """
    absent, stale, refs = _split(subjects, observation)
    category, rule = "duplicate_migration", "old_identity_not_serving_or_referenced"

    if absent:
        return _result(CurrentValidity.STILL_PRESENT,
                       f"{len(absent)} identity/identities are absent while the "
                       "incident's references remain",
                       category, rule, observation, absent, stale, refs)
    if stale:
        return _result(CurrentValidity.STILL_PRESENT,
                       f"the older identity is retained but not serving "
                       f"({', '.join(stale)}); a parallel identity carries the state",
                       category, rule, observation, absent, stale, refs)
    if refs:
        return _result(CurrentValidity.STILL_PRESENT,
                       "current configuration still references the duplicated identity",
                       category, rule, observation, absent, stale, refs)
    return _result(CurrentValidity.NO_LONGER_PRESENT,
                   "every identity is present and serving, and no current "
                   "configuration reference to the duplicate remains",
                   category, rule, observation, absent, stale, refs)


def _functional_bug(incident, observation, subjects):
    """The defect lives in the configuration relationship, not in entities.

    A self-referencing automation action is broken whether or not both
    entities are available, so entity state is deliberately not consulted for
    the verdict -- only whether the configuration still expresses it.
    """
    absent, stale, refs = _split(subjects, observation)
    category, rule = "functional_bug", "configuration_relationship_still_expressed"

    if not observation.config_references:
        return _result(CurrentValidity.INSUFFICIENT_EVIDENCE,
                       "no current configuration search was performed, so the "
                       "structural relationship could not be re-verified",
                       category, rule, observation, absent, stale, refs)
    if refs:
        return _result(CurrentValidity.STILL_PRESENT,
                       "current configuration still expresses the faulty "
                       f"relationship for {', '.join(refs[:3])}",
                       category, rule, observation, absent, stale, refs)
    return _result(CurrentValidity.NO_LONGER_PRESENT,
                   "the configuration no longer references the subjects that "
                   "formed this relationship",
                   category, rule, observation, absent, stale, refs)


def _hygiene(incident, observation, subjects):
    """An active writer still targeting a stale identity.

    Requires BOTH halves to stay present: a writer that still exists, and a
    target that is still stale. If the target became healthy the writer is no
    longer writing to a dead identity.
    """
    absent, stale, refs = _split(subjects, observation)
    category, rule = "hygiene", "writer_still_targets_stale_identity"

    if not observation.config_references:
        return _result(CurrentValidity.INSUFFICIENT_EVIDENCE,
                       "no current configuration search was performed",
                       category, rule, observation, absent, stale, refs)
    if refs and (absent or stale):
        return _result(CurrentValidity.STILL_PRESENT,
                       "an active writer still targets an identity that is "
                       "absent or not serving",
                       category, rule, observation, absent, stale, refs)
    if refs and not (absent or stale):
        return _result(CurrentValidity.NO_LONGER_PRESENT,
                       "the referenced identity is present and serving, so the "
                       "writer no longer targets a stale identity",
                       category, rule, observation, absent, stale, refs)
    return _result(CurrentValidity.NO_LONGER_PRESENT,
                   "no current configuration writer targets these identities",
                   category, rule, observation, absent, stale, refs)


#: category -> rule. Absence from this table is meaningful: see reconcile().
CATEGORY_RULES = {
    "duplicate_migration": _duplicate_migration,
    "functional_bug": _functional_bug,
    "hygiene": _hygiene,
}


def reconcile(
    incident: dict[str, Any], observation: ReconciliationObservation
) -> ReconciliationResult:
    """Decide current validity from fresh, category-appropriate evidence."""
    category = str(incident.get("category") or "unknown")
    subjects = _subjects(incident)

    if not observation.is_fresh:
        return _result(
            CurrentValidity.INSUFFICIENT_EVIDENCE,
            "the observation carries no scan identity or timestamp, so it "
            "cannot establish current truth",
            category, "freshness_required", observation,
        )
    if not subjects:
        return _result(
            CurrentValidity.MANUAL_REVIEW,
            "the incident names no entity subject that could be re-verified",
            category, "no_subjects", observation,
        )

    rule = CATEGORY_RULES.get(category)
    if rule is None:
        # Unknown means uncertain, not resolved. Auto-closing a category
        # nobody has written a rule for is how a reconciliation engine
        # quietly empties a queue of real defects.
        return _result(
            CurrentValidity.MANUAL_REVIEW,
            f"no reconciliation rule exists for category {category!r}; "
            "an unrecognised incident is never auto-closed",
            category, "unknown_category_fail_safe", observation,
        )
    return rule(incident, observation, subjects)
