"""Configurable automatic scan scheduling.

Reuses ScanCoordinator.async_request_scan (trigger="scheduled") as the only
entry point into scanning -- this module owns no capture/analysis/persist
logic of its own, only the interval timer and one cancellable listener.
ScanCoordinator's own asyncio.Lock/coalescing already guarantees a scheduled
scan can never overlap a manual (or another scheduled) scan; this scheduler
does not duplicate that guard, it relies on it.

Scheduling is built on Home Assistant's own async_call_later (self-
rescheduled after each scan attempt) rather than a raw asyncio.sleep loop,
so it integrates correctly with HA's real event loop *and* its test
harness's time-travel/cleanup machinery -- a bare long-lived
`await asyncio.sleep(3600)` task is exactly the kind of dangling background
work HA's test fixtures are built to catch.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .runtime_projection import RuntimeProjection
from .scan_coordinator import ScanCoordinator

_LOGGER = logging.getLogger(__name__)

MINIMUM_INTERVAL_SECONDS = 15 * 60.0


class ScanScheduler:
    """Own one recurring "scheduled" scan trigger for one config entry."""

    def __init__(
        self,
        hass: Any,
        coordinator: ScanCoordinator,
        projection: RuntimeProjection,
        *,
        interval_seconds: float = 3_600.0,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._projection = projection
        self._interval = max(MINIMUM_INTERVAL_SECONDS, float(interval_seconds))
        self._cancel: Callable[[], None] | None = None
        self._closed = False

    def async_start(self) -> None:
        """Arm the recurring scan listener, resuming the configured
        cadence from whenever the last successful scan actually completed
        rather than blindly rescanning on every restart.
        """
        if self._closed or self._cancel is not None:
            return
        from homeassistant.helpers.event import async_call_later

        self._cancel = async_call_later(self._hass, self._initial_delay(), self._tick)

    async def async_stop(self) -> None:
        """Cancel the owned listener; safe to call more than once."""
        self._closed = True
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    def _initial_delay(self) -> float:
        """Resume the configured cadence from the last successful scan
        instead of blindly rescanning on every restart.
        """
        completed = self._projection.snapshot.scan_completed
        if completed is None:
            return self._interval
        elapsed = (datetime.now(UTC) - completed).total_seconds()
        return max(0.0, self._interval - elapsed)

    async def _tick(self, _now: Any) -> None:
        if self._closed:
            return
        try:
            await self._coordinator.async_request_scan(trigger="scheduled")
        except Exception:
            # A failed scheduled scan must never crash the scheduler or
            # take down previously-persisted results -- the scan
            # coordinator/projection already retain the last successful
            # state; this listener only needs to try again next interval.
            _LOGGER.warning(
                "HAMIE scheduled scan failed; retaining previous results",
                exc_info=True,
            )
        if self._closed:
            return
        from homeassistant.helpers.event import async_call_later

        self._cancel = async_call_later(self._hass, self._interval, self._tick)
