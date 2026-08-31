"""Tests for AbandonedBugfixForkAnalyzer (mission Part 5).

The water_bill_estimate_2/water_cost_today_2/water_flow_gpm_2 pattern:
must NEVER trigger on the suffix pattern alone -- only the exact
zero-source + zero-reference + marker combination.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hamie.analysis.analyzers.abandoned_bugfix_fork import AbandonedBugfixForkAnalyzer
from hamie.application.ports import EntityRecord
from hamie.domain.dependency_references import (
    SCANNED_SOURCES,
    DependencyScanCoverage,
    EntityReferenceIndex,
    ReferenceHit,
)
from hamie.domain.findings import RecommendationKind
from hamie.infrastructure.source_definition_index import (
    ConfigSourceFile,
    SourceDefinitionIndex,
)

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
ANALYZER = AbandonedBugfixForkAnalyzer(source_instance="test_home")


def _rec(entity_id: str, *, unique_id: str | None, state: str = "unavailable") -> EntityRecord:
    domain = entity_id.partition(".")[0]
    return EntityRecord(
        entity_id=entity_id,
        state=state,
        last_changed=NOW,
        last_updated=NOW,
        registry_id=f"reg-{entity_id}",
        unique_id=unique_id,
        device_id=None,
        config_entry_id=None,
        disabled=False,
        restored=None,
        domain=domain,
    )


def _index(path: str, content: str) -> SourceDefinitionIndex:
    return SourceDefinitionIndex.build((ConfigSourceFile(path=path, content=content),))


def _analyze(records, *, reference_index=None, source_index=None):
    return ANALYZER.analyze_collection(
        records, observed_at=NOW, reference_index=reference_index, source_index=source_index
    )


# --------------------------------------------------------------------------
# True positive: anonymized water_bill_estimate_2 shape.
# --------------------------------------------------------------------------


def test_detects_abandoned_bugfix_fork() -> None:
    base = _rec("sensor.water_cost_today", unique_id="water_cost_today", state="12.50")
    fork = _rec("sensor.water_cost_today_2", unique_id="water_cost_today_fixed", state="unavailable")
    empty_index = SourceDefinitionIndex.build(())
    empty_refs = EntityReferenceIndex(
        references={}, coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES)
    )
    outcome = _analyze((base, fork), reference_index=empty_refs, source_index=empty_index)

    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.title_key == "abandoned_bugfix_fork"
    assert finding.recommendation.kind is RecommendationKind.DISABLE_CANDIDATE
    predicates = {e.predicate: e.value for e in finding.evidence}
    assert predicates["hamie.entity.abandoned_bugfix_fork_marker@1"] == "fixed"


# --------------------------------------------------------------------------
# False-positive suppression: suffix + marker alone is never enough.
# --------------------------------------------------------------------------


def test_marker_alone_without_zero_source_and_references_is_not_flagged() -> None:
    base = _rec("sensor.water_cost_today", unique_id="water_cost_today", state="12.50")
    fork = _rec("sensor.water_cost_today_2", unique_id="water_cost_today_fixed", state="on")
    package = """
template:
  - sensor:
      - name: Water Cost Fixed
        unique_id: water_cost_today_fixed
"""
    # Has a live source definition -- not abandoned.
    outcome = _analyze((base, fork), source_index=_index("packages/water.yaml", package))
    assert outcome.findings == ()


def test_marker_with_live_reference_is_not_flagged() -> None:
    base = _rec("sensor.water_cost_today", unique_id="water_cost_today", state="12.50")
    fork = _rec("sensor.water_cost_today_2", unique_id="water_cost_today_fixed", state="unavailable")
    referenced_index = EntityReferenceIndex(
        references={
            "sensor.water_cost_today_2": (
                ReferenceHit(source="dashboard", referencing_object_id="dashboard:default:view_0"),
            )
        },
        coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES),
    )
    outcome = _analyze(
        (base, fork), reference_index=referenced_index, source_index=SourceDefinitionIndex.build(())
    )
    assert outcome.findings == ()


def test_suffix_alone_with_no_marker_is_never_flagged() -> None:
    """Plain `_2` suffix with no distinguishing marker in its unique_id --
    must never be treated as an abandoned fork just because it is
    unreferenced and undefined (that alone is orphaned_definitions.py's
    job, not this analyzer's)."""
    base = _rec("sensor.plain_thing", unique_id="plain_thing", state="on")
    sibling = _rec("sensor.plain_thing_2", unique_id="plain_thing_v9_2024_release", state="unavailable")
    empty_refs = EntityReferenceIndex(
        references={}, coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES)
    )
    outcome = _analyze(
        (base, sibling), reference_index=empty_refs, source_index=SourceDefinitionIndex.build(())
    )
    assert outcome.findings == ()


# --------------------------------------------------------------------------
# Degradation: one malformed group never aborts the whole scan.
# --------------------------------------------------------------------------


class _PoisonReferenceIndex:
    def __init__(self, poison_entity_id: str) -> None:
        self._poison = poison_entity_id
        self.coverage = DependencyScanCoverage(scanned_sources=SCANNED_SOURCES)

    def referenced_by(self, entity_id: str):
        if entity_id == self._poison:
            raise RuntimeError("simulated malformed reference lookup")
        return ()


def test_one_malformed_group_never_aborts_the_whole_scan() -> None:
    poisoned_base = _rec("sensor.poisoned", unique_id="poisoned", state="on")
    poisoned_fork = _rec("sensor.poisoned_2", unique_id="poisoned_fixed", state="unavailable")
    good_base = _rec("sensor.water_cost_today", unique_id="water_cost_today", state="12.50")
    good_fork = _rec(
        "sensor.water_cost_today_2", unique_id="water_cost_today_fixed", state="unavailable"
    )
    outcome = _analyze(
        (poisoned_base, poisoned_fork, good_base, good_fork),
        reference_index=_PoisonReferenceIndex("sensor.poisoned_2"),
        source_index=SourceDefinitionIndex.build(()),
    )
    assert any(f.subject.source_id == "sensor.water_cost_today_2" for f in outcome.findings)
    assert "sensor.poisoned" in outcome.uncovered_subjects
    assert "sensor.poisoned" not in outcome.covered_subjects
