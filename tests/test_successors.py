"""Tests for domain/successors.py (mission Parts 8/47/54/154).

The required guarantee: a stale->canonical relationship keeps one
durable identity (``fingerprint``) across revalidation, while its
evidence-backed content (``evidence_digest``) changes the moment the
underlying claim materially changes -- the mechanism a future
reopen-on-material-change check hooks into.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hamie.domain.evidence import EvidenceItem
from hamie.domain.findings import Confidence, ConfidenceFactor, ConfidenceLevel
from hamie.domain.identity import SubjectIdentity
from hamie.domain.knowledge_provenance import KnowledgeProvenance
from hamie.domain.successors import (
    EntitySuccessorRelationship,
    SuccessorRelationshipType,
    SuccessorStatus,
)

_AT = datetime(2026, 8, 25, 5, 30, tzinfo=UTC)
_LATER = datetime(2026, 8, 25, 6, 0, tzinfo=UTC)


def _subject(entity_id: str) -> SubjectIdentity:
    return SubjectIdentity(
        durable_id=entity_id,
        kind="home_assistant.entity",
        source_instance="home_assistant",
        source_id=entity_id,
    )


def _evidence(entity_id: str, predicate: str = "home_assistant.entity.exists@1") -> tuple[EvidenceItem, ...]:
    return (
        EvidenceItem(
            subject=_subject(entity_id),
            predicate=predicate,
            value=True,
            observed_at=_AT,
            source_id="home_assistant.entity_registry",
            source_revision="rev-1",
        ),
    )


def _confidence(level: ConfidenceLevel = ConfidenceLevel.HIGH) -> Confidence:
    return Confidence(
        level=level,
        factors=(
            ConfidenceFactor(
                code="unique_id_continuity",
                effect=70,
                rationale="canonical entity's unique_id predates the affected config",
            ),
        ),
        rule_revision="successor-confidence@1",
    )


def _relationship(**overrides: object) -> EntitySuccessorRelationship:
    defaults: dict[str, object] = dict(
        stale_entity_id="sensor.bidet_plug_power",
        canonical_entity_id="sensor.bidet_plug_power_2",
        relationship_type=SuccessorRelationshipType.RENAMED_OR_RECREATED_SUCCESSOR,
        confidence=_confidence(),
        evidence=_evidence("sensor.bidet_plug_power_2"),
        first_observed=_AT,
        last_verified=_AT,
        provenance=KnowledgeProvenance.CLAUDE_ASSISTED_INVESTIGATION,
    )
    defaults.update(overrides)
    return EntitySuccessorRelationship(**defaults)  # type: ignore[arg-type]


def test_fingerprint_is_stable_across_revalidation() -> None:
    """last_verified/evidence/confidence changing must not change fingerprint."""
    original = _relationship()
    revalidated = _relationship(
        last_verified=_LATER,
        confidence=_confidence(ConfidenceLevel.MEDIUM),
    )
    assert original.fingerprint == revalidated.fingerprint
    assert original.relationship_id == revalidated.relationship_id


def test_evidence_digest_changes_when_confidence_changes() -> None:
    """The reopen-on-material-change signal must actually move."""
    original = _relationship()
    changed = _relationship(confidence=_confidence(ConfidenceLevel.LOW))
    assert original.fingerprint == changed.fingerprint
    assert original.evidence_digest != changed.evidence_digest


def test_evidence_digest_changes_when_remediation_flags_change() -> None:
    original = _relationship()
    remediated = _relationship(reference_remediated=True)
    assert original.evidence_digest != remediated.evidence_digest


def test_rejects_identical_stale_and_canonical_entity_ids() -> None:
    with pytest.raises(ValueError, match="two distinct entity ids"):
        _relationship(
            stale_entity_id="sensor.same", canonical_entity_id="sensor.same"
        )


def test_requires_at_least_one_evidence_item() -> None:
    with pytest.raises(ValueError, match="requires evidence"):
        _relationship(evidence=())


def test_last_verified_cannot_precede_first_observed() -> None:
    with pytest.raises(ValueError, match="cannot precede"):
        _relationship(first_observed=_LATER, last_verified=_AT)


def test_superseded_status_requires_superseded_by_fingerprint() -> None:
    with pytest.raises(ValueError, match="SUPERSEDED"):
        _relationship(status=SuccessorStatus.SUPERSEDED)
    # Providing the fingerprint is accepted.
    superseded = _relationship(
        status=SuccessorStatus.SUPERSEDED, superseded_by_fingerprint="a" * 64
    )
    assert superseded.status is SuccessorStatus.SUPERSEDED


def test_relationship_id_is_prefixed_and_bounded() -> None:
    relationship = _relationship()
    assert relationship.relationship_id.startswith("hamie_successor_")
    assert len(relationship.relationship_id) == len("hamie_successor_") + 32
