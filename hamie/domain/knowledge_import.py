"""Conservative importer for preserved remediation-evidence artifacts
(mission Parts 13/45/46/159).

Turns a HAMIE/Claude-assisted remediation session's preserved evidence
(the ``modified_this_session`` shape a ``phase_b1_actions.json``-style
artifact already uses) into durable ``EntitySuccessorRelationship``
knowledge -- and only that. This module never fabricates a mapping it
cannot read directly from the artifact's own structured fields.

**What gets imported.** A root-cause entry is only accepted when at
least one of its ``entities_affected`` strings is an explicit
``"<stale> -> <canonical>"`` pair. Deliberately conservative: several
real root causes in this project's own evidence (e.g.
``vacuum_self_reference``, ``example_appliance_self_reference``) only
list the *canonical* entities that were referenced correctly after the
fix, never the dead entity id the fix replaced -- recovering that dead
id would mean guessing a suffix-stripped base slug, which is exactly
the naming-alone inference ``domain/duplicate_classifier.py`` already
refuses to trust as evidence (mission Part 32). Those root causes are
recorded as ``skipped`` with an honest reason, never silently dropped
and never guessed at.

**What never gets imported.** Nothing here ever authorizes remediation
or changes what any HAMIE recommendation is allowed to execute --
imported knowledge is advisory context only (mission Part 158): a
future analyzer/consultation step may *cite* an imported relationship,
never act on it unattended.

Pure and I/O-free like every other ``domain/`` module: the caller (an
``infrastructure/`` adapter, or a one-off evidence-import script) reads
the artifact file and passes its already-parsed JSON document plus the
artifact's own path/hash in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .common import require_non_empty
from .evidence import EvidenceItem, EvidenceKind, Sensitivity
from .findings import Confidence, ConfidenceFactor, ConfidenceLevel
from .identity import SubjectIdentity
from .knowledge_provenance import KnowledgeProvenance
from .successors import (
    EntitySuccessorRelationship,
    SuccessorRelationshipType,
)

IMPORTER_ID = "hamie.knowledge_import.remediation_actions"
IMPORTER_RULE_VERSION = "1.0.0"
_ARROW = " -> "


@dataclass(frozen=True, slots=True)
class SkippedImportRecord:
    """One root-cause entry this importer declined to turn into knowledge."""

    root_cause_id: str
    source_file: str
    reason: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.root_cause_id, "root_cause_id"),
            (self.source_file, "source_file"),
            (self.reason, "reason"),
        ):
            require_non_empty(value, name)


@dataclass(frozen=True, slots=True)
class KnowledgeImportResult:
    """Everything one import run produced, accepted and declined alike."""

    accepted: tuple[EntitySuccessorRelationship, ...]
    skipped: tuple[SkippedImportRecord, ...]


def _parse_mapping(raw: str) -> tuple[str, str] | None:
    """Return ``(stale, canonical)`` if ``raw`` is an explicit mapping string."""
    if _ARROW not in raw:
        return None
    stale, _, canonical = raw.partition(_ARROW)
    stale = stale.strip()
    canonical = canonical.strip()
    if not stale or not canonical or stale == canonical:
        return None
    return stale, canonical


def _subject(entity_id: str) -> SubjectIdentity:
    return SubjectIdentity(
        durable_id=entity_id,
        kind="home_assistant.entity",
        source_instance="home_assistant",
        source_id=entity_id,
    )


def _confidence(*, sha256_verified: bool) -> Confidence:
    factors = [
        ConfidenceFactor(
            code="explicit_old_to_new_mapping_in_evidence",
            effect=40,
            rationale=(
                "the preserved evidence artifact records an explicit "
                "'<stale> -> <canonical>' mapping, not an inferred one"
            ),
        )
    ]
    if sha256_verified:
        factors.append(
            ConfidenceFactor(
                code="byte_verified_deployed_fix",
                effect=40,
                rationale=(
                    "the fix that established this mapping was byte-verified "
                    "(pre/post sha256 match) on the file it was applied to"
                ),
            )
        )
    return Confidence(
        level=ConfidenceLevel.HIGH if sha256_verified else ConfidenceLevel.MEDIUM,
        factors=tuple(factors),
        rule_revision=f"{IMPORTER_ID}@{IMPORTER_RULE_VERSION}",
    )


def _behavior_changed(activation_status: str | None) -> bool:
    """Conservative default: only ``True`` when the artifact says so directly.

    Every root cause in this project's evidence to date reports an
    ``activation_status`` of either ``deployed_inactive_pending_reload_or_restart``
    or ``deployed_but_no_live_behavior_change`` -- both mean the fix has
    not yet taken behavioral effect. A future artifact whose status text
    does not contain ``inactive``/``no_live_behavior_change`` is treated
    as unknown, not assumed active -- ``False`` unless positive evidence
    of a live behavior change is present.
    """
    if not activation_status:
        return False
    lowered = activation_status.lower()
    if "inactive" in lowered or "no_live_behavior_change" in lowered:
        return False
    return "behavior_changed" in lowered and "no_live_behavior_change" not in lowered


def import_entity_successors_from_remediation_actions(
    document: dict,
    *,
    source_artifact: str,
    source_artifact_hash: str,
    imported_at: datetime | None = None,
) -> KnowledgeImportResult:
    """Import durable successor knowledge from one remediation-actions document.

    ``document`` is the already-parsed JSON of a
    ``phase_b1_actions.json``-shaped artifact: a ``modified_this_session``
    list of ``{file, backup, sha256_verified, root_causes_fixed:
    [{id, description, entities_affected, ...}], activation_status}``
    entries. Any entry missing a required field is skipped (recorded,
    never silently dropped) rather than raising -- a malformed or
    partially-shaped artifact must not abort import of the entries that
    *are* well-formed.
    """
    require_non_empty(source_artifact, "source_artifact")
    require_non_empty(source_artifact_hash, "source_artifact_hash")
    observed_at = imported_at or datetime.now(UTC)
    if observed_at.tzinfo is None:
        raise ValueError("imported_at must be timezone-aware")

    accepted: list[EntitySuccessorRelationship] = []
    skipped: list[SkippedImportRecord] = []

    entries = document.get("modified_this_session")
    if not isinstance(entries, list):
        return KnowledgeImportResult(accepted=(), skipped=())

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_file = entry.get("file")
        if not isinstance(source_file, str) or not source_file.strip():
            continue
        sha256_verified = bool(entry.get("sha256_verified", False))
        activation_status = entry.get("activation_status")
        root_causes = entry.get("root_causes_fixed")
        if not isinstance(root_causes, list):
            continue
        for root_cause in root_causes:
            if not isinstance(root_cause, dict):
                continue
            root_cause_id = root_cause.get("id")
            if not isinstance(root_cause_id, str) or not root_cause_id.strip():
                continue
            affected = root_cause.get("entities_affected")
            mappings = [
                mapping
                for mapping in (
                    _parse_mapping(item)
                    for item in (affected if isinstance(affected, list) else [])
                    if isinstance(item, str)
                )
                if mapping is not None
            ]
            if not mappings:
                skipped.append(
                    SkippedImportRecord(
                        root_cause_id=root_cause_id,
                        source_file=source_file,
                        reason=(
                            "entities_affected contains no explicit "
                            "'<stale> -> <canonical>' mapping -- importing "
                            "would require guessing the stale entity id from "
                            "a naming pattern, which this importer refuses "
                            "to do (see module docstring)"
                        ),
                    )
                )
                continue
            description = root_cause.get("description")
            relationship_type = (
                SuccessorRelationshipType.WRONG_DOMAIN_CORRECTED
                if root_cause.get("action_verb_changed")
                else SuccessorRelationshipType.RENAMED_OR_RECREATED_SUCCESSOR
            )
            for stale_entity_id, canonical_entity_id in mappings:
                evidence_items: list[EvidenceItem] = [
                    EvidenceItem(
                        subject=_subject(canonical_entity_id),
                        predicate="hamie.knowledge_import.source_file@1",
                        value=source_file,
                        observed_at=observed_at,
                        source_id=source_artifact,
                        source_revision=source_artifact_hash,
                        kind=EvidenceKind.ASSERTED,
                        sensitivity=Sensitivity.PUBLIC,
                    ),
                    EvidenceItem(
                        subject=_subject(canonical_entity_id),
                        predicate="hamie.knowledge_import.sha256_verified@1",
                        value=sha256_verified,
                        observed_at=observed_at,
                        source_id=source_artifact,
                        source_revision=source_artifact_hash,
                        kind=EvidenceKind.ASSERTED,
                        sensitivity=Sensitivity.PUBLIC,
                    ),
                ]
                if isinstance(description, str) and description.strip():
                    evidence_items.append(
                        EvidenceItem(
                            subject=_subject(canonical_entity_id),
                            predicate="hamie.knowledge_import.remediation_description@1",
                            value=description[:1_500],
                            observed_at=observed_at,
                            source_id=source_artifact,
                            source_revision=source_artifact_hash,
                            kind=EvidenceKind.ASSERTED,
                            sensitivity=Sensitivity.PUBLIC,
                        )
                    )
                accepted.append(
                    EntitySuccessorRelationship(
                        stale_entity_id=stale_entity_id,
                        canonical_entity_id=canonical_entity_id,
                        relationship_type=relationship_type,
                        confidence=_confidence(sha256_verified=sha256_verified),
                        evidence=tuple(evidence_items),
                        first_observed=observed_at,
                        last_verified=observed_at,
                        provenance=KnowledgeProvenance.IMPORTED_EVIDENCE_ARTIFACT,
                        reference_remediated=True,
                        behavior_changed=_behavior_changed(activation_status),
                        source_artifact=source_artifact,
                        source_artifact_hash=source_artifact_hash,
                        notes=(
                            f"imported from root_cause '{root_cause_id}' in "
                            f"{source_file}"
                        ),
                    )
                )

    return KnowledgeImportResult(accepted=tuple(accepted), skipped=tuple(skipped))


def merge_entity_successors(
    existing: tuple[EntitySuccessorRelationship, ...],
    imported: tuple[EntitySuccessorRelationship, ...],
) -> tuple[EntitySuccessorRelationship, ...]:
    """Idempotently merge imported relationships into an existing set.

    A relationship whose ``fingerprint`` already exists in ``existing``
    is never duplicated or overwritten by a re-import -- re-running the
    same import against the same artifact is always a no-op (mission
    Part 45: "importing the same evidence twice must not create
    duplicate knowledge records"). Updating an already-known
    relationship with genuinely new evidence is a distinct, explicit
    operation this function deliberately does not perform.
    """
    known_fingerprints = {item.fingerprint for item in existing}
    additions = tuple(
        item for item in imported if item.fingerprint not in known_fingerprints
    )
    return existing + additions
