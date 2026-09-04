"""Tests for FunctionalSelfReferenceAnalyzer (mission Part 5, test
patterns 1, 9, 12).

Pattern 1 / 12: the confirmed version-bump self-reference regression
(kitchen-cleaning exact shape, plus a second anonymized instance
matching vacuum-status/water-goal-percentage's structure) -- proves
both true-positive detection and that the recommendation stays
advisory (REPAIR, never an automatic file edit).

Pattern 9: a security-relevant subject still gets detected but is
capped at RemediationSafetyGate.PROTECTED, never treated as an
ordinary functional bug alone.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hamie.analysis.analyzers.functional_self_reference import (
    FunctionalSelfReferenceAnalyzer,
)
from hamie.application.ports import EntityRecord
from hamie.domain.findings import RecommendationKind, RemediationSafetyGate
from hamie.infrastructure.source_definition_index import (
    ConfigSourceFile,
    SourceDefinitionIndex,
)

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
ANALYZER = FunctionalSelfReferenceAnalyzer(source_instance="test_home")


def _rec(
    entity_id: str,
    *,
    unique_id: str | None,
    state: str = "on",
    disabled: bool = False,
    device_class: str | None = None,
    friendly_name: str | None = None,
) -> EntityRecord:
    domain = entity_id.partition(".")[0]
    return EntityRecord(
        entity_id=entity_id,
        state=state,
        last_changed=NOW,
        last_updated=NOW,
        registry_id=f"reg-{entity_id}",
        unique_id=unique_id,
        device_id=None,
        config_entry_id=None,
        disabled=disabled,
        restored=False if state != "unavailable" else None,
        domain=domain,
        device_class=device_class,
        friendly_name=friendly_name,
    )


def _index(path: str, content: str) -> SourceDefinitionIndex:
    return SourceDefinitionIndex.build((ConfigSourceFile(path=path, content=content),))


def _analyze(records, source_index):
    return ANALYZER.analyze_collection(records, observed_at=NOW, source_index=source_index)


# --------------------------------------------------------------------------
# Pattern 1 / 12: the confirmed kitchen-cleaning-shaped bug.
# --------------------------------------------------------------------------


def test_detects_version_bump_self_reference_regression() -> None:
    base = _rec("vacuum.example_appliance", unique_id="example_appliance_v1", state="unavailable")
    sibling = _rec("vacuum.example_appliance_2", unique_id="example_appliance_v2", state="cleaning")
    package = """
template:
  - binary_sensor:
      - name: Kitchen Dispatch Gate
        unique_id: example_appliance_v2
        state: "{{ is_state('vacuum.example_appliance', 'cleaning') }}"
"""
    outcome = _analyze((base, sibling), _index("packages/kitchen.yaml", package))

    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.title_key == "functional_self_reference_regression"
    assert finding.category == "functional_bug"
    assert finding.recommendation.kind is RecommendationKind.REPAIR
    assert finding.recommendation.safety_gate is RemediationSafetyGate.FUNCTIONAL_BUG
    # Advisory only -- never a claim of having fixed anything.
    assert "HAMIE never edits" in finding.recommendation.action
    assert "vacuum.example_appliance_2" in finding.recommendation.action


def test_detects_second_anonymized_instance_example_metric_shape() -> None:
    """Anonymized second real structural instance (water-goal-percentage
    shape): a security/usage-alert-adjacent package still referencing a
    dead base slug after a version bump."""
    base = _rec("sensor.example_metric_percentage", unique_id="example_metric_pct_r1", state="unavailable")
    sibling = _rec("sensor.example_metric_percentage_2", unique_id="example_metric_pct_r2", state="42")
    package = """
template:
  - sensor:
      - name: Water Usage Alert
        unique_id: example_metric_pct_r2
        state: "{{ states('sensor.example_metric_percentage') }}"
