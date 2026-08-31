"""Periodic connector health heartbeat.

Reuses ConnectorManager.async_test as the sole network probe for every
enabled connector -- this module owns no connector-specific networking of
its own, only the scheduling and the per-connector cancellable listener.
Scheduling is built on Home Assistant's own async_call_later (self-
rescheduled after each probe) rather than a raw asyncio.sleep loop, so it
integrates correctly with HA's real event loop *and* its test harness's
time-travel/cleanup machinery -- a bare `await asyncio.sleep(3600)` task
left running is exactly the kind of dangling background work HA's test
fixtures are built to catch. One listener per enabled connector, staggered
on startup so four connectors never fire their first probe in the same
event-loop tick; each one backs off independently based on
ConnectorManager's own consecutive-failure tracking (see
connectors/health.py), never on state owned here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .manager import ConnectorManager

_LOGGER = logging.getLogger(__name__)

MINIMUM_HEARTBEAT_INTERVAL_SECONDS = 15.0
MAXIMUM_BACKOFF_INTERVAL_SECONDS = 300.0
STARTUP_STAGGER_SECONDS = 2.0


class ConnectorHeartbeat:
    """Own one recurring lightweight health probe per enabled connector."""

    def __init__(
        self,
        hass: Any,
        manager: ConnectorManager,
        *,
        interval_seconds: float = 60.0,
    ) -> None:
        self._hass = hass
        self._manager = manager
        self._interval = max(
            MINIMUM_HEARTBEAT_INTERVAL_SECONDS, float(interval_seconds)
        )
        self._cancels: dict[str, Callable[[], None]] = {}
        self._closed = False

    def async_start(self) -> None:
        """Arm one staggered probe per currently-enabled connector.

        Idempotent: connectors already armed are left alone, so calling
        this again only adds listeners for connectors not yet running.
        """
        if self._closed:
            return
        from homeassistant.helpers.event import async_call_later

        for index, connector_id in enumerate(self._manager.enabled_ids):
            if connector_id in self._cancels:
                continue
            delay = index * STARTUP_STAGGER_SECONDS
            self._cancels[connector_id] = async_call_later(
                self._hass, delay, self._make_tick(connector_id)
            )

    async def async_stop(self) -> None:
        """Cancel every owned listener; safe to call more than once."""
        self._closed = True
        cancels = tuple(self._cancels.values())
        self._cancels.clear()
        for cancel in cancels:
            cancel()

    def _make_tick(self, connector_id: str) -> Callable[[Any], Any]:
        async def _tick(_now: Any) -> None:
            if self._closed:
                return
            try:
                await self._manager.async_test(connector_id)
            except Exception:
                # Failure is already classified and recorded by
                # ConnectorManager._run (HealthCache.failure) and already
                # fanned out via _notify -- the heartbeat itself only
                # needs to keep rescheduling, never log at warning level
                # on every transient network hiccup.
                _LOGGER.debug(
                    "HAMIE connector heartbeat probe failed: connector=%s",
                    connector_id,
                    exc_info=True,
                )
            if self._closed:
                return
            from homeassistant.helpers.event import async_call_later

            self._cancels[connector_id] = async_call_later(
                self._hass,
                self._next_delay(connector_id),
                self._make_tick(connector_id),
            )

        return _tick

    def _next_delay(self, connector_id: str) -> float:
        """Bounded exponential backoff while a connector keeps failing,
        returning immediately to the configured interval on the very next
        success (see HealthCache.success -- consecutive_failures resets to
        zero the moment one probe succeeds).
        """
        consecutive = self._manager.health(connector_id).consecutive_failures
        if consecutive <= 0:
            return self._interval
        return min(MAXIMUM_BACKOFF_INTERVAL_SECONDS, self._interval * (2**consecutive))
