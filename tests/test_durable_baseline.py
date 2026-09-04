"""Durable baselines: what HAMIE still knows after a reboot.

Both defects these cover were measured on the live installation:

* after a restart, coverage reported analyzed_total=0 and
  analyzed_scan_id=None while 18 recommendations sat persisted -- HAMIE held
  an analysis's conclusions with no record that it had run.
* the remediation lifecycle reported `baseline_available: false` after a
  restart between mutation and reconciliation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hamie.application.persistence import RepositoryState
from hamie.domain.durable_baseline import (
    BASELINE_SCHEMA_VERSION,
    MAX_RETAINED_REMEDIATION_BASELINES,
    AnalysisBaseline,
    BaselineStatus,
    RemediationBaseline,
    decode_analysis_baseline,
    decode_remediation_baseline,
    encode_analysis_baseline,
    encode_remediation_baseline,
    load_remediation_baseline,
    prune_remediation_baselines,
)
from hamie.infrastructure.storage import decode_document, encode_document

NOW = datetime(2026, 8, 28, 6, 0, tzinfo=UTC)


def _analysis(**kw) -> AnalysisBaseline:
    base = dict(
        schema_version=BASELINE_SCHEMA_VERSION,
        created_at=NOW,
        updated_at=NOW,
        scan_id="scan-1",
        eligible_total=1522,
        analyzed_finding_ids=tuple(f"hamie_{i:032x}" for i in range(53)),
        analyzed_group_ids=tuple(f"grp_{i}" for i in range(20)),
        failed_group_ids=("grp_bad",),
        recommendation_ids=tuple(f"rec_{i}" for i in range(18)),
    )
    base.update(kw)
    return AnalysisBaseline(**base)


def _remediation(**kw) -> RemediationBaseline:
    base = dict(
        schema_version=BASELINE_SCHEMA_VERSION,
        plan_identity="plan-a",
        incident_id="inc-1",
        captured_at=NOW,
        pre_repair_scan_id="scan-pre",
        active_incident_ids=("inc-1", "inc-2"),
        incident_finding_ids=("f1", "f2"),
        unavailable_counts=(("automation", 553), ("script", 55)),
        scope_entity_ids=("automation.a", "script.b"),
    )
    base.update(kw)
    return RemediationBaseline(**base)


# ------------------------------------------------------- analysis baseline


def test_analysis_baseline_round_trips() -> None:
    restored = decode_analysis_baseline(encode_analysis_baseline(_analysis()))
    assert restored.analyzed_total == 53
    assert restored.eligible_total == 1522
    assert restored.scan_id == "scan-1"
    assert len(restored.analyzed_group_ids) == 20
    assert restored.failed_group_ids == ("grp_bad",)
    assert restored.digest == _analysis().digest


def test_absent_analysis_baseline_round_trips_as_none() -> None:
    assert encode_analysis_baseline(None) is None
    assert decode_analysis_baseline(None) is None


def test_an_unreadable_analysis_baseline_raises() -> None:
    """Corruption must not read as 'nothing was ever analyzed'."""
    with pytest.raises(ValueError):
        decode_analysis_baseline({"scan_id": "x"})
    with pytest.raises(ValueError):
        decode_analysis_baseline("not-an-object")


def test_identity_lists_are_bounded_and_say_so() -> None:
    from hamie.domain.durable_baseline import MAX_BASELINE_FINDING_IDS

    huge = _analysis(
        analyzed_finding_ids=tuple(f"f{i}" for i in range(MAX_BASELINE_FINDING_IDS + 500)),
        truncated=True,
    )
    assert huge.analyzed_total == MAX_BASELINE_FINDING_IDS
    assert huge.truncated is True


def test_digest_changes_with_what_was_covered() -> None:
    assert _analysis().digest != _analysis(scan_id="scan-2").digest
    assert _analysis().digest != _analysis(analyzed_group_ids=("grp_0",)).digest


def test_analysis_baseline_survives_a_store_round_trip() -> None:
    state = RepositoryState(analysis_baseline=_analysis())
    restored = decode_document(encode_document(state))
    assert restored.analysis_baseline is not None
    assert restored.analysis_baseline.analyzed_total == 53
    assert restored.analysis_baseline.scan_id == "scan-1"


def test_a_document_without_the_new_keys_still_decodes() -> None:
    """Additive-optional inside schema 10: no second migration was needed."""
    from hamie.domain.common import canonical_json, stable_digest

    document = encode_document(RepositoryState())
    del document["payload"]["analysis_baseline"]
    del document["payload"]["remediation_baselines"]
    document["checksum"] = stable_digest(canonical_json(document["payload"]))
    state = decode_document(document)
    assert state.analysis_baseline is None
    assert state.remediation_baselines == ()


# ---------------------------------------------------- remediation baseline


def test_remediation_baseline_round_trips() -> None:
    restored = decode_remediation_baseline(encode_remediation_baseline(_remediation()))
    assert restored.plan_identity == "plan-a"
    assert restored.incident_id == "inc-1"
    assert restored.pre_repair_scan_id == "scan-pre"
    assert dict(restored.unavailable_counts)["automation"] == 553


def test_a_baseline_is_found_only_for_its_exact_repair() -> None:
    load = load_remediation_baseline(
        (_remediation(),), plan_identity="plan-a", incident_id="inc-1"
    )
    assert load.status is BaselineStatus.LOADED
    assert load.usable


def test_a_baseline_is_never_reused_across_incidents() -> None:
    """Comparing a repair against a world it never ran in is worse than none."""
    load = load_remediation_baseline(
        (_remediation(),), plan_identity="plan-a", incident_id="inc-OTHER"
    )
    assert load.status is BaselineStatus.FOREIGN_PLAN
    assert not load.usable


def test_absent_and_corrupt_stay_distinguishable() -> None:
    absent = load_remediation_baseline((), plan_identity="p", incident_id="i")
    assert absent.status is BaselineStatus.ABSENT
    assert not absent.usable

    incompatible = load_remediation_baseline(
        (_remediation(schema_version=99),), plan_identity="plan-a", incident_id="inc-1"
    )
    assert incompatible.status is BaselineStatus.INCOMPATIBLE
    assert not incompatible.usable


def test_an_unreadable_remediation_baseline_raises() -> None:
    with pytest.raises(ValueError):
        decode_remediation_baseline({"plan_identity": "p"})


def test_remediation_baselines_survive_a_store_round_trip() -> None:
    state = RepositoryState(remediation_baselines=(_remediation(),))
    restored = decode_document(encode_document(state))
    assert len(restored.remediation_baselines) == 1
    assert restored.remediation_baselines[0].plan_identity == "plan-a"


# ------------------------------------------------------------- retention


def test_retention_never_discards_an_unfinished_repair() -> None:
    """The only record of the world before an unreconciled repair."""
    incomplete = tuple(
        _remediation(plan_identity=f"open-{i}", captured_at=NOW - timedelta(days=400 + i))
        for i in range(5)
    )
    complete = tuple(
        _remediation(plan_identity=f"done-{i}", captured_at=NOW - timedelta(minutes=i), complete=True)
        for i in range(MAX_RETAINED_REMEDIATION_BASELINES + 30)
    )
    kept = prune_remediation_baselines(incomplete + complete)
    assert all(item in kept for item in incomplete), "unfinished evidence was pruned"
    assert len(kept) <= MAX_RETAINED_REMEDIATION_BASELINES + len(incomplete)


def test_retention_keeps_the_most_recent_completed_records() -> None:
    complete = tuple(
        _remediation(plan_identity=f"done-{i}", captured_at=NOW - timedelta(minutes=i), complete=True)
        for i in range(MAX_RETAINED_REMEDIATION_BASELINES + 10)
    )
    kept = prune_remediation_baselines(complete)
    assert len(kept) == MAX_RETAINED_REMEDIATION_BASELINES
    assert kept[0].plan_identity == "done-0"


def test_pruning_an_empty_set_is_safe() -> None:
    assert prune_remediation_baselines(()) == ()
