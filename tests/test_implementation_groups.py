"""Tests for domain/implementation_groups.py (mission Parts 9/48/179-182).

The required guarantee: ``automatic_cleanup_allowed`` can never be
constructed as ``True`` -- membership in a parallel/versioned
implementation group must never, structurally, authorize automatic
cleanup of any member.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hamie.domain.evidence import EvidenceItem
from hamie.domain.findings import Confidence, ConfidenceFactor, ConfidenceLevel
from hamie.domain.identity import SubjectIdentity
from hamie.domain.implementation_groups import (
    ImplementationGroup,
    ImplementationGroupClassification,
    UnresolvedDecision,
)
from hamie.domain.knowledge_provenance import KnowledgeProvenance

_AT = datetime(2026, 8, 25, 5, 30, tzinfo=UTC)


def _subject(entity_id: str) -> SubjectIdentity:
    return SubjectIdentity(
        durable_id=entity_id,
        kind="home_assistant.entity",
        source_instance="home_assistant",
        source_id=entity_id,
    )


def _evidence(entity_id: str) -> tuple[EvidenceItem, ...]:
    return (
        EvidenceItem(
            subject=_subject(entity_id),
            predicate="home_assistant.automation.state@1",
            value="off",
            observed_at=_AT,
            source_id="home_assistant",
            source_revision="rev-1",
        ),
    )


def _confidence() -> Confidence:
    return Confidence(
        level=ConfidenceLevel.HIGH,
        factors=(
            ConfidenceFactor(
                code="live_state_reverified",
                effect=60,
                rationale="all three automation states re-checked live",
            ),
        ),
        rule_revision="implementation-group-confidence@1",
    )


_MEMBERS = (
    "automation.master_toilet_adaptive_light",
    "automation.master_toilet_adaptive_light_2",
    "automation.master_toilet_adaptive_light_v3_5",
)


def _decision() -> UnresolvedDecision:
    return UnresolvedDecision(
        decision_type="user_product_decision",
        question="Which master-toilet lighting implementation should be authoritative?",
        context="v3.5 is currently the only enabled implementation.",
    )


def _group(**overrides: object) -> ImplementationGroup:
    defaults: dict[str, object] = dict(
        group_id="master_toilet_lighting",
        members=_MEMBERS,
        classification=ImplementationGroupClassification.PARALLEL_OR_VERSIONED_IMPLEMENTATIONS,
        confidence=_confidence(),
        evidence=_evidence(_MEMBERS[0]),
        first_observed=_AT,
        last_verified=_AT,
        provenance=KnowledgeProvenance.CLAUDE_ASSISTED_INVESTIGATION,
        unresolved_decision=_decision(),
    )
    defaults.update(overrides)
    return ImplementationGroup(**defaults)  # type: ignore[arg-type]


def test_automatic_cleanup_allowed_can_never_be_true() -> None:
    with pytest.raises(ValueError, match="automatic_cleanup_allowed"):
        _group(automatic_cleanup_allowed=True)


def test_automatic_cleanup_allowed_defaults_false() -> None:
    assert _group().automatic_cleanup_allowed is False


def test_parallel_or_versioned_requires_unresolved_decision() -> None:
    with pytest.raises(ValueError, match="unresolved_decision"):
        _group(unresolved_decision=None)


def test_intentional_parallel_capability_does_not_require_unresolved_decision() -> None:
    group = _group(
        classification=ImplementationGroupClassification.INTENTIONAL_PARALLEL_CAPABILITY,
        unresolved_decision=None,
    )
    assert group.unresolved_decision is None


def test_requires_two_or_more_members() -> None:
    with pytest.raises(ValueError, match="2\\+ members"):
        _group(members=(_MEMBERS[0],))


def test_fingerprint_changes_when_membership_changes() -> None:
    """Membership drift must reopen the group (mission Part 23)."""
    original = _group()
    fewer_members = _group(members=_MEMBERS[:2])
    assert original.fingerprint != fewer_members.fingerprint


def test_fingerprint_stable_when_only_evidence_or_confidence_changes() -> None:
    original = _group()
    revalidated = _group(last_verified=_AT, confidence=_confidence())
    assert original.fingerprint == revalidated.fingerprint


def test_members_are_deduplicated_and_sorted() -> None:
    group = _group(members=(*_MEMBERS, _MEMBERS[0]))
    assert group.members == tuple(sorted(set(_MEMBERS)))


def test_group_record_id_is_prefixed() -> None:
    assert _group().group_record_id.startswith("hamie_implgroup_")
