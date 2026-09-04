"""Tests for domain/protection.py (mission Part 4) and the additive
RemediationSafetyGate model (mission Part 3), including backward
compatibility of Recommendation serialization for records persisted
before either field existed.
"""

from __future__ import annotations

import sys

import pytest

from hamie.domain.protection import is_protected_subject

# hamie/domain/serialization.py uses PEP 695 generic function syntax
# (`def _enum[T: Enum](...)`), which requires Python 3.12+ -- a
# pre-existing repository constraint (present since the very baseline
# commit, unrelated to this pass) that this local sandbox's Python
# 3.11 cannot import at all. No existing test in this suite imports
# that module for the same reason (verified: zero hits before this
# file). Skipped here rather than silently working around it, so the
# real round-trip logic still runs wherever a matching Python is
# available (e.g. production Home Assistant, which requires a newer
# Python than this sandbox has).
_requires_py312_serialization = pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason=(
        "hamie/domain/serialization.py requires Python 3.12+ (PEP 695 "
        "generics) -- pre-existing repo/sandbox mismatch, not introduced "
        "by this change"
    ),
)


def test_protected_domain_alone_is_sufficient() -> None:
    assert is_protected_subject(entity_id="lock.front_door", domain="lock")
    assert is_protected_subject(entity_id="alarm_control_panel.house", domain="alarm_control_panel")


def test_protected_device_class_alone_is_sufficient() -> None:
    assert is_protected_subject(
        entity_id="binary_sensor.hallway", domain="binary_sensor", device_class="smoke"
    )
    assert is_protected_subject(
        entity_id="sensor.basement", domain="sensor", device_class="moisture"
    )


def test_protected_keyword_in_entity_id() -> None:
    assert is_protected_subject(entity_id="switch.garage_door_opener", domain="switch")
    assert is_protected_subject(entity_id="automation.backyard_loitering_alert", domain="automation")
    assert is_protected_subject(entity_id="automation.house_empty_lighting", domain="automation")


def test_protected_keyword_in_friendly_name_or_source_file() -> None:
    assert is_protected_subject(
        entity_id="light.strip_1", domain="light", friendly_name="Exterior Security Light"
    )
    assert is_protected_subject(
        entity_id="sensor.pct", domain="sensor", source_file="packages/security.yaml"
    )


def test_ordinary_entity_not_protected() -> None:
    assert not is_protected_subject(entity_id="light.kitchen_lamp", domain="light")
    assert not is_protected_subject(
        entity_id="sensor.living_room_temperature", domain="sensor", device_class="temperature"
    )


# --------------------------------------------------------------------------
# RemediationSafetyGate: backward-compatible additive field.
# --------------------------------------------------------------------------


def _make_recommendation(**overrides):
    from hamie.domain.dependencies import DependencyAssessment, DependencyCoverage
    from hamie.domain.evidence import EvidenceItem, EvidenceKind, Sensitivity
    from hamie.domain.findings import (
        Confidence,
        ConfidenceFactor,
        ConfidenceLevel,
        Recommendation,
        RecommendationKind,
        Risk,
        RiskLevel,
    )
    from hamie.domain.identity import SubjectIdentity
    from datetime import UTC, datetime

    subject = SubjectIdentity(
        durable_id="d1", kind="home_assistant.entity", source_instance="test", source_id="light.x"
    )
    evidence = (
        EvidenceItem(
            subject=subject,
            predicate="test.predicate@1",
            value=True,
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_id="test",
            source_revision="rev",
            kind=EvidenceKind.OBSERVED,
            sensitivity=Sensitivity.PUBLIC,
        ),
    )
    dependency = DependencyAssessment(
        subject=subject,
        required_capabilities=("cap@1",),
        used_capabilities=(),
        coverage=DependencyCoverage.PARTIAL,
        rationale="test",
    )
    confidence = Confidence(
        level=ConfidenceLevel.LOW,
        factors=(ConfidenceFactor(code="c", effect=1, rationale="r"),),
        rule_revision="rev@1",
    )
    risk = Risk(
        likelihood=RiskLevel.LOW,
        impact=RiskLevel.LOW,
        reversible=True,
        affected_scope="test",
        overall=RiskLevel.LOW,
        rationale="test",
    )
    kwargs = dict(
        kind=RecommendationKind.MONITOR,
        action="do something",
        rationale="because",
        evidence=evidence,
        confidence=confidence,
        dependency_assessment=dependency,
        risk=risk,
        analyzer_id="test.analyzer",
        rule_revision="1.0.0",
    )
    kwargs.update(overrides)
    return Recommendation(**kwargs)


def test_default_safety_gate_is_recommend_review() -> None:
    """An analyzer written before RemediationSafetyGate existed (every
    pre-Part-3 analyzer) must implicitly read as RECOMMEND_REVIEW, never
    a stronger gate it never earned."""
    from hamie.domain.findings import RemediationSafetyGate

    rec = _make_recommendation()
    assert rec.safety_gate is RemediationSafetyGate.RECOMMEND_REVIEW
    assert rec.blocked_reason is None


def test_blocked_insufficient_evidence_requires_blocked_reason() -> None:
    from hamie.domain.findings import RemediationSafetyGate

    with pytest.raises(ValueError, match="blocked_reason"):
        _make_recommendation(safety_gate=RemediationSafetyGate.BLOCKED_INSUFFICIENT_EVIDENCE)

    rec = _make_recommendation(
        safety_gate=RemediationSafetyGate.BLOCKED_INSUFFICIENT_EVIDENCE,
        blocked_reason="short recorder retention",
    )
    assert rec.blocked_reason == "short recorder retention"


def test_safe_to_remove_registry_requires_dependency_safe_to_remove() -> None:
    from hamie.domain.findings import RemediationSafetyGate

    with pytest.raises(ValueError, match="safe_to_remove"):
        _make_recommendation(safety_gate=RemediationSafetyGate.SAFE_TO_REMOVE_REGISTRY)


@_requires_py312_serialization
def test_recommendation_serialization_round_trips_safety_gate() -> None:
    from hamie.domain.findings import RemediationSafetyGate
    from hamie.domain.serialization import _decode_recommendation, _encode_recommendation

    rec = _make_recommendation(
        safety_gate=RemediationSafetyGate.PROTECTED,
    )
    encoded = _encode_recommendation(rec)
    decoded = _decode_recommendation(encoded)
    assert decoded.safety_gate is RemediationSafetyGate.PROTECTED


@_requires_py312_serialization
def test_recommendation_decode_defaults_safety_gate_for_legacy_records() -> None:
    """A record persisted before safety_gate existed has no such key at
    all -- must decode to the same conservative default the dataclass
    itself uses, not raise and not fabricate a stronger gate."""
    from hamie.domain.findings import RemediationSafetyGate
    from hamie.domain.serialization import _decode_recommendation, _encode_recommendation

    rec = _make_recommendation()
    encoded = _encode_recommendation(rec)
    del encoded["safety_gate"]
    del encoded["blocked_reason"]
    decoded = _decode_recommendation(encoded)
    assert decoded.safety_gate is RemediationSafetyGate.RECOMMEND_REVIEW
    assert decoded.blocked_reason is None
