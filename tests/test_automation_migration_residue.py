"""Tests for AutomationMigrationResidueAnalyzer (mission Part 5, test
patterns 6, 10).

Pattern 6: the backyard-loitering/house-empty-observer-shaped automation
ID residue -- a dead automation.* paired with its live current sibling.
Pattern 10: insufficient-history case -- with no reference scan (short/
no evidence), the analyzer must tag INSUFFICIENT_HISTORY and stay
BLOCKED_INSUFFICIENT_EVIDENCE, never claim the old automation is dead.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hamie.analysis.analyzers.automation_migration_residue import (
    AutomationMigrationResidueAnalyzer,
)
from hamie.application.ports import EntityRecord
from hamie.domain.automation_residue import AutomationResidueTemporalTag
from hamie.domain.dependency_references import (
    SCANNED_SOURCES,
    DependencyScanCoverage,
    EntityReferenceIndex,
)
from hamie.domain.findings import RecommendationKind, RemediationSafetyGate

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
ANALYZER = AutomationMigrationResidueAnalyzer(source_instance="test_home")


def _rec(
    entity_id: str,
    *,
    state: str = "on",
    source_definition_missing: bool | None = None,
) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        state=state,
        last_changed=NOW,
        last_updated=NOW,
        registry_id=f"reg-{entity_id}",
        device_id=None,
        config_entry_id=None,
        disabled=False,
        restored=None,
        domain="automation",
        source_definition_missing=source_definition_missing,
    )


def _analyze(records, reference_index=None):
    return ANALYZER.analyze_collection(records, observed_at=NOW, reference_index=reference_index)


# --------------------------------------------------------------------------
# Pattern 6: backyard-loitering / house-empty-observer shaped residue.
# --------------------------------------------------------------------------


def test_detects_automation_id_residue_supported() -> None:
    dead = _rec("automation.kitchen_usage_watch_v1", state="unavailable", source_definition_missing=True)
    live = _rec("automation.kitchen_usage_watch_v1_2", state="on", source_definition_missing=False)
    complete_index = EntityReferenceIndex(
        references={}, coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES)
    )
    outcome = _analyze((dead, live), complete_index)

    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.title_key == "automation_migration_residue"
    predicates = {e.predicate: e.value for e in finding.evidence}
    assert predicates["hamie.automation_residue.temporal_tag@1"] == (
        AutomationResidueTemporalTag.SUPPORTED.value
    )
    assert finding.recommendation.kind is RecommendationKind.DELETE_CANDIDATE
    assert finding.recommendation.safety_gate is RemediationSafetyGate.SAFE_TO_REMOVE_REGISTRY
    # Never PROVEN -- no live automation_triggered event reader exists.
    assert predicates["hamie.automation_residue.temporal_tag@1"] != (
        AutomationResidueTemporalTag.PROVEN.value
    )


# --------------------------------------------------------------------------
# Pattern 10: insufficient-history case.
# --------------------------------------------------------------------------


def test_no_reference_scan_stays_insufficient_history() -> None:
    dead = _rec("automation.house_empty_observer_v1", state="unavailable", source_definition_missing=True)
    live = _rec("automation.house_empty_observer_v1_2", state="on", source_definition_missing=False)
    outcome = _analyze((dead, live), reference_index=None)

    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    predicates = {e.predicate: e.value for e in finding.evidence}
    assert predicates["hamie.automation_residue.temporal_tag@1"] == (
        AutomationResidueTemporalTag.INSUFFICIENT_HISTORY.value
    )
    assert finding.recommendation.kind is RecommendationKind.NEEDS_EVIDENCE
    assert finding.recommendation.safety_gate is RemediationSafetyGate.BLOCKED_INSUFFICIENT_EVIDENCE
    assert finding.recommendation.blocked_reason is not None
    # Never claims safe_to_remove without real evidence.
    assert finding.recommendation.dependency_assessment.safe_to_remove is False


def test_never_emits_proven_regardless_of_evidence_strength() -> None:
    """Structural guarantee: even the strongest available evidence
    (complete zero-reference scan) never reaches PROVEN -- see
    domain/automation_residue.py's own disclosed infra-gap docstring."""
    dead = _rec("automation.x_v1", state="unavailable", source_definition_missing=True)
    live = _rec("automation.x_v1_2", state="on", source_definition_missing=False)
    complete_index = EntityReferenceIndex(
        references={}, coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES)
    )
    outcome = _analyze((dead, live), complete_index)
    for finding in outcome.findings:
        predicates = {e.predicate: e.value for e in finding.evidence}
        assert predicates["hamie.automation_residue.temporal_tag@1"] != (
            AutomationResidueTemporalTag.PROVEN.value
        )


# --------------------------------------------------------------------------
# False-positive suppression: no dead/live pairing -> no finding.
# --------------------------------------------------------------------------


def test_no_finding_when_only_one_member_in_group() -> None:
    lone = _rec("automation.solo", state="on", source_definition_missing=False)
    outcome = _analyze((lone,))
    assert outcome.findings == ()


def test_no_finding_when_neither_member_has_confirmed_missing_source() -> None:
    first = _rec("automation.both_fine", state="on", source_definition_missing=False)
    second = _rec("automation.both_fine_2", state="on", source_definition_missing=False)
    outcome = _analyze((first, second))
    assert outcome.findings == ()


class _PoisonReferenceIndex:
    """A reference_index whose `.referenced_by` raises for one specific
    entity -- proves one malformed group degrades without aborting the
    whole scan (mission Part 6)."""

    def __init__(self, poison_entity_id: str) -> None:
        self._poison = poison_entity_id
        self.coverage = DependencyScanCoverage(scanned_sources=SCANNED_SOURCES)

    def referenced_by(self, entity_id: str):
        if entity_id == self._poison:
            raise RuntimeError("simulated malformed reference lookup")
        return ()


def test_one_malformed_group_never_aborts_the_whole_scan() -> None:
    poisoned_dead = _rec("automation.poisoned_v1", state="unavailable", source_definition_missing=True)
    poisoned_live = _rec("automation.poisoned_v1_2", state="on", source_definition_missing=False)
    good_dead = _rec("automation.healthy_v1", state="unavailable", source_definition_missing=True)
    good_live = _rec("automation.healthy_v1_2", state="on", source_definition_missing=False)

    outcome = _analyze(
        (poisoned_dead, poisoned_live, good_dead, good_live),
        reference_index=_PoisonReferenceIndex("automation.poisoned_v1"),
    )
    # The poisoned group degrades to uncovered; the healthy group still
    # produces its finding normally.
    assert any(f.subject.source_id == "automation.healthy_v1" for f in outcome.findings)
    assert "automation.poisoned_v1" in outcome.uncovered_subjects


def test_protected_naming_pattern_caps_safety_gate() -> None:
    """The exact naming signal this session identified as real (mission
    Part 4): even with a complete zero-reference scan, a
    security-relevant automation name never reaches SAFE_TO_REMOVE_REGISTRY."""
    dead = _rec("automation.backyard_loitering_v1", state="unavailable", source_definition_missing=True)
    live = _rec("automation.backyard_loitering_v1_2", state="on", source_definition_missing=False)
    complete_index = EntityReferenceIndex(
        references={}, coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES)
    )
    outcome = _analyze((dead, live), complete_index)
    assert len(outcome.findings) == 1
    assert outcome.findings[0].recommendation.safety_gate is RemediationSafetyGate.PROTECTED
