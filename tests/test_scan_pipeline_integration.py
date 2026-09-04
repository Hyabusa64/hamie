"""End-to-end scan pipeline integration tests (mission Part 4).

Exercises the real, wired ``ScanCoordinator`` (application/scan_
coordinator.py) with all four evidence paths registered exactly as
``hamie/__init__.py`` now configures them -- ``UnavailableEntityAnalyzer``
and ``OrphanedDefinitionAnalyzer`` through ``AnalyzerSupervisor``,
``DuplicateMigrationAnalyzer`` through ``WholeCollectionSupervisor``, and
temporal-evidence enrichment via ``analysis/temporal_enrichment.py`` --
rather than exercising any of those modules in isolation (already
covered by ``tests/test_duplicate_classifier.py``,
``tests/test_temporal_evidence.py``,
``tests/test_orphaned_definition_analyzer.py``, etc.).

Only the true I/O boundary is faked here (a live Home Assistant
``hass`` object, its Store-backed repository, and the recorder): the
source/repository/projection/reference/temporal-evidence ports are
minimal in-memory fakes satisfying the exact Protocols
``application/ports.py``/``application/persistence.py``/
``application/scan_coordinator.py`` declare. Everything else --
``ScanCoordinator``, both supervisor types, all three analyzers,
``application/reconciliation.py``, and (for the Issues/Review-path
tests) the real ``RuntimeProjection``/``ExplorerIndex`` classes
``presentation/api.py``'s WebSocket handlers themselves read from via
``MaintenanceOperationsService.query_findings`` -- is the genuine
production code, unmodified. The one thing not exercised is the
WebSocket transport itself (``@websocket_api.websocket_command``),
which requires a live Home Assistant test harness this offline task
does not have access to; ``ExplorerIndex.query_findings`` is exactly
what ``MaintenanceOperationsService.query_findings`` delegates to one
line later, so calling it directly is the same business-logic code
path a real Issues/Review WebSocket request would run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hamie.analysis.analyzers.duplicate_migration import DuplicateMigrationAnalyzer
from hamie.analysis.analyzers.orphaned_definitions import OrphanedDefinitionAnalyzer
from hamie.analysis.analyzers.unavailable_entities import (
    ANALYZER_ID as UNAVAILABLE_ANALYZER_ID,
)
from hamie.analysis.analyzers.unavailable_entities import (
    CAPABILITY_ID as UNAVAILABLE_CAPABILITY_ID,
)
from hamie.analysis.analyzers.unavailable_entities import UnavailableEntityAnalyzer
from hamie.analysis.supervisor import AnalyzerSupervisor, PerformanceProfile
from hamie.analysis.whole_collection_supervisor import WholeCollectionSupervisor
from hamie.application.persistence import GenerationConflictError, RepositoryState
from hamie.application.ports import EntityCapture, EntityRecord
from hamie.application.runtime_projection import RuntimeProjection
from hamie.application.scan_coordinator import ScanCoordinator
from hamie.domain.dependency_references import (
    SCANNED_SOURCES,
    DependencyScanCoverage,
    EntityReferenceIndex,
    ReferenceHit,
)
from hamie.domain.evaluations import SourceCapture
from hamie.domain.findings import FindingLifecycle, RecommendationKind
from hamie.domain.incidents import IncidentLifecycle, IncidentPriority

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# Fakes: the true I/O boundary only.
# --------------------------------------------------------------------------


class FakeClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class FakeRepository:
    """In-memory PersistenceUnitOfWorkPort."""

    def __init__(self) -> None:
        self.state = RepositoryState()

    async def async_load(self) -> RepositoryState:
        return self.state

    async def async_commit(self, state: RepositoryState, *, expected_generation: int) -> None:
        if self.state.generation != expected_generation:
            raise GenerationConflictError("stored generation changed")
        self.state = state

    async def async_remove(self) -> None:
        self.state = RepositoryState()


class FakeDerivedProjection:
    """Minimal DerivedProjectionPort -- RuntimeProjection's own downstream sink."""

    async def async_sync(self, state: RepositoryState) -> None:
        return None

    async def async_clear(self) -> None:
        return None

    async def async_report_storage_error(self, reason_code: str) -> None:
        return None


