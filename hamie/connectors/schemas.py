"""Strict versioned connector payload schemas."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from ..domain.intelligence import AI_SCHEMA_VERSION
from ..domain.remediation_resources import list_editable_resources

_MARKDOWN_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*)\n\s*```\s*$", re.DOTALL)


def unwrap_markdown_fence(text: str) -> str:
    """Unwrap a ```json ... ``` fence some models wrap structured output in.

    Shared by every real AI response parsing path (Home Assistant AI Task
    in ai_executor.py, and the direct/legacy Ollama connector in
    ollama.py) -- a common, harmless real-world model formatting habit.
    Purely a parsing tolerance: the strict field-set/content checks in
    validate_ai_response() below run unchanged on whatever this returns,
    so this cannot weaken the safety validation, only avoid rejecting
    otherwise-valid JSON for cosmetic reasons.
    """
    match = _MARKDOWN_JSON_FENCE.match(text)
    return match.group(1) if match else text


AI_RESPONSE_REQUIRED_FIELDS = frozenset(
    {"schema_version", "summary", "confidence", "model", "generated_at"}
)

# Deterministically defaultable to an empty list when a provider omits them
# entirely. These are HAMIE-authored *lists the AI populated*, not required
# facts: an absent key and an explicitly empty array both mean "the model
# had nothing to report here" -- so filling the gap with () is not
# inventing evidence, entities, or recommendations, only recognizing an
# already-legal empty value the model failed to spell out. See
# repair_ai_response() below.
AI_RESPONSE_DEFAULTABLE_ARRAY_FIELDS = frozenset(
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
)

# Optional, nullable: present in every valid response (repair_ai_response
# fills an absent key with None, exactly like the array fields above are
# filled with []) but the value itself is either null or one small,
# closed-shape object -- never required, never inferred as "safe to
# execute". See domain/llm_proposal.py for the authoritative structural
# model and domain/remediation_llm_proposal.py for the deterministic
# policy that decides whether a non-null value ever becomes executable.
AI_RESPONSE_OPTIONAL_NULLABLE_FIELDS = frozenset({"proposed_action"})

AI_RESPONSE_FIELDS = (
    AI_RESPONSE_REQUIRED_FIELDS
    | AI_RESPONSE_DEFAULTABLE_ARRAY_FIELDS
    | AI_RESPONSE_OPTIONAL_NULLABLE_FIELDS
)

_REQUIRED_FIELD_TYPES = {
    "schema_version": "integer, must be 1",
    "summary": "string",
    "confidence": 'one of "low", "medium", "high"',
    "model": "string",
    "generated_at": "ISO 8601 timezone-aware timestamp string",
}


def _editable_resource_prompt_hint() -> str:
    resources = list_editable_resources()
    if not resources:
        return "no editable resources are currently available"
    return "; ".join(f"{item.resource_id} ({item.description})" for item in resources)


def _field_shape_description() -> str:
    """One compact, deterministic description of every AI response field
    and its type, generated from the same AI_RESPONSE_REQUIRED_FIELDS /
    AI_RESPONSE_DEFAULTABLE_ARRAY_FIELDS sets validate_ai_response_schema()
    enforces, so the prompt can never drift out of sync with the actual
    schema. Confirmed live (Qwen3.5, thinking disabled) that a small
    quantized model reliably returns valid JSON once thinking no longer
    exhausts its output budget, but invents its own response shape
    instead of HAMIE's without this: "matching HAMIE AI schema version 1"
    alone names nothing concrete for the model to imitate on a first
    attempt, forcing every real request through a corrective retry.
    """
    required = ", ".join(
        f"{field} ({_REQUIRED_FIELD_TYPES[field]})"
        for field in sorted(AI_RESPONSE_REQUIRED_FIELDS)
    )
    arrays = ", ".join(sorted(AI_RESPONSE_DEFAULTABLE_ARRAY_FIELDS))
    return (
        f"Required fields: {required}. Required string-array fields (use "
        f"[] if none apply): {arrays}. Optional field 'proposed_action' "
        "(use null if none applies): if present, must be an object with "
        "exactly resource_id (string), action_type (string, must be "
        "'yaml_set'), operation (object with exactly 'key' and 'value' "
        "string fields), evidence_ids (array of strings, from the "
        "evidence ids supplied to you in this request only), and reason "
        "(string). No other top-level fields."
    )


SYSTEM_INSTRUCTIONS = (
    "Return only one JSON object matching HAMIE AI schema version 1 -- "
    "no markdown code fence, no prose or explanation before or after it. "
    f"{_field_shape_description()} "
    "Base your analysis only on the evidence provided in this request; "
    "do not invent facts, entities, or evidence not present in it. "
    "Advisory explanations only; do not emit executable YAML, service "
    "calls, shell commands, deletion, disablement, or self-approval. "
    "You may optionally propose one narrow, reviewable file annotation "
    "via 'proposed_action', but only against one of these HAMIE-reviewed "
    f"editable resources: {_editable_resource_prompt_hint()}. Never invent "
    "a resource id, a file path, or an evidence id; a proposed_action is "
    "only ever a suggestion a human must explicitly review and approve, "
    "and it is never applied automatically."
)


class SchemaValidationError(ValueError):
    """A structural/type failure: wrong shape, missing/extra field, bad
    type, or an unsupported schema version. Distinct from
    SemanticValidationError so callers can retry a format mistake but must
    never retry a safety rejection the same way."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class SemanticValidationError(ValueError):
    """A HAMIE safety/business-rule failure on an otherwise well-formed
    response (e.g. executable content). Never safe to blindly retry the
    same request -- the model produced valid JSON in the right shape but
    the content itself violates HAMIE policy."""


