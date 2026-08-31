"""Single-flight logical evaluation and duplicate-request coalescing."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import monotonic
from typing import Protocol
from uuid import uuid4

from ..analysis.supervisor import AnalyzerSupervisor, PerformanceProfile, SupervisorPort
from ..analysis.temporal_enrichment import (
    async_enrich_unavailable_findings_with_temporal_evidence,
)
from ..domain.common import redact_secret_looking_text
from ..domain.evaluations import (
    CoverageState,
    EvaluationIdentity,
    EvaluationMetrics,
    EvaluationRecord,
    EvaluationState,
)
from ..domain.findings import RemediationSafetyGate
from ..domain.intelligence import (
    ExplorerIndex,
    apply_suppression_reviews,
    mark_recommendations_stale,
)
from ..domain.incidents import build_incidents, reconcile_incidents
from .persistence import PersistenceUnitOfWorkPort, RepositoryState
from .ports import Clock, OperationalSourcePort, ReferenceIndexPort, TemporalEvidenceSourcePort
from .reconciliation import (
    reconcile_findings,
    record_policy_reopens,
    reopen_expired_snoozes,
)


class ProjectionPort(Protocol):
    """Derived presentation projection repaired after canonical commit."""

    async def async_scan_started(
        self, *, scan_id: str, started_at: datetime, runtime_profile: str
    ) -> None:
        """Publish a finite scan start."""

    async def async_scan_failed(
        self,
        *,
        error_classification: str | None = None,
        error_summary: str | None = None,
    ) -> None:
        """Publish a failed scan terminal state."""

    async def async_scan_cancelled(self) -> None:
        """Publish a cancelled scan terminal state."""

    async def async_queue_changed(self, pending_requests: int) -> None:
        """Publish the bounded coalesced queue state."""

    async def async_sync(self, state: RepositoryState) -> None:
        """Synchronize derived presentation from committed state."""

    async def async_clear(self) -> None:
        """Remove HAMIE-owned derived presentation state."""

    async def async_report_storage_error(self, reason_code: str) -> None:
        """Publish an actionable, non-sensitive persistence setup failure."""


class ScanLifecyclePort(Protocol):
    """Optional finite lifecycle event sink invoked outside reconciliation."""

    async def async_scan_started(
        self,
        *,
        scan_id: str,
        trigger: str,
        generation: int,
        projection_revision: int,
    ) -> None: ...

    async def async_scan_committed(
        self,
        current: RepositoryState,
        committed: RepositoryState,
        *,
        scan_id: str,
    ) -> None: ...

    async def async_scan_failed(
        self,
        *,
        scan_id: str,
        error_code: str,
        generation: int,
        projection_revision: int,
    ) -> None: ...


class ScanCoordinatorStoppingError(RuntimeError):
    """Raised when a scan request races coordinator shutdown."""


_LOGGER = logging.getLogger(__name__)


class SystemClock:
    """UTC system clock adapter."""

    def now(self) -> datetime:
        """Return the current UTC instant."""
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Application result for one committed logical evaluation."""

    evaluation: EvaluationRecord
    state: RepositoryState


@dataclass(frozen=True, slots=True)
class _SafetyGateSummary:
    """Scan-summary-only counts (mission Part 6) -- never per-finding
    detail at this log level; per-group evidence stays at DEBUG inside
    each analyzer's own module (see analysis/analyzers/*.py's
    _LOGGER.debug calls)."""

    candidate_count: int
    functional_bug_count: int
    remediation_safe_count: int
    protected_count: int
    insufficient_evidence_count: int
    analyzer_partial_or_unknown_count: int


