"""Shared deterministic domain utilities."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

_SECRET_VALUE_PATTERN = re.compile(
    r"(password|secret|token|api[_-]?key|authorization)\s*[:=]\s*\S+"
    r"|bearer\s+\S+",
    re.IGNORECASE,
)

#: Same connection-URI-embedded-credential shape
#: ``tools/secret_scan.py``'s ``connection_uri_credential`` rule detects
#: in tracked files. Duplicated here (not imported) deliberately: ``tools/``
#: is a dev-only directory outside ``hamie/build_deploy.py``'s package
#: scope and must never become a runtime dependency of the shipped
#: integration. A database connection string's own credential has no
#: ``key: value`` boundary right at the secret the way
#: ``_SECRET_VALUE_PATTERN`` expects -- the username and password sit
#: directly ahead of the host, joined by a colon, with no recognizable
#: key name at all -- so it needed its own pattern, found by testing
#: this exact gap while building the repair-orchestration escalation
#: packet (an artifact meant to be pasted somewhere external, where this
#: gap would otherwise leak a
#: real credential).
_CONNECTION_URI_CREDENTIAL_PATTERN = re.compile(
    r"\b(?:mysql|mariadb|postgres(?:ql)?|mongodb(?:\+srv)?|redis|amqp|"
    r"mssql|oracle|sqlite\+\w+|mysql\+\w+|postgresql\+\w+)"
    r"://[^:/@\s]+:(?!\s*!secret\b)[^@/\s]+@[^\s/]+",
    re.IGNORECASE,
)


def redact_secret_looking_text(value: str | None) -> str | None:
    """Best-effort redaction for freeform diagnostic/log-adjacent text.

    Shared implementation of the same pattern
    ``domain/remediation_execution.py``'s adapter-error redaction
    established: deliberately narrower than a bare substring check on
    words like "token" (this codebase's own idempotency/replay
    machinery uses "token" as an ordinary identifier name in legitimate,
    non-secret text). A recognized secret keyword immediately followed by
    ``key=value``/``key: value`` syntax, a bare ``Bearer <value>``, or a
    database/queue connection URI with a live embedded password
    (``!secret``-referenced or credential-free URIs are left alone, same
    as ``tools/secret_scan.py``) is treated as an actual embedded secret.
    """
    if value is None:
        return None
    if _SECRET_VALUE_PATTERN.search(value) or _CONNECTION_URI_CREDENTIAL_PATTERN.search(value):
        return "[redacted: error text withheld, may contain sensitive data]"
    return value


def require_utc(value: datetime, field_name: str) -> datetime:
    """Validate and normalize a timezone-aware timestamp to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def canonical_json(value: Any) -> str:
    """Serialize a bounded JSON value deterministically."""
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as err:
        raise ValueError("value must be JSON-representable") from err


def stable_digest(*parts: object) -> str:
    """Return a version-independent SHA-256 digest for semantic parts."""
    encoded = canonical_json([str(part) for part in parts]).encode()
    return hashlib.sha256(encoded).hexdigest()


def require_non_empty(value: str, field_name: str) -> str:
    """Reject empty or surrounding-whitespace string values."""
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty normalized string")
    return value
