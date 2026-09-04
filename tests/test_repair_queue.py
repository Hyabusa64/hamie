"""The repair queue must turn a large findings/incident set into a small,
honestly-tiered "worth fixing now" list -- never inflate what's actually
actionable to make the queue look more useful than it is.
"""

from __future__ import annotations

import pytest

from hamie.domain.repair_queue import (
    RepairQueueEntry,
    RepairTier,
    rank_queue,
    top_recommendations,
)


def _entry(**overrides) -> RepairQueueEntry:
    defaults = dict(
        incident_id="inc_1",
        disposition="repair_candidate",
        priority="p1",
        root_cause="stale entity reference",
        confidence=0.9,
        risk="config_mutation",
    )
    defaults.update(overrides)
    return RepairQueueEntry(**defaults)


def test_rejects_an_unrecognised_disposition() -> None:
    with pytest.raises(ValueError):
        _entry(disposition="made_up_disposition")


def test_rejects_confidence_outside_zero_to_one() -> None:
    with pytest.raises(ValueError):
        _entry(confidence=1.5)
    with pytest.raises(ValueError):
        _entry(confidence=-0.1)


@pytest.mark.parametrize(
    ("disposition", "expected_tier"),
    [
        ("repair_candidate", RepairTier.READY_TO_APPROVE),
        ("operator_decision_required", RepairTier.NEEDS_A_DECISION),
        ("insufficient_evidence", RepairTier.NOT_YET_ACTIONABLE),
        ("external_action_required", RepairTier.NOT_YET_ACTIONABLE),
        ("blocked", RepairTier.NOT_HAMIES_TO_FIX),
        ("no_action", RepairTier.NOT_HAMIES_TO_FIX),
    ],
)
def test_every_disposition_maps_to_a_tier(disposition: str, expected_tier: RepairTier) -> None:
    assert _entry(disposition=disposition).tier is expected_tier


def test_rank_queue_orders_ready_to_approve_before_needs_a_decision() -> None:
    ready = _entry(incident_id="a", disposition="repair_candidate", priority="p3")
    decision = _entry(incident_id="b", disposition="operator_decision_required", priority="p0")
    ranked = rank_queue((decision, ready))
    # Tier outranks priority: a lower-priority repair_candidate still
    # comes before a higher-priority operator-decision item, because it
    # is strictly more actionable right now.
    assert ranked[0].incident_id == "a"


def test_rank_queue_orders_by_priority_within_a_tier() -> None:
    p2 = _entry(incident_id="a", priority="p2")
    p0 = _entry(incident_id="b", priority="p0")
    ranked = rank_queue((p2, p0))
    assert [e.incident_id for e in ranked] == ["b", "a"]


def test_rank_queue_orders_by_confidence_within_tier_and_priority() -> None:
    low = _entry(incident_id="a", confidence=0.3)
    high = _entry(incident_id="b", confidence=0.95)
    ranked = rank_queue((low, high))
    assert [e.incident_id for e in ranked] == ["b", "a"]


def test_unrecognised_priority_is_never_sorted_to_the_very_bottom_silently() -> None:
    """A labeling gap must not hide an incident below even 'info'
    priority items -- it is treated as at least as urgent as the worst
    known priority.
    """
    unknown_priority = _entry(incident_id="a", priority="p99")
    info = _entry(incident_id="b", priority="info")
    ranked = rank_queue((info, unknown_priority))
    assert ranked.index(unknown_priority) <= ranked.index(info)


def test_top_recommendations_never_includes_non_actionable_tiers() -> None:
    entries = (
        _entry(incident_id="ready", disposition="repair_candidate"),
        _entry(incident_id="decision", disposition="operator_decision_required"),
        _entry(incident_id="insufficient", disposition="insufficient_evidence"),
        _entry(incident_id="blocked", disposition="blocked"),
    )
    top = top_recommendations(entries, limit=10)
    assert {e.incident_id for e in top} == {"ready", "decision"}


def test_top_recommendations_respects_the_limit() -> None:
    entries = tuple(
        _entry(incident_id=f"inc_{i}", disposition="repair_candidate") for i in range(20)
    )
    assert len(top_recommendations(entries, limit=6)) == 6


def test_top_recommendations_rejects_a_limit_below_one() -> None:
    with pytest.raises(ValueError):
        top_recommendations((), limit=0)


def test_top_recommendations_on_a_realistic_mixed_set_surfaces_the_right_six() -> None:
    """Mirrors the real production shape this module exists for: a large
    set dominated by non-actionable items, with a handful genuinely
    worth surfacing.
    """
    noise = tuple(
        _entry(incident_id=f"noise_{i}", disposition="insufficient_evidence", priority="p3")
        for i in range(50)
    )
    actionable = (
        _entry(incident_id="fix_1", disposition="repair_candidate", priority="p0", confidence=0.95),
        _entry(incident_id="fix_2", disposition="repair_candidate", priority="p1", confidence=0.8),
        _entry(incident_id="decide_1", disposition="operator_decision_required", priority="p0"),
    )
    top = top_recommendations(noise + actionable, limit=6)
    assert [e.incident_id for e in top] == ["fix_1", "fix_2", "decide_1"]


def test_stable_order_among_exact_ties_uses_incident_id() -> None:
    a = _entry(incident_id="b")
    b = _entry(incident_id="a")
    ranked = rank_queue((a, b))
    assert [e.incident_id for e in ranked] == ["a", "b"]