def _safety_gate_summary(supervisions: list) -> _SafetyGateSummary:
    """Reduce one scan cycle's raw supervisions into the bounded summary
    counts mission Part 6 asks the normal-level scan-completion log to
    carry. Pure and side-effect-free -- only ever reads already-computed
    ``SupervisionResult`` values, never performs I/O."""
    gates = [
        finding.recommendation.safety_gate
        for supervision in supervisions
        for finding in supervision.findings
    ]
    return _SafetyGateSummary(
        candidate_count=len(gates),
        functional_bug_count=sum(1 for g in gates if g is RemediationSafetyGate.FUNCTIONAL_BUG),
        remediation_safe_count=sum(
            1
            for g in gates
            if g in (RemediationSafetyGate.SAFE_TO_REMOVE_REGISTRY, RemediationSafetyGate.SAFE_TO_FIX_SOURCE)
        ),
        protected_count=sum(1 for g in gates if g is RemediationSafetyGate.PROTECTED),
        insufficient_evidence_count=sum(
            1 for g in gates if g is RemediationSafetyGate.BLOCKED_INSUFFICIENT_EVIDENCE
        ),
        analyzer_partial_or_unknown_count=sum(
            1
            for supervision in supervisions
            if supervision.coverage.state is not CoverageState.COMPLETE
        ),
    )


