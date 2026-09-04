"""HA compatibility rule registry: mechanism only.

DEFAULT_HA_COMPATIBILITY_RULES ships empty (see the module docstring):
no real deprecated-syntax incident exists in this project's history to
build a rule from. These tests prove the registry MECHANISM works
correctly using synthetic example rules defined only in this test file
-- they must never be promoted into the shipped default registry
without a real, cited incident.
"""

from __future__ import annotations

import pytest

from hamie.domain.ha_compatibility import (
    DEFAULT_HA_COMPATIBILITY_RULES,
    HACompatibilityRegistry,
    HACompatibilityRule,
    default_registry,
    parse_ha_version,
)


def test_default_registry_ships_empty() -> None:
    """The whole point: no fabricated rule, ever."""
    assert DEFAULT_HA_COMPATIBILITY_RULES == ()
    assert default_registry().rules == ()


@pytest.mark.parametrize(
    ("version_string", "expected"),
    [
        ("2026.8.3", (2026, 8, 3)),
        ("2026.8", (2026, 8)),
        ("2026.8.3b0", (2026, 8, 3)),
        ("2026.8.0.dev0", (2026, 8, 0)),
    ],
)
def test_parse_ha_version(version_string: str, expected: tuple[int, ...]) -> None:
    assert parse_ha_version(version_string) == expected


def test_parse_ha_version_rejects_unparseable_input() -> None:
    with pytest.raises(ValueError):
        parse_ha_version("not-a-version")


def _example_rule() -> HACompatibilityRule:
    """A synthetic example: 'service:' key should be 'action:' from 2024.8+.

    Purely illustrative of the mechanism -- not a real cited incident,
    and therefore never added to DEFAULT_HA_COMPATIBILITY_RULES.
    """
    return HACompatibilityRule(
        rule_id="example.service_key_renamed_to_action",
        description="'service:' was renamed to 'action:' starting Home Assistant 2024.8.",
        min_ha_version=(2024, 8),
        max_ha_version=None,
        detect=lambda step: "service" in step and "action" not in step,
        rewrite=lambda step: {**{k: v for k, v in step.items() if k != "service"}, "action": step["service"]},
        documentation_reference="https://www.home-assistant.io/blog/2024/08/07/release-20248/",
    )


def test_rule_construction_requires_id_and_description() -> None:
    with pytest.raises(ValueError):
        HACompatibilityRule(
            rule_id="",
            description="x",
            min_ha_version=None,
            max_ha_version=None,
            detect=lambda s: False,
        )


def test_rule_detects_a_matching_structure() -> None:
    rule = _example_rule()
    finding = rule.evaluate({"service": "light.turn_on"})
    assert finding is not None
    assert finding.rule_id == "example.service_key_renamed_to_action"
    assert finding.rewrite_available is True


def test_rule_does_not_fire_on_a_non_matching_structure() -> None:
    rule = _example_rule()
    assert rule.evaluate({"action": "light.turn_on"}) is None


def test_rule_applies_version_bounds() -> None:
    rule = _example_rule()
    assert rule.applies_to_version((2024, 8)) is True
    assert rule.applies_to_version((2026, 1)) is True
    assert rule.applies_to_version((2024, 7)) is False


def test_rule_with_an_upper_bound_excludes_later_versions() -> None:
    bounded = HACompatibilityRule(
        rule_id="example.bounded",
        description="only applies in a narrow window",
        min_ha_version=(2024, 1),
        max_ha_version=(2024, 12),
        detect=lambda s: True,
    )
    assert bounded.applies_to_version((2024, 6)) is True
    assert bounded.applies_to_version((2025, 1)) is False
    assert bounded.applies_to_version((2023, 12)) is False


def test_apply_rewrite_produces_the_exact_supported_replacement() -> None:
    rule = _example_rule()
    rewritten = rule.apply_rewrite({"service": "light.turn_on", "target": {"entity_id": "light.a"}})
    assert rewritten == {"target": {"entity_id": "light.a"}, "action": "light.turn_on"}


def test_apply_rewrite_refuses_a_rule_with_no_rewrite() -> None:
    detect_only = HACompatibilityRule(
        rule_id="example.detect_only",
        description="no safe rewrite known",
        min_ha_version=None,
        max_ha_version=None,
        detect=lambda s: True,
    )
    with pytest.raises(ValueError):
        detect_only.apply_rewrite({})


def test_apply_rewrite_refuses_a_structure_the_rule_does_not_actually_match() -> None:
    """Never rewrite something detect() didn't confirm -- fail-closed, not
    trust-the-caller.
    """
    rule = _example_rule()
    with pytest.raises(ValueError):
        rule.apply_rewrite({"action": "already_fine"})


def test_registry_rejects_duplicate_rule_ids() -> None:
    rule = _example_rule()
    with pytest.raises(ValueError):
        HACompatibilityRegistry((rule, rule))


def test_registry_register_returns_a_new_registry_immutably() -> None:
    empty = HACompatibilityRegistry()
    with_rule = empty.register(_example_rule())
    assert empty.rules == ()
    assert len(with_rule.rules) == 1


def test_applicable_rules_filters_by_version() -> None:
    registry = HACompatibilityRegistry((_example_rule(),))
    assert len(registry.applicable_rules((2026, 1))) == 1
    assert len(registry.applicable_rules((2020, 1))) == 0


def test_evaluate_runs_only_version_applicable_rules_against_a_structure() -> None:
    registry = HACompatibilityRegistry((_example_rule(),))
    findings_old = registry.evaluate({"service": "light.turn_on"}, ha_version=(2020, 1))
    findings_new = registry.evaluate({"service": "light.turn_on"}, ha_version=(2026, 1))
    assert findings_old == ()
    assert len(findings_new) == 1
    assert findings_new[0].rule_id == "example.service_key_renamed_to_action"


def test_evaluate_finds_nothing_for_an_already_compliant_structure() -> None:
    registry = HACompatibilityRegistry((_example_rule(),))
    assert registry.evaluate({"action": "light.turn_on"}, ha_version=(2026, 1)) == ()
