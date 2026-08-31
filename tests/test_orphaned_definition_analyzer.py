"""Tests for the extended OrphanedDefinitionAnalyzer (mission Part 2/5).

Covers: allowed_recommendations now includes DELETE_CANDIDATE; a
confirmed orphan with a complete, zero-reference dependency scan
surfaces DELETE_CANDIDATE (advisory only); everything else still
surfaces the original, weaker DISABLE.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hamie.analysis.analyzers.orphaned_definitions import OrphanedDefinitionAnalyzer
from hamie.analysis.contracts import AnalysisPartition
from hamie.application.ports import EntityRecord
from hamie.domain.dependency_references import (
    SCANNED_SOURCES,
    DependencyScanCoverage,
    EntityReferenceIndex,
    ReferenceHit,
)
from hamie.domain.findings import RecommendationKind

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def _orphan_record(entity_id: str = "automation.orphan") -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        state="unavailable",
        last_changed=NOW,
        last_updated=NOW,
        registry_id="reg1",
        device_id=None,
        config_entry_id=None,
        disabled=False,
        restored=False,
        domain="automation",
        platform="automation",
        source_definition_missing=True,
    )


def _partition(record: EntityRecord) -> AnalysisPartition:
    return AnalysisPartition(
        partition_id="p1",
        capability_id="home_assistant.definition_presence@1",
        source_revision="rev1",
        records=(record,),
    )


def test_allowed_recommendations_includes_delete_candidate() -> None:
    analyzer = OrphanedDefinitionAnalyzer()
    assert RecommendationKind.DELETE_CANDIDATE in analyzer.descriptor.allowed_recommendations
    assert RecommendationKind.DISABLE in analyzer.descriptor.allowed_recommendations


def test_no_reference_index_supplied_stays_disable() -> None:
    analyzer = OrphanedDefinitionAnalyzer()
    outcome = analyzer.analyze(_partition(_orphan_record()), observed_at=NOW)
    finding = outcome.findings[0]
    assert finding.recommendation.kind is RecommendationKind.DISABLE
    assert finding.recommendation.dependency_assessment.safe_to_remove is False


def test_complete_zero_reference_scan_surfaces_delete_candidate() -> None:
    analyzer = OrphanedDefinitionAnalyzer()
    complete_index = EntityReferenceIndex(
        references={},
        coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES),
    )
    outcome = analyzer.analyze(
        _partition(_orphan_record()), observed_at=NOW, reference_index=complete_index
    )
    finding = outcome.findings[0]
    assert finding.recommendation.kind is RecommendationKind.DELETE_CANDIDATE
    assert finding.recommendation.dependency_assessment.safe_to_remove is True
    assert finding.recommendation.dependency_assessment.coverage.value == "complete"


def test_referenced_orphan_stays_disable_even_with_reference_index() -> None:
    analyzer = OrphanedDefinitionAnalyzer()
    referenced_index = EntityReferenceIndex(
        references={
            "automation.orphan": (
                ReferenceHit(source="automation", referencing_object_id="automation.other"),
            )
        },
        coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES),
    )
    outcome = analyzer.analyze(
        _partition(_orphan_record()), observed_at=NOW, reference_index=referenced_index
    )
    finding = outcome.findings[0]
    assert finding.recommendation.kind is RecommendationKind.DISABLE
    assert finding.recommendation.dependency_assessment.safe_to_remove is False


def test_incomplete_coverage_stays_disable_even_with_zero_references() -> None:
    """A reference scan that found nothing but had a failed source must
    not be trusted as strongly as a fully successful one.
    """
    analyzer = OrphanedDefinitionAnalyzer()
    partial_index = EntityReferenceIndex(
        references={},
        coverage=DependencyScanCoverage(
            scanned_sources=("automation",), failed_sources=("dashboard",)
        ),
    )
    outcome = analyzer.analyze(
        _partition(_orphan_record()), observed_at=NOW, reference_index=partial_index
    )
    finding = outcome.findings[0]
    assert finding.recommendation.kind is RecommendationKind.DISABLE


def test_never_flags_a_present_definition() -> None:
    analyzer = OrphanedDefinitionAnalyzer()
    record = EntityRecord(
        entity_id="automation.fine",
        state="on",
        last_changed=NOW,
        last_updated=NOW,
        registry_id="reg2",
        device_id=None,
        config_entry_id=None,
        disabled=False,
        restored=False,
        domain="automation",
        platform="automation",
        source_definition_missing=False,
    )
    outcome = analyzer.analyze(_partition(record), observed_at=NOW)
    assert outcome.findings == ()
