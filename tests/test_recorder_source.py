"""Tests for infrastructure/recorder_source.py's pure-logic helpers
(mission Part 2b).

``RecorderStatisticsSource`` itself cannot be exercised end-to-end
here -- it requires a live ``hass``/``homeassistant.components.recorder``
process this task never has access to (see the module's own docstring
for the full explanation and what *was* verified: real recorder data,
pulled read-only via the ``mysql``/``mariadb`` CLI, feeding
``domain/temporal_evidence.py``'s classification logic directly --
that validation lives in
``benchmark/validate_temporal_evidence_offline.py``, not here).

What *is* fully offline-testable, and covered below: the three pure
functions that turn already-fetched row data into ``TemporalEvidence``
inputs (``_summarize_raw_history``, ``_seconds_since_last_statistics_row``,
``_chunk``) -- none of them import or require ``homeassistant`` at all,
so their row-shape-handling logic (including the defensive
"unexpected shape -> no evidence, never raise" fallback) is exercised
against realistic fakes standing in for HA's row objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from hamie.infrastructure.recorder_source import (
    _chunk,
    _seconds_since_last_statistics_row,
    _summarize_raw_history,
)

NOW = datetime(2026, 8, 24, 3, 30, tzinfo=UTC)


@dataclass
class _FakeState:
    state: str
    last_changed: datetime
    last_updated: datetime


def test_chunk_splits_into_fixed_size_groups() -> None:
    items = [f"e{i}" for i in range(11)]
    chunks = list(_chunk(items, 4))
    assert chunks == [
        ("e0", "e1", "e2", "e3"),
        ("e4", "e5", "e6", "e7"),
        ("e8", "e9", "e10"),
    ]


def test_chunk_empty_input_yields_nothing() -> None:
    assert list(_chunk([], 4)) == []


def test_summarize_raw_history_all_unavailable_no_contradiction() -> None:
    window_start = NOW - timedelta(days=10)
    states = [
        _FakeState("unavailable", NOW - timedelta(days=6), NOW - timedelta(days=6)),
        _FakeState("unavailable", NOW - timedelta(days=3), NOW - timedelta(days=3)),
    ]
    facts = _summarize_raw_history(states, observed_at=NOW, window_start=window_start)
    assert facts.contradicting_activity_found is False
    assert facts.available_seconds is not None and facts.available_seconds > 0
    assert facts.unavailable_seconds is not None and facts.unavailable_seconds > 0
    # Structural invariant TemporalEvidence itself also enforces --
    # this producer must never violate it.
    assert facts.unavailable_seconds <= facts.available_seconds


def test_summarize_raw_history_real_activity_sets_contradiction() -> None:
    window_start = NOW - timedelta(days=10)
    states = [
        _FakeState("unavailable", NOW - timedelta(days=6), NOW - timedelta(days=6)),
        _FakeState("on", NOW - timedelta(hours=2), NOW - timedelta(hours=2)),
    ]
    facts = _summarize_raw_history(states, observed_at=NOW, window_start=window_start)
    assert facts.contradicting_activity_found is True


def test_summarize_raw_history_empty_rows_is_no_evidence() -> None:
    facts = _summarize_raw_history(None, observed_at=NOW, window_start=NOW - timedelta(days=1))
    assert facts.available_seconds is None
    assert facts.unavailable_seconds is None
    assert facts.contradicting_activity_found is False


def test_summarize_raw_history_unexpected_shape_degrades_gracefully() -> None:
    # A row with no timestamp attribute at all -- the module's own
    # documented "unexpected shape -> no evidence, never raise" rule.
    facts = _summarize_raw_history(
        [object()], observed_at=NOW, window_start=NOW - timedelta(days=1)
    )
    assert facts.available_seconds is None
    assert facts.contradicting_activity_found is False


def test_seconds_since_last_statistics_row_uses_latest_start() -> None:
    rows = [
        {"start": NOW - timedelta(days=90), "state": 1.0},
        {"start": NOW - timedelta(days=45), "state": 1.0},
        {"start": NOW - timedelta(days=45.5), "state": 1.0},  # out of order on purpose
    ]
    seconds = _seconds_since_last_statistics_row(rows, observed_at=NOW)
    assert seconds is not None
    expected = int(timedelta(days=45).total_seconds())
    assert abs(seconds - expected) < 5


def test_seconds_since_last_statistics_row_no_rows_is_none() -> None:
    assert _seconds_since_last_statistics_row([], observed_at=NOW) is None
    assert _seconds_since_last_statistics_row(None, observed_at=NOW) is None


def test_seconds_since_last_statistics_row_unexpected_shape_degrades_gracefully() -> None:
    assert _seconds_since_last_statistics_row([object()], observed_at=NOW) is None
