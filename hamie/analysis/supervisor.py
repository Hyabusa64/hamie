"""Bounded deterministic in-process analyzer supervision."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from time import monotonic
from typing import Protocol

from ..application.ports import EntityCapture
from ..domain.common import require_utc, stable_digest
from ..domain.dependency_references import EntityReferenceIndex, reference_index_revision
from ..domain.evaluations import CoverageAssessment, CoverageState
from ..domain.findings import CandidateFinding
from .analyzers.unavailable_entities import UnavailableEntityAnalyzer
from .contracts import AnalysisPartition, AnalyzerOutcome


class PerformanceProfile(StrEnum):
    """Scheduling-only resource profiles."""

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    PERFORMANCE = "performance"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    """Bounded profile settings that cannot alter analysis semantics."""

    concurrency: int
    batch_size: int
    cache_entries: int = 64

    def __post_init__(self) -> None:
        if not 1 <= self.concurrency <= 8:
            raise ValueError("concurrency must be between 1 and 8")
        if not 1 <= self.batch_size <= 128:
            raise ValueError("batch_size must be between 1 and 128")
        if not 0 <= self.cache_entries <= 256:
            raise ValueError("cache_entries must be between 0 and 256")


PROFILE_LIMITS = {
    PerformanceProfile.CONSERVATIVE: ExecutionLimits(1, 32),
    PerformanceProfile.BALANCED: ExecutionLimits(2, 64),
    PerformanceProfile.PERFORMANCE: ExecutionLimits(4, 128),
}


@dataclass(frozen=True, slots=True)
class SupervisionResult:
    """Canonical reduced result for one analyzer over one capture."""

    findings: tuple[CandidateFinding, ...]
    coverage: CoverageAssessment
    partitions_processed: int
    partitions_skipped: int
    analyzer_duration_ms: int
    concurrency_used: int


class SupervisorPort(Protocol):
    """The call shape ``application/scan_coordinator.py`` invokes uniformly
    over every entry in its ``supervisors`` tuple (mission Part 1.1).

    Both ``AnalyzerSupervisor`` (below, per-partition analyzers) and
    ``analysis.whole_collection_supervisor.WholeCollectionSupervisor``
    (whole-collection analyzers, e.g.
    ``DuplicateMigrationAnalyzer``) satisfy this Protocol without
    inheriting from a shared base class -- ``ScanCoordinator`` never
    needs to know or care which kind of supervisor it is holding.
    """

    async def async_evaluate(
        self,
        capture: EntityCapture,
        *,
        observed_at: datetime,
        profile: PerformanceProfile = PerformanceProfile.CONSERVATIVE,
        timeout_seconds: float = 30.0,
        custom_limits: ExecutionLimits | None = None,
        reference_index: EntityReferenceIndex | None = None,
    ) -> SupervisionResult: ...


class AnalyzerSupervisor:
    """Execute one governed analyzer sequentially or with bounded concurrency."""

    def __init__(self, analyzer: UnavailableEntityAnalyzer | None = None) -> None:
        self._analyzer = analyzer or UnavailableEntityAnalyzer()
        self._cache: OrderedDict[str, AnalyzerOutcome] = OrderedDict()

    async def async_evaluate(
        self,
        capture: EntityCapture,
        *,
        observed_at: datetime,
        profile: PerformanceProfile = PerformanceProfile.CONSERVATIVE,
        timeout_seconds: float = 30.0,
        custom_limits: ExecutionLimits | None = None,
        reference_index: EntityReferenceIndex | None = None,
    ) -> SupervisionResult:
        """Evaluate a capture with cancellation and a hard logical timeout.

        ``reference_index`` is optional and purely additive (mission
        Part 1.4): when supplied, it is threaded through unchanged to
        every partition's ``analyzer.analyze(..., reference_index=...)``
        call -- the same pre-existing, optional keyword both
        ``UnavailableEntityAnalyzer`` and ``OrphanedDefinitionAnalyzer``
        already accept (see their own ``analyze`` docstrings). Omitting
        it preserves the exact prior behavior. It is also folded into
        this call's cache key (see ``_run_partitions``) so a changed
        reference index is never served a stale cached outcome computed
        against a previous (or absent) one.
        """
        at = require_utc(observed_at, "observed_at")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        limits = self._limits(profile, custom_limits)
        requested = tuple(item.entity_id for item in capture.entities)

        if (
            not capture.metadata.consistent
            or capture.metadata.is_stale_at(at)
            or capture.metadata.missing_scopes
        ):
            stale = requested if capture.metadata.is_stale_at(at) else ()
            uncovered = requested if not stale else ()
            return SupervisionResult(
                findings=(),
                coverage=CoverageAssessment(
                    analyzer_id=self._analyzer.descriptor.analyzer_id,
                    policy_version=self._analyzer.descriptor.policy_version,
                    state=CoverageState.UNKNOWN,
                    requested_subjects=requested,
                    covered_subjects=(),
                    uncovered_subjects=uncovered,
                    stale_subjects=stale,
                ),
                partitions_processed=0,
                partitions_skipped=0,
                analyzer_duration_ms=0,
                concurrency_used=1,
            )

        partitions = self._partitions(capture, limits.batch_size)
        started = monotonic()
        async with asyncio.timeout(timeout_seconds):
            outcomes, processed, skipped = await self._run_partitions(
                partitions,
                observed_at=at,
                limits=limits,
                reference_index=reference_index,
            )
        duration_ms = max(0, int((monotonic() - started) * 1000))
        return self._reduce(
            capture,
            outcomes,
            processed=processed,
            skipped=skipped,
            duration_ms=duration_ms,
            concurrency_used=min(limits.concurrency, max(1, len(partitions))),
        )

    def clear_cache(self) -> None:
        """Drop the bounded performance-only cache."""
        self._cache.clear()

    def _limits(
        self, profile: PerformanceProfile, custom: ExecutionLimits | None
    ) -> ExecutionLimits:
        if profile is PerformanceProfile.CUSTOM:
            if custom is None:
                raise ValueError("custom profile requires explicit bounded limits")
            return custom
        if custom is not None:
            raise ValueError("custom limits require the custom profile")
        return PROFILE_LIMITS[profile]

    def _partitions(
        self, capture: EntityCapture, batch_size: int
    ) -> tuple[AnalysisPartition, ...]:
        records = capture.entities
        partitions: list[AnalysisPartition] = []
        for offset in range(0, len(records), batch_size):
            batch = records[offset : offset + batch_size]
            record_revision = stable_digest(*(item.record_revision for item in batch))
            first = batch[0].entity_id
            last = batch[-1].entity_id
            partitions.append(
                AnalysisPartition(
                    partition_id=stable_digest(
                        self._analyzer.descriptor.capability_id, first, last
                    )[:24],
                    capability_id=self._analyzer.descriptor.capability_id,
                    source_revision=record_revision,
                    records=batch,
                )
            )
        return tuple(partitions)

    async def _run_partitions(
        self,
        partitions: tuple[AnalysisPartition, ...],
        *,
        observed_at: datetime,
        limits: ExecutionLimits,
        reference_index: EntityReferenceIndex | None = None,
    ) -> tuple[tuple[AnalyzerOutcome, ...], int, int]:
        outcomes: list[AnalyzerOutcome] = []
        missing: list[tuple[str, AnalysisPartition]] = []
        # reference_index's own revision is folded into the cache key
        # (mission Part 1.4/1.5): the same partition content with a
        # different (or newly-absent) reference index must never be
        # served the other's cached outcome -- see
        # domain/dependency_references.py::reference_index_revision's
        # docstring for the correctness bug this closes.
        reference_revision = reference_index_revision(reference_index)
        for partition in partitions:
            cache_key = stable_digest(
                self._analyzer.descriptor.analyzer_id,
                self._analyzer.descriptor.policy_version,
                partition.semantic_revision,
                self._analyzer.semantic_cache_discriminator(
                    partition, observed_at=observed_at
                ),
                reference_revision,
            )
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                outcomes.append(cached)
            else:
                missing.append((cache_key, partition))

        semaphore = asyncio.Semaphore(limits.concurrency)

        async def run_one(
            cache_key: str, partition: AnalysisPartition
        ) -> tuple[str, AnalyzerOutcome]:
            async with semaphore:
                outcome = self._analyzer.analyze(
                    partition, observed_at=observed_at, reference_index=reference_index
                )
                await asyncio.sleep(0)
                return cache_key, outcome

        if limits.concurrency == 1:
            completed = [await run_one(key, part) for key, part in missing]
        else:
            completed = list(
                await asyncio.gather(*(run_one(key, part) for key, part in missing))
            )
        for cache_key, outcome in completed:
            outcomes.append(outcome)
            if limits.cache_entries:
                self._cache[cache_key] = outcome
                self._cache.move_to_end(cache_key)
                while len(self._cache) > limits.cache_entries:
                    self._cache.popitem(last=False)
        return tuple(outcomes), len(missing), len(partitions) - len(missing)

    def _reduce(
        self,
        capture: EntityCapture,
        outcomes: tuple[AnalyzerOutcome, ...],
        *,
        processed: int,
        skipped: int,
        duration_ms: int,
        concurrency_used: int,
    ) -> SupervisionResult:
        ordered = tuple(sorted(outcomes, key=lambda item: item.partition_id))
        for outcome in ordered:
            if (
                outcome.analyzer_id != self._analyzer.descriptor.analyzer_id
                or outcome.policy_version != self._analyzer.descriptor.policy_version
            ):
                raise ValueError("analyzer outcome authority does not match descriptor")
            if any(
                finding.recommendation.kind
                not in self._analyzer.descriptor.allowed_recommendations
                for finding in outcome.findings
            ):
                raise ValueError("analyzer emitted an unauthorized recommendation")
        findings = tuple(
            sorted(
                (finding for outcome in ordered for finding in outcome.findings),
                key=lambda item: item.finding_id,
            )
        )
        finding_ids = [item.finding_id for item in findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("analyzer emitted duplicate stable finding IDs")
        covered = tuple(
            subject for outcome in ordered for subject in outcome.covered_subjects
        )
        excluded = tuple(
            subject for outcome in ordered for subject in outcome.excluded_subjects
        )
        uncovered = tuple(
            subject for outcome in ordered for subject in outcome.uncovered_subjects
        )
        stale = tuple(
            subject for outcome in ordered for subject in outcome.stale_subjects
        )
        indeterminate = tuple(
            subject for outcome in ordered for subject in outcome.indeterminate_subjects
        )
        state = (
            CoverageState.COMPLETE
            if not (uncovered or stale or indeterminate)
            else CoverageState.PARTIAL
        )
        return SupervisionResult(
            findings=findings,
            coverage=CoverageAssessment(
                analyzer_id=self._analyzer.descriptor.analyzer_id,
                policy_version=self._analyzer.descriptor.policy_version,
                state=state,
                requested_subjects=tuple(item.entity_id for item in capture.entities),
                covered_subjects=covered,
                excluded_subjects=excluded,
                uncovered_subjects=uncovered,
                stale_subjects=stale,
                indeterminate_subjects=indeterminate,
            ),
            partitions_processed=processed,
            partitions_skipped=skipped,
            analyzer_duration_ms=duration_ms,
            concurrency_used=concurrency_used,
        )
