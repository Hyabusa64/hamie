"""Structural automation/script definition inspection.

Locating an exact reference's structural path (not just "this file
contains this entity id somewhere") is what makes a scoped, non-blind
mutation possible -- see docs/REPAIR_ORCHESTRATION.md's caution about a
real prior mistake where a blind text substitution inverted a comment's
meaning.
"""

from __future__ import annotations

from hamie.domain.definition_inspection import (
    DefinitionInspection,
    find_automation_entry,
    find_script_entry,
    inspect_automation,
    inspect_script,
)
from hamie.infrastructure.source_definition_index import parse_config_yaml


def test_finds_automation_inside_a_package_automation_key() -> None:
    doc = parse_config_yaml(
        """
automation:
  - id: "abc123"
    trigger:
      - platform: state
        entity_id: binary_sensor.example_trigger
    action:
      - service: light.turn_on
        target:
          entity_id: light.example
"""
    )
    entry = find_automation_entry(doc, "abc123")
    assert entry is not None
    assert entry["id"] == "abc123"


def test_finds_automation_in_a_bare_top_level_list() -> None:
    doc = parse_config_yaml(
        """
- id: "xyz789"
  trigger: []
  action: []
"""
    )
    entry = find_automation_entry(doc, "xyz789")
    assert entry is not None


def test_automation_not_found_returns_none() -> None:
    doc = parse_config_yaml("automation:\n  - id: 'other'\n")
    assert find_automation_entry(doc, "missing") is None


def test_finds_script_inside_a_package_script_key() -> None:
    doc = parse_config_yaml(
        """
script:
  my_script:
    sequence:
      - service: light.turn_off
        target:
          entity_id: light.example
"""
    )
    entry = find_script_entry(doc, "my_script")
    assert entry is not None
    assert "sequence" in entry


def test_finds_script_in_a_bare_top_level_mapping() -> None:
    doc = parse_config_yaml("my_script:\n  sequence: []\n")
    entry = find_script_entry(doc, "my_script")
    assert entry is not None


def test_script_not_found_returns_none() -> None:
    doc = parse_config_yaml("script:\n  other_script:\n    sequence: []\n")
    assert find_script_entry(doc, "missing") is None


def test_inspect_automation_returns_none_when_id_absent() -> None:
    doc = parse_config_yaml("automation:\n  - id: 'x'\n")
    assert inspect_automation(doc, entity_id="automation.a", unique_id="missing", defining_file="f") is None


def test_inspect_automation_captures_trigger_condition_action_references() -> None:
    doc = parse_config_yaml(
        """
automation:
  - id: "abc123"
    trigger:
      - platform: state
        entity_id: binary_sensor.example_trigger
    condition:
      - condition: state
        entity_id: input_boolean.example_gate
        state: "on"
    action:
      - service: light.turn_on
        target:
          entity_id: light.example
      - service: notify.mobile_app_test
        data:
          message: hello
"""
    )
    inspection = inspect_automation(
        doc, entity_id="automation.example", unique_id="abc123", defining_file="packages/example.yaml"
    )
    assert inspection is not None
    assert isinstance(inspection, DefinitionInspection)
    assert inspection.domain == "automation"
    assert inspection.defining_file == "packages/example.yaml"
    entity_ids = {ref.entity_id for ref in inspection.references}
    assert entity_ids == {
        "binary_sensor.example_trigger",
        "input_boolean.example_gate",
        "light.example",
    }
    # notify.mobile_app_test has no entity_id field at all -- must not be
    # hallucinated as a reference.
    assert "notify.mobile_app_test" not in entity_ids


def test_reference_path_is_precise_enough_for_scoped_mutation() -> None:
    doc = parse_config_yaml(
        """
automation:
  - id: "abc123"
    trigger: []
    condition: []
    action:
      - service: light.turn_on
        target:
          entity_id: light.stale
"""
    )
    inspection = inspect_automation(doc, entity_id="automation.a", unique_id="abc123", defining_file="f")
    assert inspection is not None
    locations = inspection.references_to("light.stale")
    assert len(locations) == 1
    assert locations[0].path == "action[0].target.entity_id"


def test_list_shaped_entity_id_produces_one_location_per_member() -> None:
    doc = parse_config_yaml(
        """
automation:
  - id: "abc123"
    trigger: []
    condition: []
    action:
      - service: light.turn_on
        target:
          entity_id:
            - light.a
            - light.b
"""
    )
    inspection = inspect_automation(doc, entity_id="automation.a", unique_id="abc123", defining_file="f")
    assert inspection is not None
    paths = {ref.path: ref.entity_id for ref in inspection.references}
    assert paths["action[0].target.entity_id[0]"] == "light.a"
    assert paths["action[0].target.entity_id[1]"] == "light.b"


def test_references_to_filters_by_exact_entity_id() -> None:
    doc = parse_config_yaml(
        """
automation:
  - id: "abc123"
    trigger:
      - platform: state
        entity_id: light.a
    condition: []
    action:
      - service: light.turn_on
        target:
          entity_id: light.b
"""
    )
    inspection = inspect_automation(doc, entity_id="automation.a", unique_id="abc123", defining_file="f")
    assert inspection is not None
    assert len(inspection.references_to("light.a")) == 1
    assert len(inspection.references_to("light.b")) == 1
    assert inspection.references_to("light.nonexistent") == ()


def test_inspect_script_captures_sequence_references() -> None:
    doc = parse_config_yaml(
        """
script:
  turn_things_off:
    sequence:
      - service: switch.turn_off
        target:
          entity_id: switch.example
"""
    )
    inspection = inspect_script(
        doc, entity_id="script.turn_things_off", object_id="turn_things_off", defining_file="scripts.yaml"
    )
    assert inspection is not None
    assert inspection.domain == "script"
    assert inspection.references_to("switch.example")


def test_condition_style_entity_id_field_directly_on_the_step_is_captured() -> None:
    doc = parse_config_yaml(
        """
automation:
  - id: "abc123"
    trigger: []
    condition:
      - condition: state
        entity_id: input_boolean.gate
        state: "on"
    action: []
"""
    )
    inspection = inspect_automation(doc, entity_id="automation.a", unique_id="abc123", defining_file="f")
    assert inspection is not None
    assert inspection.references_to("input_boolean.gate")


def test_unsupported_domain_is_rejected() -> None:
    import pytest

    from hamie.domain.definition_inspection import DefinitionInspection as DI

    with pytest.raises(ValueError):
        DI(
            entity_id="sensor.a",
            unique_id="u",
            domain="sensor",
            defining_file="f",
            trigger=(),
            condition=(),
            action=(),
            references=(),
        )
