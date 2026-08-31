"""Provider failures remain bounded, specific, and non-executing."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from hamie.connectors.ai_executor import AIExecutorError, HomeAssistantAiTaskExecutor
from hamie.connectors.base import MAX_RECOVERABLE_PARSE_RETRIES
from hamie.connectors.schemas import AI_RESPONSE_DEFAULTABLE_ARRAY_FIELDS


class _States:
    def get(self, _entity_id: str):
        return object()


class _Services:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls = 0

    async def async_call(self, *_args, **_kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response


class _Hass:
    def __init__(self, services: _Services) -> None:
        self.states = _States()
        self.services = services


def _valid_data(*, summary: str = "Evidence-backed advisory.") -> dict[str, object]:
    return {
        "schema_version": 1,
        "summary": summary,
        "confidence": "high",
        "model": "test-model",
        "generated_at": datetime.now(UTC).isoformat(),
        **{field: [] for field in AI_RESPONSE_DEFAULTABLE_ARRAY_FIELDS},
        "proposed_action": None,
    }


@pytest.mark.asyncio
async def test_malformed_response_exhausts_only_bounded_format_retries() -> None:
    services = _Services(response={"data": "not json"})
    executor = HomeAssistantAiTaskExecutor(_Hass(services), "ai_task.test")

    with pytest.raises(AIExecutorError) as captured:
        await executor.async_generate({"findings": []})

    assert captured.value.code == "invalid_response"
    assert services.calls == 1 + MAX_RECOVERABLE_PARSE_RETRIES


@pytest.mark.asyncio
async def test_unsupported_structured_output_is_not_retried() -> None:
    services = _Services(error=RuntimeError("provider does not support structure"))
    executor = HomeAssistantAiTaskExecutor(_Hass(services), "ai_task.test")

    with pytest.raises(AIExecutorError) as captured:
        await executor.async_generate({"findings": []})

    assert captured.value.code == "unsupported_feature"
    assert services.calls == 1


@pytest.mark.asyncio
async def test_context_overflow_fails_before_provider_call() -> None:
    services = _Services(response={"data": _valid_data()})
    executor = HomeAssistantAiTaskExecutor(
        _Hass(services),
        "ai_task.test",
        maximum_input_characters=1_000,
    )

    with pytest.raises(AIExecutorError) as captured:
        await executor.async_generate({"findings": ["x" * 10_000]})

    assert captured.value.code == "evidence_payload_too_large"
    assert services.calls == 0


@pytest.mark.asyncio
async def test_semantic_execution_marker_is_rejected_without_retry() -> None:
    services = _Services(
        response={"data": _valid_data(summary="Run service: homeassistant.restart")}
    )
    executor = HomeAssistantAiTaskExecutor(_Hass(services), "ai_task.test")

    with pytest.raises(AIExecutorError) as captured:
        await executor.async_generate({"findings": []})

    assert captured.value.code == "semantic_validation_failed"
    assert services.calls == 1


@pytest.mark.asyncio
async def test_provider_timeout_is_specific_and_not_retried() -> None:
    class _HangingServices(_Services):
        async def async_call(self, *_args, **_kwargs):
            self.calls += 1
            await asyncio.Event().wait()

    services = _HangingServices()
    executor = HomeAssistantAiTaskExecutor(
        _Hass(services), "ai_task.test", timeout=0.001
    )

    with pytest.raises(AIExecutorError) as captured:
        await executor.async_generate({"findings": []})

    assert captured.value.code == "timeout"
    assert services.calls == 1
