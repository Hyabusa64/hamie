"""Bounded deterministic supervision for whole-collection analyzers.

Sibling of ``analysis/supervisor.py::AnalyzerSupervisor``, added instead
of extending it (mission Part 1.1). ``AnalyzerSupervisor`` exists to
safely *partition* a capture and cache each partition independently
(see its own module docstring and ``_partitions``); that is the correct
shape for ``UnavailableEntityAnalyzer``/``OrphanedDefinitionAnalyzer``,
both of which classify one entity at a time with no cross-entity
comparison. ``DuplicateMigrationAnalyzer``
(``analysis/analyzers/duplicate_migration.py``) is structurally
different: suffix-duplicate grouping is a **whole-collection**
operation (``light.island_lamp`` must be compared against
``light.island_lamp_2``, and nothing guarantees two suffix siblings
ever land in the same ``AnalyzerSupervisor`` partition -- partitions are
sliced from the sorted entity list at a fixed batch size, unrelated to
which entities share a suffix group). Bending ``AnalyzerSupervisor`` to
accept a whole-collection analyzer would mean either (a) forcing a
single giant partition regardless of the configured performance
profile's batch size -- silently defeating the profile's own resource
bound for every other analyzer sharing that supervisor type, or
(b) adding a partition-count special case into ``AnalyzerSupervisor``
itself that only one analyzer ever uses. Both distort a contract that
is otherwise correct and well-tested for its actual job. A second,
small supervisor class -- implementing the exact same
``async_evaluate(capture, *, observed_at, profile, timeout_seconds,
custom_limits=None, reference_index=None) -> SupervisionResult``
call shape ``ScanCoordinator`` already invokes uniformly over every
entry in its ``supervisors`` tuple -- is the honest fix: it plugs into
the identical scheduling/reconciliation pipeline
(``application/scan_coordinator.py``, ``application/reconciliation.py``)
with zero changes to either, while never claiming a per-partition
resource bound this analyzer's whole-collection design cannot actually
honor.

``profile``/``custom_limits`` are accepted only for interface parity
with ``AnalyzerSupervisor.async_evaluate`` (so ``ScanCoordinator`` can
call every supervisor identically) and are otherwise inert here: there
is exactly one synchronous pass over the whole capture, so there is
nothing to size a batch or a concurrency level for.

**Coverage semantics are intentionally narrower than
``AnalyzerSupervisor``'s.** ``UnavailableEntityAnalyzer``/
``OrphanedDefinitionAnalyzer`` cover "every entity in the house";
``DuplicateMigrationAnalyzer`` covers "every suffix-duplicate group
found," a different and much smaller universe by design (see
``DuplicateMigrationAnalyzer.analyze_collection``'s docstring). This
supervisor's ``CoverageAssessment.requested_subjects`` is therefore
built from the analyzer's own reported ``covered_subjects`` (plus
``excluded``/``uncovered``/``indeterminate``, all empty for this
analyzer today), never from every entity_id in the capture -- doing the
latter would force this analyzer to falsely claim either coverage or
exclusion of entities it never actually reasoned about at the group
level.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Protocol

from ..application.ports import EntityCapture
from ..domain.common import require_utc, stable_digest
from ..domain.dependency_references import EntityReferenceIndex, reference_index_revision
from ..domain.evaluations import CoverageAssessment, CoverageState
from .contracts import AnalyzerOutcome
from .supervisor import ExecutionLimits, PerformanceProfile, SupervisionResult


def _context_revision(value: object | None) -> str:
    """Fold an optional whole-capture context object into the cache key.

    Defensive/duck-typed (never imports the concrete infrastructure
    types -- see ``EntityCapture``'s own docstring): reads
    ``raw_files``/``live_config_entry_domains``/``custom_component_dirs``
    off whatever was supplied, when present, so a scan whose config
    package text or installation topology genuinely changed (with no
    corresponding entity-registry change) never returns a stale cached
    outcome -- the same correctness property
    ``dependency_references.reference_index_revision`` already
    guarantees for ``reference_index``.
    """
    if value is None:
        return "no-context"
    raw_files = getattr(value, "raw_files", None)
    if isinstance(raw_files, dict):
        return stable_digest(tuple(sorted(raw_files.items())))
    domains = getattr(value, "live_config_entry_domains", None)
    dirs = getattr(value, "custom_component_dirs", None)
    if domains is not None or dirs is not None:
        return stable_digest(
            tuple(sorted(domains or ())), tuple(sorted(dirs or ()))
        )
    return "unrecognized-context"


class WholeCollectionAnalyzer(Protocol):
    """The contract a whole-collection analyzer must satisfy.

    Deliberately not ``analysis.contracts.AnalyzerDescriptor``'s
    per-partition ``analyze`` method -- see module docstring. Any
    analyzer used with ``WholeCollectionSupervisor`` needs a
    ``descriptor`` (same ``AnalyzerDescriptor`` shape, reused for its
    ``analyzer_id``/``policy_version``/``allowed_recommendations``
    authority checks below) and an ``analyze_collection`` method with
    this exact keyword shape.
    """

    @property
    def descriptor(self) -> object: ...  # AnalyzerDescriptor, see analysis/contracts.py

    def analyze_collection(
        self,
        records: tuple[object, ...],
        *,
        observed_at: datetime,
        reference_index: EntityReferenceIndex | None = None,
        source_index: object | None = None,
        installation_topology: object | None = None,
        skipped_subjects: frozenset[str] = frozenset(),
    ) -> AnalyzerOutcome: ...


@dataclass(frozen=True, slots=True)
class WholeCollectionSupervisorOptions:
    """Optional additive inputs only a whole-collection analyzer needs."""

    source_index: object | None = None


class WholeCollectionSupervisor:
    """Execute one whole-collection analyzer once per capture."""

    def __init__(
        self,
        analyzer: WholeCollectionAnalyzer,
        *,
        options: WholeCollectionSupervisorOptions | None = None,
        cache_entries: int = 8,
    ) -> None:
        self._analyzer = analyzer
        self._options = options or WholeCollectionSupervisorOptions()
        self._cache_entries = max(0, cache_entries)
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

        Mirrors ``AnalyzerSupervisor.async_evaluate``'s staleness/
        consistency early-return and timeout discipline exactly, so a
        caller iterating ``ScanCoordinator``'s ``supervisors`` tuple
        cannot tell, from behavior alone, which kind of supervisor it is
        talking to.
        """
        at = require_utc(observed_at, "observed_at")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        descriptor = self._analyzer.descriptor
        if (
            not capture.metadata.consistent
            or capture.metadata.is_stale_at(at)
            or capture.metadata.missing_scopes
        ):
            return SupervisionResult(
                findings=(),
                coverage=CoverageAssessment(
                    analyzer_id=descriptor.analyzer_id,
                    policy_version=descriptor.policy_version,
                    state=CoverageState.UNKNOWN,
                    requested_subjects=(),
                    covered_subjects=(),
                ),
                partitions_processed=0,
                partitions_skipped=0,
                analyzer_duration_ms=0,
                concurrency_used=1,
            )

        # `capture.source_index`/`capture.installation_topology` (mission
        # Part 2) are the *fresh*, per-capture values built this scan --
        # preferred over `self._options.source_index`, the static
        # construction-time fallback kept only for callers/tests that
        # never went through `EntityCapture`'s newer fields (see
        # `EntityCapture`'s own docstring in application/ports.py).
        source_index = (
            capture.source_index
            if capture.source_index is not None
            else self._options.source_index
        )
        installation_topology = getattr(capture, "installation_topology", None)
        cache_key = stable_digest(
            descriptor.analyzer_id,
            descriptor.policy_version,
            capture.metadata.revision,
            reference_index_revision(reference_index),
            _context_revision(source_index),
            _context_revision(installation_topology),
            at.isoformat(),
        )
        started = monotonic()
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            outcome = cached
            processed, skipped = 0, 1
        else:
            async with asyncio.timeout(timeout_seconds):
                outcome = self._analyzer.analyze_collection(
                    capture.entities,
                    observed_at=at,
                    reference_index=reference_index,
                    source_index=source_index,
                    installation_topology=installation_topology,
                    # Complete, uncapped set of entities this capture failed
                    # to normalize. An analyzer needs it to tell "absent from
                    # the installation" from "present but unreadable now".
                    skipped_subjects=getattr(capture, "skipped_subjects", frozenset()),
                )
                await asyncio.sleep(0)
            processed, skipped = 1, 0
            if self._cache_entries:
                self._cache[cache_key] = outcome
                self._cache.move_to_end(cache_key)
                while len(self._cache) > self._cache_entries:
                    self._cache.popitem(last=False)
        duration_ms = max(0, int((monotonic() - started) * 1000))

        if (
            outcome.analyzer_id != descriptor.analyzer_id
            or outcome.policy_version != descriptor.policy_version
        ):
            raise ValueError("analyzer outcome authority does not match descriptor")
        if any(
            finding.recommendation.kind not in descriptor.allowed_recommendations
            for finding in outcome.findings
        ):
            raise ValueError("analyzer emitted an unauthorized recommendation")
        finding_ids = [item.finding_id for item in outcome.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("analyzer emitted duplicate stable finding IDs")

        requested = tuple(
            sorted(
                set(outcome.covered_subjects)
                | set(outcome.excluded_subjects)
                | set(outcome.uncovered_subjects)
                | set(outcome.stale_subjects)
                | set(outcome.indeterminate_subjects)
            )
        )
        has_gaps = bool(
            outcome.uncovered_subjects
            or outcome.stale_subjects
            or outcome.indeterminate_subjects
        )
        return SupervisionResult(
            findings=outcome.findings,
            coverage=CoverageAssessment(
                analyzer_id=descriptor.analyzer_id,
                policy_version=descriptor.policy_version,
                state=(CoverageState.PARTIAL if has_gaps else CoverageState.COMPLETE),
                requested_subjects=requested,
                covered_subjects=outcome.covered_subjects,
                excluded_subjects=outcome.excluded_subjects,
                uncovered_subjects=outcome.uncovered_subjects,
                stale_subjects=outcome.stale_subjects,
                indeterminate_subjects=outcome.indeterminate_subjects,
            ),
            partitions_processed=processed,
            partitions_skipped=skipped,
            analyzer_duration_ms=duration_ms,
            concurrency_used=1,
        )

    def clear_cache(self) -> None:
        """Drop the bounded performance-only cache."""
        self._cache.clear()