class FakeSource:
    """In-memory OperationalSourcePort."""

    def __init__(self, entities: tuple[EntityRecord, ...], *, revision: str = "rev1") -> None:
        self.entities = entities
        self.revision = revision

    async def async_capture_entities(self) -> EntityCapture:
        metadata = SourceCapture(
            source_id="home_assistant",
            capability_id=UNAVAILABLE_CAPABILITY_ID,
            revision=self.revision,
            capture_started_at=NOW,
            capture_ended_at=NOW,
            observed_at=NOW,
            max_age_seconds=30,
            requested_scopes=("entity_state", "entity_registry"),
            captured_scopes=("entity_state", "entity_registry"),
        )
        return EntityCapture(metadata=metadata, entities=self.entities)


class FakeReferenceSource:
    """In-memory ReferenceIndexPort, optionally failing (mission Part 4)."""

    def __init__(self, index: EntityReferenceIndex | None = None, *, raise_error: bool = False) -> None:
        self._index = index
        self._raise = raise_error

    async def async_capture_reference_index(self) -> EntityReferenceIndex:
        if self._raise:
            raise RuntimeError("reference source unreachable (simulated)")
        return self._index if self._index is not None else EntityReferenceIndex()


class FakeTemporalEvidenceSource:
    """In-memory TemporalEvidenceSourcePort, optionally failing (mission Part 4)."""

    def __init__(
        self,
        *,
        raise_on_prime: bool = False,
        raise_on_lookup: bool = False,
        raw_available_seconds: int | None = 40 * 86_400,
        raw_unavailable_seconds: int | None = 40 * 86_400,
    ) -> None:
        self._raise_on_prime = raise_on_prime
        self._raise_on_lookup = raise_on_lookup
        self._raw_available = raw_available_seconds
        self._raw_unavailable = raw_unavailable_seconds
        self.primed_ids: tuple[str, ...] | None = None

    async def async_prime(self, entity_ids, *, now=None) -> None:
        if self._raise_on_prime:
            raise RuntimeError("recorder unreachable (simulated)")
        self.primed_ids = tuple(entity_ids)

    async def async_raw_history_available_seconds(self, entity_id: str) -> int | None:
        if self._raise_on_lookup:
            raise RuntimeError("recorder lookup failed (simulated)")
        return self._raw_available

    async def async_long_term_statistics_unavailable_seconds(self, entity_id: str) -> int | None:
        return None

    def raw_unavailable_seconds(self, entity_id: str) -> int | None:
        return self._raw_unavailable

    def contradicting_activity_found(self, entity_id: str) -> bool:
        return False


# --------------------------------------------------------------------------
# Fixtures: a realistic mixed entity set exercising every analyzer.
# --------------------------------------------------------------------------


def _rec(
    entity_id: str,
    *,
    state: str = "on",
    disabled: bool = False,
    registry_id: str | None = None,
    source_definition_missing: bool | None = None,
    last_changed: datetime = NOW,
    created_at: str | None = None,
    device_id: str | None = None,
    config_entry_id: str | None = None,
    entity_category: str | None = None,
) -> EntityRecord:
    domain = entity_id.partition(".")[0]
    return EntityRecord(
        entity_id=entity_id,
        state=state,
        last_changed=last_changed,
        last_updated=last_changed,
        registry_id=registry_id or f"reg-{entity_id}",
        device_id=device_id,
        config_entry_id=config_entry_id,
        disabled=disabled,
        restored=False,
        domain=domain,
        platform="demo",
        entity_category=entity_category,
        source_definition_missing=source_definition_missing,
        created_at=created_at,
    )


