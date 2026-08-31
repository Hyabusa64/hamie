"""Durable incident decisions survive scans and regress only on new evidence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from hamie.domain.incidents import (
    INCIDENT_ENGINE_REVISION,
    INCIDENT_SCHEMA_VERSION,
    EvidenceStatus,
    Incident,
    IncidentHypothesis,
    IncidentLifecycle,
    IncidentPriority,
    reconcile_incidents,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def _incident(
    *,
    lifecycle: IncidentLifecycle = IncidentLifecycle.NEW,
    digest: str = "digest-a",
) -> Incident:
    return Incident(
        incident_id="inc_test",
        schema_version=INCIDENT_SCHEMA_VERSION,
        engine_revision=INCIDENT_ENGINE_REVISION,
        root_key="root:test",
        title="Test incident",
        category="test",
        root_cause="Deterministic test cause.",
        evidence_status=EvidenceStatus.VERIFIED,
        confidence=0.98,
        priority=IncidentPriority.P2,
        lifecycle=lifecycle,
        finding_ids=("finding-a",),
        affected_subject_ids=("sensor.test",),
        affected_systems=("sensor",),
        hypotheses=(
            IncidentHypothesis(
                statement="Deterministic test cause.",
                status=EvidenceStatus.VERIFIED,
                evidence_ids=("evidence-a",),
                rationale="Observed test evidence.",
            ),
        ),
        recommended_next_step="Investigate.",
        first_seen=NOW,
        last_seen=NOW,
        occurrence_count=1,
        latest_scan_id="scan-a",
        content_revision=1,
        material_digest=digest,
    )


def test_dismissed_incident_stays_dismissed_when_evidence_is_unchanged() -> None:
    old = _incident(lifecycle=IncidentLifecycle.DISMISSED)
    result = reconcile_incidents(
        (old,), (_incident(),), at=NOW + timedelta(hours=1), scan_id="scan-b"
    )

    assert result[0].lifecycle is IncidentLifecycle.DISMISSED


def test_dismissed_incident_regresses_when_material_evidence_changes() -> None:
    old = _incident(lifecycle=IncidentLifecycle.DISMISSED)
    changed = _incident(digest="digest-b")
    result = reconcile_incidents(
        (old,), (changed,), at=NOW + timedelta(hours=1), scan_id="scan-b"
    )

    assert result[0].lifecycle is IncidentLifecycle.REGRESSED
    assert result[0].content_revision == 2


def test_absent_incident_resolves_and_reappearance_regresses() -> None:
    resolved = reconcile_incidents(
        (_incident(),), (), at=NOW + timedelta(hours=1), scan_id="scan-b"
    )[0]
    assert resolved.lifecycle is IncidentLifecycle.RESOLVED

    reappeared = reconcile_incidents(
        (resolved,), (_incident(),), at=NOW + timedelta(hours=2), scan_id="scan-c"
    )[0]
    assert reappeared.lifecycle is IncidentLifecycle.REGRESSED
    assert reappeared.first_seen == NOW


def test_material_change_does_not_overwrite_confirmed_user_decision() -> None:
    old = _incident(lifecycle=IncidentLifecycle.CONFIRMED)
    changed = replace(_incident(digest="digest-b"), priority=IncidentPriority.P1)
    result = reconcile_incidents(
        (old,), (changed,), at=NOW + timedelta(hours=1), scan_id="scan-b"
    )

    assert result[0].lifecycle is IncidentLifecycle.CONFIRMED
    assert result[0].priority is IncidentPriority.P1
    assert result[0].content_revision == 2
