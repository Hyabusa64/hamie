"""Deterministic entity-reference index (mission Part 12/13).

Pure, I/O-free: consumes already-captured ``ReferenceSourceResult``
values (``infrastructure/dependency_source.py`` builds these; nothing
here ever touches Home Assistant) and answers "is entity X referenced
anywhere HAMIE actually checked, and by what?"

Honesty is the entire point of this module. ``SCANNED_SOURCES`` is
every reference-bearing subsystem HAMIE actually attempts to scan this
release -- deliberately the sources a real, local, deterministic
"is this entity safe to disable" decision needs (automations, scripts,
scenes, groups, Lovelace dashboards, templates, entity-referencing
helpers, the Energy dashboard). Blueprint-instantiated automations and
scripts are covered *indirectly*: a blueprint only ever produces a
regular automation/script entity, and that entity's own
``referenced_entities`` already reflects whatever the instantiated
blueprint actually references -- there is no separate "blueprint"
reference surface to scan.

``UNSCANNED_SOURCES`` is deliberately narrower than earlier releases:
recorder/statistics answer a *different* question ("does this entity
have history?", not "does something depend on this entity?") and n8n/
HKG/MCP are optional *external* connectors a user may not have
configured at all -- none of the five belongs in the same
pass/fail gate a purely local cleanup decision uses. See
``domain/cleanup_classifier.py``'s dependency-coverage check and
``implemented_sources_succeeded`` below: a disabled/unconfigured
optional connector must never globally block an otherwise-complete
local cleanup decision, and recorder/statistics existing must never by
itself make an entity look "referenced".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import stable_digest

SCANNED_SOURCES = (
    "automation",
    "script",
    "scene",
    "group",
    "dashboard",
    "template",
    "helper",
    "energy",
)
# Context-only: informative, never gates implemented_sources_succeeded.
CONTEXT_ONLY_SOURCES = ("recorder", "statistics")
# Optional external connectors: informative when configured, never
# required, never gates implemented_sources_succeeded regardless of
# whether the user has them enabled at all.
OPTIONAL_EXTERNAL_SOURCES = ("n8n", "hkg", "mcp")
UNSCANNED_SOURCES = CONTEXT_ONLY_SOURCES + OPTIONAL_EXTERNAL_SOURCES


@dataclass(frozen=True, slots=True)
class ReferenceSourceResult:
    """One source's capture outcome -- honest, never fabricated.

    ``references`` is a bounded tuple of
    ``(referencing_object_id, referenced_entity_id)`` pairs.
    """

    source: str
    status: str  # "succeeded" | "unavailable" | "failed"
    references: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "unavailable", "failed"}:
            raise ValueError("invalid reference source status")
        if len(self.references) > 20_000:
            raise ValueError("reference source result exceeds bounded size")


@dataclass(frozen=True, slots=True)
class ReferenceHit:
    """One concrete reference to an entity, from one scanned source."""

    source: str
    referencing_object_id: str


@dataclass(frozen=True, slots=True)
class DependencyScanCoverage:
    """What was actually checked this scan -- never inferred as "everything"."""

    scanned_sources: tuple[str, ...]
    failed_sources: tuple[str, ...] = ()
    unavailable_sources: tuple[str, ...] = ()
    unscanned_sources: tuple[str, ...] = UNSCANNED_SOURCES

    @property
    def is_complete(self) -> bool:
        """Return whether every reference source that exists to scan succeeded.

        Never true while ``unscanned_sources`` is non-empty -- a
        genuinely exhaustive scan (every subsystem listed in
        ``UNSCANNED_SOURCES`` too) is only possible once HAMIE
        implements every one of them. Use this for future-proofing and
        tests, not for gating today's cleanup decisions -- see
        ``implemented_sources_succeeded``.
        """
        return (
            not self.failed_sources
            and not self.unavailable_sources
            and not self.unscanned_sources
            and bool(self.scanned_sources)
        )

    @property
    def implemented_sources_succeeded(self) -> bool:
        """Return whether every source HAMIE actually attempts this release succeeded.

        This is the practical, honest meaning of a "complete" dependency
        check for cleanup-eligibility purposes (mission Part 3/12):
        every automation/script/scene/group scan HAMIE knows how to run
        actually ran and returned a result, with none failed or
        unavailable. It is deliberately *not* the same claim as
        ``is_complete`` -- the cleanup classifier's evidence/rationale
        text must always disclose ``unscanned_sources`` alongside this,
        never imply Home Assistant was checked exhaustively.
        """
        return (
            bool(self.scanned_sources)
            and not self.failed_sources
            and not self.unavailable_sources
        )


@dataclass(slots=True)
class EntityReferenceIndex:
    """Queryable index of entity_id -> what references it."""

    references: dict[str, tuple[ReferenceHit, ...]] = field(default_factory=dict)
    coverage: DependencyScanCoverage = field(
        default_factory=lambda: DependencyScanCoverage(scanned_sources=())
    )

    def referenced_by(self, entity_id: str) -> tuple[ReferenceHit, ...]:
        return self.references.get(entity_id, ())

    def is_referenced(self, entity_id: str) -> bool:
        return bool(self.references.get(entity_id))


def reference_index_revision(index: EntityReferenceIndex | None) -> str:
    """Return a stable digest of one reference index's semantic content.

    Used by ``analysis/supervisor.py`` (mission Part 1.4/1.5) to fold a
    supplied ``EntityReferenceIndex`` into the analyzer partition cache
    key: without this, a scan whose live references genuinely changed
    (a dashboard reference removed, a new automation added) but whose
    entity-state partition otherwise hashed identically would silently
    return a stale cached ``AnalyzerOutcome`` computed against the
    *previous* reference index -- a real correctness bug the cache was
    never previously exposed to, because no caller threaded a reference
    index through the supervisor before this wiring pass. ``None``
    (no reference index supplied at all) gets its own stable sentinel,
    distinct from any real index's digest.
    """
    if index is None:
        return "no-reference-index"
    return stable_digest(
        tuple(
            sorted(
                (entity_id, hit.source, hit.referencing_object_id)
                for entity_id, hits in index.references.items()
                for hit in hits
            )
        ),
        index.coverage.scanned_sources,
        index.coverage.failed_sources,
        index.coverage.unavailable_sources,
        index.coverage.unscanned_sources,
    )


def build_reference_index(
    source_results: tuple[ReferenceSourceResult, ...],
) -> EntityReferenceIndex:
    """Build a deterministic reference index from captured source results."""
    references: dict[str, list[ReferenceHit]] = {}
    scanned: list[str] = []
    failed: list[str] = []
    unavailable: list[str] = []
    for result in source_results:
        if result.status == "succeeded":
            scanned.append(result.source)
            for referencing_object_id, target_entity_id in result.references:
                references.setdefault(target_entity_id, []).append(
                    ReferenceHit(
                        source=result.source,
                        referencing_object_id=referencing_object_id,
                    )
                )
        elif result.status == "unavailable":
            unavailable.append(result.source)
        else:
            failed.append(result.source)
    frozen_references = {key: tuple(value) for key, value in references.items()}
    coverage = DependencyScanCoverage(
        scanned_sources=tuple(scanned),
        failed_sources=tuple(failed),
        unavailable_sources=tuple(unavailable),
    )
    return EntityReferenceIndex(references=frozen_references, coverage=coverage)