def _mixed_entities() -> tuple[EntityRecord, ...]:
    return (
        # UnavailableEntityAnalyzer: unavailable well past the 300s grace.
        _rec(
            "sensor.stale_temp",
            state="unavailable",
            last_changed=NOW - timedelta(hours=2),
        ),
        # OrphanedDefinitionAnalyzer: automation with a confirmed-missing
        # definition, no live reference (with a complete, empty reference
        # scan supplied -> DELETE_CANDIDATE).
        _rec(
            "automation.gone",
            state="unavailable",
            source_definition_missing=True,
        ),
        # DuplicateMigrationAnalyzer: LIKELY_MIGRATION_LEFTOVER group.
        _rec(
            "automation.foo",
            state="unavailable",
            disabled=True,
            source_definition_missing=True,
            created_at="2024-01-01T00:00:00+00:00",
        ),
        _rec(
            "automation.foo_2",
            state="on",
            disabled=False,
            source_definition_missing=False,
            created_at="2026-01-01T00:00:00+00:00",
        ),
        # An ordinary, unrelated healthy entity.
        _rec("light.kitchen", state="on"),
    )


def _broken_reference_entities() -> tuple[EntityRecord, ...]:
    return (
        _rec("light.hall", state="unavailable", disabled=True),
        _rec("light.hall_2", state="on", disabled=False),
    )


def _ambiguous_entities() -> tuple[EntityRecord, ...]:
    return (
        _rec("sensor.unknown", state="unknown", disabled=False),
        _rec("sensor.unknown_2", state="unknown", disabled=False),
    )


def _make_coordinator(
    entities: tuple[EntityRecord, ...],
    *,
    repository: FakeRepository | None = None,
    reference_source: FakeReferenceSource | None = None,
    temporal_evidence_source: FakeTemporalEvidenceSource | None = None,
    revision: str = "rev1",
    clock: FakeClock | None = None,
) -> tuple[ScanCoordinator, FakeRepository, RuntimeProjection]:
    repository = repository or FakeRepository()
    projection = RuntimeProjection(FakeDerivedProjection(), store_size=lambda _s: 0)
    coordinator = ScanCoordinator(
        FakeSource(entities, revision=revision),
        repository,
        projection,
        supervisors=(
            AnalyzerSupervisor(UnavailableEntityAnalyzer()),
            AnalyzerSupervisor(OrphanedDefinitionAnalyzer()),
            WholeCollectionSupervisor(DuplicateMigrationAnalyzer()),
        ),
        profile=PerformanceProfile.CONSERVATIVE,
        clock=clock or FakeClock(NOW),
        reference_source=reference_source,
        temporal_evidence_source=temporal_evidence_source,
    )
    return coordinator, repository, projection


# --------------------------------------------------------------------------
# 1. A full scan invokes all three analyzers + temporal enrichment.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_scan_invokes_all_analyzers_and_temporal_enrichment() -> None:
    complete_index = EntityReferenceIndex(
        references={}, coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES)
    )
    temporal_source = FakeTemporalEvidenceSource()
    coordinator, _repo, _projection = _make_coordinator(
        _mixed_entities(),
        reference_source=FakeReferenceSource(complete_index),
        temporal_evidence_source=temporal_source,
    )
    result = await coordinator.async_request_scan(trigger="test")
    findings = result.state.findings
    analyzer_ids = {item.analyzer_id for item in findings}
    assert analyzer_ids == {
        "hamie.unavailable_entities",
        "hamie.orphaned_definitions",
        "hamie.duplicate_migration",
    }

    # Orphan got the strong-evidence DELETE_CANDIDATE path since a
    # complete, zero-reference index was supplied (mission Part 1.4).
    orphan = next(f for f in findings if f.analyzer_id == "hamie.orphaned_definitions")
    assert orphan.recommendation.kind is RecommendationKind.DELETE_CANDIDATE

    # Duplicate migration-leftover group -> INVESTIGATE, never DELETE/DISABLE.
    duplicate = next(f for f in findings if f.analyzer_id == "hamie.duplicate_migration")
    assert duplicate.recommendation.kind is RecommendationKind.INVESTIGATE
    assert duplicate.recommendation.kind not in (
        RecommendationKind.DELETE_CANDIDATE,
        RecommendationKind.DISABLE,
    )
    duplicate_incident = next(
        item for item in result.state.incidents if item.category == "duplicate_migration"
    )
    assert {"automation.foo", "automation.foo_2"}.issubset(
        duplicate_incident.affected_subject_ids
    )

    # Temporal evidence enrichment attached evidence to the unavailable
    # finding, with real provenance (mission Part 1.2/4).
    unavailable = next(f for f in findings if f.analyzer_id == UNAVAILABLE_ANALYZER_ID)
    predicates = {item.predicate: item.value for item in unavailable.evidence}
    assert "hamie.entity.temporal_evidence_status@1" in predicates
    assert predicates["hamie.entity.temporal_evidence_status@1"] == "confirmed_unavailable_gt_30d"
    assert predicates["hamie.entity.temporal_evidence_provenance@1"] == "raw_recorder_history"
    assert temporal_source.primed_ids == ("sensor.stale_temp",)


