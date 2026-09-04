"""Bounded House Knowledge Graph query-only enrichment adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Any

from .base import ConnectorTransport, validate_endpoint
from .redaction import redact_payload

MAX_HKG_RELATIONSHIPS = 64
SUPPORTED_RELATIONSHIP_TYPES = frozenset(
    {
        "n8n_workflow_reference",
        "house_scorecard_dependency",
        "battery_intelligence_dependency",
        "ai_project_dependency",
        "historical_alias",
        "renamed_object",
        "object_ownership",
        "object_purpose",
        "family_impact",
    }
)


@dataclass(frozen=True, slots=True)
class HkgConfig:
    endpoint: str
    authentication: str | None
    timeout: float
    verify_tls: bool
    mode: str
    allowed_hosts: tuple[str, ...]
    maximum_subjects: int = 32
    maximum_relationships: int = MAX_HKG_RELATIONSHIPS
    cache_duration: int = 0

    def __post_init__(self) -> None:
        if self.mode != "query_only":
            raise ValueError("only HKG query_only mode is implemented")
        if not 1 <= self.timeout <= 60:
            raise ValueError("HKG timeout exceeds bounds")
        if not 1 <= self.maximum_subjects <= 32:
            raise ValueError("HKG subject limit exceeds bounds")
        if not 1 <= self.maximum_relationships <= MAX_HKG_RELATIONSHIPS:
            raise ValueError("HKG relationship limit exceeds bounds")
        if not 0 <= self.cache_duration <= 3_600:
            raise ValueError("HKG cache duration exceeds bounds")
        validate_endpoint(self.endpoint, self.allowed_hosts)


class HkgConnector:
    connector_id = "hkg"

    def __init__(self, config: HkgConfig, transport: ConnectorTransport) -> None:
        self.config = config
        self.capability_mode = config.mode
        self._transport = transport
        self._cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
        self.closed = False

    async def async_query(self, subject_ids: tuple[str, ...]) -> dict[str, Any]:
        """Query a bounded subset; never download the full graph."""
        if not subject_ids or len(subject_ids) > self.config.maximum_subjects:
            raise ValueError("HKG query subject count exceeds bounds")
        cache_key = tuple(sorted(subject_ids))
        cached = self._cache.get(cache_key)
        if cached is not None and monotonic() - cached[0] <= self.config.cache_duration:
            return dict(cached[1])
        headers = {"Content-Type": "application/json"}
        if self.config.authentication:
            headers["Authorization"] = f"Bearer {self.config.authentication}"
        result = await self._transport.async_request_json(
            method="POST",
            url=validate_endpoint(self.config.endpoint, self.config.allowed_hosts),
            payload={
                "schema_version": 1,
                "operation": "bounded_relationship_query",
                "subject_ids": list(subject_ids),
                "limit": self.config.maximum_relationships,
            },
            headers=headers,
            timeout=self.config.timeout,
            verify_tls=self.config.verify_tls,
        )
        if not 200 <= result.status < 300 or not isinstance(result.data, dict):
            raise RuntimeError("HKG query failed")
        relationships = result.data.get("relationships", [])
        if not isinstance(relationships, list):
            raise ValueError("HKG relationships must be an array")
        accepted = []
        for item in relationships[: self.config.maximum_relationships]:
            if not isinstance(item, dict):
                continue
            required = {
                "source_id",
                "target_id",
                "relationship_type",
                "source_revision",
                "confidence",
                "verified_at",
                "stale",
            }
            if (
                not required <= set(item)
                or item["relationship_type"] not in SUPPORTED_RELATIONSHIP_TYPES
                or not isinstance(item["stale"], bool)
                or item["confidence"] not in {"low", "medium", "high"}
                or any(
                    not isinstance(item[field], str)
                    or not item[field]
                    or len(item[field]) > 256
                    for field in required - {"stale"}
                )
            ):
                continue
            try:
                verified_at = datetime.fromisoformat(item["verified_at"])
            except ValueError:
                continue
            if verified_at.tzinfo is None or verified_at.utcoffset() is None:
                continue
            accepted.append(
                redact_payload(
                    {
                        **{key: item[key] for key in required},
                        "source": "hkg",
                    }
                )
            )
        response = {
            "coverage": "partial",
            "authoritative_source": "home_assistant",
            "relationships": accepted,
            "truncated": len(relationships) > self.config.maximum_relationships,
        }
        if self.config.cache_duration:
            if len(self._cache) >= 8:
                self._cache.clear()
            self._cache[cache_key] = (monotonic(), response)
        return dict(response)

    async def async_test(self) -> None:
        await self.async_query(("hamie:connection_test",))

    async def async_close(self) -> None:
        self._cache.clear()
        self.closed = True
