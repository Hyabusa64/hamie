"""HAMIE's shared AI execution abstraction.

Every HAMIE background-analysis action (Analyze Highest Priority, Analyze
Selected Finding, Analyze Selected Group, Refresh AI Explanation, and any
future maintenance-summary generation) goes through the same
AIExecutorPort contract:

  redacted evidence payload -> AIExecutorPort.async_generate -> a dict
  validated by connectors.schemas.validate_ai_response

The primary implementation, HomeAssistantAiTaskExecutor, calls Home
Assistant's documented ai_task.generate_data action so HAMIE never
duplicates provider integration, credentials, or endpoint configuration --
Home Assistant AI Task owns all of that. DirectOllamaExecutor wraps the
existing OllamaConnector as an explicitly legacy/advanced fallback.

Conversation entities are never used here: conversation.process is a
dialogue action, not a background batch-analysis action, and Home
Assistant AI Task is the only primary/background pipeline HAMIE maintains.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol

from .base import (
    MAX_RECOVERABLE_PARSE_RETRIES,
    RECOVERABLE_PIPELINE_STAGES,
    PipelineStage,
    PipelineTracer,
    build_ai_evidence_prompt,
    is_likely_truncated_llm_response,
    parse_llm_json,
)
from .schemas import (
    SYSTEM_INSTRUCTIONS,
    SchemaValidationError,
    SemanticValidationError,
    correction_hint,
    repair_ai_response,
    validate_ai_response_schema,
    validate_ai_response_semantics,
)

_LOGGER = logging.getLogger(__name__)

AI_TASK_DOMAIN = "ai_task"
AI_TASK_SERVICE_GENERATE_DATA = "generate_data"
AI_TASK_TASK_NAME = "hamie_advisory_analysis"


def ai_task_structure() -> dict[str, dict[str, Any]]:
    """Return Home Assistant's native structured-output selector schema.

    The same semantic validator still runs after the provider returns.  This
    schema improves first-pass reliability; it never replaces HAMIE's strict
    field, evidence, and execution-safety validation.
    """
    fields: dict[str, dict[str, Any]] = {
        "schema_version": {
            "description": "HAMIE AI schema version; always 1.",
            "required": True,
            "selector": {"number": {"min": 1, "max": 1, "step": 1}},
        },
        "summary": {
            "description": "Evidence-grounded incident summary.",
            "required": True,
            "selector": {"text": {"multiline": True}},
        },
        "confidence": {
            "description": "Confidence level.",
            "required": True,
            "selector": {"select": {"options": ["low", "medium", "high"]}},
        },
        "model": {
            "description": "Provider model identifier.",
            "required": True,
            "selector": {"text": {}},
        },
        "generated_at": {
            "description": "Timezone-aware ISO 8601 generation timestamp.",
            "required": True,
            "selector": {"text": {}},
        },
    }
    for field in sorted(
        {
            "probable_causes",
            "recommended_checks",
            "proposed_repair_plan",
            "supporting_finding_ids",
            "supporting_group_ids",
            "assumptions",
            "missing_evidence",
            "risk_notes",
            "do_not_do",
        }
    ):
        fields[field] = {
            "description": f"Bounded list for {field.replace('_', ' ')}; empty if none.",
            "required": True,
            "selector": {"text": {"multiple": True}},
        }
    fields["proposed_action"] = {
        "description": "Optional narrow HAMIE proposal object; omit when none.",
        "required": False,
        "selector": {"object": {}},
    }
    return fields


class AIExecutorError(RuntimeError):
    """One stable, sanitized AI execution failure category."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AIExecutorPort(Protocol):
    """The one execution abstraction every HAMIE analysis action uses."""

    async def async_generate(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def _build_instructions(payload: dict[str, Any], maximum_input_characters: int) -> str:
    """Bound one flat instructions string for ai_task.generate_data,
    which takes no separate system/user roles the way a chat API does."""
    prompt = build_ai_evidence_prompt(payload, maximum_input_characters)
    return f"{SYSTEM_INSTRUCTIONS}\n\n{prompt}"


def _build_correction_instructions(previous_output: Any, err: Exception) -> str:
    """Build one short corrective follow-up instead of resending the full
    evidence payload again: the concise machine-generated feedback plus
    the model's own previous (bounded) output, so it can fix the one
    thing that was wrong without needing the original context repeated.
    """
    text = (
        previous_output
        if isinstance(previous_output, str)
        else json.dumps(previous_output, separators=(",", ":"), sort_keys=True)
    )
    return (
        f"{SYSTEM_INSTRUCTIONS}\n\n{correction_hint(err)}\n\n"
        f"Your previous output was:\n{text[:4_000]}"
    )


def _parse_generated_data(data: Any, tracer: PipelineTracer) -> dict[str, Any]:
    """Accept either a JSON string or an already-structured dict response,
    tracing JSON parsing, structural schema validation, and semantic
    safety validation as three separate stages so a failure is always
    attributed to the exact one that failed -- and so a schema-format
    mistake can be retried while a semantic safety rejection never is.
    """
    with tracer.stage(PipelineStage.PARSE_RESPONSE):
        if isinstance(data, dict):
            decoded: Any = data
        elif isinstance(data, str):
            if len(data) > 128_000:
                raise AIExecutorError("invalid_response")
            try:
                decoded = parse_llm_json(data)
            except json.JSONDecodeError as err:
                if is_likely_truncated_llm_response(data):
                    raise AIExecutorError("ai_response_truncated") from err
                raise AIExecutorError("invalid_response") from err
        else:
            raise AIExecutorError("invalid_response")
    with tracer.stage(PipelineStage.VALIDATE_SCHEMA):
        repaired = repair_ai_response(decoded) if isinstance(decoded, dict) else decoded
        try:
            schema_result = validate_ai_response_schema(repaired)
        except SchemaValidationError as err:
            raise AIExecutorError("schema_validation_failed") from err
    with tracer.stage(PipelineStage.VALIDATE_SEMANTICS):
        try:
            return validate_ai_response_semantics(schema_result)
        except SemanticValidationError as err:
            raise AIExecutorError("semantic_validation_failed") from err


class HomeAssistantAiTaskExecutor:
    """Primary AI executor: Home Assistant's ai_task.generate_data action.

    HAMIE never calls a provider directly in this mode; the entity's own
    integration owns credentials, endpoint, and model configuration.
    """

    def __init__(
        self,
        hass: Any,
        entity_id: str,
        *,
        timeout: float = 60,
        maximum_input_characters: int = 16_000,
        maximum_output_tokens: int = 1_024,
    ) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._timeout = timeout
        self._maximum_input_characters = maximum_input_characters
        self._maximum_output_tokens = maximum_output_tokens

    async def async_generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run one bounded advisory analysis task, tracing every stage.

        A recoverable failure -- the provider's text not parsing as JSON,
        or not matching HAMIE's schema -- is retried automatically, up to
        MAX_RECOVERABLE_PARSE_RETRIES extra attempts, before ever being
        surfaced to the user. On a retry, HAMIE sends a short corrective
        follow-up naming exactly what was wrong instead of resending the
        full evidence payload again. A semantic safety rejection (e.g.
        executable content) is never retried, regardless of attempt
        count. Every other failure (timeout, missing entity, unsupported
        feature, execution error) is also never retried.
        """
        if self._hass.states.get(self._entity_id) is None:
            raise AIExecutorError("entity_not_found")
        tracer = PipelineTracer(
            provider="ha_ai_task", model=self._entity_id, logger=_LOGGER
        )
        try:
            with tracer.stage(PipelineStage.BUILD_PROMPT):
                instructions = _build_instructions(
                    payload, self._maximum_input_characters
                )
        except ValueError as err:
            # The evidence payload itself was too large for the
            # configured budget -- a real, connector-independent
            # condition, distinct from (and must never be conflated
            # with) a provider response failing to parse as JSON. See
            # DirectOllamaExecutor.async_generate for the matching fix
            # on the direct-Ollama path.
            raise _reclassified(err, "evidence_payload_too_large") from err

        max_attempts = 1 + MAX_RECOVERABLE_PARSE_RETRIES
        last_err: Exception | None = None
        current_instructions = instructions
        for attempt in range(1, max_attempts + 1):
            raw_data: Any = None
            try:
                with tracer.stage(PipelineStage.CALL_PROVIDER):
                    try:
                        response = await asyncio.wait_for(
                            self._hass.services.async_call(
                                AI_TASK_DOMAIN,
                                AI_TASK_SERVICE_GENERATE_DATA,
                                {
                                    "entity_id": self._entity_id,
                                    "task_name": AI_TASK_TASK_NAME,
                                    "instructions": current_instructions,
                                    "structure": ai_task_structure(),
                                },
                                blocking=True,
                                return_response=True,
                            ),
                            timeout=self._timeout,
                        )
                    except TimeoutError as err:
                        raise AIExecutorError("timeout") from err
                    except Exception as err:
                        text = str(err).casefold()
                        if "not found" in text:
                            raise AIExecutorError("entity_not_found") from err
                        if "does not support" in text or "unsupported" in text:
                            raise AIExecutorError("unsupported_feature") from err
                        raise AIExecutorError("execution_failed") from err
                    if not isinstance(response, dict) or "data" not in response:
                        raise AIExecutorError("invalid_response")
                    raw_data = response["data"]
                return _parse_generated_data(raw_data, tracer)
            except Exception as err:
                last_err = err
                stage = getattr(err, "pipeline_stage", None)
                if stage not in RECOVERABLE_PIPELINE_STAGES or attempt == max_attempts:
                    raise
                _LOGGER.warning(
                    "HAMIE retrying analysis after a recoverable %s failure: "
                    "attempt=%d/%d provider=ha_ai_task entity=%s",
                    stage,
                    attempt,
                    max_attempts,
                    self._entity_id,
                )
                current_instructions = _build_correction_instructions(raw_data, err)
        assert last_err is not None
        raise last_err


class DirectOllamaExecutor:
    """Legacy/advanced fallback executor wrapping the direct Ollama connector.

    Kept only for migration rollback and explicitly deprecated advanced
    use; Home Assistant AI Task is the recommended and default pipeline.

    Production defect fixed here: OllamaConnector.async_explain() (its own
    older, independent response-parsing implementation -- confirmed live
    against the deployed RockPi instance's actual configuration, which
    runs in "direct" mode) raises bare ValueError/RuntimeError for every
    real failure (invalid response envelope, non-JSON content, a
    non-2xx HTTP status, or a schema-violating response), never the
    AIExecutorError/.code system the rest of this module and
    presentation/api.py's error surfacing rely on. Confirmed live: a real
    Analyze Now call against the real configured Ollama server returned
    the literal, meaningless string "ValueError" to the user with this
    wrapping missing. Reclassified here so every real reason ("invalid_response"
    for a JSON parse failure, "schema_validation_failed" for a structural
    mismatch repair could not fix, "semantic_validation_failed" for a
    safety rejection, "execution_failed" for a bad HTTP status) reaches
    the user as honest, specific text via the same path AI Task mode
    already uses.
    """

    def __init__(self, connector: Any) -> None:
        self._connector = connector

    async def async_generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._connector.async_explain(payload)
        except SemanticValidationError as err:
            raise _reclassified(err, "semantic_validation_failed") from err
        except SchemaValidationError as err:
            raise _reclassified(err, "schema_validation_failed") from err
        except ValueError as err:
            # A bare ValueError can come from three genuinely different
            # stages that must never share one label: building the
            # prompt (the evidence payload itself was too large for the
            # configured budget -- this is the exact beta.11 production
            # defect, where a build-time payload-size failure was
            # blanket-mislabeled "could not parse the AI provider's
            # response as JSON" even though the provider was never
            # called), the provider's response envelope being malformed,
            # or the response content simply not being JSON. PipelineTracer
            # (connectors/base.py) already attaches the real stage to
            # every exception it wraps; use it instead of guessing.
            stage = getattr(err, "pipeline_stage", None)
            existing_code = getattr(err, "code", None)
            if stage == PipelineStage.BUILD_PROMPT.value:
                code = "evidence_payload_too_large"
            elif existing_code == "ai_response_truncated":
                # OllamaConnector.async_explain already distinguished a
                # structurally-truncated response from a merely malformed
                # one (is_likely_truncated_llm_response) -- preserve that,
                # never collapse it back into the generic invalid_response
                # bucket.
                code = existing_code
            else:
                code = "invalid_response"
            raise _reclassified(err, code) from err
        except RuntimeError as err:
            if str(err) == "connector is closed":
                raise
            raise _reclassified(err, "execution_failed") from err


_PIPELINE_ATTRS = (
    "pipeline_stage",
    "pipeline_elapsed_ms",
    "pipeline_provider",
    "pipeline_model",
    "pipeline_error_code",
    "pipeline_reason",
)


def _reclassified(err: Exception, code: str) -> AIExecutorError:
    """Wrap a raw OllamaConnector exception in the shared AIExecutorError
    type (so every AI executor raises the same stable, sanitized error
    category) while preserving any pipeline-stage context PipelineTracer
    already attached to it -- reclassifying must never silently drop the
    exact-stage diagnostics."""
    wrapped = AIExecutorError(code)
    for attr in _PIPELINE_ATTRS:
        if hasattr(err, attr):
            setattr(wrapped, attr, getattr(err, attr))
    return wrapped
