"""Evaluation, source capture, coverage, and metric values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .common import require_non_empty, require_utc


class CoverageState(StrEnum):
    """HAMIE-calculated evaluation coverage."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class EvaluationState(StrEnum):
    """Terminal logical evaluation states."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class EvaluationIdentity:
    """Unique scan identity and target persistence generation."""

    scan_id: str
    generation: int

    def __post_init__(self) -> None:
        require_non_empty(self.scan_id, "scan_id")
        if self.generation < 1:
            raise ValueError("generation must be positive")


@dataclass(frozen=True, slots=True)
class SourceCapture:
    """Source-specific revision, freshness, and capture interval."""

    source_id: str
    capability_id: str
    revision: str
    capture_started_at: datetime
    capture_ended_at: datetime
    observed_at: datetime
    max_age_seconds: int
    requested_scopes: tuple[str, ...]
    captured_scopes: tuple[str, ...]
    missing_scopes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    consistent: bool = True

    def __post_init__(self) -> None:
        require_non_empty(self.source_id, "source_id")
        require_non_empty(self.capability_id, "capability_id")
        require_non_empty(self.revision, "revision")
        if "@" not in self.capability_id:
            raise ValueError("capability_id must include a schema version")
        started = require_utc(self.capture_started_at, "capture_started_at")
        ended = require_utc(self.capture_ended_at, "capture_ended_at")
        observed = require_utc(self.observed_at, "observed_at")
        if ended < started:
            raise ValueError("capture interval cannot be negative")
        if observed < started:
            raise ValueError("observed_at cannot precede capture start")
        if self.max_age_seconds < 1:
            raise ValueError("max_age_seconds must be positive")
        object.__setattr__(self, "capture_started_at", started)
        object.__setattr__(self, "capture_ended_at", ended)
        object.__setattr__(self, "observed_at", observed)
        for field_name in (
            "requested_scopes",
            "captured_scopes",
            "missing_scopes",
            "warnings",
        ):
            value = tuple(sorted(set(getattr(self, field_name))))
            object.__setattr__(self, field_name, value)
        requested = set(self.requested_scopes)
        if not set(self.captured_scopes) <= requested:
            raise ValueError("captured scopes must be requested")
        if not set(self.missing_scopes) <= requested:
            raise ValueError("missing scopes must be requested")
        if set(self.captured_scopes) & set(self.missing_scopes):
            raise ValueError("captured and missing scopes must be disjoint")
        if set(self.captured_scopes) | set(self.missing_scopes) != requested:
            raise ValueError("every requested scope must be captured or missing")

    def is_stale_at(self, at: datetime) -> bool:
        """Return whether this capture is stale at a UTC instant."""
        current = require_utc(at, "at")
        return (current - self.observed_at).total_seconds() > self.max_age_seconds


@dataclass(frozen=True, slots=True)
class CoverageAssessment:
    """HAMIE-calculated coverage for one analyzer evaluation."""

    analyzer_id: str
    policy_version: str
    state: CoverageState
    requested_subjects: tuple[str, ...]
    covered_subjects: tuple[str, ...]
    excluded_subjects: tuple[str, ...] = ()
    uncovered_subjects: tuple[str, ...] = ()
    stale_subjects: tuple[str, ...] = ()
    indeterminate_subjects: tuple[str, ...] = ()
    rule_version: int = 1

    def __post_init__(self) -> None:
        require_non_empty(self.analyzer_id, "analyzer_id")
        require_non_empty(self.policy_version, "policy_version")
        if self.rule_version < 1:
            raise ValueError("coverage rule_version must be positive")
        fields = (
            "requested_subjects",
            "covered_subjects",
            "excluded_subjects",
            "uncovered_subjects",
            "stale_subjects",
            "indeterminate_subjects",
        )
        for field_name in fields:
            object.__setattr__(
                self, field_name, tuple(sorted(set(getattr(self, field_name))))
            )
        requested = set(self.requested_subjects)
        classified = [set(getattr(self, field_name)) for field_name in fields[1:]]
        if any(not values <= requested for values in classified):
            raise ValueError("coverage classifications must be requested subjects")
        for index, values in enumerate(classified):
            if any(values & other for other in classified[index + 1 :]):
                raise ValueError("coverage classifications must be disjoint")
        if set().union(*classified) != requested:
            raise ValueError("every requested subject must be classified")
        if self.state is CoverageState.COMPLETE and (
            self.uncovered_subjects
            or self.stale_subjects
            or self.indeterminate_subjects
        ):
            raise ValueError("complete coverage cannot contain gaps")


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    """Bounded scan-updated observability values."""

    duration_ms: int
    analyzer_duration_ms: int
    partitions_processed: int
    partitions_skipped: int
    findings_created: int
    findings_retained: int
    findings_resolved: int
    findings_unchanged: int
    active_profile: str
    concurrency_used: int

    def __post_init__(self) -> None:
        values = (
            self.duration_ms,
            self.analyzer_duration_ms,
            self.partitions_processed,
            self.partitions_skipped,
            self.findings_created,
            self.findings_retained,
            self.findings_resolved,
            self.findings_unchanged,
        )
        if any(value < 0 for value in values):
            raise ValueError("evaluation metrics cannot be negative")
        require_non_empty(self.active_profile, "active_profile")
        if self.concurrency_used < 1:
            raise ValueError("concurrency_used must be positive")


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    """Durable bounded summary of one logical evaluation."""

    identity: EvaluationIdentity
    trigger: str
    started_at: datetime
    ended_at: datetime
    state: EvaluationState
    captures: tuple[SourceCapture, ...]
    coverage: tuple[CoverageAssessment, ...]
    metrics: EvaluationMetrics
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.trigger, "trigger")
        started = require_utc(self.started_at, "started_at")
        ended = require_utc(self.ended_at, "ended_at")
        if ended < started:
            raise ValueError("evaluation interval cannot be negative")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "ended_at", ended)
        object.__setattr__(
            self,
            "captures",
            tuple(sorted(self.captures, key=lambda item: item.source_id)),
        )
        object.__setattr__(
            self,
            "coverage",
            tuple(sorted(self.coverage, key=lambda item: item.analyzer_id)),
        )
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))
