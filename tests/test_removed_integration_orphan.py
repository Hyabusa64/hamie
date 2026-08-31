"""Tests for RemovedIntegrationOrphanAnalyzer (mission Part 5, test
patterns 3, 4, 11).

Pattern 3: the proven Lutron pattern, generalized/anonymized.
Pattern 4: an official migration replacement (live config entry, real
device) -- must never be flagged.
Pattern 11: a template-platform entity with a legitimately-absent
config_entry_id -- must never be treated as automatic orphan evidence
just because config_entry_id is None.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hamie.analysis.analyzers.removed_integration_orphan import (
    RemovedIntegrationOrphanAnalyzer,
)
from hamie.application.ports import EntityRecord
from hamie.domain.dependency_references import (
    SCANNED_SOURCES,
    DependencyScanCoverage,
    EntityReferenceIndex,
    ReferenceHit,
)
from hamie.domain.findings import RecommendationKind, RemediationSafetyGate
from hamie.infrastructure.installation_topology import build_installation_topology

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
ANALYZER = RemovedIntegrationOrphanAnalyzer(source_instance="test_home")


def _rec(
    entity_id: str,
    *,
    platform: str | None,
    device_id: str | None = None,
    config_entry_id: str | None = None,
    state: str = "unavailable",
    friendly_name: str | None = None,
    source_definition_missing: bool | None = None,
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
        disabled=False,
        restored=None,
        domain=domain,
        platform=platform,
        friendly_name=friendly_name,
        source_definition_missing=source_definition_missing,
    )


def _analyze(records, topology, reference_index=None):
    return ANALYZER.analyze_collection(
        records,
        observed_at=NOW,
        installation_topology=topology,
        reference_index=reference_index,
    )


def _complete_reference_index(references=None):
    return EntityReferenceIndex(
        references=references or {},
        coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES),
    )


# --------------------------------------------------------------------------
# Pattern 3: removed custom integration (anonymized Lutron shape).
# --------------------------------------------------------------------------


def test_detects_removed_custom_integration_orphan() -> None:
    record = _rec("scene.old_lighting_scene", platform="legacy_bridge_pro")
    topology = build_installation_topology(
        config_entry_domains=frozenset({"hue", "zwave_js"}),
        custom_component_dirs=frozenset({"some_other_custom_thing"}),
    )
    outcome = _analyze((record,), topology, _complete_reference_index())
    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.title_key == "removed_integration_orphan"
    assert finding.recommendation.kind in (
        RecommendationKind.DELETE_CANDIDATE,
    )


def test_incomplete_reference_evidence_never_recommends_cleanup() -> None:
    record = _rec("scene.old_lighting_scene", platform="legacy_bridge_pro")
    topology = build_installation_topology(
        config_entry_domains=frozenset(), custom_component_dirs=frozenset()
    )

    outcome = _analyze((record,), topology)

    assert len(outcome.findings) == 1
    recommendation = outcome.findings[0].recommendation
    assert recommendation.kind is RecommendationKind.INVESTIGATE
    assert (
        recommendation.safety_gate
        is RemediationSafetyGate.BLOCKED_INSUFFICIENT_EVIDENCE
    )
    assert recommendation.dependency_assessment.safe_to_remove is False


def test_referenced_removed_integration_is_dependency_bug_not_cleanup_candidate() -> None:
    record = _rec("light.legacy_but_still_targeted", platform="legacy_bridge_pro")
    topology = build_installation_topology(
        config_entry_domains=frozenset(), custom_component_dirs=frozenset()
    )
    index = _complete_reference_index(
        {
            record.entity_id: (
                ReferenceHit(
                    source="automation",
                    referencing_object_id="automation.depends_on_legacy_light",
                ),
            )
        }
    )

    outcome = _analyze((record,), topology, index)

    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.condition_key == "removed_integration_broken_reference"
    assert finding.recommendation.kind is RecommendationKind.INVESTIGATE
    assert finding.recommendation.safety_gate is RemediationSafetyGate.FUNCTIONAL_BUG
    assert finding.recommendation.dependency_assessment.safe_to_remove is False
    assert finding.recommendation.dependency_assessment.supporting_subject_ids == (
        "integration:legacy_bridge_pro",
    )
    assert "Do not remove" in finding.recommendation.action


def test_repeated_across_many_entities_16x_shape() -> None:
    """Mirrors this session's real finding of 16 Lutron entities."""
    records = tuple(
        _rec(f"scene.legacy_scene_{i}", platform="legacy_bridge_pro") for i in range(16)
    )
    topology = build_installation_topology(
        config_entry_domains=frozenset({"hue"}), custom_component_dirs=frozenset()
    )
    outcome = _analyze(records, topology)
    assert len(outcome.findings) == 16


# --------------------------------------------------------------------------
# Pattern 4: official migration replacement -- must not be flagged.
# --------------------------------------------------------------------------


def test_live_integration_with_device_and_config_entry_not_flagged() -> None:
    record = _rec(
        "light.hue_kitchen",
        platform="hue",
        device_id="device-1",
        config_entry_id="entry-1",
        state="on",
    )
    topology = build_installation_topology(
        config_entry_domains=frozenset({"hue"}), custom_component_dirs=frozenset()
    )
    outcome = _analyze((record,), topology)
    assert outcome.findings == ()
    assert "light.hue_kitchen" in outcome.excluded_subjects