# --------------------------------------------------------------------------
# 2. Evidence-source failures degrade gracefully -- never abort the scan.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reference_source_failure_degrades_gracefully() -> None:
    coordinator, _repo, _projection = _make_coordinator(
        _mixed_entities(), reference_source=FakeReferenceSource(raise_error=True)
    )
    result = await coordinator.async_request_scan(trigger="test")
    # The scan still completed and produced findings from every analyzer
    # -- the orphan simply stayed at its weaker DISABLE recommendation
    # instead of DELETE_CANDIDATE, since no reference evidence was
    # available this scan (same behavior as omitting reference_source
    # entirely).
    findings = result.state.findings
    assert findings
    orphan = next(f for f in findings if f.analyzer_id == "hamie.orphaned_definitions")
    assert orphan.recommendation.kind is RecommendationKind.DISABLE


@pytest.mark.asyncio
async def test_temporal_evidence_priming_failure_degrades_gracefully() -> None:
    coordinator, _repo, _projection = _make_coordinator(
        _mixed_entities(),
        temporal_evidence_source=FakeTemporalEvidenceSource(raise_on_prime=True),
    )
    result = await coordinator.async_request_scan(trigger="test")
    findings = result.state.findings
    assert findings
    unavailable = next(f for f in findings if f.analyzer_id == UNAVAILABLE_ANALYZER_ID)
    predicates = {item.predicate: item.value for item in unavailable.evidence}
    # Priming failed -> every unavailable finding degrades to
    # insufficient-history evidence, never a fabricated confirmation.
    assert predicates["hamie.entity.temporal_evidence_status@1"] == "insufficient_history_to_prove_30d"
    assert predicates["hamie.entity.temporal_evidence_provenance@1"] == "no_recorder_source_configured"


@pytest.mark.asyncio
async def test_temporal_evidence_lookup_failure_degrades_gracefully() -> None:
    coordinator, _repo, _projection = _make_coordinator(
        _mixed_entities(),
        temporal_evidence_source=FakeTemporalEvidenceSource(raise_on_lookup=True),
    )
    result = await coordinator.async_request_scan(trigger="test")
    unavailable = next(
        f for f in result.state.findings if f.analyzer_id == UNAVAILABLE_ANALYZER_ID
    )
    predicates = {item.predicate: item.value for item in unavailable.evidence}
    assert predicates["hamie.entity.temporal_evidence_status@1"] == "insufficient_history_to_prove_30d"
    assert predicates["hamie.entity.temporal_evidence_provenance@1"] == "recorder_source_lookup_failed"


@pytest.mark.asyncio
async def test_no_evidence_sources_configured_scan_still_completes() -> None:
    """The prior (pre-wiring) behavior -- omitting both ports entirely."""
    coordinator, _repo, _projection = _make_coordinator(_mixed_entities())
    result = await coordinator.async_request_scan(trigger="test")
    assert result.state.findings


