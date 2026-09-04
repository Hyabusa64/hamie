"""Bounded signed n8n event and inbound-command adapter.

Outbound (HAMIE -> n8n's webhook) and inbound (n8n -> HAMIE's
/api/hamie/n8n) authentication are separate concerns with separate modes
and separate stored credentials -- they are never conflated, and a single
submitted credential value is never silently applied to both directions.

Outbound supports exactly what n8n's webhook trigger natively supports:
an API key (sent as a bearer token), HTTP Basic auth, or no
authentication. Inbound verifies n8n's call back to HAMIE using either a
bearer token or an HMAC shared-secret signature.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from ..domain.common import canonical_json
from .base import (
    ConnectorTestError,
    ConnectorTransport,
    bounded_payload,
    validate_endpoint,
)
from .redaction import redact_payload

ALLOWED_OUTBOUND_EVENTS = frozenset(
    {
        "scan_started",
        "scan_completed",
        "scan_failed",
        "group_created",
        "group_updated",
        "finding_created",
        "finding_updated",
        "finding_resolved",
        "finding_suppressed",
        "review_action",
        "ai_recommendation_created",
        "connector_error",
    }
)

ALLOWED_INBOUND_COMMANDS = frozenset(
    {
        "request_scan",
        "request_group_refresh",
        "acknowledge_group",
        "dismiss_group",
        "snooze_group",
        "retain_group",
        "suppress_group",
        "request_ai_analysis",
    }
)

OUTBOUND_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_type",
        "event_id",
        "timestamp",
        "installation_id",
        "generation",
        "projection_revision",
        "idempotency_key",
        "redacted_payload",
    }
)

OUTBOUND_AUTHENTICATION_MODES = frozenset({"api_key", "username_and_password", "none"})
INBOUND_AUTHENTICATION_MODES = frozenset({"none", "bearer_token", "shared_secret"})

_DNS_FAILURE_MARKERS = (
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "getaddrinfo failed",
)
_CONNECTION_REFUSED_MARKERS = (
    "connection refused",
    "connect call failed",
    "econnrefused",
)


def _classify_transport_exception(err: Exception, prefix: str) -> str:
    """Map an uncaught transport-layer exception to one stable n8n code.

    The shared HTTP transport does not itself distinguish DNS failure
    from connection-refused for exceptions raised inside the underlying
    HTTP client (only its own pre-flight DNS check does, and that is
    already handled by the caller before reaching here) -- this keeps
    that distinction n8n-local instead of changing shared transport
    behavior other connectors depend on.
    """
    text = str(err).casefold()
    name = type(err).__name__.casefold()
    if isinstance(err, ConnectionRefusedError) or any(
        marker in text for marker in _CONNECTION_REFUSED_MARKERS
    ):
        return f"{prefix}_connection_refused"
    if "dns" in name or any(marker in text for marker in _DNS_FAILURE_MARKERS):
        return f"{prefix}_dns_failure"
    return f"{prefix}_unreachable"


def _non_empty_text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 256
    ):
        raise ValueError(f"n8n {field} is invalid")
    return value


def validate_outbound_event(value: object) -> dict[str, Any]:
    """Validate the exact versioned event envelope before delivery."""
    if not isinstance(value, dict) or set(value) != OUTBOUND_EVENT_FIELDS:
        raise ValueError("invalid n8n outbound event schema")
    if (
        value["schema_version"] != 1
        or value["event_type"] not in ALLOWED_OUTBOUND_EVENTS
    ):
        raise ValueError("unsupported n8n outbound event")
    for field in (
        "event_type",
        "event_id",
        "timestamp",
        "installation_id",
        "idempotency_key",
    ):
        _non_empty_text(value[field], field)
    for field in ("generation", "projection_revision"):
        item = value[field]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ValueError(f"n8n {field} is invalid")
    try:
        timestamp = datetime.fromisoformat(value["timestamp"])
    except ValueError as err:
        raise ValueError("n8n timestamp is invalid") from err
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("n8n timestamp must be timezone-aware")
    if not isinstance(value["redacted_payload"], dict):
        raise ValueError("n8n event payload must be an object")
    return value


def _validate_command_payload(command: str, value: object) -> None:
    if not isinstance(value, dict):
        raise ValueError("inbound command payload must be an object")
    if command in {"request_scan", "request_group_refresh"}:
        required: set[str] = set()
    elif command in {"acknowledge_group", "dismiss_group", "retain_group"}:
        required = {"group_id"}
    elif command == "snooze_group":
        required = {"group_id", "snooze_until"}
    elif command == "suppress_group":
        required = {"group_id", "reason"}
    elif command == "request_ai_analysis":
        required = {"finding_ids", "group_ids"}
    else:
        raise PermissionError("inbound command is not allowed")
    if set(value) != required:
        raise ValueError("invalid inbound command payload schema")
    if command == "request_ai_analysis":
        selections = []
        for field in ("finding_ids", "group_ids"):
            item = value[field]
            if not isinstance(item, list) or len(item) > 50:
                raise ValueError("inbound AI selection is outside bounds")
            for member in item:
                selections.append(_non_empty_text(member, field))
        if not 1 <= len(selections) <= 50:
            raise ValueError("inbound AI selection is outside bounds")
        return
    for field in required:
        item = value[field]
        if field.endswith("_ids"):
            if not isinstance(item, list) or not 1 <= len(item) <= 50:
                raise ValueError("inbound AI selection is outside bounds")
            for member in item:
                _non_empty_text(member, field)
        else:
            _non_empty_text(item, field)
    if command == "snooze_group":
        try:
            snooze_until = datetime.fromisoformat(value["snooze_until"])
        except ValueError as err:
            raise ValueError("inbound snooze timestamp is invalid") from err
        if snooze_until.tzinfo is None or snooze_until.utcoffset() is None:
            raise ValueError("inbound snooze timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class N8nConfig:
    """Bounded n8n settings with fully independent outbound/inbound auth.

    ``outbound_webhook_url`` may be an empty string, meaning the user has
    not configured an outbound webhook yet -- this is a legitimate,
    expected state (event delivery and webhook-readiness testing are
    simply unavailable), never treated the same as an invalid URL.
    """

    base_url: str
    outbound_webhook_url: str
    timeout: float
    verify_tls: bool
    selected_events: tuple[str, ...]
    retry_count: int
    retry_backoff: float
    maximum_payload_size: int
    inbound_commands_enabled: bool
    allowed_hosts: tuple[str, ...]
    outbound_authentication_mode: str = "none"
    outbound_api_key: str | None = None
    username: str | None = None
    password: str | None = None
    inbound_authentication_mode: str = "none"
    inbound_bearer_token: str | None = None
    shared_secret: str | None = None

    def __post_init__(self) -> None:
        validate_endpoint(self.base_url, self.allowed_hosts)
        if self.outbound_webhook_url:
            validate_endpoint(self.outbound_webhook_url, self.allowed_hosts)
        if not 1 <= self.timeout <= 60 or not 0 <= self.retry_count <= 3:
            raise ValueError("n8n timeout or retries exceed bounds")
        if any(event not in ALLOWED_OUTBOUND_EVENTS for event in self.selected_events):
            raise ValueError("n8n selected event is not allowed")
        if not 0 <= self.retry_backoff <= 5:
            raise ValueError("n8n retry backoff exceeds bounds")
        if self.outbound_authentication_mode not in OUTBOUND_AUTHENTICATION_MODES:
            raise ValueError("unsupported n8n outbound authentication mode")
        if self.inbound_authentication_mode not in INBOUND_AUTHENTICATION_MODES:
            raise ValueError("unsupported n8n inbound authentication mode")


class N8nConnector:
    connector_id = "n8n"
    capability_mode = "authenticated_hamie_commands"

    def __init__(self, config: N8nConfig, transport: ConnectorTransport) -> None:
        self.config = config
        self._transport = transport
        self._seen_tokens: deque[str] = deque(maxlen=128)
        self._inbound_lock = asyncio.Lock()
        self.closed = False

    def sign(self, payload: dict[str, Any]) -> str:
        """Return the expected inbound HMAC signature for one payload."""
        if not self.config.shared_secret:
            return ""
        return hmac.new(
            self.config.shared_secret.encode(),
            canonical_json(payload).encode(),
            sha256,
        ).hexdigest()

    def _outbound_headers(self) -> dict[str, str]:
        """Build headers for HAMIE's own call to n8n's webhook."""
        headers = {"Content-Type": "application/json"}
        mode = self.config.outbound_authentication_mode
        if mode == "api_key" and self.config.outbound_api_key:
            headers["Authorization"] = f"Bearer {self.config.outbound_api_key}"
        elif (
            mode == "username_and_password"
            and self.config.username
            and self.config.password
        ):
            encoded = base64.b64encode(
                f"{self.config.username}:{self.config.password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {encoded}"
        return headers

    async def async_deliver(self, event: dict[str, Any]) -> None:
        """Deliver one redacted event with finite retries only."""
        validate_outbound_event(event)
        await self._async_post(event)

    async def _async_post(self, event: dict[str, Any]) -> None:
        """Post one bounded redacted payload with finite retries."""
        if self.closed:
            raise RuntimeError("connector is closed")
        if not self.config.outbound_webhook_url:
            raise ConnectorTestError("n8n_webhook_not_configured")
        payload = bounded_payload(
            redact_payload(event), self.config.maximum_payload_size
        )
        headers = self._outbound_headers()
        last_error: Exception | None = None
        for attempt in range(self.config.retry_count + 1):
            try:
                result = await self._transport.async_request_json(
                    method="POST",
                    url=self.config.outbound_webhook_url,
                    payload=payload,
                    headers=headers,
                    timeout=self.config.timeout,
                    verify_tls=self.config.verify_tls,
                )
                if 200 <= result.status < 300:
                    return
                raise RuntimeError(f"n8n returned status {result.status}")
            except Exception as err:
                last_error = err
                if attempt < self.config.retry_count and self.config.retry_backoff:
                    await asyncio.sleep(self.config.retry_backoff * (attempt + 1))
        assert last_error is not None
        raise last_error

    def verify_inbound(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        """Authenticate and validate one fixed HAMIE command envelope."""
        if not self.config.inbound_commands_enabled:
            raise PermissionError("inbound commands are disabled")
        mode = self.config.inbound_authentication_mode
        if mode == "shared_secret" and self.config.shared_secret:
            expected = self.sign(payload)
            provided = headers.get("X-HAMIE-Signature", "")
            authenticated = hmac.compare_digest(expected, provided)
        elif mode == "bearer_token" and self.config.inbound_bearer_token:
            expected_authorization = f"Bearer {self.config.inbound_bearer_token}"
            authenticated = hmac.compare_digest(
                expected_authorization,
                headers.get("Authorization", ""),
            )
        else:
            authenticated = False
        if not authenticated:
            raise PermissionError("invalid inbound authentication")
        required = {
            "schema_version",
            "command",
            "idempotency_token",
            "expected_revision",
            "payload",
        }
        if set(payload) != required or payload["schema_version"] != 1:
            raise ValueError("invalid inbound command schema")
        if payload["command"] not in ALLOWED_INBOUND_COMMANDS:
            raise PermissionError("inbound command is not allowed")
        token = payload["idempotency_token"]
        if not isinstance(token, str) or not token or len(token) > 128:
            raise ValueError("invalid inbound idempotency token")
        if token in self._seen_tokens:
            raise ValueError("inbound command was already accepted")
        revision = payload["expected_revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("inbound command requires expected revision")
        _validate_command_payload(payload["command"], payload["payload"])
        return payload

    def accept_inbound_token(self, token: str) -> None:
        """Record a token only after the command has passed all dispatch checks."""
        if token in self._seen_tokens:
            raise ValueError("inbound command was already accepted")
        self._seen_tokens.append(token)

    async def async_verify_and_reserve_inbound(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
        *,
        current_revision: int,
    ) -> dict[str, Any]:
        """Atomically authenticate, validate, and reserve a replay token."""
        async with self._inbound_lock:
            verified = self.verify_inbound(payload, headers)
            if verified["expected_revision"] != current_revision:
                raise RuntimeError("stale_expected_revision")
            self.accept_inbound_token(verified["idempotency_token"])
            return verified

    async def async_test(self) -> dict[str, Any]:
        """Test n8n base service health and webhook readiness separately.

        Base service health is the authoritative connectivity signal for
        this connector -- it uses the configured Base URL's read-only
        ``/healthz`` endpoint and never depends on the outbound webhook
        being configured. Webhook readiness is reported alongside it but
        never raises on its own: a blank or misconfigured webhook must
        never be indistinguishable from n8n itself being unreachable.
        """
        health = await self.async_test_service_health()
        webhook = await self.async_test_webhook_readiness()
        return {
            "service_health": "healthy",
            "service_latency_ms": health["latency_ms"],
            "webhook_readiness": webhook["status"],
            "webhook_error_code": webhook["error_code"],
        }

    async def async_test_service_health(self) -> dict[str, Any]:
        """Test only the base n8n service via its deterministic health endpoint.

        Never touches the outbound webhook and never requires it to be
        configured -- base service health and webhook readiness are
        independent facts about the connector.
        """
        url = f"{self.config.base_url.rstrip('/')}/healthz"
        try:
            result = await self._transport.async_request_json(
                method="GET",
                url=url,
                payload=None,
                headers={},
                timeout=self.config.timeout,
                verify_tls=self.config.verify_tls,
            )
        except ConnectorTestError as err:
            raise ConnectorTestError(
                "n8n_dns_failure"
                if err.code == "unreachable"
                else "n8n_service_unreachable"
            ) from err
        except TimeoutError as err:
            raise ConnectorTestError("n8n_service_timeout") from err
        except ValueError as err:
            raise ConnectorTestError("n8n_health_invalid_response") from err
        except Exception as err:
            raise ConnectorTestError(
                _classify_transport_exception(err, "n8n_service")
            ) from err
        if result.status == 401:
            raise ConnectorTestError("n8n_authentication_failed")
        if result.status == 403:
            raise ConnectorTestError("n8n_forbidden")
        if not 200 <= result.status < 300:
            raise ConnectorTestError("n8n_health_http_error")
        if not isinstance(result.data, dict):
            raise ConnectorTestError("n8n_health_invalid_response")
        return {"latency_ms": result.latency_ms}

    async def async_test_webhook_readiness(self) -> dict[str, Any]:
        """Check outbound webhook readiness without triggering a workflow.

        Never raises: an unconfigured, unreachable, or ambiguously-answered
        webhook is a distinct, non-fatal fact reported alongside base
        service health, not a connector-test failure by itself.

        Uses a single OPTIONS probe -- n8n webhook trigger nodes only ever
        fire for their one configured HTTP method (GET/POST/etc; OPTIONS is
        never a selectable trigger method), so this never executes the
        production workflow.

        Live-verified against a real n8n instance (2026-07-31): OPTIONS is
        answered generically by n8n's HTTP layer
        before any webhook-routing check -- a registered webhook path and a
        deliberately nonexistent control path both returned a bare 204 with
        no body. A GET to the same two paths, by contrast, correctly
        distinguished them (a specific "webhook ... is not registered" 404
        vs. n8n's own JSON error body), confirming OPTIONS carries no
        information about whether the path is actually registered on this
        n8n version. A successful OPTIONS response is therefore reported as
        ``readiness_unknown``, never ``readiness_confirmed`` -- claiming
        confirmation from a signal proven uninformative would be a false
        positive, not a safety improvement. GET (informative here) and HEAD
        (n8n sends no body for HEAD, which this connector's JSON-only
        response parsing can't interpret either) were both rejected as the
        probe method: GET is a real, commonly-configured n8n trigger method,
        so using it risks executing the production workflow, which this
        check must never do.
        """
        url = self.config.outbound_webhook_url
        not_configured = {
            "status": "not_configured",
            "error_code": "n8n_webhook_not_configured",
        }
        if not url:
            return not_configured
        try:
            validate_endpoint(url, self.config.allowed_hosts)
        except ValueError:
            return not_configured
        headers = self._outbound_headers()
        try:
            result = await self._transport.async_request_json(
                method="OPTIONS",
                url=url,
                payload=None,
                headers=headers,
                timeout=self.config.timeout,
                verify_tls=self.config.verify_tls,
            )
        except ConnectorTestError:
            return {"status": "unreachable", "error_code": "n8n_webhook_unreachable"}
        except TimeoutError:
            return {"status": "timeout", "error_code": "n8n_webhook_timeout"}
        except ValueError:
            # Reached the host but the OPTIONS response body was not valid
            # JSON -- a real, ambiguous answer, not a transport failure.
            return {
                "status": "readiness_unknown",
                "error_code": "n8n_webhook_readiness_unknown",
            }
        except Exception:
            return {"status": "unreachable", "error_code": "n8n_webhook_unreachable"}
        if result.status == 404:
            return {"status": "not_found", "error_code": "n8n_webhook_not_found"}
        if result.status == 401:
            return {
                "status": "authentication_failed",
                "error_code": "n8n_authentication_failed",
            }
        if result.status == 403:
            return {"status": "forbidden", "error_code": "n8n_forbidden"}
        if result.status == 405:
            return {
                "status": "method_not_allowed",
                "error_code": "n8n_webhook_method_not_allowed",
            }
        # A 2xx from OPTIONS is not evidence of registration (see the
        # docstring: live-verified to be unconditional on real n8n), and any
        # other unmapped status is likewise a fact this connector has no
        # confident interpretation for -- neither is proof the webhook is
        # unreachable, so both report readiness_unknown rather than a
        # guessed positive or negative result.
        return {
            "status": "readiness_unknown",
            "error_code": "n8n_webhook_readiness_unknown",
        }

    async def async_close(self) -> None:
        self.closed = True
        self._seen_tokens.clear()
