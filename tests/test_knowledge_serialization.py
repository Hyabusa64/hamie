"""Round-trip tests for domain/knowledge_serialization.py.

``knowledge_serialization.py`` imports ``domain/serialization.py``,
which uses PEP 695 generic function syntax (Python 3.12+) -- see
``tests/test_protection.py``'s ``_requires_py312_serialization`` for
the full explanation of this pre-existing sandbox/repo mismatch. This
file is skipped under the same condition, for the same reason.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

import pytest

if sys.version_info < (3, 12):
    pytest.skip(
        "hamie/domain/serialization.py requires Python 3.12+ (PEP 695 "
        "generics) -- pre-existing repo/sandbox mismatch, not introduced "
        "by this change",
        allow_module_level=True,
    )

from hamie.domain.evidence import EvidenceItem
from hamie.domain.findings import Confidence, ConfidenceFactor, ConfidenceLevel
from hamie.domain.identity import SubjectIdentity
from hamie.domain.implementation_groups import (
    ImplementationGroup,
    ImplementationGroupClassification,
    UnresolvedDecision,
)
from hamie.domain.knowledge_provenance import KnowledgeProvenance
from hamie.domain.knowledge_serialization import (
    decode_entity_successor,
    decode_implementation_group,
    encode_entity_successor,
    encode_implementation_group,
)
from hamie.domain.successors import (
    EntitySuccessorRelationship,
    SuccessorRelationshipType,
)

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
            predicate="home_assistant.entity.exists@1",
            value=True,
            observed_at=_AT,
            source_id="home_assistant.entity_registry",
            source_revision="rev-1",
        ),
    )


def _confidence() -> Confidence:
    return Confidence(
        level=ConfidenceLevel.HIGH,
        factors=(
            ConfidenceFactor(code="unique_id_continuity", effect=70, rationale="r"),
        ),
        rule_revision="rev@1",
    )


def test_entity_successor_round_trips() -> None:
    original = EntitySuccessorRelationship(
        stale_entity_id="sensor.bidet_plug_power",
        canonical_entity_id="sensor.bidet_plug_power_2",
        relationship_type=SuccessorRelationshipType.RENAMED_OR_RECREATED_SUCCESSOR,
        confidence=_confidence(),
        evidence=_evidence("sensor.bidet_plug_power_2"),
        first_observed=_AT,
        last_verified=_AT,
        provenance=KnowledgeProvenance.IMPORTED_EVIDENCE_ARTIFACT,
        reference_remediated=True,
        source_artifact="benchmark/.../phase_b1_actions.json",
        source_artifact_hash="deadbeef",
    )
    decoded = decode_entity_successor(encode_entity_successor(original))
    assert decoded == original
    assert decoded.fingerprint == original.fingerprint
    assert decoded.evidence_digest == original.evidence_digest


def test_implementation_group_round_trips() -> None:
    original = ImplementationGroup(
        group_id="master_toilet_lighting",
        members=(
            "automation.master_toilet_adaptive_light",
            "automation.master_toilet_adaptive_light_2",
            "automation.master_toilet_adaptive_light_v3_5",
        ),
        classification=ImplementationGroupClassification.PARALLEL_OR_VERSIONED_IMPLEMENTATIONS,
        confidence=_confidence(),
        evidence=_evidence("automation.master_toilet_adaptive_light_v3_5"),
        first_observed=_AT,
        last_verified=_AT,
        provenance=KnowledgeProvenance.CLAUDE_ASSISTED_INVESTIGATION,
        unresolved_decision=UnresolvedDecision(
            decision_type="user_product_decision",
            question="Which implementation should be authoritative?",
            context="v3.5 is the only enabled automation today.",
        ),
    )
    decoded = decode_implementation_group(encode_implementation_group(original))
    assert decoded == original
    assert decoded.fingerprint == original.fingerprint
    assert decoded.automatic_cleanup_allowed is False


def test_implementation_group_without_unresolved_decision_round_trips() -> None:
    original = ImplementationGroup(
        group_id="water_normalization",
        members=("sensor.water_flow_raw", "sensor.water_flow_cleaned"),
        classification=ImplementationGroupClassification.INTENTIONAL_PARALLEL_CAPABILITY,
        confidence=_confidence(),
        evidence=_evidence("sensor.water_flow_cleaned"),
        first_observed=_AT,
        last_verified=_AT,
        provenance=KnowledgeProvenance.HAMIE_ANALYZER,
    )
    decoded = decode_implementation_group(encode_implementation_group(original))
    assert decoded == original
    assert decoded.unresolved_decision is None
