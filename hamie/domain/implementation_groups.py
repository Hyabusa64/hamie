"""Durable implementation-group knowledge (mission Parts 9/48/161/179-182).

A suffix-duplicate group (``domain/duplicate_classifier.py``) answers
"do these entities look like the same thing registered twice." An
*implementation group* answers a related but different question:
"do these subjects (often automations/scripts/packages, not bare
entities) represent multiple generations or parallel versions of the
same conceptual feature, where picking a single authoritative one is a
product/behavior decision -- not a technical defect to fix."

The master-toilet case is the exact motivating example (mission Part
48): ``automation.master_toilet_adaptive_light`` (v2),
``automation.master_toilet_adaptive_light_2`` (this package's
automation), and ``automation.master_toilet_adaptive_light_v3_5`` are
three real, independently-defined automations. Only one is currently
enabled. Nothing about that shape is a bug HAMIE can fix by editing
config -- it is a "which one should be authoritative" decision that
belongs to a human, every time, permanently (mission Part 179-182:
never auto-enable, auto-disable, or auto-delete any member because a
group exists).

Before this module, "this looks like an intentional parallel/versioned
implementation, don't recommend deleting anything" was an *emergent*
property of several analyzers' individually conservative defaults
(``duplicate_classifier.py``'s ``ACTIVE_OLD_ID_WITH_NEW_SIBLING``,
``abandoned_bugfix_fork.py``'s marker+zero-evidence gate) -- correct in
effect, but there was no durable, queryable, first-class record a
human or a future analyzer could point at and ask "is this already a
known implementation group, and what did we already establish about
it."

Pure and I/O-free like every other ``domain/`` module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .common import require_non_empty, require_utc, stable_digest
from .evidence import EvidenceItem
from .findings import Confidence
from .knowledge_provenance import KnowledgeProvenance

IMPLEMENTATION_GROUP_FINGERPRINT_VERSION = 1


class ImplementationGroupClassification(StrEnum):
    """Every implementation group lands in exactly one of these."""

    # Multiple automations/scripts/packages implement related or
    # overlapping behavior across generations (v1/v2/v3-style), or as
    # deliberately separate concurrent implementations -- selecting one
    # as authoritative is a product decision, not a technical cleanup
    # (the master-toilet case).
    PARALLEL_OR_VERSIONED_IMPLEMENTATIONS = "parallel_or_versioned_implementations"
    # Two or more subjects were investigated and are confirmed to be
    # intentionally separate/coexisting by design (e.g. a device
    # legitimately exposing both a raw vendor sensor and a normalized
    # template sensor) -- distinct from the above in that there is no
    # unresolved "which one should be authoritative" question at all.
    INTENTIONAL_PARALLEL_CAPABILITY = "intentional_parallel_capability"


@dataclass(frozen=True, slots=True)
class UnresolvedDecision:
    """One explicit, unresolved product/behavior question about a group.

    Kept separate from a technical defect: a ``decision_type`` of
    ``user_product_decision`` is never something HAMIE guesses at
    (mission Part 179-182) -- it is recorded so the question is not
    silently dropped and does not have to be rediscovered by hand every
    scan.
    """

    decision_type: str
    question: str
    context: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.decision_type, "decision_type"),
            (self.question, "question"),
            (self.context, "context"),
        ):
            require_non_empty(value, name)


@dataclass(frozen=True, slots=True)
class ImplementationGroup:
    """One durable, evidence-backed group of related implementations.

    ``automatic_cleanup_allowed`` is structurally pinned to ``False`` in
    ``__post_init__`` -- not merely defaulted -- so no future caller can
    construct a group that claims automatic cleanup authority by
    passing a truthy value; the field exists (per mission Part 9) so a
    consumer can see explicitly that cleanup is prohibited, never so it
    could be flipped on.
    """

    group_id: str
    members: tuple[str, ...]
    classification: ImplementationGroupClassification
    confidence: Confidence
    evidence: tuple[EvidenceItem, ...]
    first_observed: datetime
    last_verified: datetime
    provenance: KnowledgeProvenance
    unresolved_decision: UnresolvedDecision | None = None
    automatic_cleanup_allowed: bool = False
    source_artifact: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        require_non_empty(self.group_id, "group_id")
        if self.automatic_cleanup_allowed:
            raise ValueError(
                "automatic_cleanup_allowed must always be False -- "
                "implementation-group membership never authorizes "
                "automatic cleanup (mission Part 9/179-182)"
            )
        members = tuple(sorted(set(self.members)))
        if len(members) < 2:
            raise ValueError("an implementation group requires 2+ members")
        if any(not item or item != item.strip() for item in members):
            raise ValueError("members must be non-empty normalized strings")
        object.__setattr__(self, "members", members)
        if not self.evidence:
            raise ValueError("implementation group requires evidence")
        first_observed = require_utc(self.first_observed, "first_observed")
        last_verified = require_utc(self.last_verified, "last_verified")
        if last_verified < first_observed:
            raise ValueError("last_verified cannot precede first_observed")
        object.__setattr__(self, "first_observed", first_observed)
        object.__setattr__(self, "last_verified", last_verified)
        object.__setattr__(
            self,
            "evidence",
            tuple(sorted(self.evidence, key=lambda item: item.evidence_id)),
        )
        if (
            self.classification
            is ImplementationGroupClassification.PARALLEL_OR_VERSIONED_IMPLEMENTATIONS
            and self.unresolved_decision is None
        ):
            raise ValueError(
                "PARALLEL_OR_VERSIONED_IMPLEMENTATIONS requires an "
                "unresolved_decision -- that classification exists "
                "precisely because a human decision is still open"
            )
        if self.source_artifact is not None:
            require_non_empty(self.source_artifact, "source_artifact")
        if len(self.notes) > 2_000:
            raise ValueError("notes must be 2000 characters or fewer")

    @property
    def fingerprint(self) -> str:
        """Stable identity of this group's *membership set*.

        Deliberately independent of evidence/confidence content. A
        membership change (a member added or removed) changes this
        fingerprint on purpose (mission Part 23: "implementation
        group's members change -> flag the group for review") -- a
        stored record whose fingerprint no longer matches the group as
        currently reconstructed is the reopening signal.
        """
        return stable_digest(
            IMPLEMENTATION_GROUP_FINGERPRINT_VERSION,
            "implementation_group",
            self.group_id,
            self.members,
        )

    @property
    def group_record_id(self) -> str:
        """Return a compact stable identifier for storage/reference."""
        return f"hamie_implgroup_{self.fingerprint[:32]}"
