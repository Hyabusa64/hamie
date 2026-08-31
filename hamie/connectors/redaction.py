"""Recursive connector-boundary redaction."""

from __future__ import annotations

from typing import Any

SECRET_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bearer_token",
        "client_secret",
        "password",
        "refresh_token",
        "secret",
        "shared_secret",
        "token",
    }
)
COORDINATE_KEYS = frozenset(
    {"latitude", "longitude", "gps_accuracy", "location", "coordinates"}
)
MAX_REDACTION_DEPTH = 8
MAX_REDACTION_ITEMS = 256
MAX_REDACTED_STRING = 2_000


def redact_payload(value: Any, *, depth: int = 0) -> Any:
    """Return a bounded JSON-safe value with sensitive material removed."""
    if depth > MAX_REDACTION_DEPTH:
        return "[truncated]"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:MAX_REDACTED_STRING]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= MAX_REDACTION_ITEMS:
                result["_truncated"] = True
                break
            key = str(raw_key)
            lowered = key.casefold()
            if lowered in SECRET_KEYS or lowered in COORDINATE_KEYS:
                result[key] = "[redacted]"
            else:
                result[key] = redact_payload(item, depth=depth + 1)
        return result
    if isinstance(value, list | tuple):
        return [
            redact_payload(item, depth=depth + 1)
            for item in value[:MAX_REDACTION_ITEMS]
        ]
    return "[unsupported]"


def public_options(options: dict[str, Any]) -> dict[str, Any]:
    """Return connector configuration without credentials or precise endpoints."""
    result: dict[str, Any] = {}
    for key, value in options.items():
        lowered = key.casefold()
        if any(token in lowered for token in SECRET_KEYS):
            continue
        if lowered.endswith(("_url", "_endpoint", "_host")):
            result[key] = "[configured]" if value else ""
        else:
            result[key] = redact_payload(value)
    return result
