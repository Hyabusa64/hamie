"""Durable entity-successor knowledge (mission Parts 8/47/54/154).

Home Assistant's own registries never persist "this entity id was
replaced by that one" -- when a device is re-paired under a new
integration/config entry, or a template's own version-bumped
unique_id leaves its old entity_id dead, the *fact* that one specific
stale id was proven to have been replaced by one specific live id
only ever existed in a Claude conversation, a benchmark report, or a
human's memory before this module. ``duplicate_classifier.py`` already
computes a very similar-looking ``primary_entity_id`` (see
``domain/duplicate_classifier.py``'s ``DuplicateGroupDecision``), but
that is a *per-scan inference*, recomputed fresh every run and never
written anywhere durable -- there was previously no way for a
validated stale-reference-to-successor conclusion, once proven, to
make the next scan cheaper or quieter.

``EntitySuccessorRelationship`` is that durable record. It is
deliberately narrow: it only ever asserts "entity X is stale, entity Y
is its verified successor, here is why, here is who decided, here is
when" -- it never grants HAMIE (or anything reading it) authority to
rewrite Home Assistant configuration or the entity registry itself
(mission Part 27/28/158). A future remediation-recommendation consumer
may *cite* an active relationship as supporting evidence; nothing here
executes a repair.

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

SUCCESSOR_FINGERPRINT_VERSION = 1


class SuccessorRelationshipType(StrEnum):
    """How the stale entity relates to its canonical successor.

    Distinct kinds are kept separate (rather than one generic
    "successor") because the evidence that supports each looks
    different and a future consumer may reasonably trust them
    differently -- see each member's docstring.
    """

    # A device/integration re-registration or a template's own
    # version-bumped unique_id left the old entity_id dead; the new
    # entity_id is the same underlying capability continuing under a
    # new registry row (the bidet_plug_power -> bidet_plug_power_2
    # shape: zero registry matches for the old id, the new id's
    # unique_id/integration/creation-chronology evidence supports it
    # being the same physical sensor continuing).
    RENAMED_OR_RECREATED_SUCCESSOR = "renamed_or_recreated_successor"
    # An integration migration (cloud -> local, vendor -> official,
    # legacy -> core) produced a new entity_id for the same capability.
    MIGRATION_SUCCESSOR = "migration_successor"
    # The "successor" is not a different physical entity at all -- the
    # original defect was an action/service call using the wrong
    # domain against a still-correct target (mission Part 74); this
    # relationship records the domain-corrected target as the
    # canonical reference going forward.
    WRONG_DOMAIN_CORRECTED = "wrong_domain_corrected"
    # A human explicitly asserted the mapping rather than HAMIE/Claude
    # inferring it from registry/reference evidence.
    USER_ASSERTED_SUCCESSOR = "user_asserted_successor"


class SuccessorStatus(StrEnum):
    """Lifecycle of one successor relationship (mission Part 54)."""

    # Currently believed true; evidence has not been contradicted.
    ACTIVE = "active"
    # A newer relationship (see ``superseded_by_fingerprint``) replaced
    # this one -- kept, never deleted, for audit history.
    SUPERSEDED = "superseded"
    # Positively disproven (e.g. the stale entity reappeared in the
    # registry, or the canonical entity was itself removed).
    INVALIDATED = "invalidated"
    # Two knowledge sources disagree and confidence was insufficient to
    # pick a winner -- never silently resolved in either direction
    # (mission Part 24).
    CONFLICTING = "conflicting"
    # Identity/evidence fingerprints changed materially since
    # ``last_verified`` (mission Part 23); still usable as a hint, but
    # a future scan should re-confirm before relying on it further.
    PENDING_REVALIDATION = "pending_revalidation"


@dataclass(frozen=True, slots=True)
class EntitySuccessorRelationship:
    """One durable, evidence-backed stale-entity -> canonical-entity fact.

    Never self-authorizing: this record only ever describes a
    relationship HAMIE or a Claude-assisted investigation believes is
    true, with its supporting evidence and provenance attached. Nothing
    in this module rewrites configuration, the entity registry, or
    automation enablement -- see the module docstring.
    """

    stale_entity_id: str
    canonical_entity_id: str
    relationship_type: SuccessorRelationshipType
    confidence: Confidence
    evidence: tuple[EvidenceItem, ...]
    first_observed: datetime
    last_verified: datetime
    provenance: KnowledgeProvenance
    status: SuccessorStatus = SuccessorStatus.ACTIVE
    # Whether the *stale reference in configuration* has been repaired
    # (e.g. the YAML now points at canonical_entity_id). Independent of
    # ``behavior_changed`` -- a reference can be fixed in a disabled
    # automation/package with zero behavioral effect (the bidet case:
    # the reference was repaired, but the automations consuming it
    # remain off, per mission Part 47's explicit instruction that this
    # must be recorded as not having authorized any behavior change).
    reference_remediated: bool = False
    behavior_changed: bool = False
    source_artifact: str | None = None
    source_artifact_hash: str | None = None
    # Set only on a SUPERSEDED record -- the fingerprint of the
    # relationship that replaced it (mission Part 24: prior conclusions
    # are preserved, never mutated into whatever is currently believed).
    superseded_by_fingerprint: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        require_non_empty(self.stale_entity_id, "stale_entity_id")
        require_non_empty(self.canonical_entity_id, "canonical_entity_id")
        if self.stale_entity_id == self.canonical_entity_id:
            raise ValueError(
                "a successor relationship requires two distinct entity ids"
            )
        if not self.evidence:
            raise ValueError("entity successor relationship requires evidence")
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
            self.status is SuccessorStatus.SUPERSEDED
            and not (self.superseded_by_fingerprint or "").strip()
        ):
            raise ValueError("SUPERSEDED status requires superseded_by_fingerprint")
        if self.source_artifact is not None:
            require_non_empty(self.source_artifact, "source_artifact")
        if self.source_artifact_hash is not None:
            require_non_empty(self.source_artifact_hash, "source_artifact_hash")
        if len(self.notes) > 2_000:
            raise ValueError("notes must be 2000 characters or fewer")

    @property
    def fingerprint(self) -> str:
        """Stable identity of this stale->canonical *pair*.

        Deliberately independent of evidence/confidence/status content
        (see ``evidence_digest`` for that) so the same relationship
        keeps one durable identity across revalidation -- a fingerprint
        change would silently orphan review history and suppressions
        keyed to it.
        """
        return stable_digest(
            SUCCESSOR_FINGERPRINT_VERSION,
            "entity_successor",
            self.stale_entity_id,
            self.canonical_entity_id,
        )

    @property
    def relationship_id(self) -> str:
        """Return a compact stable identifier for storage/reference."""
        return f"hamie_successor_{self.fingerprint[:32]}"

    @property
    def evidence_digest(self) -> str:
        """Deterministic signature of the evidence-backed claim content.

        Changes whenever the evidence, confidence, relationship type,
        or remediation/behavior flags materially change -- the value a
        future revalidation check compares against a stored prior
        value to decide whether to move this record to
        ``PENDING_REVALIDATION`` (mission Part 53).
        """
        return stable_digest(
            self.fingerprint,
            self.relationship_type.value,
            self.confidence.level.value,
            tuple((item.code, item.effect) for item in self.confidence.factors),
            tuple(item.evidence_id for item in self.evidence),
            self.reference_remediated,
            self.behavior_changed,
        )
