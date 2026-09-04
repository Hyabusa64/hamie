"""The investigation loop must re-impose determinism over the model."""

from __future__ import annotations

import json

import pytest

from hamie.application.investigator import (
    EvidencePackage,
    InvestigationStatus,
    Investigator,
)

AI_PC = "switch.example_inference_host_plug"


def _model(payload):
    async def call(_system: str, _user: str) -> str:
        return payload if isinstance(payload, str) else json.dumps(payload)

    return call


def _pkg(question="why?", ids=("EV-1", "EV-2")):
    return EvidencePackage(
        question=question,
        items=tuple({"id": i, "fact": f"fact {i}"} for i in ids),
    )


@pytest.mark.asyncio
async def test_root_cause_with_cited_evidence() -> None:
    res = await Investigator(
        _model(
            {
                "root_cause": "stale reference",
                "classification": "verified",
                "confidence": 0.95,
                "evidence_ids": ["EV-1"],
                "proposed_action": "replace reference",
                "action_type": "replace_entity_reference",
                "affected_objects": ["sensor.old"],
                "validation": ["config valid"],
                "rollback": "restore backup",
            }
        )
    ).async_investigate(_pkg())
    assert res.status is InvestigationStatus.ROOT_CAUSE_FOUND
    assert res.classification == "verified"
    assert res.proposal is not None
    assert res.proposal.executable is False, "proposals must never self-execute"


@pytest.mark.asyncio
async def test_uncited_verified_claim_is_downgraded() -> None:
    """A confident sentence citing nothing is not a verified finding."""
    res = await Investigator(
        _model(
            {
                "root_cause": "vibes",
                "classification": "verified",
                "confidence": 0.99,
                "evidence_ids": ["NOT-REAL"],
                "proposed_action": "none",
            }
        )
    ).async_investigate(_pkg())
    assert res.classification == "inference"
    assert res.confidence <= 0.5
    assert any("downgraded" in n for n in res.notes)


@pytest.mark.asyncio
async def test_protected_dependency_blocks_proposal() -> None:
    """The registry, not the model, decides. Model 'confidence' is irrelevant."""
    res = await Investigator(
        _model(
            {
                "root_cause": "AI PC wastes power",
                "classification": "verified",
                "confidence": 1.0,
                "evidence_ids": ["EV-1"],
                "proposed_action": "turn off the AI PC plug",
                "action_type": "turn_off",
                "affected_objects": [AI_PC],
            }
        )
    ).async_investigate(_pkg())
    assert res.status is InvestigationStatus.BLOCKED_BY_INVARIANT
    assert res.proposal is not None
    assert res.proposal.protection["verdict"] == "blocked"
    inv = res.proposal.protection["matched_invariants"][0]
    assert inv["id"] == "hamie-local-inference-power"
    assert "Ollama" in inv["chain"]
    assert res.proposal.executable is False


@pytest.mark.asyncio
async def test_unavailable_model_fails_safe() -> None:
    async def boom(_s, _u):
        raise TimeoutError("ollama down")

    res = await Investigator(boom).async_investigate(_pkg())
    assert res.status is InvestigationStatus.LLM_UNAVAILABLE
    assert res.proposal is None


@pytest.mark.asyncio
async def test_malformed_output_rejected() -> None:
    res = await Investigator(_model("not json at all")).async_investigate(_pkg())
    assert res.status is InvestigationStatus.INVALID_MODEL_OUTPUT
    assert res.proposal is None


@pytest.mark.asyncio
async def test_fenced_json_is_tolerated() -> None:
    fenced = '```json\n{"root_cause":"x","classification":"inference",' \
             '"confidence":0.6,"evidence_ids":["EV-1"],"proposed_action":"none"}\n```'
    res = await Investigator(_model(fenced)).async_investigate(_pkg())
    assert res.status is InvestigationStatus.ROOT_CAUSE_FOUND
    assert res.classification == "inference"


@pytest.mark.asyncio
async def test_no_evidence_short_circuits_before_calling_model() -> None:
    called = False

    async def spy(_s, _u):
        nonlocal called
        called = True
        return "{}"

    res = await Investigator(spy).async_investigate(EvidencePackage("q", ()))
    assert res.status is InvestigationStatus.NEEDS_MORE_EVIDENCE
    assert not called, "must not spend tokens with nothing to reason over"


@pytest.mark.asyncio
async def test_evidence_is_bounded() -> None:
    big = EvidencePackage(
        "q", tuple({"id": f"E{i}", "blob": "x" * 400} for i in range(500))
    )
    assert len(big.bounded()) < 500


@pytest.mark.asyncio
async def test_confidence_is_clamped() -> None:
    res = await Investigator(
        _model(
            {
                "root_cause": "x",
                "classification": "inference",
                "confidence": 42,
                "evidence_ids": ["EV-1"],
                "proposed_action": "none",
            }
        )
    ).async_investigate(_pkg())
    assert 0.0 <= res.confidence <= 1.0
