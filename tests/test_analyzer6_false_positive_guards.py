"""Tests for Analyzer 6 (mission Part 2/5): false-positive suppression
in domain/duplicate_classifier.py, using the real structural patterns
this session confirmed were safe -- not synthetic examples untethered
from what was actually found.

Covers test patterns 2, 7, 8 (mission Part 5):
2. legitimate `_2` second physical endpoint (Dreo humidifier pattern --
   different device_id).
7. disabled optional entity that is NOT a migration leftover.
8. same-name distinct sensor measurement.

Plus the zero-padded-suffix real bug fix this pass made to
``group_suffix_siblings`` (a 12-outlet Matter power strip / MQTT
LED-strip-segment shaped false positive a bare digit-suffix regex alone
would have caught).
"""

from __future__ import annotations

from hamie.domain.duplicate_classifier import (
    DuplicateGroupClassification,
    DuplicateGroupMember,
    classify_duplicate_group,
    group_suffix_siblings,
)

# --------------------------------------------------------------------------
# Zero-padded suffix fix: channel/zone numbering is not HA's convention.
# --------------------------------------------------------------------------


def test_zero_padded_suffixes_are_never_grouped_as_ha_duplicates() -> None:
    """A 12-outlet Matter power strip's own channel numbering
    (``_001``..``_012``) must never be treated as HA's ``_2``/``_3``
    collision-avoidance suffix."""
    entity_ids = tuple(f"switch.power_strip_{i:03d}" for i in range(1, 13))
    groups = group_suffix_siblings(entity_ids)
    assert groups == {}


def test_mqtt_led_strip_segments_zero_padded_not_grouped() -> None:
    entity_ids = ("light.led_strip_01", "light.led_strip_02", "light.led_strip_03")
    groups = group_suffix_siblings(entity_ids)
    assert groups == {}


def test_ordinary_ha_bare_suffix_still_groups_normally() -> None:
    """The zero-pad fix must not regress HA's real, bare-digit suffix
    convention (``_2``, ``_3``, ..., ``_10``, ``_11``)."""
    groups = group_suffix_siblings(("light.lamp", "light.lamp_2", "light.lamp_10"))
    assert groups == {"light.lamp": ("light.lamp", "light.lamp_10", "light.lamp_2")}


# --------------------------------------------------------------------------
# Pattern 2: legitimate `_2` second physical endpoint (Dreo humidifier
# shape -- different device_id, and this session additionally confirmed
# a different device MODEL, a signal HAMIE's infra does not capture
# today -- see the final report for that disclosed gap).
# --------------------------------------------------------------------------


def test_dreo_humidifier_shaped_distinct_physical_units_not_flagged() -> None:
    members = (
        DuplicateGroupMember(
            entity_id="humidifier.bedroom",
            unique_id="dreo-serial-aaa",
            platform="dreo",
            config_entry_id="entry-dreo-1",
            device_id="device-dreo-1",
            area_id="bedroom",
            disabled=False,
            available=True,
            referenced_by_count=2,
        ),
        DuplicateGroupMember(
            entity_id="humidifier.bedroom_2",
            unique_id="dreo-serial-bbb",
            platform="dreo",
            config_entry_id="entry-dreo-2",
            device_id="device-dreo-2",
            area_id="nursery",
            disabled=False,
            available=True,
            referenced_by_count=1,
        ),
    )
    decision = classify_duplicate_group("humidifier.bedroom", members)
    assert decision.classification is DuplicateGroupClassification.LIKELY_DISTINCT_ENTITIES


def test_bambu_ams_filament_trays_distinct_device_ids_not_flagged() -> None:
    members = tuple(
        DuplicateGroupMember(
            entity_id=f"sensor.ams_tray{'' if i == 1 else f'_{i}'}",
            unique_id=f"bambu-tray-{i}",
            platform="bambu_lab",
            config_entry_id="entry-bambu",
            device_id=f"device-tray-{i}",
            area_id="workshop",
            disabled=False,
            available=True,
            referenced_by_count=0,
        )
        for i in (1, 2, 3, 4)
    )
    decision = classify_duplicate_group("sensor.ams_tray", members)
    assert decision.classification is DuplicateGroupClassification.LIKELY_DISTINCT_ENTITIES


