"""Regression tests for the deterministic evidence-serialisation defect.

RemovedIntegrationOrphanAnalyzer emitted `hamie.dependency.referenced_by@1`
with a tuple `value`.  EvidenceValue is declared scalar-only, but nothing
enforced it at construction, so the tuple serialised happily and only failed
later in decode_evidence() -- by which point the corrupt document had already
replaced known-good persisted state.  Every fresh scan regenerated it, so the
store could never be read back ("HAMIE Store payload failed validation").

These tests lock in both halves of the fix:
  1. EvidenceItem rejects non-scalar values at construction (guardrail).
  2. The analyzer emits only scalar evidence, keeping per-reference provenance.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

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
from hamie.domain.evidence import EvidenceItem, EvidenceKind, Sensitivity
from hamie.domain.serialization import decode_evidence, encode_evidence
from hamie.infrastructure.installation_topology import build_installation_topology

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
ANALYZER = RemovedIntegrationOrphanAnalyzer(source_instance="test_home")
SCALAR_TYPES = (str, int, float, bool)


def _rec(entity_id: str, *, platform: str) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        state="unavailable",
        last_changed=NOW,
        last_updated=NOW,
        registry_id=f"reg-{entity_id}",
        device_id=None,
        config_entry_id=None,
        disabled=False,
        restored=None,
        domain=entity_id.partition(".")[0],
        platform=platform,
        friendly_name=None,
        source_definition_missing=None,
    )


def _index(refs: dict[str, tuple[ReferenceHit, ...]] | None = None):
    return EntityReferenceIndex(
        references=refs or {},
        coverage=DependencyScanCoverage(scanned_sources=SCANNED_SOURCES),
    )


def _evidence_for(reference_count: int) -> tuple[EvidenceItem, ...]:
    entity = "scene.old_lighting_scene"
    refs = {
        entity: tuple(
            ReferenceHit(source="automation", referencing_object_id=f"auto_{i}")
            for i in range(reference_count)
        )
    }
    topology = build_installation_topology(
        config_entry_domains=frozenset({"hue"}),
        custom_component_dirs=frozenset({"unrelated"}),
    )
    outcome = ANALYZER.analyze_collection(
        (_rec(entity, platform="legacy_bridge_pro"),),
        observed_at=NOW,
        installation_topology=topology,
        reference_index=_index(refs if reference_count else None),
    )
    assert outcome.findings, "analyzer produced no finding"
    return outcome.findings[0].evidence


# ---------------------------------------------------------------- guardrail


@pytest.mark.parametrize(
    "bad_value", [("a", "b"), ["a", "b"], {"a": 1}, {"a", "b"}, ()]
)
def test_evidence_item_rejects_non_scalar_value(bad_value: object) -> None:
    """No analyzer may construct evidence the store cannot read back."""
    with pytest.raises(TypeError, match="must be a JSON scalar"):
        EvidenceItem(
            subject=_subject(),
            predicate="hamie.test.bad@1",
            value=bad_value,  # type: ignore[arg-type]
            observed_at=NOW,
            source_id="test",
            source_revision="rev",
        )


@pytest.mark.parametrize("good_value", ["text", 7, 1.5, True, None])
def test_evidence_item_accepts_scalars(good_value: object) -> None:
    item = EvidenceItem(
        subject=_subject(),
        predicate="hamie.test.good@1",
        value=good_value,  # type: ignore[arg-type]
        observed_at=NOW,
        source_id="test",
        source_revision="rev",
        kind=EvidenceKind.OBSERVED,
        sensitivity=Sensitivity.PUBLIC,
    )
    assert item.value == good_value
    # full round-trip must survive
    assert decode_evidence(encode_evidence(item)).value == good_value


def _subject():
    from hamie.domain.evidence import SubjectIdentity

    return SubjectIdentity(
        durable_id="d" * 32,
        kind="home_assistant.entity",
        source_instance="test_home",
        source_id="scene.old_lighting_scene",
        display_hint="Old Lighting Scene",
        aliases=("scene.old_lighting_scene",),
    )


# ------------------------------------------------------------ analyzer output


@pytest.mark.parametrize("count", [0, 1, 3])
def test_analyzer_emits_only_scalar_evidence(count: int) -> None:
    """Zero, one, and many references must all serialise."""
    for item in _evidence_for(count):
        assert item.value is None or isinstance(item.value, SCALAR_TYPES), (
            f"non-scalar evidence for {item.predicate}: {type(item.value)}"
        )


@pytest.mark.parametrize("count", [0, 1, 3])
def test_analyzer_evidence_round_trips(count: int) -> None:
    for item in _evidence_for(count):
        assert decode_evidence(encode_evidence(item)).value == item.value


@pytest.mark.parametrize("count", [0, 1, 3])
def test_reference_count_evidence_always_present(count: int) -> None:
    """The 'no references' fact must survive, not vanish with an empty list."""
    counts = [
        e.value
        for e in _evidence_for(count)
        if e.predicate == "hamie.dependency.referenced_by_count@1"
    ]
    assert counts == [count]


def test_each_reference_gets_its_own_scalar_observation() -> None:
    refs = [
        e.value
        for e in _evidence_for(3)
        if e.predicate == "hamie.dependency.referenced_by@1"
    ]
    assert len(refs) == 3
    assert all(isinstance(r, str) for r in refs)
    # Every reference is individually addressable (no lossy join).  Findings
    # order evidence by evidence_id digest rather than insertion order, so the
    # set -- not the sequence -- is the contract here; run-to-run stability is
    # asserted separately by test_evidence_ids_are_stable_across_runs.
    assert set(refs) == {
        "automation:auto_0",
        "automation:auto_1",
        "automation:auto_2",
    }


def test_evidence_ids_are_stable_across_runs() -> None:
    first = [e.evidence_id for e in _evidence_for(3)]
    second = [e.evidence_id for e in _evidence_for(3)]
    assert first == second
