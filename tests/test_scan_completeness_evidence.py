"""Skipped subjects are evidence; warning prose is presentation.

The capture always knew which entities it failed to normalize, but it flattened
them into `metadata.warnings` -- bounded at MAX_SKIPPED_ENTITY_WARNINGS -- and
discarded the set. Past that cap a run reported a count and nothing else, so
"absent from the installation" and "present but unreadable this scan" became
indistinguishable. Any negative analyzer conclusion built on that would be
guessing, and recovering the ids by parsing log strings would be worse.
"""

from __future__ import annotations

import pytest

from hamie.analysis.analyzers.duplicate_migration import (
    DuplicateMigrationAnalyzer,
    _duplicate_base,
)
from hamie.application.ports import EntityCapture
from hamie.domain.evaluations import SourceCapture
from tests.test_duplicate_migration_analyzer import _rec

from datetime import UTC, datetime

_NOW = datetime(2026, 8, 29, tzinfo=UTC)


def _capture(entities=(), skipped=frozenset()):
    return EntityCapture(
        metadata=SourceCapture(
            source_id="test", capability_id="test.capability@1", revision="r1",
            capture_started_at=_NOW, capture_ended_at=_NOW, observed_at=_NOW,
            max_age_seconds=60,
            requested_scopes=("state",), captured_scopes=("state",),
        ),
        entities=tuple(entities),
        skipped_subjects=frozenset(skipped),
    )


def test_capture_retains_a_skipped_subject_structurally():
    assert _capture(skipped={"sensor.broken"}).skipped_subjects == {"sensor.broken"}


def test_capture_retains_far_more_than_the_warning_display_cap():
    # The human cap is 20. Evidence must not be truncated to match it.
    from hamie.infrastructure.ha_source import MAX_SKIPPED_ENTITY_WARNINGS

    many = {f"sensor.broken_{i}" for i in range(MAX_SKIPPED_ENTITY_WARNINGS * 5)}
    capture = _capture(skipped=many)
    assert len(capture.skipped_subjects) == len(many) > MAX_SKIPPED_ENTITY_WARNINGS
    assert capture.skipped_subjects == many


def test_default_capture_has_an_empty_skipped_set_not_none():
    assert _capture().skipped_subjects == frozenset()


# ------------------------------------------------------- relevance is narrow


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.thing_2", "sensor.thing"),
        ("sensor.thing_9", "sensor.thing"),
        ("sensor.thing", "sensor.thing"),
        ("sensor.thing_10", "sensor.thing_10"),   # only a single 2-9 suffix
        ("sensor.thing_1", "sensor.thing_1"),
        ("notanentity", "notanentity"),
    ],
)
def test_duplicate_base_matches_the_grouping_rule(entity_id, expected):
    assert _duplicate_base(entity_id) == expected


def _analyze(records, skipped=frozenset()):
    return DuplicateMigrationAnalyzer().analyze_collection(
        tuple(records),
        observed_at=_NOW,
        skipped_subjects=frozenset(skipped),
    )


def test_skipped_member_of_an_observed_group_becomes_indeterminate():
    records = [_rec("sensor.thing", state="on"), _rec("sensor.thing_2", state="unavailable")]
    outcome = _analyze(records, skipped={"sensor.thing_3"})
    assert "sensor.thing_3" in outcome.indeterminate_subjects


def test_unrelated_skipped_entity_does_not_touch_this_analyzer():
    records = [_rec("sensor.thing", state="on"), _rec("sensor.thing_2", state="unavailable")]
    outcome = _analyze(records, skipped={"climate.upstairs_thermostat"})
    assert outcome.indeterminate_subjects == ()
    assert "climate.upstairs_thermostat" not in outcome.covered_subjects


def test_no_skipped_material_leaves_the_outcome_complete():
    records = [_rec("sensor.thing", state="on"), _rec("sensor.thing_2", state="unavailable")]
    outcome = _analyze(records)
    assert outcome.indeterminate_subjects == ()


def test_indeterminate_never_overlaps_covered():
    # AnalyzerOutcome requires the classifications to be disjoint; a skipped
    # subject was by definition never captured, so it cannot be covered.
    records = [_rec("sensor.thing", state="on"), _rec("sensor.thing_2", state="unavailable")]
    outcome = _analyze(records, skipped={"sensor.thing_3", "light.hall"})
    assert not set(outcome.indeterminate_subjects) & set(outcome.covered_subjects)


# --------------------------------- every whole-collection analyzer must accept
#                                    the supervisor's actual call shape
#
# Threading skipped_subjects into WholeCollectionSupervisor broke production:
# only duplicate_migration had been updated, so the first real scan after
# deployment died with
#   TypeError: FunctionalSelfReferenceAnalyzer.analyze_collection()
#              got an unexpected keyword argument 'skipped_subjects'
# Unit tests missed it because they call each analyzer directly. This test
# calls them the way the supervisor does.


def test_every_whole_collection_analyzer_accepts_the_supervisor_call_shape():
    import importlib
    import inspect
    import pkgutil

    import hamie.analysis.analyzers as pkg

    checked = []
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        module = importlib.import_module(f"{pkg.__name__}.{mod_info.name}")
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            fn = getattr(obj, "analyze_collection", None)
            if fn is None or obj.__module__ != module.__name__:
                continue
            params = inspect.signature(fn).parameters
            assert "skipped_subjects" in params, (
                f"{obj.__name__}.analyze_collection must accept the "
                "supervisor's skipped_subjects argument"
            )
            checked.append(obj.__name__)
    assert checked, "no whole-collection analyzers were discovered"
