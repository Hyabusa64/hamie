"""Duplicate-automation-action detection must compare effect, never names.

Generalizes a real incident: three differently-named automations (two
exact-duplicate versions of one, plus an unrelated-sounding third) all
independently fired the same dock-notification action, causing triple
announcements. A name-similarity check would have missed this entirely.
"""

from __future__ import annotations

import pytest

from hamie.domain.action_duplication import (
    ActionDuplicationFinding,
    ActionDuplicationVerdict,
    AutomationActionProfile,
    NormalizedAction,
    compare_profiles,
    detect_duplicate_actions,
    identify_authoritative,
    normalize_actions,
)


def _profile(entity_id: str, unique_id: str, raw_actions) -> AutomationActionProfile:
    return AutomationActionProfile(
        entity_id=entity_id, unique_id=unique_id, actions=normalize_actions(raw_actions)
    )


NOTIFY_ACTION = [
    {
        "service": "notify.mobile_app_test_phone",
        "data": {"message": "Dock is full", "title": "Vacuum"},
    }
]
NOTIFY_ACTION_DIFFERENT_WORDING = [
    {
        "service": "notify.mobile_app_test_phone",
        "data": {"message": "Dock is full", "title": "Roomba Update"},
    }
]
VOLUME_CAP_60 = [
    {
        "service": "media_player.volume_set",
        "target": {"entity_id": "media_player.living_room"},
        "data": {"volume_level": 0.6},
    }
]
VOLUME_CAP_80 = [
    {
        "service": "media_player.volume_set",
        "target": {"entity_id": "media_player.living_room"},
        "data": {"volume_level": 0.8},
    }
]
TURN_ON_LIGHT = [
    {"service": "light.turn_on", "target": {"entity_id": "light.porch"}}
]
TURN_OFF_LIGHT = [
    {"service": "light.turn_off", "target": {"entity_id": "light.porch"}}
]


def test_normalize_actions_skips_unrecognized_shapes_rather_than_guessing() -> None:
    raw = [
        {"service": "light.turn_on", "target": {"entity_id": "light.a"}},
        {"delay": "00:00:05"},
        {"choose": []},
        {"repeat": {"count": 3, "sequence": []}},
        "not_a_dict",
    ]
    actions = normalize_actions(raw)
    assert len(actions) == 1
    assert actions[0].service == "light.turn_on"


def test_normalize_actions_reads_service_and_action_keys() -> None:
    assert normalize_actions([{"action": "light.turn_on", "target": {"entity_id": "light.a"}}])
    assert normalize_actions([{"service": "light.turn_on", "target": {"entity_id": "light.a"}}])


def test_title_only_difference_is_insignificant() -> None:
    a = normalize_actions(NOTIFY_ACTION)[0]
    b = normalize_actions(NOTIFY_ACTION_DIFFERENT_WORDING)[0]
    assert a.effect_digest == b.effect_digest


def test_message_difference_is_significant() -> None:
    a = normalize_actions(NOTIFY_ACTION)[0]
    b = normalize_actions(
        [{"service": "notify.mobile_app_test_phone", "data": {"message": "different"}}]
    )[0]
    assert a.effect_digest != b.effect_digest


def test_entity_id_directly_on_the_step_is_also_a_target() -> None:
    actions = normalize_actions([{"service": "light.turn_on", "entity_id": "light.a"}])
    assert actions[0].target_entities == ("light.a",)


def test_exact_duplicate_detected_for_identical_notification_automations() -> None:
    left = _profile("automation.dock_v2_6", "uid_a", NOTIFY_ACTION)
    right = _profile("automation.dock_v2_7", "uid_b", NOTIFY_ACTION_DIFFERENT_WORDING)
    finding = compare_profiles(left, right)
    assert finding is not None
    assert finding.verdict is ActionDuplicationVerdict.EXACT_DUPLICATE


def test_unrelated_looking_automation_still_matches_on_effect_not_name() -> None:
    """The real incident's third automation ("Dock Manager 2.4") looked
    unrelated by name but fired the identical effect -- name similarity
    must play no role in detection.
    """
    left = _profile("automation.totally_different_name_xyz", "uid_a", NOTIFY_ACTION)
    right = _profile("automation.dock_manager_2_4", "uid_b", NOTIFY_ACTION)
    finding = compare_profiles(left, right)
    assert finding is not None
    assert finding.verdict is ActionDuplicationVerdict.EXACT_DUPLICATE


def test_no_shared_target_is_not_a_finding_at_all() -> None:
    left = _profile("automation.a", "uid_a", TURN_ON_LIGHT)
    right = _profile(
        "automation.b", "uid_b",
        [{"service": "climate.set_temperature", "target": {"entity_id": "climate.hall"}}],
    )
    assert compare_profiles(left, right) is None


def test_same_target_different_significant_parameter_is_overlapping_not_exact() -> None:
    left = _profile("automation.volume_cap_a", "uid_a", VOLUME_CAP_60)
    right = _profile("automation.volume_cap_b", "uid_b", VOLUME_CAP_80)
    finding = compare_profiles(left, right)
    assert finding is not None
    assert finding.verdict is ActionDuplicationVerdict.OVERLAPPING_DUPLICATE


def test_one_side_with_an_extra_unrelated_action_is_overlapping_not_exact() -> None:
    """Generalizes the real case where one duplicate also announced an
    unrelated mop-drying event and had to be kept, not deleted outright.
    """
    left = _profile("automation.dock_a", "uid_a", NOTIFY_ACTION)
    right = _profile(
        "automation.dock_b", "uid_b",
        NOTIFY_ACTION + [{"service": "notify.mobile_app_test_phone", "data": {"message": "Mop is drying"}}],
    )
    finding = compare_profiles(left, right)
    assert finding is not None
    assert finding.verdict is ActionDuplicationVerdict.OVERLAPPING_DUPLICATE


