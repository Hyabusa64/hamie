"""Strict read-only Home Assistant MCP capability adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ConnectorTransport, validate_endpoint
from .redaction import redact_payload

ALLOWED_CAPABILITIES = frozenset(
    {
        "read_entity_metadata",
        "read_device_metadata",
        "read_integration_metadata",
        "read_automation_script_references",
        "read_dashboard_references",
        "read_configuration_validation_status",
        "request_hamie_scan",
        "retrieve_hamie_findings",
        "retrieve_hamie_groups",
    }
)
FORBIDDEN_MARKERS = frozenset(
    {
        "delete",
        "disable",
        "execute_service",
        "shell",
        "write_file",
        "write_registry",
        "write_yaml",
        "update_automation",
        "update_dashboard",
    }
)


@dataclass(frozen=True, slots=True)
class McpConfig:
    endpoint: str
    authentication: str | None
    timeout: float
    verify_tls: bool
    mode: str
    allowed_hosts: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.mode != "read_only":
            raise ValueError("only MCP read_only mode is implemented")
        if not 1 <= self.timeout <= 60:
            raise ValueError("MCP timeout exceeds bounds")
        validate_endpoint(self.endpoint, self.allowed_hosts)


class McpConnector:
    connector_id = "mcp"

    def __init__(self, config: McpConfig, transport: ConnectorTransport) -> None:
        self.config = config
        self.capability_mode = config.mode
        self._transport = transport
        self.closed = False

    @staticmethod
    def validate_capability(name: str) -> str:
        """Allow only fixed read and HAMIE-local capability names."""
        lowered = name.casefold()
        if name not in ALLOWED_CAPABILITIES or any(
            marker in lowered for marker in FORBIDDEN_MARKERS
        ):
            raise PermissionError("MCP capability is not allowed")
        return name

    async def async_read(
        self, capability: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Invoke one allowed supplemental evidence operation."""
        self.validate_capability(capability)
        headers = {"Content-Type": "application/json"}
        if self.config.authentication:
            headers["Authorization"] = f"Bearer {self.config.authentication}"
        result = await self._transport.async_request_json(
            method="POST",
            url=validate_endpoint(self.config.endpoint, self.config.allowed_hosts),
            payload={
                "schema_version": 1,
                "capability": capability,
                "payload": redact_payload(payload),
            },
            headers=headers,
            timeout=self.config.timeout,
            verify_tls=self.config.verify_tls,
        )
        if not 200 <= result.status < 300 or not isinstance(result.data, dict):
            raise RuntimeError("MCP request failed")
        return redact_payload(result.data)

    async def async_test(self) -> dict[str, Any]:
        """Discover and classify a bounded public capability name list."""
        headers = {"Content-Type": "application/json"}
        if self.config.authentication:
            headers["Authorization"] = f"Bearer {self.config.authentication}"
        result = await self._transport.async_request_json(
            method="POST",
            url=validate_endpoint(self.config.endpoint, self.config.allowed_hosts),
            payload={"schema_version": 1, "operation": "discover_capabilities"},
            headers=headers,
            timeout=self.config.timeout,
            verify_tls=self.config.verify_tls,
        )
        if not 200 <= result.status < 300 or not isinstance(result.data, dict):
            raise RuntimeError("MCP capability discovery failed")
        capabilities = result.data.get("capabilities")
        if (
            not isinstance(capabilities, list)
            or len(capabilities) > 64
            or any(
                not isinstance(item, str) or not item or len(item) > 128
                for item in capabilities
            )
        ):
            raise ValueError("MCP capability discovery response is invalid")
        names = tuple(sorted(set(capabilities)))
        accepted = tuple(name for name in names if name in ALLOWED_CAPABILITIES)
        rejected = tuple(name for name in names if name not in ALLOWED_CAPABILITIES)
        return {
            "accepted_capabilities": accepted,
            "rejected_capabilities": rejected,
        }

    async def async_close(self) -> None:
        self.closed = True
