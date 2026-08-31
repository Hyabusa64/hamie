"""Tests for domain/duplicate_classifier.py (mission Part 3c/5).

The required guarantee: a suffix match alone (``foo``/``foo_2``) must
never be enough, on its own, to call two entities a migration-leftover
duplicate -- distinct devices/config entries/areas must win out.
"""

from __future__ import annotations

import pytest

from hamie.domain.duplicate_classifier import (
    DuplicateGroupClassification,
    DuplicateGroupMember,
    classify_duplicate_group,
    group_suffix_siblings,
)


def test_group_suffix_siblings_groups_bare_base_with_numbered_siblings() -> None:
    groups = group_suffix_siblings(
        ("light.island_lamp", "light.island_lamp_2", "light.other")
    )
    assert groups == {"light.island_lamp": ("light.island_lamp", "light.island_lamp_2")}


def test_group_suffix_siblings_ignores_lone_numbered_entity() -> None:
    """An entity object_id that merely ends in a digit, with no sibling
    at all, is not a duplicate group.
    """
    groups = group_suffix_siblings(("sensor.channel_2", "sensor.unrelated"))
    assert groups == {}


def test_suffix_alone_is_not_enough_distinct_devices_are_not_a_leftover() -> None:
    """Two members sharing a base name but backed by different devices,
    config entries, and areas, both actively in use, must be
    LIKELY_DISTINCT_ENTITIES -- never blindly grouped as a duplicate to
    clean up just because their names collided.
    """
    members = (
        DuplicateGroupMember(
            entity_id="switch.plug",
            unique_id="uid-a",
            platform="tplink",
            config_entry_id="entry-a",
            device_id="device-a",
            area_id="kitchen",
            disabled=False,
            available=True,
            referenced_by_count=1,
        ),
        DuplicateGroupMember(
            entity_id="switch.plug_2",
            unique_id="uid-b",
            platform="tplink",
            config_entry_id="entry-b",
            device_id="device-b",
            area_id="garage",
            disabled=False,
            available=True,
            referenced_by_count=2,
        ),
    )
    decision = classify_duplicate_group("switch.plug", members)
    assert decision.classification is DuplicateGroupClassification.LIKELY_DISTINCT_ENTITIES


def test_one_alive_rest_dead_is_migration_leftover() -> None:
    members = (
        DuplicateGroupMember(
            entity_id="automation.foo",
            unique_id="uid-old",
            platform="automation",
            config_entry_id=None,
            device_id=None,
            area_id=None,
            disabled=True,
            available=False,
            referenced_by_count=0,
            source_definition_missing=True,
            created_at="2024-01-01T00:00:00+00:00",
        ),
        DuplicateGroupMember(
            entity_id="automation.foo_2",
            unique_id="uid-new",
            platform="automation",
            config_entry_id=None,
            device_id=None,
            area_id=None,
            disabled=False,
            available=True,
            referenced_by_count=1,
            source_definition_missing=False,
            created_at="2026-01-01T00:00:00+00:00",
        ),
    )
    decision = classify_duplicate_group("automation.foo", members)
    assert decision.classification is DuplicateGroupClassification.LIKELY_MIGRATION_LEFTOVER
    assert decision.primary_entity_id == "automation.foo_2"


def test_active_old_id_with_new_sibling() -> None:
    members = (
        DuplicateGroupMember(
            entity_id="media_player.tv",
            unique_id="uid-old",
            platform="cast",
            config_entry_id=None,
            device_id=None,
            area_id=None,
            disabled=False,
            available=True,
            referenced_by_count=1,
            created_at="2023-01-01T00:00:00+00:00",
        ),
        DuplicateGroupMember(
            entity_id="media_player.tv_2",
            unique_id="uid-new",
            platform="cast",
            config_entry_id=None,
            device_id=None,
            area_id=None,
            disabled=False,
            available=True,
            referenced_by_count=0,
            created_at="2026-06-01T00:00:00+00:00",
        ),
    )
    decision = classify_duplicate_group("media_player.tv", members)
    assert (
        decision.classification
        is DuplicateGroupClassification.ACTIVE_OLD_ID_WITH_NEW_SIBLING
    )
    assert decision.primary_entity_id == "media_player.tv"


def test_broken_reference_to_old_sibling() -> None:
    members = (
        DuplicateGroupMember(
            entity_id="light.hall",
            unique_id="uid-old",
            platform="hue",
            config_entry_id=None,
            device_id=None,
            area_id=None,
            disabled=True,
            available=False,
            referenced_by_count=2,
        ),
        DuplicateGroupMember(
            entity_id="light.hall_2",
            unique_id="uid-new",
            platform="hue",
            config_entry_id=None,
            device_id=None,
            area_id=None,
            disabled=False,
            available=True,
            referenced_by_count=1,
        ),
    )
    decision = classify_duplicate_group("light.hall", members)
    assert (
        decision.classification
        is DuplicateGroupClassification.BROKEN_REFERENCE_TO_OLD_SIBLING
    )


def test_insufficient_evidence_is_ambiguous_not_guessed() -> None:
    """No availability/reference/device signal at all for either member
    -- must never be forced into a confident bucket.
    """
    members = (
        DuplicateGroupMember(
            entity_id="sensor.unknown",
            unique_id="uid-a",
            platform=None,
            config_entry_id=None,
            device_id=None,
            area_id=None,
            disabled=False,
            available=None,
            referenced_by_count=0,
        ),
        DuplicateGroupMember(
            entity_id="sensor.unknown_2",
            unique_id="uid-b",
            platform=None,
            config_entry_id=None,
            device_id=None,
            area_id=None,
            disabled=False,
            available=None,
            referenced_by_count=0,
        ),
    )
    decision = classify_duplicate_group("sensor.unknown", members)
    assert decision.classification is DuplicateGroupClassification.AMBIGUOUS_DUPLICATE_GROUP


def test_classify_requires_at_least_two_members() -> None:
    with pytest.raises(ValueError):
        classify_duplicate_group(
            "solo",
            (
                DuplicateGroupMember(
                    entity_id="light.solo",
                    unique_id="uid",
                    platform=None,
                    config_entry_id=None,
                    device_id=None,
                    area_id=None,
                    disabled=False,
                    available=True,
                    referenced_by_count=0,
                ),
            ),
        )