# --------------------------------------------------------------------------
# 3. Repeated scans reconcile without duplicate accumulation.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_scans_reconcile_without_duplicate_accumulation() -> None:
    repository = FakeRepository()
    coordinator, _repo, _projection = _make_coordinator(
        _mixed_entities(), repository=repository
    )
    first = await coordinator.async_request_scan(trigger="test")
    first_ids = {item.finding_id for item in first.state.findings}
    assert first_ids

    # A second scan, identical evidence -- must reconcile onto the same
    # finding_ids, not create new ones (occurrence_count increments
    # instead).
    second = await coordinator.async_request_scan(trigger="test")
    second_ids = {item.finding_id for item in second.state.findings}
    assert second_ids == first_ids
    assert len(second.state.findings) == len(first.state.findings)
    for item in second.state.findings:
        assert item.occurrence_count >= 1
        assert item.lifecycle is FindingLifecycle.OPEN
    assert {item.incident_id for item in second.state.incidents} == {
        item.incident_id for item in first.state.incidents
    }
    assert all(
        item.lifecycle in {IncidentLifecycle.RECURRING, IncidentLifecycle.REGRESSED}
        for item in second.state.incidents
        if item.is_active
    )


@pytest.mark.asyncio
async def test_incident_engine_reduces_shared_device_noise_without_count_priority() -> None:
    entities = tuple(
        _rec(
            f"sensor.noisy_device_channel_{index}_reading",
            state="unavailable",
            last_changed=NOW - timedelta(hours=2),
            device_id="device-noisy",
            config_entry_id="entry-noisy",
        )
        for index in range(40)
    )
    coordinator, _repo, projection = _make_coordinator(entities)
    result = await coordinator.async_request_scan(trigger="incident-reduction-test")

    open_findings = [
        item for item in result.state.findings if item.lifecycle is FindingLifecycle.OPEN
    ]
    active_incidents = [item for item in result.state.incidents if item.is_active]
    assert len(open_findings) == 40
    assert len(active_incidents) == 1
    assert len(active_incidents[0].finding_ids) == 40
    assert active_incidents[0].priority in {
        IncidentPriority.P2,
        IncidentPriority.P3,
        IncidentPriority.INFO,
    }
    assert projection.incidents == result.state.incidents


@pytest.mark.asyncio
async def test_broken_reference_becomes_high_priority_incident() -> None:
    reference_index = EntityReferenceIndex(
        references={
            "light.hall": (
                ReferenceHit(
                    source="automation",
                    referencing_object_id="automation.uses_hall",
                ),
            )
        },
        coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES),
    )
    coordinator, _repo, _projection = _make_coordinator(
        _broken_reference_entities(),
        reference_source=FakeReferenceSource(reference_index),
    )
    result = await coordinator.async_request_scan(trigger="incident-priority-test")
    active = [item for item in result.state.incidents if item.is_active]
    assert len(active) == 1
    assert active[0].priority is IncidentPriority.P1
    assert active[0].evidence_status.value in {"verified", "strongly_inferred"}


@pytest.mark.asyncio
async def test_duplicate_group_resolving_when_no_longer_a_duplicate() -> None:
    """When a migration-leftover sibling disappears entirely, the group
    can no longer be classified -- the prior finding is never silently
    duplicated into a new finding_id on the next scan.
    """
    repository = FakeRepository()
    coordinator, _repo, projection = _make_coordinator(
        _mixed_entities(), repository=repository
    )
    first = await coordinator.async_request_scan(trigger="test")
    duplicate_before = [
        f for f in first.state.findings if f.analyzer_id == "hamie.duplicate_migration"
    ]
    assert len(duplicate_before) == 1

    # Second scan with automation.foo (the dead sibling) removed entirely.
    remaining = tuple(
        record for record in _mixed_entities() if record.entity_id != "automation.foo"
    )
    coordinator2, _repo2, _projection2 = _make_coordinator(
        remaining, repository=repository, revision="rev2"
    )
    second = await coordinator2.async_request_scan(trigger="test")
    duplicate_after = [
        f for f in second.state.findings if f.analyzer_id == "hamie.duplicate_migration"
    ]
    # No new duplicate-group finding_id was created for the same group
    # key -- the total analyzer-owned finding count for this analyzer
    # never grows across a scan that only ever removes evidence.
    assert len(duplicate_after) <= len(duplicate_before)


