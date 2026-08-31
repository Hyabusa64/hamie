"""Finite disabled-by-default connector composition and health manager."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

from ..domain.common import stable_digest
from .ai_executor import (
    AIExecutorError,
    DirectOllamaExecutor,
    HomeAssistantAiTaskExecutor,
)
from .base import (
    MAX_CONNECTOR_QUEUE,
    Connector,
    ConnectorHealth,
    ConnectorStatus,
    ConnectorTransport,
    PipelineFailureSnapshot,
    now_utc,
    pipeline_failure_snapshot,
)
from .health import HealthCache
from .hkg import HkgConfig, HkgConnector
from .mcp import McpConfig, McpConnector
from .n8n import N8nConfig, N8nConnector
from .ollama import OllamaConfig, OllamaConnector
from .redaction import redact_payload

T = TypeVar("T")
StatusListener = Callable[
    [tuple[ConnectorHealth, ...], datetime | None, str | None], None
]

CONNECTOR_IDS = ("ollama", "n8n", "mcp", "hkg")
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "::1")


def _hosts(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return DEFAULT_ALLOWED_HOSTS
    parsed = tuple(item.strip() for item in value.split(",") if item.strip())
    return parsed or DEFAULT_ALLOWED_HOSTS


class ConnectorManager:
    """Own optional connectors with concurrency one and no background work."""

    def __init__(
        self,
        *,
        options: dict[str, Any],
        transport: ConnectorTransport | None = None,
        hass: Any | None = None,
        status_listener: StatusListener | None = None,
        installation_id: str = "hamie",
    ) -> None:
        self._options = dict(options)
        self._hass = hass
        self._status_listener = status_listener
        self._semaphore = asyncio.Semaphore(1)
        self._pending = 0
        self._closed = False
        self._last_ai_analysis: datetime | None = None
        self._last_error: str | None = None
        self._last_pipeline_failure: PipelineFailureSnapshot | None = None
        self._installation_id = installation_id
        self._event_tasks: set[asyncio.Task[None]] = set()
        self._event_results: deque[tuple[str, str, str | None]] = deque(maxlen=32)
        self._event_keys: deque[str] = deque(maxlen=128)
        self._discovered_models: tuple[str, ...] = ()
        enabled = {
            connector_id: bool(options.get(f"{connector_id}_enabled", False))
            for connector_id in CONNECTOR_IDS
        }
        if (
            enabled.get("ollama")
            and options.get("ai_connection_method", "direct") != "direct"
        ):
            # A native Home Assistant AI Task or Conversation entity is
            # selected; HAMIE must never make a direct provider-specific
            # network call in that mode. Native testing/invocation goes
            # through hass.services.async_call, not this connector.
            enabled["ollama"] = False
        if any(enabled.values()) and transport is None:
            if hass is None:
                raise ValueError("enabled connectors require a transport or hass")
            from homeassistant.helpers.aiohttp_client import async_get_clientsession

            from .ha_transport import HomeAssistantHttpTransport

            transport = HomeAssistantHttpTransport(async_get_clientsession(hass))
        self._transport = transport
        self._connectors: dict[str, Connector] = {}
        self._health = HealthCache(
            tuple(
                ConnectorHealth(
                    connector_id=connector_id,
                    enabled=enabled[connector_id],
                    status=(
                        ConnectorStatus.UNKNOWN
                        if enabled[connector_id]
                        else ConnectorStatus.DISABLED
                    ),
                    capability_mode=self._mode(connector_id),
                )
                for connector_id in CONNECTOR_IDS
            )
        )
        if transport is not None:
            if enabled["ollama"]:
                self._connectors["ollama"] = self._build_ollama(transport)
            if enabled["n8n"]:
                self._connectors["n8n"] = self._build_n8n(transport)
            if enabled["mcp"]:
                self._connectors["mcp"] = self._build_mcp(transport)
            if enabled["hkg"]:
                self._connectors["hkg"] = self._build_hkg(transport)
        self._notify()

    @property
    def enabled_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._connectors))

    @property
    def last_ai_analysis(self) -> datetime | None:
        return self._last_ai_analysis

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_pipeline_failure(self) -> PipelineFailureSnapshot | None:
        """Return the exact stage/reason/code of the last failed analysis."""
        return self._last_pipeline_failure

    @property
    def pending(self) -> int:
        return self._pending

    @property
    def ai_connection_method(self) -> str:
        """Return the configured background-analysis provider mode."""
        return str(self._options.get("ai_connection_method", "direct"))

    @property
    def ai_task_entity_id(self) -> str:
        """Return the configured ai_task.* entity, if any."""
        return str(self._options.get("ai_task_entity_id", ""))

    def ai_provider_ready(self, hass: Any = None) -> bool:
        """Return whether the configured AI provider can run analysis now.

        Conversation is deliberately excluded: it is reserved for a future
        interactive assistant, never for background analysis.
        """
        method = self.ai_connection_method
        if method == "ha_ai_task":
            entity_id = self.ai_task_entity_id
            if not entity_id:
                return False
            if hass is None:
                return True
            return hass.states.get(entity_id) is not None
        if method == "direct":
            return "ollama" in self.enabled_ids
        return False

    def public_status(self) -> tuple[dict[str, Any], ...]:
        """Return cached secret-free status only."""
        return tuple(item.public_dict() for item in self._health.values())

    def health(self, connector_id: str) -> ConnectorHealth:
        """Return one connector's current cached health record."""
        return self._health.get(connector_id)

    async def async_test(self, connector_id: str) -> dict[str, Any]:
        """Run one explicit connection test."""
        connector = self._connectors.get(connector_id)
        if connector is None:
            raise ValueError("connector is disabled")
        details = await self._run(connector_id, connector.async_test)
        if (
            connector_id == "ollama"
            and isinstance(details, dict)
            and isinstance(details.get("models"), list)
        ):
            self._discovered_models = tuple(
                str(item) for item in details["models"][:100]
            )
        result = self._health.get(connector_id).public_dict()
        if isinstance(details, dict):
            result["details"] = details
        return result

    @property
    def discovered_models(self) -> tuple[str, ...]:
        """Return the bounded sanitized runtime-only Ollama catalog."""
        return self._discovered_models

    async def async_analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Request one advisory explanation from the primary AI executor.

        Home Assistant AI Task (ai_task.generate_data) is the primary,
        recommended pipeline. Direct Ollama/OpenAI-compatible is kept only
        as an explicitly legacy fallback for the "direct" connection mode.
        Conversation is never used here; it is reserved for a future
        interactive assistant, not background analysis.
        """
        method = self.ai_connection_method
        if method == "ha_ai_task":
            result = await self._async_analyze_via_ai_task(payload)
        elif method == "direct":
            connector = self._connectors.get("ollama")
            if not isinstance(connector, OllamaConnector):
                raise ValueError("LLM connector is disabled")
            executor = DirectOllamaExecutor(connector)
            result = await self._run("ollama", lambda: executor.async_generate(payload))
        else:
            raise AIExecutorError("ai_provider_not_ready")
        self._last_ai_analysis = now_utc()
        self._notify()
        return result

    async def _async_analyze_via_ai_task(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Run one bounded ai_task.generate_data call with concurrency one."""
        entity_id = self.ai_task_entity_id
        if not entity_id or self._hass is None:
            raise AIExecutorError("ai_provider_not_ready")
        if self._pending >= MAX_CONNECTOR_QUEUE:
            raise RuntimeError("connector queue is full")
        self._pending += 1
        self._notify()  # Let subscribers (e.g. buttons) see pending immediately.
        try:
            async with self._semaphore:
                executor = HomeAssistantAiTaskExecutor(
                    self._hass,
                    entity_id,
                    timeout=float(self._options.get("ollama_timeout", 30)),
                    maximum_input_characters=int(
                        self._options.get("ollama_maximum_input_characters", 16_000)
                    ),
                    maximum_output_tokens=int(
                        self._options.get("ollama_maximum_output_tokens", 1_024)
                    ),
                )
                result = await executor.async_generate(payload)
        except Exception as err:
            snapshot = pipeline_failure_snapshot(err)
            self._last_error = snapshot.error_code
            self._last_pipeline_failure = snapshot
            self._notify()
            raise
        else:
            self._last_error = None
            self._last_pipeline_failure = None
            return result
        finally:
            self._pending -= 1

    async def async_investigate(self, system: str, user: str) -> str:
        """Canonical routing for investigation-mode completions.

        Same routing rule as async_analyze(): the connection method decides.
        There is no silent fallback -- if the configured pipeline cannot
        serve a raw investigation completion the caller gets a typed error
        and HAMIE performs no remediation.
        """
        method = self.ai_connection_method
        if method != "direct":
            # AIExecutorError carries a single stable, sanitized code.
            raise AIExecutorError("investigation_requires_direct_provider")
        connector = self._connectors.get("ollama")
        if not isinstance(connector, OllamaConnector):
            raise AIExecutorError("ai_provider_not_ready")
        return await self._run(
            "ollama", lambda: connector.async_investigate(system, user)
        )

    async def async_mcp_evidence(self, subject_ids: tuple[str, ...]) -> dict[str, Any]:
        """Retrieve bounded supplemental read-only dependency evidence."""
        connector = self._connectors.get("mcp")
        if not isinstance(connector, McpConnector):
            raise ValueError("MCP connector is disabled")
        if not subject_ids or len(subject_ids) > 32:
            raise ValueError("MCP evidence subject count exceeds bounds")
        return await self._run(
            "mcp",
            lambda: connector.async_read(
                "read_automation_script_references",
                {"subject_ids": list(subject_ids), "limit": 64},
            ),
        )

    async def async_hkg_relationships(
        self, subject_ids: tuple[str, ...]
    ) -> dict[str, Any]:
        """Query only the bounded HKG subjects selected by local evidence."""
        connector = self._connectors.get("hkg")
        if not isinstance(connector, HkgConnector):
            raise ValueError("HKG connector is disabled")
        return await self._run("hkg", lambda: connector.async_query(subject_ids))

    def connector(self, connector_id: str) -> Connector | None:
        """Return one enabled adapter for internal finite commands."""
        return self._connectors.get(connector_id)

    def schedule_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        generation: int,
        projection_revision: int,
        idempotency_key: str,
    ) -> bool:
        """Schedule one finite selected event without blocking reconciliation."""
        connector = self._connectors.get("n8n")
        if (
            self._closed
            or not isinstance(connector, N8nConnector)
            or event_type not in connector.config.selected_events
        ):
            return False
        if idempotency_key in self._event_keys:
            return False
        if len(self._event_tasks) >= MAX_CONNECTOR_QUEUE:
            self._event_results.append((event_type, "failed", "queue_full"))
            self._health.failure("n8n", at=now_utc(), error_code="queue_full")
            self._notify()
            return False
        self._event_keys.append(idempotency_key)
        timestamp = now_utc()
        event_digest = stable_digest(self._installation_id, event_type, idempotency_key)
        envelope = {
            "schema_version": 1,
            "event_id": f"evt_{event_digest[:24]}",
            "event_type": event_type,
            "timestamp": timestamp.isoformat(),
            "installation_id": self._installation_id,
            "generation": generation,
            "projection_revision": projection_revision,
            "idempotency_key": idempotency_key,
            "redacted_payload": redact_payload(payload),
        }
        task = asyncio.create_task(
            self._async_deliver_event(connector, envelope),
            name=f"hamie_n8n_{event_type}",
        )
        self._event_tasks.add(task)
        task.add_done_callback(self._event_tasks.discard)
        return True

    async def async_drain_events(self) -> tuple[tuple[str, str, str | None], ...]:
        """Wait for currently owned finite deliveries and return bounded outcomes."""
        while self._event_tasks:
            await asyncio.gather(*tuple(self._event_tasks), return_exceptions=True)
        results = tuple(self._event_results)
        self._event_results.clear()
        return results

    async def _async_deliver_event(
        self, connector: N8nConnector, envelope: dict[str, Any]
    ) -> None:
        event_type = str(envelope["event_type"])
        try:
            await self._run("n8n", lambda: connector.async_deliver(envelope))
        except Exception as err:
            self._event_results.append((event_type, "failed", type(err).__name__))
            if event_type != "connector_error":
                self.schedule_event(
                    "connector_error",
                    {
                        "failed_event_id": envelope["event_id"],
                        "failed_event_type": event_type,
                        "error_code": type(err).__name__,
                    },
                    generation=int(envelope["generation"]),
                    projection_revision=int(envelope["projection_revision"]),
                    idempotency_key=f"connector_error:{envelope['event_id']}",
                )
        else:
            self._event_results.append((event_type, "delivered", None))

    async def async_close(self) -> None:
        """Close every enabled adapter; no task or owned session remains."""
        if self._closed:
            return
        self._closed = True
        tasks = tuple(self._event_tasks)
        self._event_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._event_results.clear()
        self._event_keys.clear()
        for connector in tuple(self._connectors.values()):
            await connector.async_close()
        self._connectors.clear()

    async def _run(self, connector_id: str, operation: Callable[[], Awaitable[T]]) -> T:
        if self._closed:
            raise RuntimeError("connector manager is closed")
        if self._pending >= MAX_CONNECTOR_QUEUE:
            raise RuntimeError("connector queue is full")
        self._pending += 1
        started = now_utc()
        try:
            async with self._semaphore:
                result = await operation()
        except Exception as err:
            snapshot = pipeline_failure_snapshot(err)
            self._last_error = snapshot.error_code
            self._last_pipeline_failure = snapshot
            self._health.failure(
                connector_id, at=now_utc(), error_code=snapshot.error_code
            )
            self._notify()
            raise
        else:
            latency = max(0, int((now_utc() - started).total_seconds() * 1_000))
            self._health.success(connector_id, at=now_utc(), latency_ms=latency)
            self._last_error = None
            self._last_pipeline_failure = None
            self._notify()
            return result
        finally:
            self._pending -= 1

    def _mode(self, connector_id: str) -> str:
        defaults = {
            "ollama": "advisory_only",
            "n8n": "authenticated_hamie_commands",
            "mcp": "read_only",
            "hkg": "query_only",
        }
        return str(self._options.get(f"{connector_id}_mode", defaults[connector_id]))

    def _build_ollama(self, transport: ConnectorTransport) -> OllamaConnector:
        options = self._options
        return OllamaConnector(
            OllamaConfig(
                provider_type=str(options.get("ollama_provider_type", "ollama")),
                base_url=str(options.get("ollama_base_url", "http://127.0.0.1:11434")),
                model=str(options.get("ollama_model", "llama3.2")),
                api_key=options.get("ollama_api_key") or None,
                timeout=float(options.get("ollama_timeout", 30)),
                maximum_input_characters=int(
                    options.get("ollama_maximum_input_characters", 16_000)
                ),
                maximum_output_tokens=int(
                    options.get("ollama_maximum_output_tokens", 1_024)
                ),
                temperature=float(options.get("ollama_temperature", 0.2)),
                think=bool(options.get("ollama_think", False)),
                verify_tls=bool(options.get("ollama_verify_tls", True)),
                allowed_hosts=_hosts(options.get("ollama_allowed_hosts")),
                capabilities=tuple(
                    item.strip()
                    for item in str(
                        options.get(
                            "ollama_capabilities",
                            "explain_findings,explain_groups,prioritize,troubleshooting_steps,non_executing_repair_plans",
                        )
                    ).split(",")
                    if item.strip()
                ),
            ),
            transport,
        )

    def _build_n8n(self, transport: ConnectorTransport) -> N8nConnector:
        options = self._options
        base_url = str(options.get("n8n_base_url", "http://127.0.0.1:5678"))
        outbound_mode = str(options.get("n8n_authentication_type", "none"))
        inbound_mode = str(options.get("n8n_inbound_authentication_mode", "none"))
        return N8nConnector(
            N8nConfig(
                base_url=base_url,
                # A blank webhook URL is a legitimate "not configured yet"
                # state, never silently rewritten to a guessed path the
                # user's n8n instance may not actually have registered.
                outbound_webhook_url=str(options.get("n8n_outbound_webhook_url", "")),
                outbound_authentication_mode=outbound_mode,
                outbound_api_key=options.get("n8n_outbound_api_key") or None,
                username=str(options.get("n8n_username", "")) or None,
                password=options.get("n8n_password") or None,
                inbound_authentication_mode=inbound_mode,
                inbound_bearer_token=options.get("n8n_inbound_bearer_token") or None,
                shared_secret=options.get("n8n_shared_secret") or None,
                timeout=float(options.get("n8n_timeout", 15)),
                verify_tls=bool(options.get("n8n_verify_tls", True)),
                selected_events=tuple(
                    item.strip()
                    for item in str(options.get("n8n_selected_events", "")).split(",")
                    if item.strip()
                ),
                retry_count=int(options.get("n8n_retry_count", 1)),
                retry_backoff=float(options.get("n8n_retry_backoff", 0.5)),
                maximum_payload_size=int(
                    options.get("n8n_maximum_payload_size", 32_000)
                ),
                inbound_commands_enabled=bool(
                    options.get("n8n_inbound_commands_enabled", False)
                ),
                allowed_hosts=_hosts(options.get("n8n_allowed_hosts")),
            ),
            transport,
        )

    def _build_mcp(self, transport: ConnectorTransport) -> McpConnector:
        options = self._options
        return McpConnector(
            McpConfig(
                endpoint=str(
                    options.get("mcp_endpoint", "http://127.0.0.1:8124/hamie")
                ),
                authentication=options.get("mcp_authentication") or None,
                timeout=float(options.get("mcp_timeout", 15)),
                verify_tls=bool(options.get("mcp_verify_tls", True)),
                mode=str(options.get("mcp_mode", "read_only")),
                allowed_hosts=_hosts(options.get("mcp_allowed_hosts")),
            ),
            transport,
        )

    def _build_hkg(self, transport: ConnectorTransport) -> HkgConnector:
        options = self._options
        return HkgConnector(
            HkgConfig(
                endpoint=str(
                    options.get("hkg_endpoint", "http://127.0.0.1:8080/query")
                ),
                authentication=options.get("hkg_authentication") or None,
                timeout=float(options.get("hkg_timeout", 15)),
                verify_tls=bool(options.get("hkg_verify_tls", True)),
                mode=str(options.get("hkg_mode", "query_only")),
                allowed_hosts=_hosts(options.get("hkg_allowed_hosts")),
                maximum_subjects=int(options.get("hkg_maximum_subjects", 32)),
                maximum_relationships=int(options.get("hkg_maximum_relationships", 64)),
                cache_duration=int(options.get("hkg_cache_duration", 0)),
            ),
            transport,
        )

    def _notify(self) -> None:
        if self._status_listener is not None:
            self._status_listener(
                self._health.values(), self._last_ai_analysis, self._last_error
            )