def repair_ai_response(value: dict[str, Any]) -> dict[str, Any]:
    """Apply the one deterministic, zero-guessing repair HAMIE permits on a
    structurally-a-dict AI response: fill any of
    AI_RESPONSE_DEFAULTABLE_ARRAY_FIELDS that are entirely absent with an
    empty list. Never touches a field that is present (even if empty or
    the wrong type -- that is still a genuine validation failure, not a
    repair target), never adds or removes any other key, and never
    fabricates evidence, entities, dependencies, confidence, risks, or
    recommendations. Small local models very commonly omit one of these
    less-intuitive advisory arrays entirely while returning an otherwise
    complete, valid response; before this repair that alone caused a full
    rejection.
    """
    repaired = dict(value)
    for field in AI_RESPONSE_DEFAULTABLE_ARRAY_FIELDS:
        if field not in repaired:
            repaired[field] = []
    for field in AI_RESPONSE_OPTIONAL_NULLABLE_FIELDS:
        if field not in repaired:
            repaired[field] = None
    return repaired


def _strings(value: object, field: str, *, maximum: int = 64) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{field} must be a bounded array")
    if any(
        not isinstance(item, str) or not item.strip() or len(item) > 1_000
        for item in value
    ):
        raise ValueError(f"{field} contains invalid text")
    return tuple(dict.fromkeys(item.strip() for item in value))


def validate_ai_response_schema(value: object) -> dict[str, Any]:
    """Structural/type validation only: exact field set, schema version,
    and per-field types. Raises SchemaValidationError -- never a bare
    ValueError -- with the specific field/reason so a corrective retry can
    tell the model exactly what to fix. Callers should apply
    repair_ai_response() first so a merely-absent optional array never
    reaches here as a schema failure.
    """
    if not isinstance(value, dict):
        raise SchemaValidationError("AI response must be a JSON object")
    actual = set(value)
    if actual != AI_RESPONSE_FIELDS:
        missing = sorted(AI_RESPONSE_FIELDS - actual)
        extra = sorted(actual - AI_RESPONSE_FIELDS)
        detail = "; ".join(
            part
            for part in (
                f"missing: {', '.join(missing)}" if missing else "",
                f"unexpected: {', '.join(extra)}" if extra else "",
            )
            if part
        )
        raise SchemaValidationError(
            f"AI response fields do not match schema version 1 ({detail})",
            field=(missing or extra)[0] if (missing or extra) else None,
        )
    if value["schema_version"] != AI_SCHEMA_VERSION:
        raise SchemaValidationError(
            "unsupported AI response schema version", field="schema_version"
        )
    for field in ("summary", "confidence", "model", "generated_at"):
        if (
            not isinstance(value[field], str)
            or not value[field].strip()
            or len(value[field]) > 4_000
        ):
            raise SchemaValidationError(f"AI response {field} is invalid", field=field)
    if value["confidence"] not in {"low", "medium", "high"}:
        raise SchemaValidationError(
            "AI confidence must be low, medium, or high", field="confidence"
        )
    try:
        generated = datetime.fromisoformat(value["generated_at"])
    except ValueError as err:
        raise SchemaValidationError(
            "AI generated_at is not a valid timestamp", field="generated_at"
        ) from err
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise SchemaValidationError(
            "AI generated_at must be timezone-aware", field="generated_at"
        )
    result: dict[str, Any] = {
        "schema_version": AI_SCHEMA_VERSION,
        "summary": value["summary"].strip(),
        "confidence": value["confidence"],
        "model": value["model"].strip(),
        "generated_at": generated.astimezone(UTC),
    }
    for field in AI_RESPONSE_DEFAULTABLE_ARRAY_FIELDS:
        try:
            result[field] = _strings(value[field], field)
        except ValueError as err:
            raise SchemaValidationError(str(err), field=field) from err
    proposed_action = value["proposed_action"]
    if proposed_action is not None and not isinstance(proposed_action, dict):
        raise SchemaValidationError(
            "AI response proposed_action must be null or an object",
            field="proposed_action",
        )
    if isinstance(proposed_action, dict) and len(proposed_action) > 16:
        raise SchemaValidationError(
            "AI response proposed_action has too many fields",
            field="proposed_action",
        )
    result["proposed_action"] = proposed_action
    return result


