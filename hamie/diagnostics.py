"""Privacy-redacted, projection-backed HAMIE diagnostics."""

from __future__ import annotations

from typing import Any

from .build_info import BUILD_INFO
from .const import VERSION


async def async_get_config_entry_diagnostics(hass: Any, entry: Any) -> dict[str, Any]:
    """Return bounded aggregate diagnostics without persistence I/O."""
    from homeassistant.components.diagnostics import async_redact_data

    snapshot = entry.runtime_data.projection.snapshot
    explorer = entry.runtime_data.projection.explorer
    stale_reasons: dict[str, int] = {}
    for recommendation in explorer.recommendations:
        for reason in recommendation.stale_reasons:
            stale_reasons[reason] = stale_reasons.get(reason, 0) + 1
    diagnostics: dict[str, Any] = {
        "version": VERSION,
        **BUILD_INFO.as_dict(),
        "entry": dict(entry.data),
        "storage_schema": 3,
        "generation": snapshot.generation,
        "projection_revision": snapshot.projection_revision,
        "runtime_profile": snapshot.runtime_profile,
        "queue_depth": snapshot.queue_depth,
        "pending_requests": snapshot.pending_requests,
        "store_size": snapshot.store_size,
        "last_scan_id": snapshot.last_scan_id,
        "scan": {
            "status": snapshot.scan_status.value,
            "started_at": (
                snapshot.scan_started.isoformat() if snapshot.scan_started else None
            ),
            "completed_at": (
                snapshot.scan_completed.isoformat() if snapshot.scan_completed else None
            ),
            "duration_seconds": snapshot.scan_duration,
            "entities_scanned": snapshot.entities_scanned,
            "last_error_classification": snapshot.last_scan_error_classification,
            "last_error_summary": snapshot.last_scan_error_summary,
            # True only once a scan has actually completed successfully.
            # After a failed scan, every finding/health/coverage field
            # above is either still whatever the last successful scan
            # computed (results_current stays accurate about that), or
            # (if no scan has ever succeeded) the honest "never scanned"
            # default -- never a fabricated authoritative zero.
            "results_current": snapshot.scan_status.value == "completed",
        },
        "finding_counts": {
            "total": snapshot.findings_total,
            "open": snapshot.findings_open,
            "warning": snapshot.findings_warning,
            "critical": snapshot.findings_critical,
            "new": snapshot.findings_new,
            "resolved": snapshot.findings_resolved,
        },
        "availability_health": {
            "scope": "availability_only",
            "score": snapshot.availability_health,
            "scoring_revision": snapshot.scoring_revision,
        },
        "coverage": {
            "state": snapshot.coverage_state,
            "covered_categories": list(snapshot.covered_categories),
            "uncovered_categories": list(snapshot.uncovered_categories),
        },
        "implemented_analyzers": list(snapshot.implemented_analyzers),
        "explorer": {
            "finding_groups": snapshot.finding_groups,
            "suppressed_findings": snapshot.suppressed_findings,
            "pending_ai_recommendations": snapshot.pending_ai_recommendations,
            "stale_ai_reasons": stale_reasons,
        },
        "connectors": {
            "statuses": dict(snapshot.connector_statuses),
            "last_ai_analysis": (
                snapshot.last_ai_analysis.isoformat()
                if snapshot.last_ai_analysis
                else None
            ),
            "last_error_code": snapshot.last_connector_error,
        },
    }
    return async_redact_data(diagnostics, {"installation_id"})
