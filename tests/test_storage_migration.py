"""Tests for Store migrations, knowledge records, and durable incidents.

No pre-existing test file exercised ``decode_document``/
``encode_document``/the ``_migrate_vN`` chain directly before this
file -- these tests cover the new v7->v8 step this change adds, plus a
full round trip through the real Store encode/decode path with
populated knowledge records.

``infrastructure/storage.py`` transitively imports
``domain/serialization.py``, which uses PEP 695 generic function
syntax (Python 3.12+) -- see ``tests/test_protection.py``'s
``_requires_py312_serialization`` for the full explanation of this
pre-existing sandbox/repo mismatch (present since this repo's
baseline, unrelated to this change). Skipped here under the same
condition.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from datetime import UTC, datetime

import pytest

if sys.version_info < (3, 12):
    pytest.skip(
        "hamie/domain/serialization.py requires Python 3.12+ (PEP 695 "
        "generics) -- pre-existing repo/sandbox mismatch, not introduced "
        "by this change",
        allow_module_level=True,
    )

from hamie.application.persistence import RepositoryState
from hamie.domain.evidence import EvidenceItem
from hamie.domain.findings import Confidence, ConfidenceFactor, ConfidenceLevel
from hamie.domain.identity import SubjectIdentity
from hamie.domain.implementation_groups import (
    ImplementationGroup,
    ImplementationGroupClassification,
    UnresolvedDecision,
)
from hamie.domain.knowledge_provenance import KnowledgeProvenance
from hamie.domain.successors import (
    EntitySuccessorRelationship,
    SuccessorRelationshipType,
)
from hamie.infrastructure.storage import (
    STORAGE_SCHEMA_VERSION,
    decode_document,
    encode_document,
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


def _successor() -> EntitySuccessorRelationship:
    return EntitySuccessorRelationship(
        stale_entity_id="sensor.bidet_plug_power",
        canonical_entity_id="sensor.bidet_plug_power_2",
        relationship_type=SuccessorRelationshipType.RENAMED_OR_RECREATED_SUCCESSOR,
        confidence=_confidence(),
        evidence=(
            EvidenceItem(
                subject=_subject("sensor.bidet_plug_power_2"),
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
        reference_remediated=True,
    )


def _implementation_group() -> ImplementationGroup:
    return ImplementationGroup(
        group_id="master_toilet_lighting",
        members=(
            "automation.master_toilet_adaptive_light",
            "automation.master_toilet_adaptive_light_2",
            "automation.master_toilet_adaptive_light_v3_5",
        ),
        classification=ImplementationGroupClassification.PARALLEL_OR_VERSIONED_IMPLEMENTATIONS,
        confidence=_confidence(),
        evidence=(
            EvidenceItem(
                subject=_subject("automation.master_toilet_adaptive_light_v3_5"),
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
            decision_type="user_product_decision",
            question="Which implementation should be authoritative?",
            context="v3.5 is the only enabled automation today.",
        ),
    )


def test_current_schema_round_trips_knowledge_records() -> None:
    state = RepositoryState(
        generation=1,
        entity_successors=(_successor(),),
        implementation_groups=(_implementation_group(),),
    )
    document = encode_document(state)
    assert document["schema_version"] == STORAGE_SCHEMA_VERSION
    decoded = decode_document(document)
    assert decoded.entity_successors == state.entity_successors
    assert decoded.implementation_groups == state.implementation_groups


def test_v7_document_without_knowledge_fields_migrates_to_current_with_empty_knowledge() -> None:
    """A real pre-upgrade v7 document has no entity_successors/
    implementation_groups keys at all -- the migration must default
    both to empty tuples, never fabricate records, and record "7->8" in
    migration_history.
    """
    v8_document = encode_document(RepositoryState(generation=3))
    v7_document = deepcopy(v8_document)
    v7_document["schema_version"] = 7
    v7_document["compatibility"] = {"minimum_reader": 7, "maximum_reader": 7}
    del v7_document["payload"]["entity_successors"]
    del v7_document["payload"]["implementation_groups"]
    v7_document["checksum"] = _recompute_checksum(v7_document["payload"])

    decoded = decode_document(v7_document)

    assert decoded.entity_successors == ()
    assert decoded.implementation_groups == ()
    assert decoded.generation == 3
    assert "7->8" in decoded.migration_history
    assert "8->9" in decoded.migration_history


def test_v8_document_without_incidents_migrates_to_empty_incident_set() -> None:
    current_document = encode_document(RepositoryState(generation=4))
    v8_document = deepcopy(current_document)
    v8_document["schema_version"] = 8
    v8_document["compatibility"] = {"minimum_reader": 8, "maximum_reader": 8}
    del v8_document["payload"]["incidents"]
    v8_document["checksum"] = _recompute_checksum(v8_document["payload"])

    decoded = decode_document(v8_document)

    assert decoded.incidents == ()
    assert decoded.generation == 4
    assert "8->9" in decoded.migration_history


def _recompute_checksum(payload: object) -> str:
    from hamie.domain.common import canonical_json, stable_digest

    return stable_digest(canonical_json(payload))
