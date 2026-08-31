"""Regression tests for the production capture-layer fix that let
disabled-entity duplicate/migration-leftover siblings reach analysis.

Root cause (see ``hamie/infrastructure/ha_source.py``'s
``HomeAssistantOperationalSource._records``/``_record`` docstrings for
the full account): the capture layer only ever built an ``EntityRecord``
for an entity present in ``hass.states.async_all()``. A disabled entity
(``disabled_by`` set) never gets a live ``State`` object at all, so it
was silently absent from every capture -- including
``DuplicateMigrationAnalyzer``'s whole-collection view -- forever. That
made the analyzer systematically blind to exactly the shape
``LIKELY_MIGRATION_LEFTOVER`` exists to catch: one live entity next to
its disabled predecessor. A real production audit confirmed 100% of
``device_tracker`` and 87.5% of ``button`` historical duplicate-suffix
groups were missing from a live scan for exactly this reason (every
missing group had a fully- or partially-disabled member).

This module exercises the *analyzer* end of that fix
(``DuplicateMigrationAnalyzer.analyze_collection``, fed
``EntityRecord``s shaped exactly like ``ha_source.py`` now produces for
a registry-only entity) rather than the capture layer itself (covered
by ``tests/test_ha_source.py``), and separately locks down the safety
invariants this pass must not regress.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hamie.analysis.analyzers.duplicate_migration import DuplicateMigrationAnalyzer
from hamie.analysis.analyzers.unavailable_entities import IGNORED_DOMAINS
from hamie.application.ports import EntityRecord
from hamie.domain.findings import RecommendationKind

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
ANALYZER = DuplicateMigrationAnalyzer(source_instance="test_home")


def _rec(
    entity_id: str,
    *,
    state: str = "on",
    disabled: bool = False,
    device_id: str | None = None,
    config_entry_id: str | None = None,
    area_id: str | None = None,
    referenced_by_count: int = 0,
    created_at: str | None = None,
) -> EntityRecord:
    domain = entity_id.partition(".")[0]
    return EntityRecord(
        entity_id=entity_id,
        state=state,
        last_changed=NOW,
        last_updated=NOW,
        registry_id=f"reg-{entity_id}",
        unique_id=None,
        device_id=device_id,
        config_entry_id=config_entry_id,
        disabled=disabled,
        restored=False if state != "unavailable" else None,
        domain=domain,
        area_id=area_id,
        created_at=created_at,
    )


def _analyze(*records: EntityRecord):
    return ANALYZER.analyze_collection(records, observed_at=NOW, reference_index=None)


# --------------------------------------------------------------------------
# device_tracker / button siblings can now reach duplicate analysis.
# --------------------------------------------------------------------------


def test_device_tracker_migration_leftover_reaches_analysis() -> None:
    """The exact production shape: a live device_tracker next to its
    disabled predecessor (the pair the old capture bug hid entirely).
    """
    live = _rec("device_tracker.example_phone_15", state="home")
    disabled = _rec(
        "device_tracker.example_phone_15_2", state="unavailable", disabled=True
    )
    outcome = _analyze(live, disabled)

    assert outcome.covered_subjects == ("device_tracker.example_phone_15",)
    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.category == "duplicate_migration"
    classification = next(
        ev.value
        for ev in finding.evidence
        if ev.predicate == "hamie.duplicate_group.classification@1"
    )
    assert classification == "likely_migration_leftover"
    # The group was actually produced -- NOT silently dropped the way it
    # was before the ha_source.py fix (the whole point of this test).
    member_ids = {
        entity_id
        for ev in finding.evidence
        if ev.predicate == "hamie.duplicate_group.members@1"
        for entity_id in ev.value.split(",")
    }
    assert member_ids == {
        "device_tracker.example_phone_15",
        "device_tracker.example_phone_15_2",
    }


def test_button_migration_leftover_reaches_analysis() -> None:
    """Same shape, button domain -- 7 of 8 real production button groups
    were missing before this fix; this proves the survivor case.
    """
    live = _rec("button.garage_reset_alarm", state="on")
    disabled = _rec("button.garage_reset_alarm_2", state="unavailable", disabled=True)
    outcome = _analyze(live, disabled)

    assert outcome.covered_subjects == ("button.garage_reset_alarm",)
    assert len(outcome.findings) == 1


# --------------------------------------------------------------------------
# The duplicate pipeline must never silently inherit
# UnavailableEntityAnalyzer's own IGNORED_DOMAINS -- these are genuinely
# independent configuration, not shared state.
# --------------------------------------------------------------------------


def test_ignored_domains_from_unavailable_analyzer_are_not_skipped_here() -> None:
    """``button`` and ``event`` are in UnavailableEntityAnalyzer's own
    IGNORED_DOMAINS (excluded from ITS per-entity findings) -- confirm
    that policy is scoped to that analyzer alone, never bleeding into
    DuplicateMigrationAnalyzer's whole-collection scan.
    """
    assert "button" in IGNORED_DOMAINS
    assert "event" in IGNORED_DOMAINS

    button_live = _rec("button.foo", state="on")
    button_disabled = _rec("button.foo_2", state="unavailable", disabled=True)
    event_live = _rec("event.foo", state="on")
    event_disabled = _rec("event.foo_2", state="unavailable", disabled=True)

    outcome = _analyze(button_live, button_disabled, event_live, event_disabled)

    covered = set(outcome.covered_subjects)
    assert "button.foo" in covered
    assert "event.foo" in covered
    assert len(outcome.findings) == 2


# --------------------------------------------------------------------------
# Legitimate distinct devices sharing a domain must still not be falsely
# flagged as a duplicate -- the fix must not regress this correctness
# guarantee for the newly-reachable domains either.
# --------------------------------------------------------------------------


def test_distinct_device_trackers_are_not_flagged_as_duplicates() -> None:
    """Two independently alive device_tracker entities backed by distinct
    devices are a name collision, not a migration leftover -- mirrors
    the existing media_player-style distinct-entities test pattern in
    tests/test_duplicate_classifier.py, extended to a domain this pass
    newly makes reachable.
    """
    first = _rec(
        "device_tracker.plug",
        state="home",
        device_id="device-a",
        area_id="kitchen",
    )
    second = _rec(
        "device_tracker.plug_2",
        state="not_home",
        device_id="device-b",
        area_id="garage",
    )
    outcome = _analyze(first, second)

    # No finding at all: the classifier's verdict here is "not a duplicate to
    # clean up", and emitting a finding for that made a healthy group
    # indistinguishable from a defective one -- which is exactly why a
    # duplicate_migration finding could never retire. The group must still be
    # COVERED, because "I examined this group and found nothing to report" is
    # the fresh deterministic evidence reconciliation needs to resolve a prior
    # finding for it.
    assert outcome.findings == ()
    assert "device_tracker.plug" in outcome.covered_subjects
    assert "device_tracker.plug" not in outcome.uncovered_subjects


# --------------------------------------------------------------------------
# Hard safety invariant: suffix alone must never yield a delete/disable
# recommendation, for any domain, including the newly-reachable ones.
# --------------------------------------------------------------------------


def test_suffix_alone_never_yields_delete_or_disable_for_any_domain() -> None:
    domains_and_pairs = [
        ("device_tracker", "device_tracker.a", "device_tracker.a_2"),
        ("button", "button.b", "button.b_2"),
        ("sensor", "sensor.c", "sensor.c_2"),
        ("binary_sensor", "binary_sensor.d", "binary_sensor.d_2"),
    ]
    records: list[EntityRecord] = []
    for _domain, first_id, second_id in domains_and_pairs:
        records.append(_rec(first_id, state="on"))
        records.append(_rec(second_id, state="unavailable", disabled=True))

    outcome = _analyze(*records)
    assert len(outcome.findings) == len(domains_and_pairs)
    for finding in outcome.findings:
        assert finding.recommendation.kind not in (
            RecommendationKind.DELETE_CANDIDATE,
            RecommendationKind.DISABLE,
        )
        assert finding.recommendation.dependency_assessment.safe_to_remove is False


# --------------------------------------------------------------------------
# Idempotency: repeated analysis of an identical collection (including
# the newly-reachable domains) must be stable.
# --------------------------------------------------------------------------


def test_repeated_analysis_is_idempotent_for_newly_reachable_domains() -> None:
    live = _rec("device_tracker.pixel_6a", state="home")
    disabled = _rec("device_tracker.pixel_6a_2", state="unavailable", disabled=True)
    button_live = _rec("button.front_door_trigger_alarm", state="on")
    button_disabled = _rec(
        "button.front_door_trigger_alarm_2", state="unavailable", disabled=True
    )

    first = _analyze(live, disabled, button_live, button_disabled)
    second = _analyze(live, disabled, button_live, button_disabled)

    first_ids = tuple(f.finding_id for f in first.findings)
    second_ids = tuple(f.finding_id for f in second.findings)
    assert first_ids == second_ids
    assert first.covered_subjects == second.covered_subjects
