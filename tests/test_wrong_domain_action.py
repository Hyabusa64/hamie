"""Tests for WrongDomainActionAnalyzer (mission Part 5, test pattern 5).

The porch-light pattern: an automation's action calls `light.turn_on`
against an entity_id that is itself orphaned, while a live sibling with
the same object_id now exists under a different domain (switch) --
fixing only the entity_id would still be broken, since the service
verb's own domain must also change.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hamie.analysis.analyzers.wrong_domain_action import WrongDomainActionAnalyzer
from hamie.application.ports import EntityRecord
from hamie.domain.findings import RecommendationKind
from hamie.infrastructure.source_definition_index import (
    ConfigSourceFile,
    SourceDefinitionIndex,
)

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
ANALYZER = WrongDomainActionAnalyzer(source_instance="test_home")


def _rec(
    entity_id: str,
    *,
    state: str = "on",
    disabled: bool = False,
    device_id: str | None = None,
    config_entry_id: str | None = None,
    platform: str | None = None,
) -> EntityRecord:
    domain = entity_id.partition(".")[0]
    return EntityRecord(
        entity_id=entity_id,
        state=state,
        last_changed=NOW,
        last_updated=NOW,
        registry_id=f"reg-{entity_id}",
        device_id=device_id,
        config_entry_id=config_entry_id,
        disabled=disabled,
        restored=None,
        domain=domain,
        platform=platform,
    )


def _index(path: str, content: str) -> SourceDefinitionIndex:
    return SourceDefinitionIndex.build((ConfigSourceFile(path=path, content=content),))


def _analyze(records, source_index):
    return ANALYZER.analyze_collection(records, observed_at=NOW, source_index=source_index)


def test_detects_wrong_domain_migrated_action_target_flat_style() -> None:
    """Pre-2024.8 flat `service:`/`entity_id:` style."""
    dead_light = _rec("light.porch_switch", state="unavailable")
    live_switch = _rec("switch.porch_switch", state="on")
    automation = """
automation:
  - id: "porch_light_control"
    trigger:
      - platform: sun
        event: sunset
    action:
      - service: light.turn_on
        entity_id: light.porch_switch
"""
    outcome = _analyze(
        (dead_light, live_switch), _index("packages/porch.yaml", automation)
    )
    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.title_key == "wrong_domain_action_target"
    assert finding.recommendation.kind is RecommendationKind.REPAIR
    assert "switch.turn_on" in finding.recommendation.action
    assert "switch.porch_switch" in finding.recommendation.action


def test_detects_wrong_domain_migrated_action_target_target_style() -> None:
    """Current `action:`/`target: {entity_id: ...}` style."""
    dead_light = _rec("light.porch_switch", state="unavailable")
    live_switch = _rec("switch.porch_switch", state="on")
    automation = """
automation:
  - id: "porch_light_control"
    action:
      - action: light.turn_on
        target:
          entity_id: light.porch_switch
"""
    outcome = _analyze(
        (dead_light, live_switch), _index("packages/porch.yaml", automation)
    )
    assert len(outcome.findings) == 1


def test_no_finding_when_target_still_alive() -> None:
    live_light = _rec("light.porch_switch", state="on")
    automation = """
automation:
  - id: "porch_light_control"
    action:
      - service: light.turn_on
        entity_id: light.porch_switch
"""
    outcome = _analyze((live_light,), _index("packages/porch.yaml", automation))
    assert outcome.findings == ()


def test_no_finding_when_verb_and_target_domain_already_match() -> None:
    """Verb domain already matches the target's own written domain and
    there's no orphan/replacement situation -- ordinary, correct
    automation, never flagged."""
    live_switch = _rec("switch.fan", state="on")
    automation = """
automation:
  - id: "fan_control"
    action:
      - service: switch.turn_on
        entity_id: switch.fan
"""
    outcome = _analyze((live_switch,), _index("packages/fan.yaml", automation))
    assert outcome.findings == ()


def test_no_finding_when_multiple_ambiguous_replacement_candidates() -> None:
    """Two different domains both have a live sibling with the same
    object_id -- ambiguous, never guessed."""
    dead_light = _rec("light.porch_switch", state="unavailable")
    live_switch = _rec("switch.porch_switch", state="on")
    live_fan = _rec("fan.porch_switch", state="on")
    automation = """
automation:
  - id: "porch_light_control"
    action:
      - service: light.turn_on
        entity_id: light.porch_switch
"""
    outcome = _analyze(
        (dead_light, live_switch, live_fan), _index("packages/porch.yaml", automation)
    )
    assert outcome.findings == ()


def test_no_finding_without_raw_files() -> None:
    dead_light = _rec("light.porch_switch", state="unavailable")
    live_switch = _rec("switch.porch_switch", state="on")
    outcome = ANALYZER.analyze_collection(
        (dead_light, live_switch), observed_at=NOW, source_index=None
    )
    assert outcome.findings == ()


def test_malformed_document_degrades_without_aborting_scan() -> None:
    dead_light = _rec("light.porch_switch", state="unavailable")
    live_switch = _rec("switch.porch_switch", state="on")
    good_automation = """
automation:
  - id: "porch_light_control"
    action:
      - service: light.turn_on
        entity_id: light.porch_switch
"""
    files = (
        ConfigSourceFile(path="packages/porch.yaml", content=good_automation),
        ConfigSourceFile(path="packages/broken.yaml", content="not: [valid: yaml"),
    )
    index = SourceDefinitionIndex.build(files)
    outcome = _analyze((dead_light, live_switch), index)
    assert len(outcome.findings) == 1
    assert "packages/broken.yaml" in outcome.uncovered_subjects
