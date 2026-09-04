"""Connector ports, limits, endpoint policy, and shared values."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from time import monotonic
from typing import Any, Protocol
from urllib.parse import urlsplit

MAX_CONNECTOR_PAYLOAD_BYTES = 64_000
MAX_CONNECTOR_RESPONSE_BYTES = 128_000
MAX_CONNECTOR_TIMEOUT_SECONDS = 60
MAX_CONNECTOR_RETRIES = 3
MAX_CONNECTOR_QUEUE = 8
MAX_RECOVERABLE_PARSE_RETRIES = 2


class ConnectorStatus(StrEnum):
    """Cached connector health state."""

    DISABLED = "disabled"
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    ERROR = "error"


class ConnectorTestError(RuntimeError):
    """One stable connector test/discovery failure category."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ConnectorHealth:
    """Bounded cached connector status updated only by explicit work."""

    connector_id: str
    enabled: bool
    status: ConnectorStatus
    capability_mode: str
    last_success: datetime | None = None
    last_failure: datetime | None = None
    last_attempt: datetime | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    consecutive_failures: int = 0

    def public_dict(self) -> dict[str, Any]:
        """Return a secret-free frontend and diagnostics view."""
        last_tested = max(
            (value for value in (self.last_success, self.last_failure) if value),
            default=None,
        )
        return {
            "connector_id": self.connector_id,
            "enabled": self.enabled,
            "status": self.status.value,
            "capability_mode": self.capability_mode,
            "last_success": (
                self.last_success.isoformat() if self.last_success else None
            ),
            "last_failure": (
                self.last_failure.isoformat() if self.last_failure else None
            ),
            "last_attempt": (
                self.last_attempt.isoformat() if self.last_attempt else None
            ),
            "last_tested": last_tested.isoformat() if last_tested else None,
            "latency_ms": self.latency_ms,
            "error_code": self.error_code,
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass(frozen=True, slots=True)
class HttpResult:
    """Bounded transport result."""

    status: int
    data: Any
    latency_ms: int


class ConnectorTransport(Protocol):
    """Async HTTP boundary injected into optional network adapters."""

    async def async_request_json(
        self,
        *,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
        headers: dict[str, str],
        timeout: float,
        verify_tls: bool,
        maximum_response_bytes: int = MAX_CONNECTOR_RESPONSE_BYTES,
    ) -> HttpResult: ...


class Connector(Protocol):
    """Finite optional connector lifecycle."""

    connector_id: str
    capability_mode: str

    async def async_test(self) -> dict[str, Any] | None: ...

    async def async_close(self) -> None: ...


def validate_endpoint(url: str, allowed_hosts: tuple[str, ...]) -> str:
    """Validate an explicit HTTP endpoint against a strict host allowlist."""
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("connector endpoint must be a credential-free HTTP URL")
    hostname = parsed.hostname.casefold()
    normalized = {item.casefold().strip() for item in allowed_hosts if item.strip()}
    if hostname not in normalized:
        raise ValueError("connector endpoint host is not explicitly allowed")
    return url.rstrip("/")


def bounded_payload(payload: dict[str, Any], maximum: int) -> dict[str, Any]:
    """Reject payloads over their configured canonical JSON bound."""
    if not 1 <= maximum <= MAX_CONNECTOR_PAYLOAD_BYTES:
        raise ValueError("connector input limit is outside safe bounds")
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    if len(encoded) > maximum:
        raise ValueError("connector payload exceeds configured limit")
    return payload


def build_ai_evidence_prompt(payload: dict[str, Any], maximum_characters: int) -> str:
    """Redact and bound one evidence payload into its canonical compact
    JSON prompt fragment.

    Shared by every AI executor (ai_executor.py's ha_ai_task path,
    ollama.py's direct path) so there is exactly one implementation of
    "redact -> bound -> serialize" for the evidence half of a prompt,
    never two independently maintained copies that could silently drift
    apart. Each caller still combines this with its own provider's
    system-instructions shape (a flat string for ai_task.generate_data,
    a separate chat message for Ollama/OpenAI-compatible), since that
    part is genuinely provider-specific.
    """
    from .redaction import redact_payload

    redacted = redact_payload(payload)
    bounded_payload(redacted, maximum_characters)
    return json.dumps(redacted, separators=(",", ":"), sort_keys=True)


def now_utc() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


def _extract_first_json_value(text: str) -> str | None:
    """Return the span of the first complete top-level JSON object or
    array in ``text`` (bracket-depth matched, respecting quoted strings
    and escapes), or None if no complete top-level value is found. This
    is a structural scan, never a guess: it either finds one well-formed
    bracketed span or it finds nothing.
    """
    start = next((i for i, ch in enumerate(text) if ch in "{["), None)
    if start is None:
        return None
    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def is_likely_truncated_llm_response(content: str) -> bool:
    """Return whether ``content`` looks like JSON cut off mid-value.

    Structural, never a guess: scans the same bracket-depth-matched span
    ``_extract_first_json_value`` does (respecting quoted strings and
    escapes) and reports True only when an opening ``{``/``[`` was found
    but the input ran out before its matching close -- the honest
    signature of a provider hitting its output/token limit mid-response,
    not merely malformed or non-JSON text. Trailing garbage after an
    otherwise-complete value (``{"a": 1} oops``) is not truncation --
    depth reaches 0 before end of input -- and text with no bracket at
    all is not truncation either; both are ordinary parse failures.
    """
    start = next((i for i, ch in enumerate(content) if ch in "{["), None)
    if start is None:
        return False
    opening = content[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for char in content[start:]:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return False
    return True


def parse_llm_json(content: str) -> Any:
    """Parse one LLM text response as JSON, tolerating the common
    structured-output artifacts of local/quantized models even with a
    JSON response format requested: a whole response wrapped in a single
    markdown code fence (reusing schemas.unwrap_markdown_fence, the
    existing tested fence-unwrap logic), or a single JSON object/array
    surrounded by leading/trailing prose. Every fallback still requires
    extracting an exact, complete JSON value -- never partial or
    string-repaired -- and final schema validation still rejects any
    shape that doesn't match, so this never trades correctness for
    leniency.
    """
    import json

    from .schemas import unwrap_markdown_fence

    stripped = content.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as err:
        unwrapped = unwrap_markdown_fence(stripped)
        if unwrapped != stripped:
            try:
                return json.loads(unwrapped)
            except json.JSONDecodeError:
                pass
        span = _extract_first_json_value(stripped)
        if span is not None:
            try:
                return json.loads(span)
            except json.JSONDecodeError:
                pass
        raise err


def classify_connector_failure(err: Exception) -> str:
    """Map any connector failure to one fixed, non-sensitive category.

    Any already-typed failure (ConnectorTestError, AIExecutorError,
    ConfigurationError, ...) carries its own resolved ``.code`` and is
    returned as-is; only untyped exceptions bubbling up from a transport
    (aiohttp errors, bare ValueError/RuntimeError, ...) fall back to coarse
    text matching. This is the single source of truth for that mapping --
    callers must not re-derive categories from ``str(err)`` themselves, or
    typed codes silently get discarded and re-guessed.
    """
    code = getattr(err, "code", None)
    if isinstance(code, str) and code:
        return code
    if isinstance(err, TimeoutError):
        return "timeout"
    text = str(err).casefold()
    if "timeout" in text:
        return "timeout"
    if any(value in text for value in ("401", "403", "unauthor", "forbidden")):
        return "authentication_failed"
    if any(value in text for value in ("ssl", "tls", "certificate")):
        return "tls_error"
    if "model" in text:
        return "model_unavailable"
    if any(value in text for value in ("response", "schema", "json", "envelope")):
        return "invalid_response"
    return "unreachable"


class PipelineStage(StrEnum):
    """One named, user-visible step of one HAMIE analysis run.

    Every analysis passes through these in order. A failure is always
    attributed to the exact stage it happened in -- never collapsed into
    a generic "analysis failed".
    """

    COLLECT_FINDINGS = "collect_findings"
    BUILD_PROMPT = "build_prompt"
    CALL_PROVIDER = "call_provider"
    PARSE_RESPONSE = "parse_response"
    VALIDATE_SCHEMA = "validate_schema"
    VALIDATE_SEMANTICS = "validate_semantics"
    PERSIST = "persist"


# PARSE_RESPONSE and VALIDATE_SCHEMA are both format mistakes a model can
# plausibly correct on a re-prompt (bad JSON, a missing/extra field, a
# wrong type). VALIDATE_SEMANTICS deliberately is not recoverable here:
# a response that is well-formed JSON matching the schema but violates a
# HAMIE safety rule (e.g. executable content) must never be blindly
# retried with the same request -- see schemas.SemanticValidationError.
RECOVERABLE_PIPELINE_STAGES = frozenset(
    {PipelineStage.PARSE_RESPONSE.value, PipelineStage.VALIDATE_SCHEMA.value}
)

_PIPELINE_FAILURE_REASONS: dict[str, str] = {
    "invalid_response": (
        "The provider's response could not be parsed or did not match the "
        "expected schema."
    ),
    "evidence_payload_too_large": (
        "The selected findings' evidence was too large for the configured "
        "prompt budget, even after bounded priority-ordered selection."
    ),
    "schema_validation_failed": (
        "The provider's response was well-formed but did not match HAMIE's "
        "required structure after automatic repair."
    ),
    "semantic_validation_failed": (
        "The provider's response matched the schema but violated a HAMIE "
        "safety rule and was rejected."
    ),
    "provider_response_not_json": "The provider's HTTP response was not valid JSON.",
    "ai_response_truncated": (
        "The provider's response was cut off before it finished -- likely "
        "an output/token limit -- rather than malformed."
    ),
    "timeout": "The provider did not respond within the configured timeout.",
    "authentication_failed": "The provider rejected the configured credentials.",
    "model_unavailable": "The configured model is not available on the provider.",
    "model_not_found": "The selected model was not returned by the provider.",
    "entity_not_found": "The configured AI Task entity is no longer available.",
    "unsupported_feature": (
        "The configured AI Task entity does not support this operation."
    ),
    "ai_provider_not_ready": "No AI provider is configured and ready.",
    "execution_failed": "The provider call failed for an unspecified reason.",
    "tls_error": "TLS validation failed.",
    "unreachable": "The provider could not be reached.",
}


def _pipeline_failure_reason(error_code: str) -> str:
    return _PIPELINE_FAILURE_REASONS.get(
        error_code, "The stage failed for an unspecified reason."
    )


class PipelineTracer:
    """Time each named analysis stage for one run and, on failure, attach
    the failing stage's structured context onto the *same* exception
    instance rather than replacing or wrapping it -- callers keep their
    existing exception type/isinstance contract (tests and callers that
    match on ValueError/AIExecutorError/etc. keep working unchanged);
    diagnostics and logging just get to read the extra attributes:
    ``pipeline_stage``, ``pipeline_elapsed_ms``, ``pipeline_provider``,
    ``pipeline_model``, ``pipeline_error_code``, ``pipeline_reason``.
    """

    def __init__(self, *, provider: str, model: str | None, logger: Any = None) -> None:
        self.provider = provider
        self.model = model
        self.completed: list[tuple[str, int]] = []
        self._logger = logger

    @contextmanager
    def stage(self, stage: PipelineStage) -> Iterator[None]:
        started = monotonic()
        try:
            yield
        except Exception as err:
            elapsed_ms = max(0, int((monotonic() - started) * 1_000))
            code = classify_connector_failure(err)
            err.pipeline_stage = stage.value  # type: ignore[attr-defined]
            err.pipeline_elapsed_ms = elapsed_ms  # type: ignore[attr-defined]
            err.pipeline_provider = self.provider  # type: ignore[attr-defined]
            err.pipeline_model = self.model  # type: ignore[attr-defined]
            err.pipeline_error_code = code  # type: ignore[attr-defined]
            err.pipeline_reason = _pipeline_failure_reason(code)  # type: ignore[attr-defined]
            if self._logger is not None:
                self._logger.warning(
                    "HAMIE analysis stage failed: stage=%s elapsed_ms=%d "
                    "provider=%s model=%s error_code=%s",
                    stage.value,
                    elapsed_ms,
                    self.provider,
                    self.model,
                    code,
                )
            raise
        else:
            elapsed_ms = max(0, int((monotonic() - started) * 1_000))
            self.completed.append((stage.value, elapsed_ms))
            if self._logger is not None:
                self._logger.debug(
                    "HAMIE analysis stage completed: stage=%s elapsed_ms=%d "
                    "provider=%s model=%s",
                    stage.value,
                    elapsed_ms,
                    self.provider,
                    self.model,
                )


@dataclass(frozen=True, slots=True)
class PipelineFailureSnapshot:
    """One bounded, secret-free snapshot of the last failed analysis
    stage, suitable for diagnostics/audit -- never raw exception text."""

    stage: str | None
    elapsed_ms: int | None
    provider: str | None
    model: str | None
    reason: str | None
    error_code: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "elapsed_ms": self.elapsed_ms,
            "provider": self.provider,
            "model": self.model,
            "reason": self.reason,
            "error_code": self.error_code,
        }


def pipeline_failure_snapshot(err: Exception) -> PipelineFailureSnapshot:
    """Extract whatever pipeline-stage context an exception carries (see
    PipelineTracer) into one bounded snapshot. Exceptions that never
    passed through a traced stage still get a snapshot -- just with
    stage/elapsed/provider/model left unset -- so this is always safe to
    call on any connector or AI-execution failure.
    """
    code = classify_connector_failure(err)
    return PipelineFailureSnapshot(
        stage=getattr(err, "pipeline_stage", None),
        elapsed_ms=getattr(err, "pipeline_elapsed_ms", None),
        provider=getattr(err, "pipeline_provider", None),
        model=getattr(err, "pipeline_model", None),
        reason=getattr(err, "pipeline_reason", None) or _pipeline_failure_reason(code),
        error_code=code,
    )