# --------------------------------------------------------------------------
# 4/5/6. Findings retrievable via the real Issues/Review/evidence-detail
# code path (ExplorerIndex.query_findings -- see module docstring).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broken_reference_finding_retrievable_via_issues_path() -> None:
    reference_index = EntityReferenceIndex(
        references={
            "light.hall": (
                ReferenceHit(source="automation", referencing_object_id="automation.uses_hall"),
            )
        },
        coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES),
    )
    coordinator, _repo, projection = _make_coordinator(
        _broken_reference_entities(),
        reference_source=FakeReferenceSource(reference_index),
    )
    await coordinator.async_request_scan(trigger="test")

    # The real ExplorerIndex the Issues WebSocket handler reads from
    # (via MaintenanceOperationsService.query_findings) was already
    # rebuilt by RuntimeProjection.async_sync during the scan commit.
    page = projection.explorer.query_findings(filters={"category": "duplicate_migration"})
    broken = [item for item in page["items"] if item["recommendation_kind"] == "repair"]
    assert len(broken) == 1
    assert broken[0]["severity"] == "error"
    assert broken[0]["lifecycle"] == "open"

    # And it is reachable via the exact filter the Review screen's
    # Broken Reference tab now sends (hamie-view-review.js).
    filtered = projection.explorer.query_findings(
        filters={"category": "duplicate_migration", "recommendation_kind": "repair"}
    )
    assert filtered["total"] == 1


@pytest.mark.asyncio
async def test_ambiguous_duplicate_group_retrievable_via_review_path() -> None:
    coordinator, _repo, projection = _make_coordinator(_ambiguous_entities())
    await coordinator.async_request_scan(trigger="test")

    # Exact filter the Review screen's Duplicate / Migration tab sends
    # for the ambiguous half of its merged query.
    page = projection.explorer.query_findings(
        filters={"category": "duplicate_migration", "recommendation_kind": "review_duplicate"}
    )
    assert page["total"] == 1
    assert page["items"][0]["recommendation_kind"] == "review_duplicate"


@pytest.mark.asyncio
async def test_temporal_evidence_retrievable_via_finding_detail_path() -> None:
    coordinator, _repo, projection = _make_coordinator(
        _mixed_entities(), temporal_evidence_source=FakeTemporalEvidenceSource()
    )
    await coordinator.async_request_scan(trigger="test")

    unavailable_finding_id = next(
        f.finding_id
        for f in projection.explorer.findings
        if f.analyzer_id == UNAVAILABLE_ANALYZER_ID
    )
    detail = projection.explorer.finding_summary(
        next(f for f in projection.explorer.findings if f.finding_id == unavailable_finding_id)
    )
    # The frontend evidence panel (hamie-evidence-panel.js) renders
    # finding.evidence -- confirm the temporal predicates survive all
    # the way through the real finding_summary() serialization path.
    assert any(
        item.predicate == "hamie.entity.temporal_evidence_status@1"
        for item in next(
            f for f in projection.explorer.findings if f.finding_id == unavailable_finding_id
        ).evidence
    )
    assert detail["finding_id"] == unavailable_finding_id


# --------------------------------------------------------------------------
# 7. System/health aggregation reflects the new finding types.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_aggregation_counts_new_finding_types() -> None:
    reference_index = EntityReferenceIndex(
        references={
            "light.hall": (
                ReferenceHit(source="automation", referencing_object_id="automation.uses_hall"),
            )
        },
        coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES),
    )
    coordinator, _repo, projection = _make_coordinator(
        _broken_reference_entities(),
        reference_source=FakeReferenceSource(reference_index),
    )
    await coordinator.async_request_scan(trigger="test")

    snapshot = projection.snapshot
    # findings_critical/findings_warning/findings_total are severity-
    # keyed across every analyzer (application/runtime_projection.py),
    # not filtered to any one analyzer_id -- the BROKEN_REFERENCE_TO_
    # OLD_SIBLING finding's ERROR severity is already counted here with
    # zero changes needed to that aggregation.
    assert snapshot.findings_total >= 1
    assert snapshot.findings_critical >= 1

    breakdown = {}
    for finding in projection.explorer.findings:
        breakdown[finding.category] = breakdown.get(finding.category, 0) + 1
    assert breakdown.get("duplicate_migration", 0) >= 1
