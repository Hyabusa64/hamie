"""Tests for analysis/duplicate_group_scan.py's source-definition wiring.

Covers two things fixed in this pass:

1. ``_member_for_record`` now prefers the already-populated
   ``EntityRecord.source_definition_missing`` (computed once per scan by
   ``infrastructure/ha_source.py``) over re-deriving the same answer via
   a separately-supplied ``SourceDefinitionIndex`` -- avoiding a second,
   redundant config-tree parse in the same scan. The explicit
   ``SourceDefinitionIndex`` path is kept as a fallback for a record
   whose field was never populated.
2. ``DuplicateGroupMember.unique_id`` was previously populated from
   ``record.registry_id`` (the registry row's internal ``.id``) instead
   of the entity's real HA registry ``unique_id`` -- a pre-existing
   mislabeling bug this pass also fixes, now that ``EntityRecord`` has a
   real, distinct ``unique_id`` field to source it from.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hamie.analysis.duplicate_group_scan import _member_for_record, scan_duplicate_groups
from hamie.application.ports import EntityRecord
from hamie.infrastructure.source_definition_index import (
    ConfigSourceFile,
    SourceDefinitionIndex,
)

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)


def _rec(
    entity_id: str,
    *,
    state: str = "on",
    disabled: bool = False,
    registry_id: str | None = None,
    unique_id: str | None = None,
    source_definition_missing: bool | None = None,
    created_at: str | None = None,
) -> EntityRecord:
    domain = entity_id.partition(".")[0]
    return EntityRecord(
        entity_id=entity_id,
        state=state,
        last_changed=NOW,
        last_updated=NOW,
        registry_id=registry_id or f"reg-{entity_id}",
        unique_id=unique_id,
        device_id=None,
        config_entry_id=None,
        disabled=disabled,
        restored=False,
        domain=domain,
        platform="automation",
        source_definition_missing=source_definition_missing,
        created_at=created_at,
    )


def test_member_for_record_prefers_already_populated_field_over_index() -> None:
    """An index that would say PRESENT must not override a record whose
    source_definition_missing field was already computed as True by the
    live capture -- the record's own value always wins.
    """
    record = _rec(
        "automation.foo", disabled=True, source_definition_missing=True
    )
    index = SourceDefinitionIndex.build(
        (
            ConfigSourceFile(
                path="automations.yaml",
                content="- id: reg-automation.foo\n  alias: still here\n",
            ),
        )
    )
    member = _member_for_record(record, reference_index=None, source_index=index)
    assert member.source_definition_missing is True


def test_member_for_record_falls_back_to_index_when_field_unset() -> None:
    """When the record never had the field populated (e.g. a caller that
    did not go through HomeAssistantOperationalSource), the explicit
    SourceDefinitionIndex fallback still works.
    """
    record = _rec(
        "automation.orphan",
        disabled=True,
        unique_id="orphan_id",
        source_definition_missing=None,
    )
    index = SourceDefinitionIndex.build(())  # nothing defined anywhere
    member = _member_for_record(record, reference_index=None, source_index=index)
    assert member.source_definition_missing is True


def test_member_for_record_uses_real_unique_id_not_registry_row_id() -> None:
    """Pre-existing bug fix: DuplicateGroupMember.unique_id must carry
    the entity's real HA registry unique_id, not registry_id (the
    registry row's own internal .id, a different HA concept entirely).
    """
    record = _rec(
        "automation.foo",
        registry_id="internal-row-abc123",
        unique_id="the_real_unique_id",
    )
    member = _member_for_record(record, reference_index=None, source_index=None)
    assert member.unique_id == "the_real_unique_id"
    assert member.unique_id != record.registry_id


def test_scan_duplicate_groups_end_to_end_with_populated_field_only() -> None:
    """The whole-collection scan works correctly with zero SourceDefinitionIndex
    supplied at all, relying purely on EntityRecord.source_definition_missing
    -- the exact shape a real scan produces after this pass's ha_source.py fix.
    """
    records = (
        _rec(
            "automation.foo",
            state="unavailable",
            disabled=True,
            source_definition_missing=True,
            created_at="2024-01-01T00:00:00+00:00",
        ),
        _rec(
            "automation.foo_2",
            state="on",
            disabled=False,
            source_definition_missing=False,
            created_at="2026-01-01T00:00:00+00:00",
        ),
    )
    result = scan_duplicate_groups(records)
    assert result.groups_considered == 1
    decision = result.decisions[0]
    assert decision.classification.value == "likely_migration_leftover"
    assert decision.primary_entity_id == "automation.foo_2"
