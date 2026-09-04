"""Tests for domain/knowledge_import.py (mission Parts 13/45/46/159).

The fixture below is a trimmed, structurally faithful copy of this
project's real ``benchmark/duplicate_remediation_20260825T021648Z/
phase_b1_actions.json`` -- same shape, same real root-cause ids and
entity ids, so these tests exercise the importer against the actual
evidence schema it must handle, not an invented one.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hamie.domain.knowledge_import import (
    import_entity_successors_from_remediation_actions,
    merge_entity_successors,
)
from hamie.domain.successors import SuccessorRelationshipType

_AT = datetime(2026, 8, 25, 5, 30, tzinfo=UTC)

_REAL_SHAPED_DOCUMENT = {
    "generated_utc": "2026-08-25T05:30:00Z",
    "modified_this_session": [
        {
            "file": "/config/packages/house_empty_confidence_score_v6_2606.yaml",
            "backup": "/config/packages/house_empty_confidence_score_v6_2606.yaml.bak_pre_dupfix_20260825T040954Z",
            "sha256_verified": True,
            "root_causes_fixed": [
                {
                    "id": "vacuum_self_reference",
                    "description": "referenced dead base-slug vacuum sensors instead of live _2 siblings",
                    "lines_changed": [163, 164],
                    "substitutions": 6,
                    "entities_affected": [
                        "binary_sensor.vacuum_cleaning_active",
                        "binary_sensor.vacuum_settling_period",
                    ],
                },
                {
                    "id": "porch_light_dead_target",
                    "description": "away-mode lighting actions targeted dead lutron orphans with wrong domain",
                    "substitutions": 6,
                    "entities_affected": [
                        "light.front_porch_porch_light -> switch.front_porch_light",
                        "light.outside_back_porch_light -> switch.back_porch_light",
                    ],
                    "action_verb_changed": "light.turn_on -> switch.turn_on",
                },
            ],
            "activation_status": "deployed_inactive_pending_reload_or_restart",
        },
        {
            "file": "/config/packages/water.yaml",
            "backup": "/config/packages/water.yaml.bak_pre_dupfix_20260825T041011Z",
            "sha256_verified": True,
            "root_causes_fixed": [
                {
                    "id": "example_metric_percentage_self_reference",
                    "description": "referenced dead base-slug entity instead of live sensor.example_metric_percentage_3",
                    "substitutions": 6,
                    "entities_affected": [
                        "sensor.example_metric_percentage -> sensor.example_metric_percentage_3"
                    ],
                }
            ],
            "activation_status": "deployed_inactive_pending_reload_or_restart",
        },
        {
            "file": "/config/packages/example_appliance_intelligence_v1_0_1_2608.yaml",
            "backup": "/config/packages/example_appliance_intelligence_v1_0_1_2608.yaml.bak_pre_dupfix_20260824T024111Z",
            "sha256_verified": True,
            "root_causes_fixed": [
                {
                    "id": "example_appliance_self_reference",
                    "description": "7 sensors referenced dead base-slug siblings instead of live _2 entities",
                    "substitutions": 31,
                }
            ],
            "activation_status": "deployed_inactive_pending_reload_or_restart",
        },
        {
            "file": "/config/packages/master_toilet_adaptive_light.yaml",
            "backup": "/config/packages/master_toilet_adaptive_light.yaml.bak_pre_dupfix_20260825T052532Z",
            "sha256_before": "f6b35f0d4d10fe0312a371eb2dee2fa675d19358a29f8d60cabacba9b04f1b89",
            "sha256_after": "6a8ba4e5a71a4d7bd5bab25d7ab92851344170882cf71a4368d6dd302acfa2bd",
            "sha256_verified": True,
            "root_causes_fixed": [
                {
                    "id": "bidet_in_use_base_slug_orphan_reference",
                    "description": (
                        "binary_sensor.bidet_in_use template referenced "
                        "sensor.bidet_plug_power, which never existed in the "
                        "entity registry; live sensor is "
                        "sensor.bidet_plug_power_2 (unique_id "
                        "0x282c02bfffec502b_power_zigbee2mqtt)"
                    ),
                    "lines_changed": [15],
                    "substitutions": 1,
                    "entities_affected": [
                        "sensor.bidet_plug_power -> sensor.bidet_plug_power_2"
                    ],
                }
            ],
            "activation_status": "deployed_but_no_live_behavior_change",
        },
    ],
}


def _import(document: dict = _REAL_SHAPED_DOCUMENT):
    return import_entity_successors_from_remediation_actions(
        document,
        source_artifact="benchmark/duplicate_remediation_20260825T021648Z/phase_b1_actions.json",
        source_artifact_hash="fixture-hash-abc123",
        imported_at=_AT,
    )


def test_explicit_mappings_are_imported() -> None:
    result = _import()
    stale_ids = {item.stale_entity_id for item in result.accepted}
    assert "sensor.bidet_plug_power" in stale_ids
    assert "sensor.example_metric_percentage" in stale_ids
    assert "light.front_porch_porch_light" in stale_ids
    assert "light.outside_back_porch_light" in stale_ids


def test_entries_without_explicit_mapping_are_skipped_not_guessed() -> None:
    result = _import()
    stale_ids = {item.stale_entity_id for item in result.accepted}
    # Neither vacuum_self_reference nor example_appliance_self_reference
    # provides an explicit old->new mapping -- must never be guessed
    # from suffix-stripping "binary_sensor.vacuum_cleaning_active".
    assert "binary_sensor.vacuum_cleaning_active" not in stale_ids
    skipped_ids = {item.root_cause_id for item in result.skipped}
    assert skipped_ids == {"vacuum_self_reference", "example_appliance_self_reference"}


def test_bidet_relationship_matches_verified_evidence() -> None:
    result = _import()
    bidet = next(
        item for item in result.accepted if item.stale_entity_id == "sensor.bidet_plug_power"
    )
    assert bidet.canonical_entity_id == "sensor.bidet_plug_power_2"
    assert bidet.relationship_type is SuccessorRelationshipType.RENAMED_OR_RECREATED_SUCCESSOR
    assert bidet.reference_remediated is True
    # activation_status was "deployed_but_no_live_behavior_change" --
    # must decode to behavior_changed=False, never True.
    assert bidet.behavior_changed is False
    assert bidet.confidence.level.value == "high"


def test_wrong_domain_correction_is_classified_distinctly() -> None:
    result = _import()
    porch = next(
        item
        for item in result.accepted
        if item.stale_entity_id == "light.front_porch_porch_light"
    )
    assert porch.canonical_entity_id == "switch.front_porch_light"
    assert porch.relationship_type is SuccessorRelationshipType.WRONG_DOMAIN_CORRECTED


def test_import_is_idempotent_via_merge() -> None:
    first = _import().accepted
    second = _import().accepted
    merged_once = merge_entity_successors((), first)
    merged_twice = merge_entity_successors(merged_once, second)
    assert len(merged_twice) == len(merged_once)
    assert {item.fingerprint for item in merged_twice} == {
        item.fingerprint for item in merged_once
    }


def test_merge_adds_genuinely_new_relationships() -> None:
    partial = import_entity_successors_from_remediation_actions(
        {"modified_this_session": _REAL_SHAPED_DOCUMENT["modified_this_session"][:1]},
        source_artifact="fixture",
        source_artifact_hash="h1",
        imported_at=_AT,
    ).accepted
    full = _import().accepted
    merged = merge_entity_successors(partial, full)
    assert len(merged) == len(full)


def test_document_without_modified_this_session_returns_empty_result() -> None:
    result = import_entity_successors_from_remediation_actions(
        {}, source_artifact="fixture", source_artifact_hash="h", imported_at=_AT
    )
    assert result.accepted == ()
    assert result.skipped == ()


def test_malformed_root_cause_entries_are_skipped_not_raised() -> None:
    document = {
        "modified_this_session": [
            {
                "file": "/config/packages/x.yaml",
                "sha256_verified": True,
                "root_causes_fixed": [
                    "not-a-dict",
                    {"id": "", "entities_affected": ["a -> b"]},
                    {"entities_affected": ["a -> b"]},
                ],
            }
        ]
    }
    result = import_entity_successors_from_remediation_actions(
        document, source_artifact="fixture", source_artifact_hash="h", imported_at=_AT
    )
    assert result.accepted == ()
    assert result.skipped == ()