def _executable_yaml_key(text: str, markers: tuple[str, ...]) -> str | None:
    """Return the first marker used as a YAML key, or None.

    A YAML key is followed by whitespace or the end of the text. A colon
    immediately followed by a non-space character -- `automation:automation.x`
    -- is HAMIE's own reference notation, not a configuration block.
    """
    for marker in markers:
        for match in re.finditer(re.escape(marker) + r":", text):
            tail = text[match.end() : match.end() + 1]
            if tail == "" or tail.isspace():
                return marker
    return None


def validate_ai_response_semantics(result: dict[str, Any]) -> dict[str, Any]:
    """HAMIE safety/business-rule validation on an already schema-valid
    response. Raises SemanticValidationError, never SchemaValidationError,
    so callers know this is never safe to retry unchanged."""
    # Structural, not substring. HAMIE's OWN evidence uses `<domain>:<entity_id>`
    # reference notation -- a real production payload contained
    # "dependency_references": ["automation:automation.n8n_habit_logger_..."],
    # and the model was then rejected 5/5 for citing the reference it had just
    # been given. Substring matching punished the model for being faithful to
    # the evidence.
    #
    # What the rule is actually for is executable YAML, and in YAML a key is
    # followed by whitespace or a line break:
    #
    #     automation:            <- key, newline follows        REJECTED
    #     service: light.turn_on <- key, space follows          REJECTED
    #     automation:automation.foo  <- reference token         allowed
    #
    # So the marker must be followed by whitespace or end of text. A colon
    # immediately followed by a non-space character is not a YAML key and
    # cannot be a block of executable configuration.
    #
    # This is defence in depth, not the execution boundary: model output is
    # never executed (EXECUTION_TOOLS is empty) and a proposed_action only
    # becomes actionable through deterministic policy in
    # domain/remediation_llm_proposal.py.
    executable_markers = (
        "shell_command",
        "service",
        "target",
        "automation",
        "script",
    )
    proposed_action = result.get("proposed_action")
    proposed_action_text: tuple[str, ...] = ()
    if isinstance(proposed_action, dict):
        reason = proposed_action.get("reason")
        if isinstance(reason, str):
            proposed_action_text = (reason,)
        operation = proposed_action.get("operation")
        if isinstance(operation, dict):
            proposed_action_text = (
                *proposed_action_text,
                *(value for value in operation.values() if isinstance(value, str)),
            )
    all_text = " ".join(
        (
            result["summary"],
            *result["proposed_repair_plan"],
            *result["do_not_do"],
            *proposed_action_text,
        )
    ).casefold()
    offending = _executable_yaml_key(all_text, executable_markers)
    if offending is not None:
        raise SemanticValidationError(
            "AI response contains executable Home Assistant content "
            f"(YAML key {offending!r})"
        )
    return result


def validate_ai_response(value: object) -> dict[str, Any]:
    """Full validation pipeline: deterministic repair, then structural
    schema validation, then semantic/safety validation. Kept as the one
    entry point existing callers and tests already use; new callers that
    need to distinguish a repairable-format failure from a safety
    rejection for retry purposes should call repair_ai_response(),
    validate_ai_response_schema(), and validate_ai_response_semantics()
    directly instead (see connectors/ai_executor.py and connectors/ollama.py).
    """
    repaired = repair_ai_response(value) if isinstance(value, dict) else value
    result = validate_ai_response_schema(repaired)
    return validate_ai_response_semantics(result)


_JSON_PARSE_CORRECTION_HINT = (
    "Your previous response was not valid JSON. Return only corrected JSON "
    "matching HAMIE AI schema version 1, no explanation, no markdown fence."
)


def correction_hint(err: Exception) -> str:
    """One concise, bounded line of machine-generated corrective feedback
    for the single schema-correction retry HAMIE permits (see
    RETRY POLICY). Safe to send instead of the full original context: it
    names exactly what was wrong so the model can return a fix without
    needing the original evidence repeated. Never used for a
    SemanticValidationError -- that stage is not retried at all.

    Callers may pass either the raw SchemaValidationError (the direct
    Ollama connector's own retry loop sees it unwrapped) or an outer
    exception that wraps it via ``raise ... from err`` (AIExecutorError,
    as HomeAssistantAiTaskExecutor's shared executor-error type does) --
    both are checked so the hint is equally specific either way.
    """
    schema_error = err if isinstance(err, SchemaValidationError) else err.__cause__
    if isinstance(schema_error, SchemaValidationError):
        return (
            f"Your previous response was rejected: {schema_error}. Return only "
            "corrected JSON matching HAMIE AI schema version 1 with "
            f"exactly these fields: {', '.join(sorted(AI_RESPONSE_FIELDS))}. "
            "No explanation, no markdown fence."
        )
    return _JSON_PARSE_CORRECTION_HINT