def test_dual_outlet_meross_plug_distinct_device_ids_not_flagged() -> None:
    members = (
        DuplicateGroupMember(
            entity_id="switch.meross_outlet",
            unique_id="meross-a",
            platform="meross",
            config_entry_id="entry-meross",
            device_id="device-meross-a",
            area_id="garage",
            disabled=False,
            available=True,
            referenced_by_count=1,
        ),
        DuplicateGroupMember(
            entity_id="switch.meross_outlet_2",
            unique_id="meross-b",
            platform="meross",
            config_entry_id="entry-meross",
            device_id="device-meross-b",
            area_id="garage",
            disabled=False,
            available=True,
            referenced_by_count=1,
        ),
    )
    decision = classify_duplicate_group("switch.meross_outlet", members)
    assert decision.classification is DuplicateGroupClassification.LIKELY_DISTINCT_ENTITIES


def test_unifi_firewall_policy_switches_distinct_config_entries_not_flagged() -> None:
    members = (
        DuplicateGroupMember(
            entity_id="switch.unifi_policy",
            unique_id="unifi-policy-a",
            platform="unifiprotect",
            config_entry_id="entry-unifi-a",
            device_id="device-unifi-a",
            area_id=None,
            disabled=False,
            available=True,
            referenced_by_count=0,
        ),
        DuplicateGroupMember(
            entity_id="switch.unifi_policy_2",
            unique_id="unifi-policy-b",
            platform="unifiprotect",
            config_entry_id="entry-unifi-b",
            device_id="device-unifi-b",
            area_id=None,
            disabled=False,
            available=True,
            referenced_by_count=0,
        ),
    )
    decision = classify_duplicate_group("switch.unifi_policy", members)
    assert decision.classification is DuplicateGroupClassification.LIKELY_DISTINCT_ENTITIES


# --------------------------------------------------------------------------
# Pattern 7: disabled optional entity that is NOT a migration leftover.
# --------------------------------------------------------------------------


def test_disabled_diagnostic_entity_with_no_suffix_sibling_forms_no_group() -> None:
    """A single disabled, optional entity with no numbered sibling at
    all must never be grouped, let alone flagged -- there is nothing to
    compare it against."""
    groups = group_suffix_siblings(("sensor.wifi_signal_strength", "sensor.unrelated_thing"))
    assert groups == {}


def test_disabled_entity_next_to_an_undetermined_sibling_is_ambiguous_not_leftover() -> None:
    """Both members are disabled/unclear (neither clearly alive nor
    clearly dead) -- must land in AMBIGUOUS, never guessed as
    LIKELY_MIGRATION_LEFTOVER (which requires exactly one clearly-alive
    member)."""
    members = (
        DuplicateGroupMember(
            entity_id="sensor.diagnostic_optional",
            unique_id="uid-1",
            platform="demo",
            config_entry_id="entry-1",
            device_id="device-1",
            area_id=None,
            disabled=True,
            available=None,
            referenced_by_count=0,
        ),
        DuplicateGroupMember(
            entity_id="sensor.diagnostic_optional_2",
            unique_id="uid-2",
            platform="demo",
            config_entry_id="entry-1",
            device_id="device-1",
            area_id=None,
            disabled=True,
            available=None,
            referenced_by_count=0,
        ),
    )
    decision = classify_duplicate_group("sensor.diagnostic_optional", members)
    assert decision.classification is DuplicateGroupClassification.AMBIGUOUS_DUPLICATE_GROUP


# --------------------------------------------------------------------------
# Pattern 8: same-name distinct sensor measurement.
# --------------------------------------------------------------------------


def test_same_name_distinct_temperature_sensors_not_flagged() -> None:
    members = (
        DuplicateGroupMember(
            entity_id="sensor.temperature",
            unique_id="temp-living-room",
            platform="zwave_js",
            config_entry_id="entry-zwave",
            device_id="device-living-room",
            area_id="living_room",
            disabled=False,
            available=True,
            referenced_by_count=1,
        ),
        DuplicateGroupMember(
            entity_id="sensor.temperature_2",
            unique_id="temp-garage",
            platform="zwave_js",
            config_entry_id="entry-zwave",
            device_id="device-garage",
            area_id="garage",
            disabled=False,
            available=True,
            referenced_by_count=1,
        ),
    )
    decision = classify_duplicate_group("sensor.temperature", members)
    assert decision.classification is DuplicateGroupClassification.LIKELY_DISTINCT_ENTITIES
