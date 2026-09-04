"""Tests for infrastructure/offline_config_reference_scanner.py (mission Part 3b/5)."""

from __future__ import annotations

import json

from hamie.infrastructure.offline_config_reference_scanner import (
    scan_automation_script_scene_references,
    scan_lovelace_dashboard_references,
)
from hamie.infrastructure.source_definition_index import ConfigSourceFile

AUTOMATION_WITH_TEMPLATE = """
- id: '1'
  alias: watcher
  triggers: []
  conditions:
  - condition: template
    value_template: "{{ states('sensor.target') == 'on' and is_state('binary_sensor.other', 'off') }}"
  actions:
  - action: light.turn_on
    target:
      entity_id: light.hallway
"""


def test_template_call_references_are_found() -> None:
    result = scan_automation_script_scene_references(
        (ConfigSourceFile(path="automations.yaml", content=AUTOMATION_WITH_TEMPLATE),)
    )
    targets = {target for _, target in result.references}
    assert "sensor.target" in targets
    assert "binary_sensor.other" in targets


def test_explicit_entity_id_key_reference_is_found() -> None:
    result = scan_automation_script_scene_references(
        (ConfigSourceFile(path="automations.yaml", content=AUTOMATION_WITH_TEMPLATE),)
    )
    targets = {target for _, target in result.references}
    assert "light.hallway" in targets


def test_service_call_name_is_not_mistaken_for_an_entity_reference() -> None:
    """`action: light.turn_on` is a service call, not an entity id --
    must never appear as a discovered reference.
    """
    result = scan_automation_script_scene_references(
        (ConfigSourceFile(path="automations.yaml", content=AUTOMATION_WITH_TEMPLATE),)
    )
    targets = {target for _, target in result.references}
    assert "light.turn_on" not in targets


def test_parse_failure_reports_failed_status_when_nothing_recovered() -> None:
    result = scan_automation_script_scene_references(
        (ConfigSourceFile(path="automations.yaml", content="- id: [broken: :::"),)
    )
    assert result.status == "failed"
    assert result.references == ()


def test_lovelace_dashboard_references_are_found() -> None:
    dashboard = {
        "data": {
            "config": {
                "views": [
                    {
                        "cards": [
                            {"type": "entity", "entity": "sensor.living_room_temp"},
                        ]
                    }
                ]
            }
        }
    }
    result = scan_lovelace_dashboard_references(
        (("lovelace.test", json.dumps(dashboard)),)
    )
    targets = {target for _, target in result.references}
    assert "sensor.living_room_temp" in targets
    assert result.status == "succeeded"


def test_lovelace_malformed_json_does_not_crash() -> None:
    result = scan_lovelace_dashboard_references((("lovelace.broken", "not json"),))
    assert result.references == ()
