"""Tests for domain/temporal_evidence.py (mission Part 3d/5).

The single required guarantee: a 7-day (or any sub-30-day) raw
recorder window must never, under any combination of inputs, produce
CONFIRMED_UNAVAILABLE_GT_30D.
"""

from __future__ import annotations

import pytest

from hamie.domain.temporal_evidence import (
    THIRTY_DAYS_SECONDS,
    TemporalEvidence,
    TemporalEvidenceStatus,
    classify_temporal_evidence,
)

SEVEN_DAYS = 7 * 24 * 3600


def test_seven_day_window_never_confirms_thirty_days() -> None:
    evidence = TemporalEvidence(
        raw_history_available_seconds=SEVEN_DAYS,
        raw_unavailable_seconds=SEVEN_DAYS,
    )
    assert (
        classify_temporal_evidence(evidence)
        is TemporalEvidenceStatus.INSUFFICIENT_HISTORY_TO_PROVE_30D
    )


@pytest.mark.parametrize("window_seconds", [1, 3600, SEVEN_DAYS, THIRTY_DAYS_SECONDS - 1])
def test_any_sub_threshold_raw_window_is_insufficient(window_seconds: int) -> None:
    evidence = TemporalEvidence(
        raw_history_available_seconds=window_seconds,
        raw_unavailable_seconds=window_seconds,
    )
    assert (
        classify_temporal_evidence(evidence)
        is TemporalEvidenceStatus.INSUFFICIENT_HISTORY_TO_PROVE_30D
    )


def test_long_term_statistics_can_confirm_beyond_raw_window() -> None:
    evidence = TemporalEvidence(
        raw_history_available_seconds=SEVEN_DAYS,
        raw_unavailable_seconds=SEVEN_DAYS,
        long_term_statistics_confirm_unavailable_seconds=45 * 24 * 3600,
    )
    assert (
        classify_temporal_evidence(evidence)
        is TemporalEvidenceStatus.CONFIRMED_UNAVAILABLE_GT_30D
    )


def test_long_term_statistics_below_threshold_still_insufficient() -> None:
    evidence = TemporalEvidence(
        long_term_statistics_confirm_unavailable_seconds=THIRTY_DAYS_SECONDS - 1
    )
    assert (
        classify_temporal_evidence(evidence)
        is TemporalEvidenceStatus.INSUFFICIENT_HISTORY_TO_PROVE_30D
    )


def test_contradicting_activity_overrides_everything() -> None:
    evidence = TemporalEvidence(
        long_term_statistics_confirm_unavailable_seconds=90 * 24 * 3600,
        contradicting_activity_found=True,
    )
    assert classify_temporal_evidence(evidence) is TemporalEvidenceStatus.CONTRADICTORY_EVIDENCE


def test_not_applicable_short_circuits() -> None:
    assert (
        classify_temporal_evidence(TemporalEvidence(), applicable=False)
        is TemporalEvidenceStatus.NOT_APPLICABLE
    )


def test_no_evidence_at_all_is_insufficient() -> None:
    assert (
        classify_temporal_evidence(TemporalEvidence())
        is TemporalEvidenceStatus.INSUFFICIENT_HISTORY_TO_PROVE_30D
    )


def test_unavailable_cannot_exceed_available_window() -> None:
    with pytest.raises(ValueError):
        TemporalEvidence(
            raw_history_available_seconds=SEVEN_DAYS,
            raw_unavailable_seconds=THIRTY_DAYS_SECONDS,
        )


def test_negative_seconds_rejected() -> None:
    with pytest.raises(ValueError):
        TemporalEvidence(raw_history_available_seconds=-1)
