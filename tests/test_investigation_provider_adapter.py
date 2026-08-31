"""Regression tests for the deployed investigation provider path.

Root cause being locked in: runtime.investigation_model previously called
`self.connectors.ollama()`, which does not exist on ConnectorManager, behind
a hasattr() guard. Every call silently degraded to "no local inference
provider configured", so hamie/config_repair/investigate could never reach
the model. These tests pin the canonical routing and its failure modes.
"""

from __future__ import annotations

import pytest

from hamie.application.investigator import (
    EvidencePackage,
    InvestigationStatus,
    Investigator,
)


class _Manager:
    """Minimal stand-in for ConnectorManager's investigation contract."""

    def __init__(self, *, result=None, raises=None, method="direct"):
        self.result, self.raises, self.ai_connection_method = result, raises, method
        self.calls: list[tuple[str, str]] = []

    async def async_investigate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self.raises:
            raise self.raises
        return self.result


class _Runtime:
    """Mirrors HamieRuntime.investigation_model exactly."""

    def __init__(self, connectors):
        self.connectors = connectors

    @property
    def investigation_model(self):
        async def _call(system: str, user: str) -> str:
            return await self.connectors.async_investigate(system, user)

        return _call


def _pkg():
    return EvidencePackage(
        question="why is this unavailable?",
        items=({"id": "EV-1", "fact": "entity missing"},),
    )


def test_connector_manager_has_no_ollama_accessor() -> None:
    """The exact defect: the accessor never existed."""
    from hamie.connectors.manager import ConnectorManager

    assert not hasattr(ConnectorManager, "ollama"), (
        "if this ever exists, revisit the adapter"
    )
    assert hasattr(ConnectorManager, "async_investigate"), "canonical path missing"


def test_ollama_connector_exposes_investigate() -> None:
    from hamie.connectors.ollama import OllamaConnector

    assert hasattr(OllamaConnector, "async_investigate")


@pytest.mark.asyncio
async def test_runtime_routes_through_connector_manager() -> None:
    mgr = _Manager(result='{"root_cause":"x","classification":"inference",'
                          '"confidence":0.6,"evidence_ids":["EV-1"],'
                          '"proposed_action":"none"}')
    res = await Investigator(_Runtime(mgr).investigation_model).async_investigate(_pkg())
    assert mgr.calls, "model was never invoked"
    assert res.status is InvestigationStatus.ROOT_CAUSE_FOUND


@pytest.mark.asyncio
async def test_provider_unavailable_fails_safe_without_mutation() -> None:
    mgr = _Manager(raises=RuntimeError("ai_provider_not_ready"))
    res = await Investigator(_Runtime(mgr).investigation_model).async_investigate(_pkg())
    assert res.status is InvestigationStatus.LLM_UNAVAILABLE
    assert res.proposal is None, "no proposal may be produced without a model"


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_safe() -> None:
    mgr = _Manager(raises=TimeoutError("provider timed out"))
    res = await Investigator(_Runtime(mgr).investigation_model).async_investigate(_pkg())
    assert res.status is InvestigationStatus.LLM_UNAVAILABLE
    assert res.proposal is None


@pytest.mark.asyncio
async def test_malformed_response_refused_no_invented_fields() -> None:
    mgr = _Manager(result="I think the problem is probably the thing.")
    res = await Investigator(_Runtime(mgr).investigation_model).async_investigate(_pkg())
    assert res.status is InvestigationStatus.INVALID_MODEL_OUTPUT
    assert res.proposal is None
    assert res.root_cause == "" and res.authoritative_entity is None


@pytest.mark.asyncio
async def test_non_direct_mode_raises_typed_error_not_silent_fallback() -> None:
    from hamie.connectors.ai_executor import AIExecutorError

    mgr = _Manager(
        raises=AIExecutorError("investigation_requires_direct_provider"),
        method="ha_ai_task",
    )
    res = await Investigator(_Runtime(mgr).investigation_model).async_investigate(_pkg())
    assert res.status is InvestigationStatus.LLM_UNAVAILABLE
    assert res.proposal is None


@pytest.mark.asyncio
async def test_evidence_provenance_preserved_through_adapter() -> None:
    mgr = _Manager(result='{"root_cause":"stale ref","classification":"verified",'
                          '"confidence":0.95,"evidence_ids":["EV-1"],'
                          '"proposed_action":"replace reference",'
                          '"action_type":"replace_entity_reference",'
                          '"affected_objects":["sensor.old"]}')
    res = await Investigator(_Runtime(mgr).investigation_model).async_investigate(_pkg())
    assert "EV-1" in res.evidence_ids, "provenance must survive the adapter"
    assert res.proposal is not None and res.proposal.executable is False


@pytest.mark.asyncio
async def test_investigation_never_mutates() -> None:
    """Investigation is read-only by construction: it has no executor."""
    mgr = _Manager(result='{"root_cause":"x","classification":"verified",'
                          '"confidence":0.99,"evidence_ids":["EV-1"],'
                          '"proposed_action":"delete everything",'
                          '"action_type":"delete_entity",'
                          '"affected_objects":["sensor.old"]}')
    res = await Investigator(_Runtime(mgr).investigation_model).async_investigate(_pkg())
    assert res.proposal is not None
    assert res.proposal.executable is False, "investigation output is inert"