class ScanCoordinator:
    """Own at most one logical evaluation and one merged pending request."""

    def __init__(
        self,
        source: OperationalSourcePort,
        repository: PersistenceUnitOfWorkPort,
        projection: ProjectionPort,
        *,
        supervisor: AnalyzerSupervisor | None = None,
        supervisors: tuple[SupervisorPort, ...] | None = None,
        clock: Clock | None = None,
        profile: PerformanceProfile = PerformanceProfile.CONSERVATIVE,
        timeout_seconds: float = 30.0,
        scan_id_factory: Callable[[], str] | None = None,
        reference_source: ReferenceIndexPort | None = None,
        temporal_evidence_source: TemporalEvidenceSourcePort | None = None,
    ) -> None:
        self._source = source
        self._repository = repository
        self._projection = projection
        # `supervisors` is the general case: each supervisor governs
        # exactly one analyzer (its own AnalyzerSupervisor or
        # WholeCollectionSupervisor instance -- see
        # analysis/supervisor.py's SupervisorPort and
        # analysis/whole_collection_supervisor.py for the two kinds),
        # and every one of them runs over the same capture this scan
        # cycle. `supervisor` remains supported unchanged for
        # single-analyzer callers/tests -- passing both is invalid, and
        # passing neither preserves the exact prior single-
        # `UnavailableEntityAnalyzer` default.
        if supervisors is not None and supervisor is not None:
            raise ValueError("pass either supervisor or supervisors, not both")
        self._supervisors: tuple[SupervisorPort, ...] = supervisors or (
            (supervisor or AnalyzerSupervisor()),
        )
        self._clock = clock or SystemClock()
        self._profile = profile
        self._timeout_seconds = timeout_seconds
        self._scan_id_factory = scan_id_factory or (lambda: uuid4().hex)
        # Both optional and purely additive (mission Part 1.2/1.4):
        # omitting either preserves the exact prior behavior (every
        # analyzer runs with reference_index=None; no temporal evidence
        # is attached to unavailable-entity findings).
        self._reference_source = reference_source
        self._temporal_evidence_source = temporal_evidence_source
        self._lock = asyncio.Lock()
        self._runner: asyncio.Task[None] | None = None
        self._active_waiters: list[asyncio.Future[ScanResult]] = []
        self._pending_triggers: set[str] = set()
        self._pending_waiters: list[asyncio.Future[ScanResult]] = []
        self._cancelling = False
        self._lifecycle: ScanLifecyclePort | None = None

    def set_lifecycle_port(self, lifecycle: ScanLifecyclePort) -> None:
        """Attach the application lifecycle sink before the runtime starts."""
        self._lifecycle = lifecycle

    @property
    def is_running(self) -> bool:
        """Return whether scan work currently exists."""
        return self._runner is not None and not self._runner.done()

    async def async_request_scan(self, *, trigger: str = "manual") -> ScanResult:
        """Request a scan; concurrent duplicates merge into one pending scan."""
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[ScanResult] = loop.create_future()
        pending_requests = 0
        async with self._lock:
            if self._cancelling:
                raise ScanCoordinatorStoppingError(
                    "scan coordinator is cancelling owned work"
                )
            if self._runner is None or self._runner.done():
                self._active_waiters = [waiter]
                self._runner = asyncio.create_task(
                    self._run_loop(trigger, [waiter]), name="hamie_scan"
                )
            else:
                self._pending_triggers.add(trigger)
                self._pending_waiters.append(waiter)
                pending_requests = 1
        if pending_requests:
            await self._notify_projection("async_queue_changed", pending_requests)
        return await asyncio.shield(waiter)

    async def async_cancel(self) -> None:
        """Cancel current and pending scan work without committing partial state."""
        async with self._lock:
            self._cancelling = True
            runner = self._runner
            self._pending_triggers.clear()
            waiters = tuple(self._active_waiters + self._pending_waiters)
            self._active_waiters.clear()
            self._pending_waiters.clear()
        for waiter in waiters:
            if not waiter.done():
                waiter.cancel()
        try:
            if runner is not None and not runner.done():
                runner.cancel()
                try:
                    await runner
                except asyncio.CancelledError:
                    pass
        finally:
            async with self._lock:
                late_waiters = tuple(self._active_waiters + self._pending_waiters)
                self._active_waiters.clear()
                self._pending_waiters.clear()
                self._pending_triggers.clear()
                self._cancelling = False
            for waiter in late_waiters:
                if not waiter.done():
                    waiter.cancel()

    async def _run_loop(
        self, trigger: str, waiters: list[asyncio.Future[ScanResult]]
    ) -> None:
        try:
            current_trigger = trigger
            current_waiters = waiters
            while True:
                try:
                    result = await self._execute(current_trigger)
                except BaseException as err:
                    if isinstance(err, asyncio.CancelledError):
                        await self._notify_projection("async_scan_cancelled")
                    else:
                        summary = redact_secret_looking_text(
                            str(err).strip()[:200] or None
                        )
                        await self._notify_projection(
                            "async_scan_failed",
                            error_classification=type(err).__name__,
                            # Bounded, best-effort-redacted summary only
                            # -- the real traceback already went to the
                            # log above; this is what a diagnostics
                            # payload or a UI is allowed to show.
                            error_summary=summary,
                        )
                    for waiter in current_waiters:
                        if not waiter.done():
                            if isinstance(err, asyncio.CancelledError):
                                waiter.cancel()
                            else:
                                waiter.set_exception(err)
                    if isinstance(err, asyncio.CancelledError):
                        raise
                else:
                    for waiter in current_waiters:
                        if not waiter.done():
                            waiter.set_result(result)

                async with self._lock:
                    if not self._pending_waiters:
                        self._active_waiters = []
                        self._runner = None
                        return
                    current_waiters = self._pending_waiters
                    self._active_waiters = current_waiters
                    self._pending_waiters = []
                    current_trigger = "+".join(sorted(self._pending_triggers))
                    self._pending_triggers.clear()
                await self._notify_projection("async_queue_changed", 0)
        finally:
            async with self._lock:
                if self._runner is asyncio.current_task():
                    self._active_waiters = []
                    self._runner = None

    async def _execute(self, trigger: str) -> ScanResult:
        started_at = self._clock.now()
        started_clock = monotonic()
        scan_id = self._scan_id_factory()
        baseline = await self._repository.async_load()
        await self._notify_projection(
            "async_scan_started",
            scan_id=scan_id,
            started_at=started_at,
            runtime_profile=self._profile.value,
        )
        await self._notify_lifecycle(
            "async_scan_started",
            scan_id=scan_id,
            trigger=trigger,
            generation=baseline.generation,
            projection_revision=baseline.projection_revision,
        )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                capture = await self._source.async_capture_entities()
                observed_at = self._clock.now()
                # Reference/dependency evidence (mission Part 1.4):
                # optional and captured defensively -- a failure here
                # (or no reference_source configured at all) must never
                # abort the scan; it only means every analyzer this
                # cycle runs with reference_index=None, exactly the
                # prior behavior, and every affected recommendation
                # stays at its weaker, no-reference-evidence strength
                # (see orphaned_definitions.py/duplicate_migration.py's
                # own conservative fallbacks for what "no reference
                # index" produces).
                reference_index = None
                if self._reference_source is not None:
                    try:
                        reference_index = (
                            await self._reference_source.async_capture_reference_index()
                        )
                    except Exception:
                        _LOGGER.exception(
                            "HAMIE reference-index capture failed; this scan's "
                            "analyzers will run without reference evidence"
                        )
                        reference_index = None
                # Every registered supervisor (one per analyzer) runs
                # over the identical capture -- each is independently
                # partitioned (or, for a whole-collection analyzer, run
                # once -- see WholeCollectionSupervisor) per its own
                # analyzer's own scheduling, so this never duplicates
                # work across analyzers.
                supervisions = [
                    await one.async_evaluate(
                        capture,
                        observed_at=observed_at,
                        profile=self._profile,
                        timeout_seconds=self._timeout_seconds,
                        reference_index=reference_index,
                    )
                    for one in self._supervisors
                ]
                # Temporal (recorder/statistics) evidence enrichment
                # (mission Part 1.2): additive-only, never changes which
                # findings exist or their recommendation kind -- see
                # analysis/temporal_enrichment.py's module docstring for
                # why this is enrichment rather than a standalone
                # analyzer. A no-op for any supervision that is not
                # UnavailableEntityAnalyzer's own.
                supervisions = [
                    await async_enrich_unavailable_findings_with_temporal_evidence(
                        supervision,
                        source=self._temporal_evidence_source,
                        observed_at=observed_at,
                    )
                    for supervision in supervisions
                ]
                current = await self._repository.async_load()
                reconciled_at = self._clock.now()
                # reconcile_findings only ever resolves findings whose
                # analyzer_id matches the one SupervisionResult it was
                # given (reconciliation.py line ~173), so chaining it
                # once per analyzer over the same accumulating
                # `findings` tuple is safe: each pass only touches its
                # own analyzer's findings and leaves every other
                # analyzer's findings untouched.
                findings = current.findings
                created = retained = resolved = unchanged = 0
                for supervision in supervisions:
                    findings, counts = reconcile_findings(
                        findings,
                        supervision,
                        seen_at=reconciled_at,
                        scan_id=scan_id,
                    )
                    created += counts.created
                    retained += counts.retained
                    resolved += counts.resolved
                    unchanged += counts.unchanged
                findings, reviews = record_policy_reopens(
                    current.findings,
                    findings,
                    current.reviews,
                    at=reconciled_at,
                )
                findings, reviews = reopen_expired_snoozes(
                    findings,
                    reviews,
                    reconfirmed_finding_ids=frozenset(
                        finding.finding_id
                        for supervision in supervisions
                        for finding in supervision.findings
                    ),
                    at=reconciled_at,
                )
                findings, reviews, audits = apply_suppression_reviews(
                    findings,
                    reviews,
                    current.audits,
                    grouping_rules=current.grouping_rules,
                    suppression_rules=current.suppression_rules,
                    at=reconciled_at,
                )
                groups = ExplorerIndex(
                    findings=findings,
                    grouping_rules=current.grouping_rules,
                    suppression_rules=current.suppression_rules,
                    recommendations=current.recommendations,
                    audits=audits,
                    generation=current.generation + 1,
                    at=reconciled_at,
                ).groups
                incident_build = build_incidents(findings)
                incidents = reconcile_incidents(
                    current.incidents,
                    incident_build.incidents,
                    at=reconciled_at,
                    scan_id=scan_id,
                )
                ended_at = self._clock.now()
                duration_ms = max(0, int((monotonic() - started_clock) * 1000))
                state_value = (
                    EvaluationState.COMPLETE
                    if all(
                        supervision.coverage.state.value == "complete"
                        for supervision in supervisions
                    )
                    else EvaluationState.PARTIAL
                )
                evaluation = EvaluationRecord(
                    identity=EvaluationIdentity(
                        scan_id=scan_id, generation=current.generation + 1
                    ),
                    trigger=trigger,
                    started_at=started_at,
                    ended_at=ended_at,
                    state=state_value,
                    captures=(capture.metadata,),
                    # One CoverageAssessment per analyzer -- EvaluationRecord
                    # already accepts and sorts a tuple of these by
                    # analyzer_id (domain/evaluations.py), so a multi-analyzer
                    # scan reports every analyzer's real, independent
                    # coverage rather than collapsing them into one.
                    coverage=tuple(
                        supervision.coverage for supervision in supervisions
                    ),
                    metrics=EvaluationMetrics(
                        duration_ms=duration_ms,
                        analyzer_duration_ms=sum(
                            supervision.analyzer_duration_ms
                            for supervision in supervisions
                        ),
                        partitions_processed=sum(
                            supervision.partitions_processed
                            for supervision in supervisions
                        ),
                        partitions_skipped=sum(
                            supervision.partitions_skipped
                            for supervision in supervisions
                        ),
                        findings_created=created,
                        findings_retained=retained,
                        findings_resolved=resolved,
                        findings_unchanged=unchanged,
                        active_profile=self._profile.value,
                        concurrency_used=max(
                            (
                                supervision.concurrency_used
                                for supervision in supervisions
                            ),
                            default=1,
                        ),
                    ),
                )
                next_state = replace(
                    current,
                    generation=current.generation + 1,
                    findings=findings,
                    reviews=reviews,
                    evaluations=(*current.evaluations, evaluation)[-5:],
                    projection_revision=current.projection_revision + 1,
                    recommendations=mark_recommendations_stale(
                        current.recommendations,
                        findings,
                        groups,
                    ),
                    audits=audits,
                    incidents=incidents,
                )
                await self._repository.async_commit(
                    next_state, expected_generation=current.generation
                )
        except Exception as err:
            elapsed_ms = max(0, int((monotonic() - started_clock) * 1000))
            # ERROR with the real traceback for operators; the message
            # itself carries only bounded, non-sensitive fields (never
            # str(err) beyond the exception type name) -- exception text
            # from a third-party integration's entity data could contain
            # anything, and this is a log sink, not a user-facing surface.
            _LOGGER.error(
                "HAMIE scan failed: scan_id=%s trigger=%s elapsed_ms=%d "
                "error_classification=%s",
                scan_id,
                trigger,
                elapsed_ms,
                type(err).__name__,
                exc_info=True,
            )
            await self._notify_lifecycle(
                "async_scan_failed",
                scan_id=scan_id,
                error_code=type(err).__name__,
                generation=baseline.generation,
                projection_revision=baseline.projection_revision,
            )
            raise
        await self._projection.async_sync(next_state)
        # mission Part 6: normal-level logging stays scan-summary only
        # (never per-finding) -- gate counts are computed from this
        # cycle's raw supervisions (every CandidateFinding's
        # recommendation.safety_gate), not the reconciled `findings`
        # tuple, so a resolved-and-dropped finding from a prior scan
        # never double-counts here.
        gate_counts = _safety_gate_summary(supervisions)
        _LOGGER.info(
            "HAMIE scan completed: scan_id=%s trigger=%s elapsed_ms=%d "
            "entities=%d findings_created=%d findings_retained=%d "
            "findings_resolved=%d candidates=%d functional_bug=%d "
            "remediation_safe=%d protected=%d insufficient_evidence=%d "
            "analyzer_partial_or_unknown=%d incidents=%d "
            "findings_represented=%d normal_candidates=%d "
            "suppressed_candidates=%d context_reduction=%.3f coverage=%s",
            scan_id,
            trigger,
            duration_ms,
            len(capture.entities),
            created,
            retained,
            resolved,
            gate_counts.candidate_count,
            gate_counts.functional_bug_count,
            gate_counts.remediation_safe_count,
            gate_counts.protected_count,
            gate_counts.insufficient_evidence_count,
            gate_counts.analyzer_partial_or_unknown_count,
            sum(item.is_active for item in incidents),
            incident_build.represented_finding_count,
            len(incident_build.normal_finding_ids),
            len(incident_build.suppressed_finding_ids),
            incident_build.context_reduction_ratio,
            ",".join(
                f"{supervision.coverage.analyzer_id}={supervision.coverage.state.value}"
                for supervision in supervisions
            ),
        )
        await self._notify_lifecycle(
            "async_scan_committed",
            current,
            next_state,
            scan_id=scan_id,
        )
        return ScanResult(evaluation=evaluation, state=next_state)

    async def _notify_projection(
        self, method_name: str, *args: object, **kwargs: object
    ) -> None:
        """Call additive projection lifecycle hooks when supported."""
        method = getattr(self._projection, method_name, None)
        if method is not None:
            await method(*args, **kwargs)

    async def _notify_lifecycle(
        self, method_name: str, *args: object, **kwargs: object
    ) -> None:
        """Invoke optional connector publication without affecting scan success."""
        if self._lifecycle is None:
            return
        method = getattr(self._lifecycle, method_name)
        try:
            await method(*args, **kwargs)
        except Exception:
            return