"""
    outcome = _analyze((base, sibling), _index("packages/water.yaml", package))
    assert len(outcome.findings) == 1


# --------------------------------------------------------------------------
# False positive suppression: no textual self-reference -> no finding.
# --------------------------------------------------------------------------


def test_no_finding_when_no_textual_self_reference() -> None:
    base = _rec("vacuum.example_appliance", unique_id="example_appliance_v1", state="unavailable")
    sibling = _rec("vacuum.example_appliance_2", unique_id="example_appliance_v2", state="cleaning")
    package = """
template:
  - binary_sensor:
      - name: Unrelated
        unique_id: example_appliance_v2
        state: "{{ states('vacuum.some_other_thing') }}"
"""
    outcome = _analyze((base, sibling), _index("packages/kitchen.yaml", package))
    assert outcome.findings == ()


def test_no_finding_when_version_tokens_do_not_indicate_a_bump() -> None:
    """Sibling's unique_id is not a numerically-newer version than base's
    -- must never guess a regression from suffix alone."""
    base = _rec("vacuum.example_appliance", unique_id="example_appliance_v2", state="unavailable")
    sibling = _rec("vacuum.example_appliance_2", unique_id="example_appliance_v1", state="cleaning")
    package = """
template:
  - binary_sensor:
      - unique_id: example_appliance_v1
        state: "{{ is_state('vacuum.example_appliance', 'cleaning') }}"
"""
    outcome = _analyze((base, sibling), _index("packages/kitchen.yaml", package))
    assert outcome.findings == ()


def test_uncovered_without_raw_files() -> None:
    base = _rec("vacuum.example_appliance", unique_id="example_appliance_v1", state="unavailable")
    sibling = _rec("vacuum.example_appliance_2", unique_id="example_appliance_v2", state="cleaning")
    outcome = ANALYZER.analyze_collection((base, sibling), observed_at=NOW, source_index=None)
    assert outcome.findings == ()
    assert "vacuum.example_appliance" in outcome.uncovered_subjects


# --------------------------------------------------------------------------
# Pattern 9: security-relevant subject caps at PROTECTED.
# --------------------------------------------------------------------------


def test_protected_domain_caps_safety_gate() -> None:
    base = _rec(
        "lock.garage_side_door",
        unique_id="garage_lock_v1",
        state="unavailable",
    )
    sibling = _rec("lock.garage_side_door_2", unique_id="garage_lock_v2", state="locked")
    package = """
template:
  - binary_sensor:
      - name: Garage Lock Watchdog
        unique_id: garage_lock_v2
        state: "{{ is_state('lock.garage_side_door', 'locked') }}"
"""
    outcome = _analyze((base, sibling), _index("packages/security.yaml", package))
    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.recommendation.safety_gate is RemediationSafetyGate.PROTECTED
    assert finding.recommendation.safety_gate != RemediationSafetyGate.SAFE_TO_REMOVE_REGISTRY


# --------------------------------------------------------------------------
# Degradation: one malformed group never aborts the whole scan.
# --------------------------------------------------------------------------


def test_malformed_group_degrades_without_aborting_scan() -> None:
    base = _rec("vacuum.example_appliance", unique_id="example_appliance_v1", state="unavailable")
    sibling_good_base = _rec(
        "vacuum.example_appliance_2", unique_id="example_appliance_v2", state="cleaning"
    )
    # A second, unrelated group with no unique_id at all on either side --
    # must not raise or block the first group's real finding.
    weird_base = _rec("sensor.weird", unique_id=None, state="unavailable")
    weird_sibling = _rec("sensor.weird_2", unique_id=None, state="on")
    package = """
template:
  - binary_sensor:
      - unique_id: example_appliance_v2
        state: "{{ is_state('vacuum.example_appliance', 'cleaning') }}"
"""
    outcome = _analyze(
        (base, sibling_good_base, weird_base, weird_sibling),
        _index("packages/kitchen.yaml", package),
    )
    assert len(outcome.findings) == 1
    assert "sensor.weird" in outcome.covered_subjects
