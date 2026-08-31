"""Internal deterministic analyzer contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..application.ports import EntityRecord
from ..domain.common import require_non_empty, stable_digest
from ..domain.findings import CandidateFinding, RecommendationKind


class CostClass(StrEnum):
    """Bounded analyzer cost declaration."""

    LIGHT = "light"
    MODERATE = "moderate"
    HEAVY = "heavy"


class AnalyzerOutcomeState(StrEnum):
    """Structured analyzer-partition result state."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AnalyzerDescriptor:
    """Static analyzer authority and resource declaration."""

    analyzer_id: str
    policy_version: str
    capability_id: str
    cost_class: CostClass
    allowed_recommendations: tuple[RecommendationKind, ...]
    max_partition_size: int

    def __post_init__(self) -> None:
        for value, name in (
            (self.analyzer_id, "analyzer_id"),
            (self.policy_version, "policy_version"),
            (self.capability_id, "capability_id"),
        ):
            require_non_empty(value, name)
        if "@" not in self.capability_id:
            raise ValueError("capability_id must be versioned")
        if self.max_partition_size < 1:
            raise ValueError("max_partition_size must be positive")
        if not self.allowed_recommendations:
            raise ValueError("analyzer must declare recommendation authority")


@dataclass(frozen=True, slots=True)
class AnalysisPartition:
    """Immutable capability-and-subject analyzer input."""

    partition_id: str
    capability_id: str
    source_revision: str
    records: tuple[EntityRecord, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.partition_id, "partition_id")
        require_non_empty(self.capability_id, "capability_id")
        require_non_empty(self.source_revision, "source_revision")
        entity_ids = [item.entity_id for item in self.records]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("partition subjects must be unique")
        object.__setattr__(
            self,
            "records",
            tuple(sorted(self.records, key=lambda item: item.entity_id)),
        )

    @property
    def semantic_revision(self) -> str:
        """Return a cache key independent of scheduling and partition order."""
        return stable_digest(
            self.capability_id,
            self.source_revision,
            *(item.record_revision for item in self.records),
        )


@dataclass(frozen=True, slots=True)
class AnalyzerOutcome:
    """Bounded side-effect-free analyzer result."""

    analyzer_id: str
    policy_version: str
    partition_id: str
    state: AnalyzerOutcomeState
    findings: tuple[CandidateFinding, ...]
    covered_subjects: tuple[str, ...]
    excluded_subjects: tuple[str, ...] = ()
    uncovered_subjects: tuple[str, ...] = ()
    stale_subjects: tuple[str, ...] = ()
    indeterminate_subjects: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, name in (
            (self.analyzer_id, "analyzer_id"),
            (self.policy_version, "policy_version"),
            (self.partition_id, "partition_id"),
        ):
            require_non_empty(value, name)
        object.__setattr__(
            self,
            "findings",
            tuple(sorted(self.findings, key=lambda item: item.finding_id)),
        )
        names = (
            "covered_subjects",
            "excluded_subjects",
            "uncovered_subjects",
            "stale_subjects",
            "indeterminate_subjects",
            "warnings",
        )
        for name in names:
            object.__setattr__(self, name, tuple(sorted(set(getattr(self, name)))))
        classifications = [set(getattr(self, name)) for name in names[:-1]]
        for index, values in enumerate(classifications):
            if any(values & other for other in classifications[index + 1 :]):
                raise ValueError("outcome subject classifications must be disjoint")
        finding_subjects = {item.subject.source_id for item in self.findings}
        if not finding_subjects <= set(self.covered_subjects):
            raise ValueError("every finding subject must be covered")
