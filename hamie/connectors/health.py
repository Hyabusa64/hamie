"""Finite cached connector health updates."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .base import ConnectorHealth, ConnectorStatus


class HealthCache:
    """Small in-memory health cache with no polling."""

    def __init__(self, values: tuple[ConnectorHealth, ...]) -> None:
        self._values = {item.connector_id: item for item in values}

    def values(self) -> tuple[ConnectorHealth, ...]:
        """Return connector health in stable order."""
        return tuple(self._values[key] for key in sorted(self._values))

    def get(self, connector_id: str) -> ConnectorHealth:
        """Return one cached health record."""
        return self._values[connector_id]

    def success(
        self, connector_id: str, *, at: datetime, latency_ms: int
    ) -> ConnectorHealth:
        """Record one explicit successful operation.

        A single success always fully clears failure history -- consecutive
        failures reset to zero and status returns to HEALTHY regardless of
        how many probes failed before it, so recovery is never delayed
        waiting for some run of consecutive successes.
        """
        value = replace(
            self._values[connector_id],
            status=ConnectorStatus.HEALTHY,
            last_success=at,
            last_attempt=at,
            latency_ms=latency_ms,
            error_code=None,
            consecutive_failures=0,
        )
        self._values[connector_id] = value
        return value

    def failure(
        self, connector_id: str, *, at: datetime, error_code: str
    ) -> ConnectorHealth:
        """Record one explicit failed operation.

        Failure tolerance: a single dropped probe reports DEGRADED, not
        ERROR/Offline -- packets occasionally vanish for reasons that have
        nothing to do with the connector actually being down. Only three
        consecutive failures escalate to ERROR. The failure classification
        (error_code) is always recorded from the first failure onward, so
        an authentication failure is never hidden behind a generic
        "degraded" label merely because it hasn't repeated three times yet.
        """
        previous = self._values[connector_id]
        consecutive = previous.consecutive_failures + 1
        status = ConnectorStatus.ERROR if consecutive >= 3 else ConnectorStatus.DEGRADED
        value = replace(
            previous,
            status=status,
            last_failure=at,
            last_attempt=at,
            error_code=error_code[:128],
            consecutive_failures=consecutive,
        )
        self._values[connector_id] = value
        return value
