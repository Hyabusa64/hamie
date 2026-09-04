"""Shared bounded in-memory projection for every Home Assistant adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from ..analysis.analyzers.unavailable_entities import ANALYZER_ID
from ..connectors.base import ConnectorHealth
from ..domain.common import stable_digest
from ..domain.evidence import Sensitivity
from ..domain.findings import (
    Finding,
    FindingLifecycle,
    FindingSeverity,
    finding_is_diagnostic_entity,
)
from ..domain.intelligence import AIReviewState, ExplorerIndex, GroupingRule
from ..domain.incidents import Incident
from .persistence import RepositoryState

IMPLEMENTED_CATEGORIES = ("availability",)
KNOWN_CATEGORIES = (
    "availability",
    "broken_automations",
    "duplicate_helpers",
    "missing_entity_references",
    "orphan_entities",
    "stale_devices",
)
SCORING_REVISION = "availability-health@1"
MAX_PROJECTED_EVIDENCE = 8
MAX_PROJECTED_RELATIONSHIPS = 32


class ScanStatus(StrEnum):
    """Finite scan lifecycle exposed by the runtime projection."""

    NEVER_RUN = "never_run"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class EvidenceView:
    """Bounded, privacy-aware evidence summary for local presentation."""

    predicate: str
    value: str
    kind: str
    source: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class FindingView:
    """One bounded finding page selected from canonical state."""

    finding_id: str
    entity_id: str
    severity: str
    category: str
    title_key: str
    recommendation: str
    confidence: str
    dependency_risk: str
    evidence: tuple[EvidenceView, ...]
    risk: str
    risk_rationale: str
    dependency_count: int
    referenced_by: tuple[str, ...]
    safe_to_remove: bool
    supporting_objects: tuple[str, ...]
    dependency_coverage: str
    dependency_rationale: str
    lifecycle: str
    review_state: str
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime
    content_revision: int


@dataclass(frozen=True, slots=True)
class RuntimeProjectionSnapshot:
    """Single scan-updated source for entities, diagnostics, and controls."""

    generation: int = 0
    projection_revision: int = 0
    scan_started: datetime | None = None
    scan_completed: datetime | None = None
    scan_duration: float | None = None
    scan_status: ScanStatus = ScanStatus.NEVER_RUN
    entities_scanned: int = 0
    findings_total: int = 0
    findings_open: int = 0
    findings_warning: int = 0
    findings_critical: int = 0
    findings_new: int = 0
    findings_resolved: int = 0
    availability_health: int | None = None
    # Health-dimension split (mission: maintenance-console redesign) --
    # see async_update()'s own comment for the exact, documented formula
    # each one uses. None means genuinely not enough data, never a
    # fabricated score.
    operational_health: int | None = None
    registry_cleanliness: int | None = None
    implemented_categories: tuple[str, ...] = IMPLEMENTED_CATEGORIES
    covered_categories: tuple[str, ...] = ()
    uncovered_categories: tuple[str, ...] = KNOWN_CATEGORIES
    coverage_state: str = "unknown"
    implemented_analyzers: tuple[str, ...] = (ANALYZER_ID,)
    scoring_revision: str = SCORING_REVISION
    store_size: int = 0
    queue_depth: int = 0
    runtime_profile: str = "conservative"
    pending_requests: int = 0
    last_scan_id: str | None = None
    selected_finding: FindingView | None = None
    selected_index: int = 0
    selectable_findings: int = 0
    finding_groups: int = 0
    suppressed_findings: int = 0
    connector_statuses: tuple[tuple[str, str], ...] = (
        ("hkg", "disabled"),
        ("mcp", "disabled"),
        ("n8n", "disabled"),
        ("ollama", "disabled"),
    )
    last_ai_analysis: datetime | None = None
    pending_ai_recommendations: int = 0
    last_connector_error: str | None = None
    last_scan_error_classification: str | None = None
    last_scan_error_summary: str | None = None


class DerivedProjectionPort(Protocol):
    """HAMIE-owned presentation synchronized after canonical commits."""

    async def async_sync(self, state: RepositoryState) -> None: ...

    async def async_clear(self) -> None: ...

    async def async_report_storage_error(self, reason_code: str) -> None: ...


class RuntimeProjection:
    """Publish committed state through one quiet, bounded memory projection."""

    def __init__(
        self,
        derived_projection: DerivedProjectionPort,
        *,
        store_size: Callable[[RepositoryState], int],
        clock: Callable[[], datetime] | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self._derived_projection = derived_projection
        self._store_size = store_size
        self._clock = clock or (lambda: datetime.now(UTC))
        self._options = dict(options or {})
        self._snapshot = RuntimeProjectionSnapshot()
        self._explorer = ExplorerIndex(findings=())
        self._findings: tuple[Finding, ...] = ()
        self._incidents: tuple[Incident, ...] = ()
        self._capability: Any = None
        self._analysis_baseline: Any = None
        self._remediation_baselines: tuple[Any, ...] = ()
        self._selected_finding_id: str | None = None
        self._listeners: set[Callable[[], None]] = set()

    @property
    def explorer(self) -> ExplorerIndex:
        """Return the bounded in-memory findings explorer."""
        return self._explorer

    @property
    def snapshot(self) -> RuntimeProjectionSnapshot:
        """Return the current immutable projection snapshot."""
        return self._snapshot

    @property
    def incidents(self) -> tuple[Incident, ...]:
        """Return the committed incident projection without Store I/O."""
        return self._incidents

    @property
    def analysis_baseline(self) -> Any:
        """Return the durable analysis-coverage baseline without Store I/O."""
        return self._analysis_baseline

    @property
    def remediation_baselines(self) -> tuple[Any, ...]:
        """Return durable pre-repair baselines without Store I/O."""
        return self._remediation_baselines

    @property
    def capability(self) -> Any:
        """Return the committed provider-capability record without Store I/O.

        Read synchronously by the analysis gate, which must be able to refuse
        a bulk run without awaiting a Store load.
        """
        return self._capability

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to finite projection changes without polling."""
        self._listeners.add(listener)

        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe

    async def async_sync(self, state: RepositoryState) -> None:
        """Publish one committed state and synchronize derived Repairs."""
        self._findings = state.findings
        self._incidents = state.incidents
        self._capability = state.capability
        self._analysis_baseline = state.analysis_baseline
        self._remediation_baselines = state.remediation_baselines
        self._normalize_selection()
        last = state.evaluations[-1] if state.evaluations else None
        configured_rules = self._configured_grouping_rules()
        dimensions = tuple(
            item.strip()
            for item in str(self._options.get("enabled_grouping_dimensions", "")).split(
                ","
            )
            if item.strip()
        )
        if not bool(
            self._options.get("collapse_same_device_unavailable_entities", True)
        ):
            dimensions = tuple(item for item in dimensions if item != "device_id")
        if not bool(self._options.get("collapse_same_integration_failures", True)):
            dimensions = tuple(
                item
                for item in dimensions
                if item
                not in {"integration_domain", "config_entry_id", "source_provider"}
            )
        threshold_value = self._options.get("grouping_confidence_threshold", 0)
        threshold = (
            {"low": 0.33, "medium": 0.66, "high": 1.0}.get(str(threshold_value), 0)
            if isinstance(threshold_value, str)
            else float(threshold_value)
        )
        default_visibility = str(
            self._options.get("default_suppression_visibility", "default")
        )
        self._explorer = ExplorerIndex(
            findings=state.findings,
            grouping_rules=(*state.grouping_rules, *configured_rules),
            suppression_rules=state.suppression_rules,
            recommendations=state.recommendations,
            audits=state.audits,
            generation=state.generation,
            projection_revision=state.projection_revision,
            at=self._clock(),
            maximum_groups=int(self._options.get("maximum_projected_groups", 500)),
            minimum_group_size=int(self._options.get("minimum_group_size", 1)),
            maximum_evidence_items=int(
                self._options.get("maximum_evidence_items_displayed", 8)
            ),
            maximum_supporting_objects=int(
                self._options.get("maximum_supporting_objects_displayed", 32)
            ),
            maximum_visible_group_members=int(
                self._options.get("maximum_visible_group_members", 100)
            ),
            show_suppressed_by_default=bool(
                self._options.get("show_suppressed_findings_by_default", False)
            )
            or default_visibility == "suppressed",
            show_snoozed_by_default=bool(
                self._options.get("show_snoozed_findings_by_default", False)
            )
            or default_visibility == "snoozed",
            enabled_grouping_dimensions=dimensions,
            primary_grouping_preference=str(
                self._options.get("primary_grouping_preference", "device_id")
            ),
            duplicate_collapsing_enabled=bool(
                self._options.get("duplicate_collapsing_enabled", True)
            ),
            collapse_mobile_app_findings=bool(
                self._options.get("collapse_common_mobile_app_findings", True)
            ),
            grouping_confidence_threshold=threshold,
        )
        open_findings = tuple(
            item for item in state.findings if item.lifecycle is FindingLifecycle.OPEN
        )
        entities_scanned = 0
        entities_evaluated = 0
        coverage_state = "unknown"
        covered_categories: tuple[str, ...] = ()
        scan_started = None
        scan_completed = None
        duration = None
        findings_new = 0
        findings_resolved = 0
        last_scan_id = None
        runtime_profile = self._snapshot.runtime_profile
        if last is not None:
            coverage = next(
                (item for item in last.coverage if item.analyzer_id == ANALYZER_ID),
                None,
            )
            if coverage is not None:
                entities_scanned = len(coverage.requested_subjects)
                entities_evaluated = len(coverage.covered_subjects)
                coverage_state = coverage.state.value
                if coverage.covered_subjects or coverage.excluded_subjects:
                    covered_categories = IMPLEMENTED_CATEGORIES
            scan_started = last.started_at
            scan_completed = last.ended_at
            duration = last.metrics.duration_ms / 1000
            findings_new = last.metrics.findings_created
            findings_resolved = last.metrics.findings_resolved
            last_scan_id = last.identity.scan_id
            runtime_profile = last.metrics.active_profile
        unavailable_count = sum(
            item.analyzer_id == ANALYZER_ID for item in open_findings
        )
        availability_health = (
            max(
                0,
                round(
                    100 * (entities_evaluated - unavailable_count) / entities_evaluated
                ),
            )
            if entities_evaluated
            else None
        )
        # Health-dimension split: which of the open unavailable-entity
        # findings are diagnostic/optional registry entities versus
        # primary ones (see domain/findings.py's finding_is_diagnostic_
        # entity). Operational Health excludes diagnostic-entity
        # unavailability entirely -- a house with hundreds of stale
        # optional diagnostic sensors but healthy primary devices must
        # never be reported as operationally unhealthy (the mission's
        # own central complaint about the prior "509 unresolved
        # findings" framing). Registry Cleanliness is the mirror: an
        # honest approximation of registry clutter using the same
        # evaluated-entity total as its denominator, since HAMIE's scan
        # coverage report does not track entity_category for every
        # evaluated subject, only for the ones that became findings --
        # directionally correct (more diagnostic-entity unavailability
        # lowers the score), not a literal "diagnostic entity
        # availability rate." "Maintenance Health" in the 5-dimension
        # display reuses `availability_health` itself (no separate field
        # needed) -- it is deliberately the *unsplit*, whole-house
        # figure, the one Operational/Registry are a documented
        # breakdown of.
        diagnostic_unavailable = sum(
            item.analyzer_id == ANALYZER_ID and finding_is_diagnostic_entity(item)
            for item in open_findings
        )
        primary_unavailable = unavailable_count - diagnostic_unavailable
        operational_health = (
            max(
                0,
                round(
                    100
                    * (entities_evaluated - primary_unavailable)
                    / entities_evaluated
                ),
            )
            if entities_evaluated
            else None
        )
        registry_cleanliness = (
            max(
                0,
                round(
                    100
                    * (entities_evaluated - diagnostic_unavailable)
                    / entities_evaluated
                ),
            )
            if entities_evaluated
            else None
        )
        uncovered = tuple(
            item for item in KNOWN_CATEGORIES if item not in covered_categories
        )
        self._snapshot = RuntimeProjectionSnapshot(
            generation=state.generation,
            projection_revision=state.projection_revision,
            scan_started=scan_started,
            scan_completed=scan_completed,
            scan_duration=duration,
            scan_status=(
                ScanStatus.COMPLETED if last is not None else ScanStatus.NEVER_RUN
            ),
            entities_scanned=entities_scanned,
            findings_total=len(state.findings),
            findings_open=len(open_findings),
            findings_warning=sum(
                item.severity is FindingSeverity.WARNING for item in open_findings
            ),
            findings_critical=sum(
                item.severity is FindingSeverity.ERROR for item in open_findings
            ),
            findings_new=findings_new,
            findings_resolved=findings_resolved,
            availability_health=availability_health,
            operational_health=operational_health,
            registry_cleanliness=registry_cleanliness,
            covered_categories=covered_categories,
            uncovered_categories=uncovered,
            coverage_state=coverage_state,
            store_size=self._store_size(state),
            runtime_profile=runtime_profile,
            last_scan_id=last_scan_id,
            selected_finding=self._selected_view(),
            selected_index=self._selected_index(),
            selectable_findings=len(self._findings),
            finding_groups=len(self._explorer.groups),
            suppressed_findings=len(self._explorer.suppressed_ids),
            connector_statuses=self._snapshot.connector_statuses,
            last_ai_analysis=self._snapshot.last_ai_analysis,
            pending_ai_recommendations=sum(
                item.review_state is AIReviewState.NEW and not item.stale
                for item in state.recommendations
            ),
            last_connector_error=self._snapshot.last_connector_error,
        )
        self._notify()
        await self._derived_projection.async_sync(
            replace(
                state,
                findings=tuple(
                    item
                    for item in state.findings
                    if item.finding_id not in self._explorer.repairs_hidden_ids
                ),
            )
        )

    def _configured_grouping_rules(self) -> tuple[GroupingRule, ...]:
        """Build bounded deterministic config-owned rules without persistence."""
        raw = self._options.get("user_defined_grouping_rules", [])
        if not isinstance(raw, list):
            return ()
        rules = []
        for item in raw[:32]:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            dimension = item.get("dimension")
            value = item.get("value")
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(dimension, str)
                or not dimension
                or not isinstance(value, str)
                or not value
            ):
                continue
            digest = stable_digest(name, dimension, value)
            rules.append(
                GroupingRule(
                    rule_id=f"cfg_{digest[:24]}",
                    name=name,
                    matcher=((dimension, value),),
                    title=name,
                )
            )
        return tuple(rules)

    async def async_scan_started(
        self, *, scan_id: str, started_at: datetime, runtime_profile: str
    ) -> None:
        """Publish a finite scan start without creating an update loop."""
        self._snapshot = replace(
            self._snapshot,
            scan_started=started_at,
            scan_status=ScanStatus.RUNNING,
            runtime_profile=runtime_profile,
            last_scan_id=scan_id,
        )
        self._notify()

    async def async_scan_failed(
        self,
        *,
        error_classification: str | None = None,
        error_summary: str | None = None,
    ) -> None:
        """Publish a terminal failed scan status.

        Never touches `findings_open`/`findings_critical`/`availability_health`/
        etc. -- only `replace()`s the scan-lifecycle fields, so whatever a
        prior successful `async_sync()` last computed stays exactly as it
        was (see docs/DEVELOPMENT.md's scan-failure-isolation discussion).
        `error_classification`/`error_summary` are bounded, non-sensitive
        diagnostics only (never raw exception text or a traceback) -- the
        real traceback goes to the log, never to a Home Assistant entity
        or diagnostics payload.
        """
        self._snapshot = replace(
            self._snapshot,
            scan_status=ScanStatus.FAILED,
            queue_depth=0,
            pending_requests=0,
            last_scan_error_classification=error_classification,
            last_scan_error_summary=error_summary,
        )
        self._notify()

    async def async_scan_cancelled(self) -> None:
        """Publish a terminal cancelled scan status."""
        self._snapshot = replace(
            self._snapshot,
            scan_status=ScanStatus.CANCELLED,
            queue_depth=0,
            pending_requests=0,
        )
        self._notify()

    async def async_queue_changed(self, pending_requests: int) -> None:
        """Publish the one-slot coalesced request queue depth."""
        self._snapshot = replace(
            self._snapshot,
            queue_depth=1 if pending_requests else 0,
            pending_requests=pending_requests,
        )
        self._notify()

    def update_connector_status(
        self,
        health: tuple[ConnectorHealth, ...],
        last_ai_analysis: datetime | None,
        last_error: str | None,
    ) -> None:
        """Publish cached connector health after explicit connector work."""
        self._snapshot = replace(
            self._snapshot,
            connector_statuses=tuple(
                (item.connector_id, item.status.value) for item in health
            ),
            last_ai_analysis=last_ai_analysis,
            last_connector_error=last_error,
        )
        self._notify()

    async def async_clear(self) -> None:
        """Clear HAMIE-owned Repairs and in-memory presentation state."""
        await self._derived_projection.async_clear()
        self._listeners.clear()
        self._findings = ()
        self._explorer = ExplorerIndex(findings=())
        self._selected_finding_id = None
        self._snapshot = RuntimeProjectionSnapshot()

    async def async_report_storage_error(self, reason_code: str) -> None:
        """Delegate actionable storage failures to the Repairs projection."""
        await self._derived_projection.async_report_storage_error(reason_code)

    def select_next(self) -> None:
        """Select the next bounded finding without persistence or I/O."""
        self._move_selection(1)

    def select_previous(self) -> None:
        """Select the previous bounded finding without persistence or I/O."""
        self._move_selection(-1)

    def _move_selection(self, offset: int) -> None:
        if not self._findings:
            return
        current = self._selected_index()
        self._selected_finding_id = self._findings[
            (current + offset) % len(self._findings)
        ].finding_id
        self._snapshot = replace(
            self._snapshot,
            selected_finding=self._selected_view(),
            selected_index=self._selected_index(),
        )
        self._notify()

    def _normalize_selection(self) -> None:
        if not self._findings:
            self._selected_finding_id = None
        elif not any(
            item.finding_id == self._selected_finding_id for item in self._findings
        ):
            self._selected_finding_id = self._findings[0].finding_id

    def _selected_index(self) -> int:
        for index, finding in enumerate(self._findings):
            if finding.finding_id == self._selected_finding_id:
                return index
        return 0

    def _selected_view(self) -> FindingView | None:
        if not self._findings:
            return None
        finding = self._findings[self._selected_index()]
        dependency = finding.recommendation.dependency_assessment
        evidence = tuple(
            EvidenceView(
                predicate=item.predicate,
                value=(
                    str(item.value)
                    if item.sensitivity is Sensitivity.PUBLIC
                    else "redacted"
                ),
                kind=item.kind.value,
                source=item.source_id,
                observed_at=item.observed_at,
            )
            for item in finding.evidence[
                : int(
                    self._options.get(
                        "maximum_evidence_items_displayed", MAX_PROJECTED_EVIDENCE
                    )
                )
            ]
        )
        references = dependency.referenced_by[:MAX_PROJECTED_RELATIONSHIPS]
        supporting = dependency.supporting_subject_ids[
            : int(
                self._options.get(
                    "maximum_supporting_objects_displayed",
                    MAX_PROJECTED_RELATIONSHIPS,
                )
            )
        ]
        return FindingView(
            finding_id=finding.finding_id,
            entity_id=finding.subject.source_id,
            severity=finding.severity.value,
            category=finding.category,
            title_key=finding.title_key,
            recommendation=finding.recommendation.action,
            confidence=finding.recommendation.confidence.level.value,
            dependency_risk=(
                "high"
                if dependency.referenced_by
                else ("low" if dependency.safe_to_remove else "unknown")
            ),
            evidence=evidence,
            risk=finding.recommendation.risk.overall.value,
            risk_rationale=finding.recommendation.risk.rationale,
            dependency_count=len(dependency.referenced_by),
            referenced_by=references,
            safe_to_remove=dependency.safe_to_remove,
            supporting_objects=supporting,
            dependency_coverage=dependency.coverage.value,
            dependency_rationale=dependency.rationale,
            lifecycle=finding.lifecycle.value,
            review_state=finding.review_state.value,
            occurrence_count=finding.occurrence_count,
            first_seen=finding.first_seen,
            last_seen=finding.last_seen,
            content_revision=finding.content_revision,
        )

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()
