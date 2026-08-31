"""Ollama and OpenAI-compatible advisory explanation adapter."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .base import (
    MAX_CONNECTOR_RESPONSE_BYTES,
    MAX_RECOVERABLE_PARSE_RETRIES,
    RECOVERABLE_PIPELINE_STAGES,
    ConnectorTestError,
    ConnectorTransport,
    PipelineStage,
    PipelineTracer,
    build_ai_evidence_prompt,
    is_likely_truncated_llm_response,
    parse_llm_json,
    validate_endpoint,
)
from .schemas import (
    SYSTEM_INSTRUCTIONS,
    correction_hint,
    repair_ai_response,
    validate_ai_response_schema,
    validate_ai_response_semantics,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    """Bounded disabled-by-default LLM connector settings."""

    provider_type: str
    base_url: str
    model: str
    api_key: str | None
    timeout: float
    maximum_input_characters: int
    maximum_output_tokens: int
    temperature: float
    verify_tls: bool
    allowed_hosts: tuple[str, ...]
    capabilities: tuple[str, ...]
    think: bool = False

    def __post_init__(self) -> None:
        if self.provider_type not in {"ollama", "openai_compatible"}:
            raise ValueError("unsupported LLM provider type")
        if len(self.model) > 128:
            raise ValueError("LLM model is invalid")
        if not 1 <= self.timeout <= 60:
            raise ValueError("LLM timeout is outside safe bounds")
        if not 1_000 <= self.maximum_input_characters <= 64_000:
            raise ValueError("LLM input limit is outside safe bounds")
        if not 16 <= self.maximum_output_tokens <= 4_096:
            raise ValueError("LLM output limit is outside safe bounds")
        if not 0 <= self.temperature <= 1:
            raise ValueError("LLM temperature is outside safe bounds")
        validate_endpoint(self.base_url, self.allowed_hosts)


def _stop_reason(raw: Any, provider_type: str) -> str | None:
    """The provider's own reason for stopping, normalized.

    Ollama uses `done_reason`; OpenAI-compatible providers use
    `choices[0].finish_reason`. Both say "length" when the output budget
    ended generation. Returns None when the provider did not say.
    """
    try:
        if provider_type == "ollama":
            value = raw.get("done_reason")
        else:
            value = (raw.get("choices") or [{}])[0].get("finish_reason")
    except (AttributeError, IndexError, TypeError):
        return None
    return str(value) if value else None


class OllamaConnector:
    """One-at-a-time structured advisory LLM connector."""

    connector_id = "ollama"
    capability_mode = "advisory_only"

    def __init__(self, config: OllamaConfig, transport: ConnectorTransport) -> None:
        self.config = config
        self._transport = transport
        self.closed = False

    async def async_test(self) -> dict[str, Any]:
        """Discover bounded provider models and verify any selected model."""
        models = await self.async_discover_models()
        if self.config.model and self.config.model not in models:
            raise ConnectorTestError("model_not_found")
        return {
            "models": list(models),
            "selected_model": self.config.model or None,
            "model_list_status": "available",
        }

    async def async_discover_models(self) -> tuple[str, ...]:
        """Return a deterministic bounded model catalog without polling."""
        if self.closed:
            raise RuntimeError("connector is closed")
        headers = {"Accept": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        suffix = "/api/tags" if self.config.provider_type == "ollama" else "/v1/models"
        result = await self._transport.async_request_json(
            method="GET",
            url=validate_endpoint(self.config.base_url, self.config.allowed_hosts)
            + suffix,
            payload=None,
            headers=headers,
            timeout=self.config.timeout,
            verify_tls=self.config.verify_tls,
            maximum_response_bytes=MAX_CONNECTOR_RESPONSE_BYTES,
        )
        if result.status in {401, 403}:
            raise ConnectorTestError("authentication_failed")
        if result.status < 200 or result.status >= 300:
            raise ConnectorTestError("model_discovery_failed")
        raw = result.data
        try:
            entries = (
                raw["models"] if self.config.provider_type == "ollama" else raw["data"]
            )
            if not isinstance(entries, list) or len(entries) > 256:
                raise TypeError
            identifiers = []
            for item in entries:
                if not isinstance(item, dict):
                    raise TypeError
                value = (
                    item.get("name")
                    if self.config.provider_type == "ollama"
                    else item.get("id")
                )
                if (
                    not isinstance(value, str)
                    or not value.strip()
                    or value != value.strip()
                    or len(value) > 128
                ):
                    raise TypeError
                identifiers.append(value)
        except (KeyError, TypeError) as err:
            raise ConnectorTestError("model_discovery_failed") from err
        models = tuple(sorted(dict.fromkeys(identifiers), key=str.casefold)[:100])
        if not models:
            raise ConnectorTestError("model_list_unavailable")
        return models

    async def async_investigate(self, system: str, user: str) -> str:
        """Raw structured-JSON completion for HAMIE's investigation loop.

        Deliberately separate from async_explain(): that method implements
        HAMIE's *finding-advisory* contract and validates the reply against
        the advisory schema. The investigation loop supplies its own prompts
        and does its own parsing, then re-imposes determinism (invariants,
        evidence citation, confidence clamping) on the result -- so it needs
        the model's text, not a pre-validated advisory object.

        Everything security-relevant is reused rather than re-implemented:
        the same endpoint allow-list, headers, transport, timeout, TLS
        verification, provider-type branching, and response-size bound.
        No new network path is introduced.
        """
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        base = validate_endpoint(self.config.base_url, self.config.allowed_hosts)
        if self.config.provider_type == "ollama":
            url = base + "/api/chat"
            body: dict[str, Any] = {
                "model": self.config.model,
                "stream": False,
                "format": "json",
                "think": self.config.think,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "options": {
                    "temperature": self.config.temperature,
                    "num_predict": self.config.maximum_output_tokens,
                },
            }
        else:
            url = base + "/v1/chat/completions"
            body = {
                "model": self.config.model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.config.temperature,
                "max_tokens": self.config.maximum_output_tokens,
            }

        result = await self._transport.async_request_json(
            method="POST",
            url=url,
            payload=body,
            headers=headers,
            timeout=self.config.timeout,
            verify_tls=self.config.verify_tls,
        )
        if result.status < 200 or result.status >= 300:
            raise RuntimeError(f"LLM provider returned status {result.status}")
        try:
            content = (
                result.data["message"]["content"]
                if self.config.provider_type == "ollama"
                else result.data["choices"][0]["message"]["content"]
            )
        except (KeyError, IndexError, TypeError) as err:
            raise ValueError("LLM provider response envelope is invalid") from err
        if not isinstance(content, str) or len(content) > 128_000:
            raise ValueError("LLM response content is invalid")
        return content

    async def async_explain(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send only redacted structured evidence and validate strict JSON
        output, tracing every stage separately (parse, schema, semantics).

        A recoverable failure -- the model's text not parsing as JSON, or
        not matching HAMIE's schema -- is retried automatically, up to
        MAX_RECOVERABLE_PARSE_RETRIES extra attempts, before ever being
        surfaced to the user. A retry sends the model's own previous turn
        plus one short corrective instruction (never the full evidence
        payload again). A semantic safety rejection (e.g. executable
        content) is never retried. Every other failure (bad status,
        timeout, malformed envelope) is also never retried.
        """
        if self.closed:
            raise RuntimeError("connector is closed")
        tracer = PipelineTracer(
            provider="direct_ollama", model=self.config.model, logger=_LOGGER
        )
        with tracer.stage(PipelineStage.BUILD_PROMPT):
            prompt = build_ai_evidence_prompt(
                payload, self.config.maximum_input_characters
            )
            headers = {"Content-Type": "application/json"}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            base_messages = [
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": prompt},
            ]
            if self.config.provider_type == "ollama":
                url = (
                    validate_endpoint(self.config.base_url, self.config.allowed_hosts)
                    + "/api/chat"
                )
            else:
                url = (
                    validate_endpoint(self.config.base_url, self.config.allowed_hosts)
                    + "/v1/chat/completions"
                )

        def _body(messages: list[dict[str, str]]) -> dict[str, Any]:
            if self.config.provider_type == "ollama":
                return {
                    "model": self.config.model,
                    "stream": False,
                    "format": "json",
                    # Hybrid-thinking models (e.g. Qwen3) can spend the
                    # entire num_predict budget on a hidden reasoning phase
                    # and return empty content -- confirmed live: even at
                    # num_predict=4096, thinking alone consumed the whole
                    # budget and content was never reached. Defaults to
                    # False (configurable via ollama_think) since an empty
                    # response is never useful for HAMIE's single-shot
                    # structured output; only the "ollama" request format
                    # supports this option at all, never openai_compatible.
                    "think": self.config.think,
                    "messages": messages,
                    "options": {
                        "temperature": self.config.temperature,
                        "num_predict": self.config.maximum_output_tokens,
                    },
                }
            return {
                "model": self.config.model,
                "response_format": {"type": "json_object"},
                "messages": messages,
                "temperature": self.config.temperature,
                "max_tokens": self.config.maximum_output_tokens,
            }

        max_attempts = 1 + MAX_RECOVERABLE_PARSE_RETRIES
        last_err: Exception | None = None
        messages = list(base_messages)
        for attempt in range(1, max_attempts + 1):
            content: str | None = None
            try:
                with tracer.stage(PipelineStage.CALL_PROVIDER):
                    result = await self._transport.async_request_json(
                        method="POST",
                        url=url,
                        payload=_body(messages),
                        headers=headers,
                        timeout=self.config.timeout,
                        verify_tls=self.config.verify_tls,
                    )
                    if result.status < 200 or result.status >= 300:
                        raise RuntimeError(
                            f"LLM provider returned status {result.status}"
                        )
                    raw = result.data
                    try:
                        content = (
                            raw["message"]["content"]
                            if self.config.provider_type == "ollama"
                            else raw["choices"][0]["message"]["content"]
                        )
                    except (KeyError, IndexError, TypeError) as err:
                        raise ValueError(
                            "LLM provider response envelope is invalid"
                        ) from err
                    if not isinstance(content, str) or len(content) > 128_000:
                        raise ValueError("LLM response content is invalid")
                    # The provider knows why it stopped; HAMIE previously only
                    # guessed from the text. Ollama reports done_reason="length"
                    # and OpenAI-compatible finish_reason="length" when the
                    # output budget cut generation off. Measured live: a
                    # 20-finding group needs ~1200-1400 tokens, and at
                    # num_predict=1024 every response came back
                    # done_reason="length" with unparseable JSON. Reading the
                    # authoritative signal turns a heuristic into a fact.
                    stop_reason = _stop_reason(raw, self.config.provider_type)
                with tracer.stage(PipelineStage.PARSE_RESPONSE):
                    try:
                        decoded = parse_llm_json(content)
                    except json.JSONDecodeError as err:
                        if stop_reason == "length" or is_likely_truncated_llm_response(
                            content
                        ):
                            truncated = ValueError(
                                "LLM response was truncated before completing "
                                "valid JSON"
                                + (
                                    " (provider reported stop reason 'length')"
                                    if stop_reason == "length"
                                    else ""
                                )
                            )
                            truncated.code = "ai_response_truncated"  # type: ignore[attr-defined]
                            truncated.stop_reason = stop_reason  # type: ignore[attr-defined]
                            raise truncated from err
                        raise ValueError("LLM response content is not JSON") from err
                    if stop_reason == "length":
                        # Parsed, but the provider says it never finished. A
                        # cut-off response that happens to close its braces is
                        # still an incomplete analysis, and accepting it would
                        # let a partial answer count as a completed one.
                        truncated = ValueError(
                            "LLM response parsed but the provider reported it "
                            "was cut off by the output budget"
                        )
                        truncated.code = "ai_response_truncated"  # type: ignore[attr-defined]
                        truncated.stop_reason = stop_reason  # type: ignore[attr-defined]
                        raise truncated
                with tracer.stage(PipelineStage.VALIDATE_SCHEMA):
                    repaired = (
                        repair_ai_response(decoded)
                        if isinstance(decoded, dict)
                        else decoded
                    )
                    schema_result = validate_ai_response_schema(repaired)
                with tracer.stage(PipelineStage.VALIDATE_SEMANTICS):
                    return validate_ai_response_semantics(schema_result)
            except Exception as err:
                last_err = err
                stage = getattr(err, "pipeline_stage", None)
                if stage not in RECOVERABLE_PIPELINE_STAGES or attempt == max_attempts:
                    raise
                _LOGGER.warning(
                    "HAMIE retrying analysis after a recoverable %s failure: "
                    "attempt=%d/%d provider=direct_ollama model=%s",
                    stage,
                    attempt,
                    max_attempts,
                    self.config.model,
                )
                messages = [
                    *base_messages,
                    {"role": "assistant", "content": content or ""},
                    {"role": "user", "content": correction_hint(err)},
                ]
        assert last_err is not None
        raise last_err

    async def async_close(self) -> None:
        """Close adapter state; the shared HA session remains HA-owned."""
        self.closed = True
