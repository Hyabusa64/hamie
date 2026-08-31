"""Live recorder/statistics adapter for ``domain/temporal_evidence.py``
(mission Part 2b).

Implements ``domain.temporal_evidence.RecorderHistorySourcePort`` --
the gap that module's docstring explicitly left open ("this module
cannot call into that live API... there is no live Home Assistant
Python process available in this task"). That constraint still holds
for *this* module too: nothing here has been executed against a real
``hass`` object, because no live HA process is reachable from this
task (see the mission's absolute constraints -- no valid API/Supervisor
token, docker protection mode deliberately left untouched). What
changed is the scope of the ask: build the adapter correctly against
HA's real, documented recorder API shapes, batched and bounded for a
large (8,000+ entity) installation, so it is ready to drop in the
moment a live process is available -- and be explicit, here and in the
final report, that this is "written correctly against the documented
API, offline" rather than "proven to run inside HA".

**API surface used, and how it was checked**: this installation runs
HA Core ``2026.8.3`` (``ssh ha "cat /config/.HA_VERSION"``, re-verified
this task). No Home Assistant Python source tree is reachable from this
task's SSH session to cross-check exact call signatures against --
this host runs HA OS in a Docker container with protection mode
deliberately left enabled (the mission's own constraint), and no
``site-packages/homeassistant`` tree exists outside that container
(confirmed: ``find / -maxdepth 8 -path '*site-packages/homeassistant*'``
found nothing). The functions below
(``homeassistant.components.recorder.get_instance``,
``.history.get_significant_states``,
``.statistics.statistics_during_period``,
``.statistics.list_statistic_ids``) are Home Assistant's own public,
long-stable recorder API -- unchanged in shape across many releases
before this task's knowledge cutoff -- but their *exact* signature on
2026.8.3 specifically was **not** independently re-verified against
installed source in this task; every call below is written
defensively (keyword arguments only, past a single positional
``hass``/``start_time``, so a shuffled-but-same-named parameter list
still binds correctly; every attribute read off a returned row uses
``getattr(..., None)`` rather than assuming a fixed shape) specifically
to reduce the blast radius of that unverified assumption. This is
flagged, not hidden.

**The one invariant this module enforces on its own, independent of
whatever the live recorder returns**: every blocking call
(``get_significant_states``, ``statistics_during_period``,
``list_statistic_ids`` are all synchronous, DB-querying functions --
never awaitable, never safe to call directly on the event loop) is
dispatched through ``recorder.get_instance(hass).async_add_executor_job``
-- the recorder's *own* single-worker executor, not
``hass.async_add_executor_job``'s shared default pool. This is Home
Assistant's own documented requirement for any recorder-touching code
(enforced in HA core's own test suite via a blocking-call detector) --
using the shared pool instead can interleave with the recorder's own
internal DB writes and corrupt state for a SQLite-backed installation
(this one is external MariaDB, lower risk, but the rule is still
correct to follow so this code is safe on any installation).

**Batched, not per-entity**: for 8,000+ entities, calling either
``get_significant_states`` or ``statistics_during_period`` once per
entity would be 8,000+ blocking DB round-trips serialized through one
executor thread. Both HA functions natively accept a collection of ids
in a single call (``entity_ids=[...]`` / ``statistic_ids=[...]``) --
``async_prime`` below chunks the full entity list into
``BATCH_SIZE``-sized groups and issues one call per chunk, never one
call per entity. ``BATCH_SIZE`` is a deliberately conservative default
(500) chosen to keep each call's SQL ``IN (...)`` clause reasonable
for MariaDB (this installation's recorder backend, confirmed via
``configuration.yaml``'s ``recorder.db_url``) without unbounded-length
query risk; tune per installation if needed.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

_LOGGER = logging.getLogger(__name__)

BATCH_SIZE = 500
# How far back to ask the raw-history API for -- deliberately capped at
# a little over this installation's own purge_keep_days (7, confirmed
# via configuration.yaml) rather than THIRTY_DAYS_SECONDS: asking a
# 7-day-raw-purge installation's recorder for 30 days of raw history
# would just return the same ~7 days of rows it actually has, at 4x
# the query cost for no additional evidence. A different installation
# with longer raw retention would still be served correctly by this
# same window -- ``classify_temporal_evidence`` only ever trusts
# ``raw_history_available_seconds`` for what it actually measures
# (the covered span, computed from the earliest row returned), never
# for what was *asked* for.
RAW_HISTORY_LOOKBACK = timedelta(days=10)
STATISTICS_PERIOD = "day"


@dataclass(frozen=True, slots=True)
class _RawHistoryFacts:
    available_seconds: int | None
    unavailable_seconds: int | None
    contradicting_activity_found: bool


class RecorderStatisticsSource:
    """Batched live recorder/statistics reader, primed once per scan.

    Satisfies ``domain.temporal_evidence.RecorderHistorySourcePort``'s
    per-entity async shape via an internal cache: call ``async_prime``
    once with every entity_id a scan needs evidence for (a handful of
    batched live calls), then the two Protocol methods below become
    pure in-memory dict lookups -- never a second live call per entity.
    Calling either Protocol method for an entity that was never primed
    falls back to a single live (unbatched) call for that one entity,
    logged as a warning, rather than raising or silently returning
    ``None`` -- but a caller scanning many entities should always prime
    first; the fallback exists only for callers with a single ad-hoc
    entity to check.
    """

    def __init__(self, hass: Any) -> None:
        self._hass = hass
        self._raw_cache: dict[str, _RawHistoryFacts] = {}
        self._stats_cache: dict[str, int | None] = {}

    async def async_prime(
        self, entity_ids: Sequence[str], *, now: datetime | None = None
    ) -> None:
        """Batched live fetch for every id in ``entity_ids``.

        Never raises for an individual chunk's failure: each chunk is
        captured defensively (matching this codebase's established
        "every source is captured defensively, capability absence/
        failure is reported honestly, never silently assumed" pattern
        -- see ``infrastructure/dependency_source.py``'s module
        docstring) -- a failed chunk simply leaves those entities
        unprimed, which the per-entity accessors below already handle
        via their documented single-entity fallback.
        """
        observed_at = now or datetime.now(UTC)
        for chunk in _chunk(entity_ids, BATCH_SIZE):
            await self._prime_raw_history_chunk(chunk, observed_at)
            await self._prime_statistics_chunk(chunk, observed_at)

    async def async_raw_history_available_seconds(self, entity_id: str) -> int | None:
        if entity_id not in self._raw_cache:
            _LOGGER.warning(
                "RecorderStatisticsSource: %s was not primed via async_prime(); "
                "falling back to one unbatched live call",
                entity_id,
            )
            await self._prime_raw_history_chunk((entity_id,), datetime.now(UTC))
        facts = self._raw_cache.get(entity_id)
        return facts.available_seconds if facts is not None else None

    async def async_long_term_statistics_unavailable_seconds(
        self, entity_id: str
    ) -> int | None:
        if entity_id not in self._stats_cache:
            _LOGGER.warning(
                "RecorderStatisticsSource: %s was not primed via async_prime(); "
                "falling back to one unbatched live call",
                entity_id,
            )
            await self._prime_statistics_chunk((entity_id,), datetime.now(UTC))
        return self._stats_cache.get(entity_id)

    def raw_unavailable_seconds(self, entity_id: str) -> int | None:
        """Non-Protocol convenience accessor -- how long, within the
        primed raw-history window, this entity has been continuously
        unavailable. Callers assembling a full ``TemporalEvidence``
        need both this and ``async_raw_history_available_seconds``'s
        window length; kept separate from the Protocol (which only
        promises the two methods ``temporal_evidence.py`` actually
        calls) rather than widening that Protocol for one extra field.
        """
        facts = self._raw_cache.get(entity_id)
        return facts.unavailable_seconds if facts is not None else None

    def contradicting_activity_found(self, entity_id: str) -> bool:
        facts = self._raw_cache.get(entity_id)
        return facts.contradicting_activity_found if facts is not None else False

    async def _prime_raw_history_chunk(
        self, entity_ids: Sequence[str], observed_at: datetime
    ) -> None:
        try:
            from homeassistant.components.recorder import get_instance, history
        except ImportError:
            _LOGGER.debug(
                "RecorderStatisticsSource: homeassistant.components.recorder "
                "is not importable in this environment; raw-history evidence "
                "unavailable for %d entities",
                len(entity_ids),
            )
            return
        recorder_instance = get_instance(self._hass)
        start_time = observed_at - RAW_HISTORY_LOOKBACK
        try:
            # get_significant_states (unlike state_changes_during_period,
            # which takes a single entity_id) natively accepts a batch of
            # entity_ids -- the correct call for this many-entity scan.
            result = await recorder_instance.async_add_executor_job(
                lambda: history.get_significant_states(
                    self._hass,
                    start_time,
                    observed_at,
                    entity_ids=list(entity_ids),
                    include_start_time_state=True,
                    significant_changes_only=False,
                    minimal_response=True,
                    no_attributes=True,
                )
            )
        except Exception:  # noqa: BLE001 -- defensive capture, see docstring
            _LOGGER.exception(
                "RecorderStatisticsSource: raw-history fetch failed for a "
                "%d-entity batch",
                len(entity_ids),
            )
            return
        for entity_id in entity_ids:
            states = result.get(entity_id) if result else None
            self._raw_cache[entity_id] = _summarize_raw_history(
                states, observed_at=observed_at, window_start=start_time
            )

    async def _prime_statistics_chunk(
        self, entity_ids: Sequence[str], observed_at: datetime
    ) -> None:
        try:
            from homeassistant.components.recorder import get_instance, statistics
        except ImportError:
            _LOGGER.debug(
                "RecorderStatisticsSource: homeassistant.components.recorder "
                "is not importable in this environment; statistics evidence "
                "unavailable for %d entities",
                len(entity_ids),
            )
            return
        recorder_instance = get_instance(self._hass)
        try:
            # list_statistic_ids first: an entity with no state_class
            # (most non-sensor domains, e.g. every automation/script)
            # has no statistics_meta row at all, and asking
            # statistics_during_period for it anyway is a wasted
            # round-trip repeated for every such entity in the batch.
            known_ids = await recorder_instance.async_add_executor_job(
                lambda: statistics.list_statistic_ids(
                    self._hass, statistic_ids=set(entity_ids)
                )
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "RecorderStatisticsSource: list_statistic_ids failed for a "
                "%d-entity batch",
                len(entity_ids),
            )
            known_ids = None
        statistic_ids_with_coverage = (
            {row.get("statistic_id") for row in known_ids if row.get("statistic_id")}
            if known_ids
            else set(entity_ids)  # unknown -- fall through and let the real query decide
        )
        for entity_id in entity_ids:
            if entity_id not in statistic_ids_with_coverage:
                self._stats_cache[entity_id] = None
        query_ids = statistic_ids_with_coverage & set(entity_ids)
        if not query_ids:
            return
        try:
            stats_result = await recorder_instance.async_add_executor_job(
                lambda: statistics.statistics_during_period(
                    self._hass,
                    observed_at - timedelta(days=400),
                    observed_at,
                    statistic_ids=query_ids,
                    period=STATISTICS_PERIOD,
                    units=None,
                    types={"state", "sum", "mean"},
                )
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "RecorderStatisticsSource: statistics_during_period failed for "
                "a %d-id batch",
                len(query_ids),
            )
            return
        for entity_id in query_ids:
            rows = stats_result.get(entity_id) if stats_result else None
            self._stats_cache[entity_id] = _seconds_since_last_statistics_row(
                rows, observed_at=observed_at
            )


def _chunk(items: Iterable[str], size: int) -> Iterable[tuple[str, ...]]:
    buf: list[str] = []
    for item in items:
        buf.append(item)
        if len(buf) >= size:
            yield tuple(buf)
            buf = []
    if buf:
        yield tuple(buf)


def _summarize_raw_history(
    states: Any, *, observed_at: datetime, window_start: datetime
) -> _RawHistoryFacts:
    """Turn one entity's raw ``get_significant_states`` rows into the
    three facts ``TemporalEvidence`` needs, never assuming a shape.

    ``states`` is HA's list of minimal-response state-like objects for
    one entity, oldest first. Every attribute access is defensive
    (``getattr``/``.get`` with a default) because this task cannot
    confirm the exact row shape 2026.8.3 returns against live source
    (see module docstring) -- an unexpected shape degrades to "no
    evidence" for that entity rather than raising.
    """
    if not states:
        return _RawHistoryFacts(None, None, False)
    try:
        first = states[0]
        first_ts = _row_timestamp(first)
        if first_ts is None:
            return _RawHistoryFacts(None, None, False)
        available_seconds = int((observed_at - max(first_ts, window_start)).total_seconds())
        unavailable_seconds = 0
        contradicting = False
        prior_ts = first_ts
        for row in states:
            ts = _row_timestamp(row) or prior_ts
            state_value = _row_state(row)
            if state_value in ("unavailable", "unknown"):
                unavailable_seconds = int((observed_at - min(ts, prior_ts)).total_seconds())
            elif state_value is not None:
                # A real, non-unavailable state observed inside the
                # window directly contradicts a "continuously
                # unavailable" claim.
                contradicting = True
            prior_ts = ts
        return _RawHistoryFacts(
            available_seconds=max(available_seconds, 0),
            unavailable_seconds=max(min(unavailable_seconds, available_seconds), 0),
            contradicting_activity_found=contradicting,
        )
    except Exception:  # noqa: BLE001 -- see docstring: unexpected shape -> no evidence
        _LOGGER.exception("RecorderStatisticsSource: could not summarize raw history rows")
        return _RawHistoryFacts(None, None, False)


def _row_timestamp(row: Any) -> datetime | None:
    for attr in ("last_changed", "last_updated"):
        value = getattr(row, attr, None) if not isinstance(row, dict) else row.get(attr)
        if isinstance(value, datetime):
            return value
    return None


def _row_state(row: Any) -> str | None:
    if isinstance(row, dict):
        return row.get("state")
    return getattr(row, "state", None)


def _seconds_since_last_statistics_row(rows: Any, *, observed_at: datetime) -> int | None:
    """The longest continuous unavailable span long-term stats confirm.

    A statistics row existing at all means the entity had a real
    ``state_class`` reading at that point; the gap between the *last*
    such row and now is the honest lower bound on how long it has been
    silent since -- never assumed to extend further back than the
    earliest row actually returned.
    """
    if not rows:
        return None
    try:
        last_start: datetime | None = None
        for row in rows:
            start = row.get("start") if isinstance(row, dict) else getattr(row, "start", None)
            if isinstance(start, datetime) and (last_start is None or start > last_start):
                last_start = start
        if last_start is None:
            return None
        seconds = int((observed_at - last_start).total_seconds())
        return max(seconds, 0)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("RecorderStatisticsSource: could not summarize statistics rows")
        return None
