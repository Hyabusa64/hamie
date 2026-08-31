"""Whole-installation duplicate/migration-leftover group scan (mission Part 3c).

Deliberately **not** built on the ``AnalysisPartition``/``AnalyzerDescriptor``
contract every other analyzer in ``analysis/analyzers/`` uses. That
contract's whole point (see ``analysis/contracts.py`` and
``analysis/supervisor.py``) is safe, cache-friendly *partitioning* --
each partition is analyzed independently, and ``AnalysisPartition``
requires its subjects to be unique but says nothing about which
subjects land in which partition together. Suffix-duplicate grouping
(``domain/duplicate_classifier.py::group_suffix_siblings``) is
structurally a **whole-collection** operation: ``light.island_lamp``
and ``light.island_lamp_2`` must be compared to each other, and nothing
in the partitioning contract guarantees two suffix siblings ever land
in the same partition (partitions are sliced from the sorted entity
list at a fixed batch size -- a sibling pair can straddle a batch
boundary). Forcing this into a per-partition analyzer would silently
produce wrong answers (a group split across two partitions looks like
two separate, ungrouped entities) rather than an honestly incomplete
one -- so this module runs once over the *whole* captured entity set
instead, exactly like ``domain/cleanup_classifier.py::compute_parent_unavailable_ratios``
already does for the same structural reason (a device's sibling-outage
ratio is also a whole-collection computation, not a per-partition one).

Still pure and I/O-free: every input (entity records, the reference
index, the source-definition index) is already computed by a caller.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..application.ports import EntityRecord
from ..domain.dependency_references import EntityReferenceIndex
from ..domain.duplicate_classifier import (
    DuplicateGroupDecision,
    DuplicateGroupMember,
    classify_duplicate_group,
    group_suffix_siblings,
)
from ..infrastructure.source_definition_index import (
    SourceDefinitionIndex,
    SourceDefinitionStatus,
)

_DEFINITION_DOMAINS = frozenset({"automation", "script", "scene"})


@dataclass(frozen=True, slots=True)
class DuplicateGroupScanResult:
    """Bounded result of one whole-installation duplicate-group scan."""

    decisions: tuple[DuplicateGroupDecision, ...]
    groups_considered: int


def _member_for_record(
    record: EntityRecord,
    *,
    reference_index: EntityReferenceIndex | None,
    source_index: SourceDefinitionIndex | None,
) -> DuplicateGroupMember:
    referenced_by_count = (
        len(reference_index.referenced_by(record.entity_id))
        if reference_index is not None
        else 0
    )
    # ``record.source_definition_missing`` is the authoritative,
    # already-computed answer: ``infrastructure/ha_source.py`` builds
    # exactly one ``SourceDefinitionIndex`` per scan and populates this
    # field for every automation/script/scene entity from it (see
    # ``HomeAssistantOperationalSource._build_source_definition_index``).
    # Preferring it here means this whole-collection scan never
    # re-parses the config tree a second time in the same scan.
    # ``source_index`` is kept only as an explicit fallback for a
    # caller that has one but a record whose field was never populated
    # (e.g. a test constructing records directly, or a future caller
    # that has not gone through ``HomeAssistantOperationalSource``) --
    # never both computed and disagreeing silently, since the record's
    # own value always wins when present.
    source_definition_missing = record.source_definition_missing
    if (
        source_definition_missing is None
        and source_index is not None
        and record.domain in _DEFINITION_DOMAINS
    ):
        result = source_index.lookup(
            entity_id=record.entity_id,
            domain=record.domain,
            platform=record.platform,
            unique_id=record.unique_id,
        )
        if result.status is SourceDefinitionStatus.MISSING_CONFIRMED:
            source_definition_missing = True
        elif result.status is SourceDefinitionStatus.PRESENT:
            source_definition_missing = False
    available = None if record.state is None else record.state not in (
        "unavailable",
        "unknown",
    )
    return DuplicateGroupMember(
        entity_id=record.entity_id,
        unique_id=record.unique_id,
        platform=record.platform,
        config_entry_id=record.config_entry_id,
        device_id=record.device_id,
        area_id=record.area_id,
        disabled=bool(record.disabled),
        available=available,
        referenced_by_count=referenced_by_count,
        created_at=record.created_at,
        source_definition_missing=source_definition_missing,
    )


def build_duplicate_group_member(
    record: EntityRecord,
    *,
    reference_index: EntityReferenceIndex | None = None,
    source_index: SourceDefinitionIndex | None = None,
) -> DuplicateGroupMember:
    """Public re-export of ``_member_for_record`` (mission Part 2): the
    new self-reference-regression/abandoned-bugfix-fork analyzers need
    the exact same ``EntityRecord`` -> ``DuplicateGroupMember`` mapping
    ``scan_duplicate_groups`` already uses, rather than a second,
    possibly-drifting reimplementation.
    """
    return _member_for_record(
        record, reference_index=reference_index, source_index=source_index
    )


def scan_duplicate_groups(
    records: tuple[EntityRecord, ...],
    *,
    reference_index: EntityReferenceIndex | None = None,
    source_index: SourceDefinitionIndex | None = None,
) -> DuplicateGroupScanResult:
    """Group suffix siblings across the whole capture and classify each group.

    ``reference_index``/``source_index`` are optional: omitting either
    is always safe (every member simply carries less evidence, which
    ``classify_duplicate_group`` already treats conservatively -- see
    ``DuplicateGroupMember.is_clearly_alive``/``is_orphaned_or_dead``,
    both of which require corroborating signals rather than assuming
    the best or worst case from partial information).
    """
    entity_ids = tuple(item.entity_id for item in records)
    by_entity_id = {item.entity_id: item for item in records}
    groups = group_suffix_siblings(entity_ids)

    decisions: list[DuplicateGroupDecision] = []
    for group_key, member_ids in groups.items():
        members = tuple(
            _member_for_record(
                by_entity_id[entity_id],
                reference_index=reference_index,
                source_index=source_index,
            )
            for entity_id in member_ids
        )
        decisions.append(classify_duplicate_group(group_key, members))

    return DuplicateGroupScanResult(
        decisions=tuple(
            sorted(decisions, key=lambda item: item.group_key)
        ),
        groups_considered=len(groups),
    )
