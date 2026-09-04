"""Tests for domain/knowledge_consultation.py (mission Part 11/52)."""

from __future__ import annotations

from datetime import UTC, datetime

from hamie.domain.evidence import EvidenceItem
from hamie.domain.findings import Confidence, ConfidenceFactor, ConfidenceLevel
from hamie.domain.identity import SubjectIdentity
from hamie.domain.implementation_groups import (
    ImplementationGroup,
    ImplementationGroupClassification,
    UnresolvedDecision,
)
from hamie.domain.knowledge_consultation import (
    consult_entity_successor,
    consult_implementation_group,
)
from hamie.domain.knowledge_provenance import KnowledgeProvenance
from hamie.domain.successors import (
    EntitySuccessorRelationship,
    SuccessorRelationshipType,
    SuccessorStatus,
)

_AT = datetime(2026, 8, 25, 5, 30, tzinfo=UTC)


def _subject(entity_id: str) -> SubjectIdentity:
    return SubjectIdentity(
        durable_id=entity_id,
        kind="home_assistant.entity",
        source_instance="home_assistant",
        source_id=entity_id,
    )


def _confidence() -> Confidence:
    return Confidence(
        level=ConfidenceLevel.HIGH,
        factors=(ConfidenceFactor(code="c", effect=50, rationale="r"),),
        rule_revision="rev@1",
    )


def _successor(
    stale: str = "sensor.bidet_plug_power",
    canonical: str = "sensor.bidet_plug_power_2",
    status: SuccessorStatus = SuccessorStatus.ACTIVE,
) -> EntitySuccessorRelationship:
    return EntitySuccessorRelationship(
        stale_entity_id=stale,
        canonical_entity_id=canonical,
        relationship_type=SuccessorRelationshipType.RENAMED_OR_RECREATED_SUCCESSOR,
        confidence=_confidence(),
        evidence=(
            EvidenceItem(
                subject=_subject(canonical),
                predicate="home_assistant.entity.exists@1",
                value=True,
                observed_at=_AT,
                source_id="home_assistant.entity_registry",
                source_revision="rev-1",
            ),
        ),
        first_observed=_AT,
        last_verified=_AT,
        provenance=KnowledgeProvenance.IMPORTED_EVIDENCE_ARTIFACT,
        status=status,
        superseded_by_fingerprint=(
            "a" * 64 if status is SuccessorStatus.SUPERSEDED else None
        ),
    )


def test_consult_entity_successor_finds_active_match() -> None:
    known = (_successor(),)
    result = consult_entity_successor("sensor.bidet_plug_power", known)
    assert result is not None
    assert result.canonical_entity_id == "sensor.bidet_plug_power_2"


def test_consult_entity_successor_ignores_non_active_status() -> None:
    known = (_successor(status=SuccessorStatus.PENDING_REVALIDATION),)
    assert consult_entity_successor("sensor.bidet_plug_power", known) is None


def test_consult_entity_successor_requires_matching_canonical_when_given() -> None:
    known = (_successor(),)
    assert (
        consult_entity_successor(
            "sensor.bidet_plug_power",
            known,
            canonical_entity_id="sensor.something_else",
        )
        is None
    )
    assert (
        consult_entity_successor(
            "sensor.bidet_plug_power",
            known,
            canonical_entity_id="sensor.bidet_plug_power_2",
        )
        is not None
    )


def test_consult_entity_successor_no_match_returns_none() -> None:
    known = (_successor(),)
    assert consult_entity_successor("sensor.unrelated", known) is None


def _group(members: tuple[str, ...]) -> ImplementationGroup:
    return ImplementationGroup(
        group_id="g",
        members=members,
        classification=ImplementationGroupClassification.PARALLEL_OR_VERSIONED_IMPLEMENTATIONS,
        confidence=_confidence(),
        evidence=(
            EvidenceItem(
                subject=_subject(members[0]),
                predicate="home_assistant.automation.state@1",
                value="on",
                observed_at=_AT,
                source_id="home_assistant",
                source_revision="rev-1",
            ),
        ),
        first_observed=_AT,
        last_verified=_AT,
        provenance=KnowledgeProvenance.CLAUDE_ASSISTED_INVESTIGATION,
        unresolved_decision=UnresolvedDecision(
            decision_type="user_product_decision", question="q", context="c"
        ),
    )


def test_consult_implementation_group_exact_match() -> None:
    known = (_group(("automation.a", "automation.b")),)
    result = consult_implementation_group(("automation.b", "automation.a"), known)
    assert result is not None
    assert result.group_id == "g"


def test_consult_implementation_group_partial_overlap_does_not_match() -> None:
    """A shrunk/grown member set must not silently match -- that's the
    membership-changed reopen signal, not a match."""
    known = (_group(("automation.a", "automation.b", "automation.c")),)
    assert consult_implementation_group(("automation.a", "automation.b"), known) is None


def test_consult_implementation_group_no_match_returns_none() -> None:
    known = (_group(("automation.a", "automation.b")),)
    assert consult_implementation_group(("automation.x", "automation.y"), known) is None
