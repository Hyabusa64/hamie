"""Tests for infrastructure/source_definition_index.py (mission Part 3a/5).

Covers the mission's required scenarios:
- a package-defined automation is NOT flagged orphaned
- a UI/storage-managed automation (living in automations.yaml, not a
  package -- the default location HA's own UI editor writes to) is NOT
  flagged orphaned
- a confirmed automation/script/scene orphan IS flagged
- an evidence-source parse failure degrades gracefully (SOURCE_UNAVAILABLE)
  instead of producing a false MISSING_CONFIRMED positive
"""

from __future__ import annotations

from hamie.infrastructure.source_definition_index import (
    ConfigSourceFile,
    SourceDefinitionIndex,
    SourceDefinitionStatus,
)

AUTOMATIONS_YAML = """
- id: '1700000000001'
  alias: UI created automation
  triggers: []
  conditions: []
  actions: []
"""

PACKAGE_YAML = """
automation:
  - id: package_defined_automation
    alias: Package automation
    triggers: []
    conditions: []
    actions: []
script:
  package_script:
    alias: Package script
    sequence: []
scene:
  - id: '1700000000099'
    name: Package scene
    entities: {}
"""

SCRIPTS_YAML = """
ui_script:
  alias: A script
  sequence: []
"""

SCENES_YAML = """
- id: '1700000000002'
  name: A scene
  entities: {}
"""


def _index() -> SourceDefinitionIndex:
    return SourceDefinitionIndex.build(
        (
            ConfigSourceFile(path="automations.yaml", content=AUTOMATIONS_YAML),
            ConfigSourceFile(path="scripts.yaml", content=SCRIPTS_YAML),
            ConfigSourceFile(path="scenes.yaml", content=SCENES_YAML),
            ConfigSourceFile(path="packages/demo.yaml", content=PACKAGE_YAML),
        )
    )


def test_package_defined_automation_is_present_not_orphaned() -> None:
    index = _index()
    result = index.lookup(
        entity_id="automation.package_defined",
        domain="automation",
        platform="automation",
        unique_id="package_defined_automation",
    )
    assert result.status is SourceDefinitionStatus.PRESENT
    assert result.source_definition_missing is False


def test_ui_managed_automation_in_top_level_yaml_is_present_not_orphaned() -> None:
    """A UI-editor-created automation lives in automations.yaml, exactly
    like a hand-authored one -- there is no separate storage surface for
    it, so it must be found the same way.
    """
    index = _index()
    result = index.lookup(
        entity_id="automation.ui_created",
        domain="automation",
        platform="automation",
        unique_id="1700000000001",
    )
    assert result.status is SourceDefinitionStatus.PRESENT
    assert result.source_definition_missing is False


def test_package_script_is_present() -> None:
    index = _index()
    result = index.lookup(
        entity_id="script.package_script",
        domain="script",
        platform="script",
        unique_id="package_script",
    )
    assert result.status is SourceDefinitionStatus.PRESENT


def test_confirmed_automation_orphan_is_flagged() -> None:
    index = _index()
    result = index.lookup(
        entity_id="automation.deleted_long_ago",
        domain="automation",
        platform="automation",
        unique_id="1699999999999",
    )
    assert result.status is SourceDefinitionStatus.MISSING_CONFIRMED
    assert result.source_definition_missing is True


def test_confirmed_script_orphan_is_flagged() -> None:
    index = _index()
    result = index.lookup(
        entity_id="script.deleted",
        domain="script",
        platform="script",
        unique_id="no_longer_exists",
    )
    assert result.status is SourceDefinitionStatus.MISSING_CONFIRMED


def test_confirmed_scene_orphan_is_flagged() -> None:
    index = _index()
    result = index.lookup(
        entity_id="scene.deleted",
        domain="scene",
        platform="homeassistant",
        unique_id="9999999999999",
    )
    assert result.status is SourceDefinitionStatus.MISSING_CONFIRMED


def test_integration_managed_scene_is_unsupported_not_missing() -> None:
    """A scene whose registry platform is not 'homeassistant' has no
    local YAML definition to check at all -- must never be claimed
    missing.
    """
    index = _index()
    result = index.lookup(
        entity_id="scene.cloud_scene",
        domain="scene",
        platform="tuya",
        unique_id="some-cloud-scene-id",
    )
    assert result.status is SourceDefinitionStatus.UNSUPPORTED
    assert result.source_definition_missing is None


def test_parse_failure_degrades_gracefully_never_false_positive() -> None:
    """A malformed package file must never cause a false MISSING_CONFIRMED
    for an entity that could legitimately be defined in that broken file.
    """
    index = SourceDefinitionIndex.build(
        (
            ConfigSourceFile(path="automations.yaml", content=AUTOMATIONS_YAML),
            ConfigSourceFile(
                path="packages/broken.yaml",
                content="automation:\n  - id: [this is not valid yaml: :::",
            ),
        )
    )
    result = index.lookup(
        entity_id="automation.maybe_in_broken_file",
        domain="automation",
        platform="automation",
        unique_id="could_be_anywhere",
    )
    assert result.status is SourceDefinitionStatus.SOURCE_UNAVAILABLE
    # Tri-state: never collapses an uncertain result to a boolean.
    assert result.source_definition_missing is None


def test_parse_failure_does_not_affect_a_definition_already_found_elsewhere() -> None:
    """A different file failing to parse must never retroactively make an
    already-found definition look uncertain.
    """
    index = SourceDefinitionIndex.build(
        (
            ConfigSourceFile(path="automations.yaml", content=AUTOMATIONS_YAML),
            ConfigSourceFile(
                path="packages/broken.yaml",
                content="automation:\n  - id: [this is not valid yaml: :::",
            ),
        )
    )
    result = index.lookup(
        entity_id="automation.ui_created",
        domain="automation",
        platform="automation",
        unique_id="1700000000001",
    )
    assert result.status is SourceDefinitionStatus.PRESENT


def test_ambiguous_when_id_defined_in_two_files() -> None:
    index = SourceDefinitionIndex.build(
        (
            ConfigSourceFile(
                path="automations.yaml",
                content="- id: 'dup1'\n  alias: one\n  triggers: []\n  conditions: []\n  actions: []\n",
            ),
            ConfigSourceFile(
                path="packages/dup.yaml",
                content="automation:\n  - id: dup1\n    alias: two\n    triggers: []\n    conditions: []\n    actions: []\n",
            ),
        )
    )
    result = index.lookup(
        entity_id="automation.dup", domain="automation", platform="automation", unique_id="dup1"
    )
    assert result.status is SourceDefinitionStatus.AMBIGUOUS
    assert len(result.defining_files) == 2


def test_no_unique_id_is_source_unavailable_not_missing() -> None:
    index = _index()
    result = index.lookup(
        entity_id="automation.no_uid", domain="automation", platform="automation", unique_id=None
    )
    assert result.status is SourceDefinitionStatus.SOURCE_UNAVAILABLE
    assert result.source_definition_missing is None


def test_unsupported_domain() -> None:
    index = _index()
    result = index.lookup(
        entity_id="light.foo", domain="light", platform="light", unique_id="abc"
    )
    assert result.status is SourceDefinitionStatus.UNSUPPORTED