def test_opposite_operations_on_same_target_are_potentially_conflicting() -> None:
    left = _profile("automation.on_a", "uid_a", TURN_ON_LIGHT)
    right = _profile("automation.off_b", "uid_b", TURN_OFF_LIGHT)
    finding = compare_profiles(left, right)
    assert finding is not None
    assert finding.verdict is ActionDuplicationVerdict.POTENTIALLY_CONFLICTING


def test_comparing_an_automation_against_itself_is_refused() -> None:
    profile = _profile("automation.a", "uid_a", TURN_ON_LIGHT)
    with pytest.raises(ValueError):
        compare_profiles(profile, profile)


def test_finding_pair_identity_is_order_independent() -> None:
    left = _profile("automation.dock_a", "uid_a", NOTIFY_ACTION)
    right = _profile("automation.dock_b", "uid_b", NOTIFY_ACTION)
    forward = compare_profiles(left, right)
    backward = compare_profiles(right, left)
    assert forward is not None and backward is not None
    assert forward.pair_id == backward.pair_id
    assert forward.left_entity_id == backward.left_entity_id
    assert forward.right_entity_id == backward.right_entity_id


def test_finding_construction_rejects_unsorted_entity_ids() -> None:
    with pytest.raises(ValueError):
        ActionDuplicationFinding(
            left_entity_id="automation.z",
            right_entity_id="automation.a",
            verdict=ActionDuplicationVerdict.EXACT_DUPLICATE,
            shared_effect_keys=("k",),
            rationale="x",
        )


def test_finding_requires_at_least_one_shared_effect_key() -> None:
    with pytest.raises(ValueError):
        ActionDuplicationFinding(
            left_entity_id="automation.a",
            right_entity_id="automation.b",
            verdict=ActionDuplicationVerdict.EXACT_DUPLICATE,
            shared_effect_keys=(),
            rationale="x",
        )


def test_detect_duplicate_actions_across_a_realistic_set_mirrors_the_real_incident() -> None:
    """Three automations, one real duplicate pair among unrelated others --
    exactly the shape (minus the third "unrelated-looking" duplicate,
    covered separately above) of the real dock-notification incident.
    """
    profiles = (
        _profile("automation.dock_v2_6", "uid_1", NOTIFY_ACTION),
        _profile("automation.dock_v2_7", "uid_2", NOTIFY_ACTION),
        _profile("automation.unrelated_climate", "uid_3", [
            {"service": "climate.set_temperature", "target": {"entity_id": "climate.hall"}},
        ]),
    )
    findings = detect_duplicate_actions(profiles)
    assert len(findings) == 1
    assert {findings[0].left_entity_id, findings[0].right_entity_id} == {
        "automation.dock_v2_6", "automation.dock_v2_7",
    }
    assert findings[0].verdict is ActionDuplicationVerdict.EXACT_DUPLICATE


def test_detect_duplicate_actions_never_compares_automations_with_no_shared_target() -> None:
    """A large, mostly-unrelated automation set must not explode
    combinatorially or produce noise -- pairs with no shared target are
    never even compared.
    """
    profiles = tuple(
        _profile(
            f"automation.independent_{i}", f"uid_{i}",
            [{"service": "light.turn_on", "target": {"entity_id": f"light.room_{i}"}}],
        )
        for i in range(20)
    )
    assert detect_duplicate_actions(profiles) == ()


def test_identify_authoritative_prefers_the_side_whose_definition_still_exists() -> None:
    left = _profile("automation.old", "uid_1", NOTIFY_ACTION)
    right = _profile("automation.new", "uid_2", NOTIFY_ACTION)
    finding = compare_profiles(left, right)
    assert finding is not None
    # compare_profiles canonicalizes by sorted entity_id, so determine
    # which side of the finding is which rather than assuming order.
    old_is_left = finding.left_entity_id == "automation.old"

    kept = identify_authoritative(
        finding,
        left_reference_count=0,
        right_reference_count=0,
        left_source_definition_missing=old_is_left,
        right_source_definition_missing=not old_is_left,
    )
    assert kept == "automation.new"


def test_identify_authoritative_refuses_when_both_definitions_are_gone() -> None:
    left = _profile("automation.a", "uid_1", NOTIFY_ACTION)
    right = _profile("automation.b", "uid_2", NOTIFY_ACTION)
    finding = compare_profiles(left, right)
    assert finding is not None

    assert identify_authoritative(
        finding,
        left_reference_count=0,
        right_reference_count=0,
        left_source_definition_missing=True,
        right_source_definition_missing=True,
    ) is None


def test_identify_authoritative_refuses_when_neither_definition_is_confirmed_missing_and_references_tie() -> None:
    left = _profile("automation.a", "uid_1", NOTIFY_ACTION)
    right = _profile("automation.b", "uid_2", NOTIFY_ACTION)
    finding = compare_profiles(left, right)
    assert finding is not None

    assert identify_authoritative(
        finding,
        left_reference_count=0,
        right_reference_count=0,
        left_source_definition_missing=False,
        right_source_definition_missing=False,
    ) is None


def test_identify_authoritative_is_never_defined_for_non_exact_verdicts() -> None:
    left = _profile("automation.volume_cap_a", "uid_a", VOLUME_CAP_60)
    right = _profile("automation.volume_cap_b", "uid_b", VOLUME_CAP_80)
    finding = compare_profiles(left, right)
    assert finding is not None
    assert finding.verdict is not ActionDuplicationVerdict.EXACT_DUPLICATE

    assert identify_authoritative(
        finding,
        left_reference_count=5,
        right_reference_count=0,
        left_source_definition_missing=False,
        right_source_definition_missing=True,
    ) is None
