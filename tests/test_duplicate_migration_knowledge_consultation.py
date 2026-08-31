"""Tests for DuplicateMigrationAnalyzer's optional
``known_implementation_groups`` consultation (mission Part 11/48).

The required guarantee: passing no known groups (or omitting the
parameter entirely) produces byte-identical findings to before this
change existed; passing a group whose member set exactly matches a
scan result's group only ever adds annotation (extra evidence + action
text), never changes ``kind``/``severity``/``risk``/``confidence``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hamie.analysis.analyzers.duplicate_migration import DuplicateMigrationAnalyzer
from hamie.application.ports import EntityRecord
from hamie.domain.evidence import EvidenceItem
from hamie.domain.findings import Confidence, ConfidenceFactor, ConfidenceLevel
from hamie.domain.implementation_groups import (
    ImplementationGroup,
    ImplementationGroupClassification,
    UnresolvedDecision,
)
from hamie.domain.knowledge_provenance import KnowledgeProvenance
from hamie.domain.identity import SubjectIdentity

NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
ANALYZER = DuplicateMigrationAnalyzer(source_instance="test_home")


def _rec(entity_id: str) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        state="on",
        last_changed=NOW,
        last_updated=NOW,
        registry_id=f"reg-{entity_id}",
        unique_id=None,
        device_id=None,
        config_entry_id=None,
        disabled=False,
        restored=False,
        domain=entity_id.partition(".")[0],
        area_id=None,
        created_at=None,
    )


def _known_group(members: tuple[str, ...]) -> ImplementationGroup:
    subject = SubjectIdentity(
        durable_id=members[0],
        kind="home_assistant.entity",
        source_instance="home_assistant",
        source_id=members[0],
    )
    return ImplementationGroup(
        group_id="foo_lighting",
        members=members,
        classification=ImplementationGroupClassification.PARALLEL_OR_VERSIONED_IMPLEMENTATIONS,
        confidence=Confidence(
            level=ConfidenceLevel.HIGH,
            factors=(ConfidenceFactor(code="c", effect=50, rationale="r"),),
            rule_revision="rev@1",
        ),
        evidence=(
            EvidenceItem(
                subject=subject,
                predicate="home_assistant.automation.state@1",
                value="on",
                observed_at=NOW,
                source_id="home_assistant",
                source_revision="rev-1",
            ),
        ),
        first_observed=NOW,
        last_verified=NOW,
        provenance=KnowledgeProvenance.CLAUDE_ASSISTED_INVESTIGATION,
        unresolved_decision=UnresolvedDecision(
            decision_type="user_product_decision",
            question="Which foo automation should be authoritative?",
            context="test fixture",
        ),
    )


def _ambiguous_group_records() -> tuple[EntityRecord, ...]:
    # Two alive members, no distinguishing device/config/area/created_at
    # signal -> AMBIGUOUS_DUPLICATE_GROUP (see duplicate_classifier.py's
    # fallthrough).
    return (_rec("automation.foo"), _rec("automation.foo_2"))


def test_no_known_groups_matches_baseline_exactly() -> None:
    with_default = ANALYZER.analyze_collection(
        _ambiguous_group_records(), observed_at=NOW, reference_index=None
    )
    with_explicit_empty = ANALYZER.analyze_collection(
        _ambiguous_group_records(),
        observed_at=NOW,
        reference_index=None,
        known_implementation_groups=(),
    )
    assert with_default.findings == with_explicit_empty.findings


def test_matching_known_group_adds_evidence_and_action_note() -> None:
    baseline = ANALYZER.analyze_collection(
        _ambiguous_group_records(), observed_at=NOW, reference_index=None
    ).findings[0]
    known = _known_group(("automation.foo", "automation.foo_2"))
    annotated = ANALYZER.analyze_collection(
        _ambiguous_group_records(),
        observed_at=NOW,
        reference_index=None,
        known_implementation_groups=(known,),
    ).findings[0]

    assert len(annotated.evidence) == len(baseline.evidence) + 1
    assert any(
        item.predicate == "hamie.knowledge.known_implementation_group@1"
        and item.value == known.group_record_id
        for item in annotated.evidence
    )
    assert "already matches a known" in annotated.recommendation.action
    assert known.unresolved_decision is not None
    assert known.unresolved_decision.question in annotated.recommendation.action

    # Annotation only -- classification-derived fields are untouched.
    assert annotated.recommendation.kind == baseline.recommendation.kind
    assert annotated.severity == baseline.severity
    assert annotated.recommendation.risk == baseline.recommendation.risk
    assert annotated.recommendation.confidence == baseline.recommendation.confidence


def test_non_matching_known_group_leaves_finding_unchanged() -> None:
    baseline = ANALYZER.analyze_collection(
        _ambiguous_group_records(), observed_at=NOW, reference_index=None
    ).findings[0]
    unrelated = _known_group(("automation.bar", "automation.bar_2"))
    result = ANALYZER.analyze_collection(
        _ambiguous_group_records(),
        observed_at=NOW,
        reference_index=None,
        known_implementation_groups=(unrelated,),
    ).findings[0]
    assert result == baseline