def test_no_device_or_config_entry_but_platform_still_live_not_flagged() -> None:
    """The platform itself still has live config entries elsewhere in the
    installation -- not a removed integration, even if this one row lost
    its own config_entry_id/device_id link somehow."""
    record = _rec("light.orphaned_row", platform="hue")
    topology = build_installation_topology(
        config_entry_domains=frozenset({"hue"}), custom_component_dirs=frozenset()
    )
    outcome = _analyze((record,), topology)
    assert outcome.findings == ()


# --------------------------------------------------------------------------
# Pattern 11: template-platform entity, legitimately no config_entry.
# --------------------------------------------------------------------------


def test_template_platform_entity_not_treated_as_orphan() -> None:
    """`template` ships with HA core -- it is never in custom_components/,
    so a bare config_entry_id/device_id absence alone must never be
    treated as removed-integration evidence for it."""
    record = _rec("sensor.template_math", platform="template", state="42")
    topology = build_installation_topology(
        config_entry_domains=frozenset({"hue"}), custom_component_dirs=frozenset()
    )
    outcome = _analyze((record,), topology)
    assert outcome.findings == ()
    assert "sensor.template_math" in outcome.covered_subjects


def test_live_review_core_platforms_are_never_removed_integration_orphans() -> None:
    """Regression for the 2026-08-25 read-only live findings review.

    These platforms legitimately have no per-row config entry/device and
    no custom_components directory.  That absence is their normal ownership
    model, not evidence that an integration was removed.
    """
    platforms = (
        "automation",
        "script",
        "scene",
        "energy",
        "homeassistant",
        "input_button",
    )
    records = tuple(
        _rec(f"{platform}.legitimate_{platform}", platform=platform, state="on")
        for platform in platforms
    )
    topology = build_installation_topology(
        config_entry_domains=frozenset(), custom_component_dirs=frozenset()
    )

    outcome = _analyze(records, topology)

    assert outcome.findings == ()
    assert outcome.uncovered_subjects == ()
    assert set(outcome.covered_subjects) == {record.entity_id for record in records}


def test_present_source_definition_is_hard_exclusion() -> None:
    """Direct definition evidence overrides absence-based topology clues."""
    record = _rec(
        "sensor.source_backed_custom_entity",
        platform="no_longer_installed_custom_platform",
        state="42",
        source_definition_missing=False,
    )
    topology = build_installation_topology(
        config_entry_domains=frozenset(), custom_component_dirs=frozenset()
    )

    outcome = _analyze((record,), topology)

    assert outcome.findings == ()
    assert outcome.uncovered_subjects == ()
    assert record.entity_id in outcome.excluded_subjects


# --------------------------------------------------------------------------
# Degradation: missing topology -> honestly uncovered, never a false answer.
# --------------------------------------------------------------------------


def test_missing_topology_degrades_to_uncovered() -> None:
    record = _rec("scene.old_lighting_scene", platform="legacy_bridge_pro")
    outcome = _analyze((record,), None)
    assert outcome.findings == ()
    assert "scene.old_lighting_scene" in outcome.uncovered_subjects


def test_missing_platform_degrades_to_uncovered_not_flagged() -> None:
    record = _rec("scene.mystery", platform=None)
    topology = build_installation_topology(
        config_entry_domains=frozenset(), custom_component_dirs=frozenset()
    )
    outcome = _analyze((record,), topology)
    assert outcome.findings == ()
    assert "scene.mystery" in outcome.uncovered_subjects


# --------------------------------------------------------------------------
# Pattern 9-adjacent: protected subject caps at PROTECTED.
# --------------------------------------------------------------------------


def test_protected_subject_caps_safety_gate() -> None:
    record = _rec("lock.legacy_garage_lock", platform="legacy_bridge_pro")
    topology = build_installation_topology(
        config_entry_domains=frozenset(), custom_component_dirs=frozenset()
    )
    outcome = _analyze((record,), topology)
    assert len(outcome.findings) == 1
    assert outcome.findings[0].recommendation.safety_gate is RemediationSafetyGate.PROTECTED


# --------------------------------------------------------------------------
# Degradation: one malformed entity never aborts the whole scan.
# --------------------------------------------------------------------------


class _PoisonTopology:
    """A topology whose platform check raises for one specific platform."""

    def __init__(self, poison_platform: str) -> None:
        self._poison = poison_platform

    def platform_has_removed_integration(self, platform: str | None) -> bool:
        if platform == self._poison:
            raise RuntimeError("simulated malformed topology lookup")
        return platform == "legacy_bridge_pro"


def test_one_malformed_entity_never_aborts_the_whole_scan() -> None:
    poisoned = _rec("scene.poisoned", platform="simulated_boom")
    healthy = _rec("scene.healthy_legacy_scene", platform="legacy_bridge_pro")
    outcome = _analyze((poisoned, healthy), _PoisonTopology("simulated_boom"))

    assert len(outcome.findings) == 1
    assert outcome.findings[0].subject.source_id == "scene.healthy_legacy_scene"
    assert "scene.poisoned" in outcome.uncovered_subjects
    assert "scene.poisoned" not in outcome.covered_subjects
