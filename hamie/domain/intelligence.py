"""Deterministic grouping, suppression, explorer, audit, and AI advisory values."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .common import require_non_empty, require_utc, stable_digest
from .evidence import Sensitivity
from .findings import Finding, FindingLifecycle, FindingSeverity
from .llm_proposal import LlmProposedAction
from .reviews import (
    ALLOWED_PRIOR_STATES,
    ReviewAction,
    ReviewRecord,
    ReviewState,
)

GROUPING_REVISION = "grouping@1"
AI_SCHEMA_VERSION = 1
MAX_GROUPS = 2_000
MAX_PAGE_SIZE = 100
MAX_SEARCH_LENGTH = 128
MAX_GRAPH_NODES = 64
MAX_GRAPH_EDGES = 128
MAX_AUDIT_RECORDS = 500
MAX_RECOMMENDATIONS = 64
MAX_SUPPRESSION_RULES = 128
MAX_GROUPING_RULES = 64
MAX_REPRESENTATIVE_SUBJECTS = 5
MAX_AI_COVERAGE_IDS = 1_000
DEFAULT_AI_PROMPT_RESERVED_CHARACTERS = 1_200


def _json_dumps_compact(value: Any) -> str:
    """Serialize one value the same deterministic, bounded way every real
    AI prompt payload is serialized (connectors/ai_executor.py,
    connectors/ollama.py) -- so a planner's own size estimate always
    matches what actually gets sent."""
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


SUPPORTED_MATCHERS = frozenset(
    {
        "integration_domain",
        "config_entry_id",
        "device_id",
        "entity_domain",
        "entity_id",
        "entity_id_prefix",
        "area_id",
        "analyzer_id",
        "condition_key",
        "category",
        "group_id",
        "source_provider",
        "name_prefix",
        "failure_condition",
        "dependency_root",
        "severity",
    }
)


class SuppressionAction(StrEnum):
    """Bounded HAMIE-owned suppression outcomes."""

    HIDE_FROM_DEFAULT_VIEW = "hide_from_default_view"
    LOWER_PRIORITY = "lower_priority"
    AUTO_ACKNOWLEDGE = "auto_acknowledge"
    SNOOZE = "snooze"


class AIReviewState(StrEnum):
    """Human review lifecycle for advisory AI output."""

    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    RETAINED = "retained"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class GroupingRule:
    """One deterministic user-owned primary grouping override."""

    rule_id: str
    name: str
    matcher: tuple[tuple[str, str], ...]
    title: str
    enabled: bool = True
    revision: int = 1

    def __post_init__(self) -> None:
        require_non_empty(self.rule_id, "grouping rule_id")
        require_non_empty(self.name, "grouping name")
        require_non_empty(self.title, "grouping title")
        _validate_matcher(self.matcher)
        if self.revision < 1:
            raise ValueError("grouping revision must be positive")
        object.__setattr__(self, "matcher", tuple(sorted(set(self.matcher))))


@dataclass(frozen=True, slots=True)
class SuppressionRule:
    """Declarative, non-executable HAMIE suppression policy."""

    rule_id: str
    name: str
    enabled: bool
    scope: str
    matcher: tuple[tuple[str, str], ...]
    reason: str
    created_at: datetime
    created_by: str
    expiration: datetime | None
    affected_analyzer_ids: tuple[str, ...]
    action: SuppressionAction
    preview_count: int
    last_match_count: int
    revision: int = 1

    def __post_init__(self) -> None:
        for value, name in (
            (self.rule_id, "suppression rule_id"),
            (self.name, "suppression name"),
            (self.scope, "suppression scope"),
            (self.reason, "suppression reason"),
            (self.created_by, "suppression created_by"),
        ):
            require_non_empty(value, name)
        _validate_matcher(self.matcher)
        object.__setattr__(self, "matcher", tuple(sorted(set(self.matcher))))
        object.__setattr__(
            self,
            "affected_analyzer_ids",
            tuple(sorted(set(self.affected_analyzer_ids))),
        )
        object.__setattr__(
            self, "created_at", require_utc(self.created_at, "created_at")
        )
        if self.expiration is not None:
            expiration = require_utc(self.expiration, "expiration")
            if expiration <= self.created_at:
                raise ValueError("suppression expiration must follow creation")
            object.__setattr__(self, "expiration", expiration)
        if self.action is SuppressionAction.SNOOZE and self.expiration is None:
            raise ValueError("snooze suppression requires an expiration")
        if self.preview_count < 0 or self.last_match_count < 0:
            raise ValueError("suppression counts cannot be negative")
        if self.revision < 1:
            raise ValueError("suppression revision must be positive")

    def active_at(self, at: datetime) -> bool:
        """Return whether the rule is enabled and unexpired."""
        current = require_utc(at, "at")
        return self.enabled and (self.expiration is None or self.expiration > current)


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One bounded secret-free HAMIE audit event."""

    audit_id: str
    event: str
    at: datetime
    actor: str
    target_ids: tuple[str, ...]
    details: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.audit_id, "audit_id")
        require_non_empty(self.event, "audit event")
        require_non_empty(self.actor, "audit actor")
        object.__setattr__(self, "at", require_utc(self.at, "audit at"))
        object.__setattr__(self, "target_ids", tuple(sorted(set(self.target_ids))))
        object.__setattr__(self, "details", tuple(sorted(set(self.details))))
        if len(self.target_ids) > 100 or len(self.details) > 32:
            raise ValueError("audit payload exceeds bounds")
        if any(_looks_secret(key) for key, _value in self.details):
            raise ValueError("audit details cannot contain secret fields")


@dataclass(frozen=True, slots=True)
class GroupSourceBinding:
    """Persisted group facts that make advisory staleness explainable."""

    group_id: str
    grouping_revision: str
    member_digest: str
    suppression_digest: str
    dependency_root: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.group_id, "group binding group_id"),
            (self.grouping_revision, "group binding grouping_revision"),
            (self.member_digest, "group binding member_digest"),
            (self.suppression_digest, "group binding suppression_digest"),
        ):
            require_non_empty(value, name)


@dataclass(frozen=True, slots=True)
class AIRecommendation:
    """Validated advisory explanation tied to deterministic source revisions."""

    recommendation_id: str
    schema_version: int
    provider: str
    model: str
    created_at: datetime
    finding_ids: tuple[str, ...]
    group_ids: tuple[str, ...]
    summary: str
    probable_causes: tuple[str, ...]
    recommended_checks: tuple[str, ...]
    proposed_repair_plan: tuple[str, ...]
    confidence: str
    assumptions: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    risk_notes: tuple[str, ...]
    do_not_do: tuple[str, ...]
    review_state: AIReviewState
    source_revisions: tuple[tuple[str, int], ...]
    source_evidence_digests: tuple[str, ...]
    group_bindings: tuple[GroupSourceBinding, ...] = ()
    stale: bool = False
    stale_reasons: tuple[str, ...] = ()
    generated_at: datetime | None = None
    analysis_started_at: datetime | None = None
    analysis_completed_at: datetime | None = None
    evidence_first_observed_at: datetime | None = None
    evidence_last_observed_at: datetime | None = None
    source_scan_id: str | None = None
    source_scan_completed_at: datetime | None = None
    source_finding_revision: int = 1
    recommendation_revision: int = 1
    analysis_total_findings: int = 0
    analysis_eligible_findings: int = 0
    analysis_selected_findings: int = 0
    analysis_skipped_findings: int = 0
    root_cause_groups_detected: int = 0
    root_cause_groups_analyzed: int = 0
    root_cause_groups_skipped: int = 0
    selection_reason: str = (
        "highest severity and impact within configured evidence budget"
    )
    coverage_state: str = "unknown"
    llm_proposed_action: LlmProposedAction | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.recommendation_id, "recommendation_id"),
            (self.provider, "recommendation provider"),
            (self.model, "recommendation model"),
            (self.summary, "recommendation summary"),
            (self.confidence, "recommendation confidence"),
        ):
            require_non_empty(value, name)
        if self.schema_version != AI_SCHEMA_VERSION:
            raise ValueError("unsupported AI recommendation schema")
        object.__setattr__(
            self,
            "created_at",
            require_utc(self.created_at, "recommendation created_at"),
        )
        for field_name in (
            "generated_at",
            "analysis_started_at",
            "analysis_completed_at",
            "evidence_first_observed_at",
            "evidence_last_observed_at",
            "source_scan_completed_at",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, require_utc(value, field_name))
        if self.generated_at is None:
            object.__setattr__(self, "generated_at", self.created_at)
        if self.analysis_started_at is None:
            object.__setattr__(self, "analysis_started_at", self.created_at)
        if self.analysis_completed_at is None:
            object.__setattr__(self, "analysis_completed_at", self.created_at)
        if self.source_finding_revision < 1 or self.recommendation_revision < 1:
            raise ValueError("recommendation provenance revisions must be positive")
        counts = (
            self.analysis_total_findings,
            self.analysis_eligible_findings,
            self.analysis_selected_findings,
            self.analysis_skipped_findings,
            self.root_cause_groups_detected,
            self.root_cause_groups_analyzed,
            self.root_cause_groups_skipped,
        )
        if any(value < 0 for value in counts):
            raise ValueError("recommendation coverage counts cannot be negative")
        if self.coverage_state not in {"unknown", "partial", "full"}:
            raise ValueError("coverage_state must be unknown, partial, or full")
        require_non_empty(self.selection_reason, "selection_reason")
        for name in (
            "finding_ids",
            "group_ids",
            "probable_causes",
            "recommended_checks",
            "proposed_repair_plan",
            "assumptions",
            "missing_evidence",
            "risk_notes",
            "do_not_do",
            "source_evidence_digests",
        ):
            values = tuple(dict.fromkeys(getattr(self, name)))
            if len(values) > 64 or any(
                not value or len(value) > 1_000 for value in values
            ):
                raise ValueError(f"{name} exceeds AI record bounds")
            object.__setattr__(self, name, values)
        revisions = tuple(sorted(set(self.source_revisions)))
        if any(revision < 1 for _source_id, revision in revisions):
            raise ValueError("AI source revisions must be positive")
        object.__setattr__(self, "source_revisions", revisions)
        object.__setattr__(
            self,
            "group_bindings",
            tuple(sorted(set(self.group_bindings), key=lambda item: item.group_id)),
        )
        object.__setattr__(
            self, "stale_reasons", tuple(sorted(set(self.stale_reasons)))
        )


@dataclass(frozen=True, slots=True)
class AIAnalysisCoverage:
    """Deterministic accounting of which findings one AI analysis request
    actually included.

    Never merely a byproduct of persistence: a real installation's open
    findings routinely exceed what fits in one bounded prompt (see
    ExplorerIndex.plan_ai_evidence), so a completed or failed analysis
    must always be able to say honestly how much of the real picture it
    covered instead of silently implying full coverage.
    """

    eligible_total: int
    selected_finding_ids: tuple[str, ...]
    skipped_finding_ids: tuple[str, ...]
    total_findings: int = 0
    root_cause_group_ids: tuple[str, ...] = ()
    analyzed_group_ids: tuple[str, ...] = ()
    selection_reason: str = (
        "highest severity and impact within configured evidence budget"
    )

    def public_dict(self) -> dict[str, Any]:
        """What THIS request selected. Every count here is request scope.

        The names carry that scope explicitly because they did not always.
        This block previously emitted `analyzed_total` and `groups_analyzed`,
        the same names the authoritative analysis state uses for ACHIEVED
        installation-scope counts -- and they meant something else here. Live,
        a mixed run reported `groups_analyzed: 2` in this block while the
        authoritative state correctly reported 1 achieved and 1 failed,
        because `analyzed_group_ids` on this object is the set of planned
        batches, not the set that succeeded. A correct store with a
        misleading response still generates false bug reports.

        `analyzed_total` was also pure duplication -- it was defined as
        len(selected_finding_ids), exactly `selected_total`. It is gone
        rather than renamed twice.

        `total_findings` keeps its name deliberately: it is the only field
        here that really is installation scope.
        """
        return {
            "scope": "request",
            "total_findings": self.total_findings or self.eligible_total,
            "request_eligible_total": self.eligible_total,
            "request_selected_total": len(self.selected_finding_ids),
            "request_skipped_total": len(self.skipped_finding_ids),
            "request_groups_detected": len(self.root_cause_group_ids),
            "request_groups_selected": len(self.analyzed_group_ids),
            "request_groups_skipped": max(
                0, len(self.root_cause_group_ids) - len(self.analyzed_group_ids)
            ),
            "selection_reason": self.selection_reason,
            "coverage": "full" if not self.skipped_finding_ids else "partial",
            "selected_finding_ids": list(self.selected_finding_ids),
        }

    def provider_dict(self) -> dict[str, Any]:
        """Coverage accounting for a MODEL, which means counts, not id lists.

        public_dict() embeds every selected finding id. That is right for the
        operator and the audit trail, and wrong for a prompt: measured live,
        it put 3,948 characters of identifiers into every per-group request,
        growing with the number of groups the run analyzes, while telling the
        model nothing it could act on. Identifiers the model genuinely needs
        are one bounded tool call away.
        """
        return {
            key: value
            for key, value in self.public_dict().items()
            if key != "selected_finding_ids"
        }


@dataclass(frozen=True, slots=True)
class FindingGroup:
    """Deterministic primary group with bounded secondary facets."""

    group_id: str
    grouping_revision: str
    group_revision: str
    title: str
    grouping_reason: str
    member_finding_ids: tuple[str, ...]
    member_count: int
    open_count: int
    warning_count: int
    critical_count: int
    first_seen: datetime
    last_seen: datetime
    confidence: str
    representative_subjects: tuple[str, ...]
    common_provider: str | None
    common_dependency_root: str | None
    coverage_state: str
    review_state: str
    suppression_state: str
    ai_explanation_state: str
    facets: tuple[tuple[str, str], ...]
    priority: int


@dataclass(frozen=True, slots=True)
class GroupActionPreview:
    """Frozen group action confirmation boundary."""

    group_id: str
    action: str
    generation: int
    findings: tuple[tuple[str, int], ...]

    @property
    def count(self) -> int:
        return len(self.findings)


def _validate_matcher(matcher: tuple[tuple[str, str], ...]) -> None:
    if not matcher:
        raise ValueError("matcher must not be empty")
    if any(
        field not in SUPPORTED_MATCHERS
        or not value
        or value != value.strip()
        or len(value) > 256
        for field, value in matcher
    ):
        raise ValueError("matcher contains an unsupported or invalid field")


def _looks_secret(value: str) -> bool:
    lowered = value.lower()
    return any(
        token in lowered
        for token in ("password", "secret", "token", "api_key", "authorization")
    )


def _support(finding: Finding, prefix: str) -> tuple[str, ...]:
    marker = f"{prefix}:"
    return tuple(
        value.removeprefix(marker)
        for value in finding.recommendation.dependency_assessment.supporting_subject_ids
        if value.startswith(marker)
    )


def _finding_decision(finding: Finding) -> tuple[int | None, str, str]:
    """Derive user-facing classification and repairability from evidence only."""
    duration = next(
        (
            int(item.value)
            for item in finding.evidence
            if item.predicate == "hamie.entity.unavailable_seconds@1"
            and isinstance(item.value, int | float)
        ),
        None,
    )
    dependency = finding.recommendation.dependency_assessment
    if finding.lifecycle is FindingLifecycle.RESOLVED:
        classification = "Resolved"
    elif dependency.referenced_by:
        classification = "Referenced entity"
    elif duration is not None and duration >= 86_400:
        classification = "Persistently unavailable"
    elif duration is not None:
        classification = "Transient unavailable"
    else:
        classification = "Manual review"
    if (
        dependency.coverage.value == "complete"
        and dependency.safe_to_remove
        and not dependency.referenced_by
    ):
        repairability = "Potentially safe to disable"
    elif dependency.coverage.value != "complete":
        repairability = "Needs more evidence"
    else:
        repairability = "Manual review"
    return duration, classification, repairability


def _facts(finding: Finding, group_id: str | None = None) -> dict[str, tuple[str, ...]]:
    entity_id = finding.subject.source_id
    supporting = finding.recommendation.dependency_assessment.supporting_subject_ids
    display = finding.subject.display_hint or entity_id
    name_prefix = _common_prefix((display,)) or display.partition("_")[0]
    return {
        "integration_domain": _support(finding, "integration"),
        "config_entry_id": _support(finding, "config_entry"),
        "device_id": _support(finding, "device"),
        "entity_domain": (entity_id.partition(".")[0],),
        "entity_id": (entity_id,),
        "entity_id_prefix": tuple(
            entity_id[:index]
            for index, char in enumerate(entity_id, start=1)
            if char == "_"
        ),
        "area_id": _support(finding, "area"),
        "analyzer_id": (finding.analyzer_id,),
        "condition_key": (finding.condition_key,),
        "category": (finding.category,),
        "group_id": (group_id,) if group_id else (),
        "source_provider": _support(finding, "integration"),
        "name_prefix": (name_prefix,),
        "failure_condition": (finding.condition_key,),
        "dependency_root": tuple(sorted(supporting)),
        "severity": (finding.severity.value,),
    }


def matcher_matches(
    matcher: tuple[tuple[str, str], ...],
    finding: Finding,
    *,
    group_id: str | None = None,
) -> bool:
    """Match only the fixed declarative matcher vocabulary."""
    facts = _facts(finding, group_id)
    for field, expected in matcher:
        values = facts[field]
        if field in {"entity_id_prefix", "name_prefix"}:
            source = (
                finding.subject.source_id
                if field == "entity_id_prefix"
                else (finding.subject.display_hint or finding.subject.source_id)
            )
            if not source.startswith(expected):
                return False
        elif expected not in values:
            return False
    return True


def _common_prefix(values: Iterable[str]) -> str | None:
    tokens = [value.replace("_", " ").split() for value in values if value]
    if not tokens:
        return None
    result: list[str] = []
    for items in zip(*tokens):
        if len({item.casefold() for item in items}) != 1:
            break
        result.append(items[0])
    text = " ".join(result).strip()
    return text if len(text) >= 2 else None


def _primary_key(
    finding: Finding,
    grouping_rules: tuple[GroupingRule, ...],
    *,
    enabled_dimensions: tuple[str, ...] = (),
    primary_dimension: str | None = None,
    collapse_duplicates: bool = True,
    collapse_mobile_app: bool = True,
) -> tuple[str, str, str, str]:
    if not collapse_duplicates:
        return (
            f"finding:{finding.finding_id}",
            finding.subject.display_hint or finding.subject.source_id,
            "duplicate collapsing disabled",
            GROUPING_REVISION,
        )
    for rule in grouping_rules:
        if rule.enabled and matcher_matches(rule.matcher, finding):
            return (
                f"rule:{rule.rule_id}",
                rule.title,
                f"user rule {rule.name}",
                f"{GROUPING_REVISION}:{rule.rule_id}:{rule.revision}",
            )
    if enabled_dimensions:
        dimensions = tuple(
            dict.fromkeys(
                (
                    *((primary_dimension,) if primary_dimension else ()),
                    *enabled_dimensions,
                )
            )
        )
        facts = _facts(finding)
        mobile_app = "mobile_app" in facts["integration_domain"]
        labels = {
            "integration_domain": "Integration",
            "config_entry_id": "Config entry",
            "device_id": "Device",
            "entity_domain": "Entity domain",
            "area_id": "Area",
            "source_provider": "Source provider",
            "name_prefix": "Name prefix",
            "failure_condition": "Failure condition",
            "dependency_root": "Dependency root",
            "analyzer_id": "Analyzer",
            "category": "Category",
            "severity": "Severity",
        }
        for field in dimensions:
            if (
                mobile_app
                and not collapse_mobile_app
                and field
                in {"integration_domain", "config_entry_id", "source_provider"}
            ):
                continue
            values = facts.get(field, ())
            if values:
                value = values[0]
                label = labels.get(field, field.replace("_", " ").title())
                return (
                    f"{field}:{value}",
                    f"{label} {value}",
                    f"common {field.replace('_', ' ')}",
                    GROUPING_REVISION,
                )
    for field, prefix, reason in (
        ("config_entry_id", "Config entry", "common config entry"),
        ("device_id", "Device", "common device"),
        ("integration_domain", "Integration", "common providing integration"),
    ):
        values = _facts(finding)[field]
        if values:
            return (
                f"{field}:{values[0]}",
                f"{prefix} {values[0]}",
                reason,
                GROUPING_REVISION,
            )
    entity_id = finding.subject.source_id
    domain = entity_id.partition(".")[0]
    return (
        f"domain:{domain}:{finding.condition_key}",
        f"{domain.title()} {finding.title_key.replace('_', ' ')}",
        "common entity domain and failure condition",
        GROUPING_REVISION,
    )


def _priority(finding: Finding, *, lowered: bool = False) -> int:
    severity = {
        FindingSeverity.INFO: 10,
        FindingSeverity.WARNING: 40,
        FindingSeverity.ERROR: 80,
    }[finding.severity]
    dependency = finding.recommendation.dependency_assessment
    dependency_score = 20 if dependency.referenced_by else 10
    score = severity + dependency_score + min(finding.occurrence_count, 20)
    if finding.review_state.value == "new":
        score += 10
    if lowered:
        score -= 30
    return score


def build_groups(
    findings: tuple[Finding, ...],
    grouping_rules: tuple[GroupingRule, ...] = (),
    *,
    suppressed_ids: frozenset[str] = frozenset(),
    lowered_ids: frozenset[str] = frozenset(),
    suppression_actions: dict[str, str] | None = None,
    recommendation_group_ids: frozenset[str] = frozenset(),
    enabled_dimensions: tuple[str, ...] = (),
    primary_dimension: str | None = None,
    collapse_duplicates: bool = True,
    collapse_mobile_app: bool = True,
) -> tuple[FindingGroup, ...]:
    """Build deterministic primary groups without LLM authority."""
    buckets: dict[str, tuple[str, str, str, list[Finding]]] = {}
    for finding in findings:
        key, bucket_title, reason, revision = _primary_key(
            finding,
            grouping_rules,
            enabled_dimensions=enabled_dimensions,
            primary_dimension=primary_dimension,
            collapse_duplicates=collapse_duplicates,
            collapse_mobile_app=collapse_mobile_app,
        )
        bucket = buckets.setdefault(key, (bucket_title, reason, revision, []))
        bucket[3].append(finding)
    groups: list[FindingGroup] = []
    for key, (fallback_title, reason, grouping_revision, members) in sorted(
        buckets.items()
    ):
        ordered = sorted(members, key=lambda item: item.finding_id)
        group_id = f"grp_{stable_digest(GROUPING_REVISION, key)[:24]}"
        title: str | None = (
            fallback_title
            if key.startswith("rule:")
            else _common_prefix(
                item.subject.display_hint or item.subject.source_id for item in ordered
            )
        )
        if title is None or len(ordered) == 1:
            title = fallback_title
        review_states = {item.review_state.value for item in ordered}
        suppression_values = [
            (suppression_actions or {}).get(
                item.finding_id,
                ("suppressed" if item.finding_id in suppressed_ids else "visible"),
            )
            for item in ordered
        ]
        dependencies = [
            set(item.recommendation.dependency_assessment.supporting_subject_ids)
            for item in ordered
        ]
        common_dependencies = set.intersection(*dependencies) if dependencies else set()
        providers = {
            value for item in ordered for value in _support(item, "integration")
        }
        facets = {
            (field, value)
            for item in ordered
            for field, values in _facts(item).items()
            if field != "entity_id_prefix"
            for value in values
        }
        groups.append(
            FindingGroup(
                group_id=group_id,
                grouping_revision=grouping_revision,
                group_revision=stable_digest(
                    grouping_revision,
                    key,
                    *(f"{item.finding_id}:{item.content_revision}" for item in ordered),
                    *(
                        sorted(
                            item
                            for item in suppressed_ids
                            if item in {member.finding_id for member in ordered}
                        )
                    ),
                    *suppression_values,
                    sorted(common_dependencies)[0] if common_dependencies else "",
                ),
                title=title,
                grouping_reason=reason,
                member_finding_ids=tuple(item.finding_id for item in ordered),
                member_count=len(ordered),
                open_count=sum(
                    item.lifecycle is FindingLifecycle.OPEN for item in ordered
                ),
                warning_count=sum(
                    item.severity is FindingSeverity.WARNING for item in ordered
                ),
                critical_count=sum(
                    item.severity is FindingSeverity.ERROR for item in ordered
                ),
                first_seen=min(item.first_seen for item in ordered),
                last_seen=max(item.last_seen for item in ordered),
                confidence=min(
                    (item.recommendation.confidence.level.value for item in ordered),
                    key={"low": 0, "medium": 1, "high": 2}.__getitem__,
                ),
                representative_subjects=tuple(
                    item.subject.source_id
                    for item in ordered[:MAX_REPRESENTATIVE_SUBJECTS]
                ),
                common_provider=next(iter(providers)) if len(providers) == 1 else None,
                common_dependency_root=(
                    sorted(common_dependencies)[0] if common_dependencies else None
                ),
                coverage_state=(
                    "complete"
                    if all(
                        item.recommendation.dependency_assessment.coverage.value
                        == "complete"
                        for item in ordered
                    )
                    else "partial"
                ),
                review_state=(
                    next(iter(review_states)) if len(review_states) == 1 else "mixed"
                ),
                suppression_state=(
                    suppression_values[0]
                    if len(set(suppression_values)) == 1
                    else "mixed"
                ),
                ai_explanation_state=(
                    "available" if group_id in recommendation_group_ids else "none"
                ),
                facets=tuple(sorted(facets)),
                priority=max(
                    _priority(item, lowered=item.finding_id in lowered_ids)
                    for item in ordered
                )
                + min(len(ordered), 20),
            )
        )
    return tuple(
        sorted(groups[:MAX_GROUPS], key=lambda item: (-item.priority, item.group_id))
    )


def mark_recommendations_stale(
    recommendations: tuple[AIRecommendation, ...],
    findings: tuple[Finding, ...],
    groups: tuple[FindingGroup, ...] = (),
) -> tuple[AIRecommendation, ...]:
    """Mark advisory output stale with persisted, explainable source reasons."""
    revisions = {item.finding_id: item.content_revision for item in findings}
    groups_by_id = {item.group_id: item for item in groups}
    result = []
    for item in recommendations:
        reasons = set(item.stale_reasons)
        if any(
            revisions.get(source_id) != revision
            for source_id, revision in item.source_revisions
            if source_id.startswith("hamie_")
        ):
            reasons.add("finding_revision_changed")
        for binding in item.group_bindings:
            group = groups_by_id.get(binding.group_id)
            if group is None:
                reasons.add("group_membership_changed")
                continue
            member_digest = stable_digest(*group.member_finding_ids)
            suppression_digest = stable_digest(group.suppression_state)
            if member_digest != binding.member_digest:
                reasons.add("group_membership_changed")
            if group.grouping_revision != binding.grouping_revision:
                reasons.add("grouping_revision_changed")
            if suppression_digest != binding.suppression_digest:
                reasons.add("group_suppression_changed")
            if (group.common_dependency_root or "") != binding.dependency_root:
                reasons.add("dependency_root_changed")
        result.append(
            replace(
                item,
                stale=item.stale or bool(reasons),
                stale_reasons=tuple(sorted(reasons)),
            )
        )
    return tuple(result[-MAX_RECOMMENDATIONS:])


def apply_suppression_reviews(
    findings: tuple[Finding, ...],
    reviews: tuple[ReviewRecord, ...],
    audits: tuple[AuditRecord, ...],
    *,
    grouping_rules: tuple[GroupingRule, ...],
    suppression_rules: tuple[SuppressionRule, ...],
    at: datetime,
) -> tuple[tuple[Finding, ...], tuple[ReviewRecord, ...], tuple[AuditRecord, ...]]:
    """Apply only canonical auto-acknowledge and snooze policy effects.

    Policy precedence is hide, snooze, auto-acknowledge, then lower priority.
    A higher-precedence match prevents a lower-precedence state transition.
    """
    current_at = require_utc(at, "suppression evaluation at")
    base_groups = build_groups(findings, grouping_rules)
    group_for = {
        finding_id: group.group_id
        for group in base_groups
        for finding_id in group.member_finding_ids
    }
    precedence = {
        SuppressionAction.LOWER_PRIORITY: 1,
        SuppressionAction.AUTO_ACKNOWLEDGE: 2,
        SuppressionAction.SNOOZE: 3,
        SuppressionAction.HIDE_FROM_DEFAULT_VIEW: 4,
    }
    changed: dict[str, Finding] = {}
    added_reviews: list[ReviewRecord] = []
    added_audits: list[AuditRecord] = []
    for finding in findings:
        if finding.lifecycle is not FindingLifecycle.OPEN:
            continue
        matches = sorted(
            (
                rule
                for rule in suppression_rules
                if rule.active_at(current_at)
                and (
                    not rule.affected_analyzer_ids
                    or finding.analyzer_id in rule.affected_analyzer_ids
                )
                and matcher_matches(
                    rule.matcher,
                    finding,
                    group_id=group_for.get(finding.finding_id),
                )
            ),
            key=lambda rule: (-precedence[rule.action], rule.rule_id),
        )
        if not matches:
            continue
        rule = matches[0]
        if rule.action is SuppressionAction.AUTO_ACKNOWLEDGE:
            action = ReviewAction.ACKNOWLEDGE
            if finding.review_state is ReviewState.ACKNOWLEDGED:
                continue
            snooze_until = None
        elif rule.action is SuppressionAction.SNOOZE:
            action = ReviewAction.SNOOZE
            snooze_until = rule.expiration
            if (
                finding.review_state is ReviewState.SNOOZED
                and finding.snooze_until == snooze_until
            ):
                continue
        else:
            continue
        if finding.review_state not in ALLOWED_PRIOR_STATES[action]:
            continue
        review = ReviewRecord(
            finding_id=finding.finding_id,
            action=action,
            actor=f"hamie_suppression_policy:{rule.rule_id}",
            at=current_at,
            finding_content_revision=finding.content_revision,
            prior_state=finding.review_state,
            resulting_state=(
                ReviewState.ACKNOWLEDGED
                if action is ReviewAction.ACKNOWLEDGE
                else ReviewState.SNOOZED
            ),
            reason=f"suppression_rule:{rule.rule_id}",
            snooze_until=snooze_until,
        )
        updated = replace(
            finding,
            review_state=review.resulting_state,
            snooze_until=snooze_until,
        )
        changed[finding.finding_id] = updated
        added_reviews.append(review)
        audit_digest = stable_digest(
            rule.rule_id,
            finding.finding_id,
            finding.content_revision,
            action.value,
        )
        added_audits.append(
            AuditRecord(
                audit_id=f"aud_{audit_digest[:24]}",
                event=f"suppression_{action.value}",
                at=current_at,
                actor=review.actor,
                target_ids=(finding.finding_id, rule.rule_id),
                details=(
                    ("action", rule.action.value),
                    ("finding_revision", str(finding.content_revision)),
                ),
            )
        )
    return (
        tuple(changed.get(item.finding_id, item) for item in findings),
        (*reviews, *added_reviews)[-500:],
        (*audits, *added_audits)[-MAX_AUDIT_RECORDS:],
    )


class ExplorerIndex:
    """Bounded indexed projection used by the panel and native adapters."""

    def __init__(
        self,
        *,
        findings: tuple[Finding, ...],
        grouping_rules: tuple[GroupingRule, ...] = (),
        suppression_rules: tuple[SuppressionRule, ...] = (),
        recommendations: tuple[AIRecommendation, ...] = (),
        audits: tuple[AuditRecord, ...] = (),
        generation: int = 0,
        projection_revision: int = 0,
        at: datetime | None = None,
        maximum_groups: int = MAX_GROUPS,
        minimum_group_size: int = 1,
        maximum_evidence_items: int = 8,
        maximum_supporting_objects: int = 32,
        maximum_visible_group_members: int = 100,
        show_suppressed_by_default: bool = False,
        show_snoozed_by_default: bool = False,
        enabled_grouping_dimensions: tuple[str, ...] = (),
        primary_grouping_preference: str | None = None,
        duplicate_collapsing_enabled: bool = True,
        collapse_mobile_app_findings: bool = True,
        grouping_confidence_threshold: float = 0,
    ) -> None:
        self.findings = findings[:10_000]
        self.generation = generation
        self.projection_revision = projection_revision
        self.at = require_utc(at or datetime.now(UTC), "explorer at")
        self.maximum_evidence_items = max(1, min(8, maximum_evidence_items))
        self.maximum_supporting_objects = max(1, min(32, maximum_supporting_objects))
        self.maximum_visible_group_members = max(
            1, min(500, maximum_visible_group_members)
        )
        self.show_suppressed_by_default = show_suppressed_by_default
        self.show_snoozed_by_default = show_snoozed_by_default
        self.grouping_rules = grouping_rules[-MAX_GROUPING_RULES:]
        self.suppression_rules = suppression_rules[-MAX_SUPPRESSION_RULES:]
        base_groups = build_groups(self.findings, grouping_rules)
        group_for = {
            finding_id: group.group_id
            for group in base_groups
            for finding_id in group.member_finding_ids
        }
        precedence = {
            SuppressionAction.LOWER_PRIORITY: 1,
            SuppressionAction.AUTO_ACKNOWLEDGE: 2,
            SuppressionAction.SNOOZE: 3,
            SuppressionAction.HIDE_FROM_DEFAULT_VIEW: 4,
        }
        effective_actions: dict[str, SuppressionAction] = {}
        for finding in self.findings:
            matching = [
                rule.action
                for rule in suppression_rules
                if rule.active_at(self.at)
                and (
                    not rule.affected_analyzer_ids
                    or finding.analyzer_id in rule.affected_analyzer_ids
                )
                and matcher_matches(
                    rule.matcher,
                    finding,
                    group_id=group_for.get(finding.finding_id),
                )
            ]
            if matching:
                effective_actions[finding.finding_id] = max(
                    matching, key=precedence.__getitem__
                )
        self.suppression_action_by_id = effective_actions
        self.suppressed_ids = frozenset(
            finding_id
            for finding_id, action in effective_actions.items()
            if action is SuppressionAction.HIDE_FROM_DEFAULT_VIEW
        )
        self.lowered_ids = frozenset(
            finding_id
            for finding_id, action in effective_actions.items()
            if action is SuppressionAction.LOWER_PRIORITY
        )
        self.policy_snoozed_ids = frozenset(
            finding_id
            for finding_id, action in effective_actions.items()
            if action is SuppressionAction.SNOOZE
        )
        self.hidden_default_ids = frozenset(
            (
                *self.suppressed_ids,
                *self.policy_snoozed_ids,
                *(
                    item.finding_id
                    for item in self.findings
                    if item.review_state.value == "snoozed"
                    and item.snooze_until is not None
                    and item.snooze_until > self.at
                ),
            )
        )
        self.repairs_hidden_ids = self.hidden_default_ids
        recommendation_groups = frozenset(
            group_id
            for item in recommendations
            if not item.stale and item.review_state is not AIReviewState.EXPIRED
            for group_id in item.group_ids
        )
        self.groups = tuple(
            item
            for item in build_groups(
                self.findings,
                grouping_rules,
                suppressed_ids=self.suppressed_ids,
                lowered_ids=self.lowered_ids,
                suppression_actions={
                    finding_id: (
                        "suppressed"
                        if action is SuppressionAction.HIDE_FROM_DEFAULT_VIEW
                        else action.value
                    )
                    for finding_id, action in self.suppression_action_by_id.items()
                },
                recommendation_group_ids=recommendation_groups,
                enabled_dimensions=enabled_grouping_dimensions,
                primary_dimension=primary_grouping_preference,
                collapse_duplicates=duplicate_collapsing_enabled,
                collapse_mobile_app=collapse_mobile_app_findings,
            )
            if item.member_count >= max(1, minimum_group_size)
            and {"low": 0.33, "medium": 0.66, "high": 1.0}[item.confidence]
            >= grouping_confidence_threshold
        )[: max(10, min(MAX_GROUPS, maximum_groups))]
        self.group_by_id = {item.group_id: item for item in self.groups}
        self.group_for_finding = {
            finding_id: group.group_id
            for group in self.groups
            for finding_id in group.member_finding_ids
        }
        self.recommendations = recommendations[-MAX_RECOMMENDATIONS:]
        self.audits = audits[-MAX_AUDIT_RECORDS:]
        self._search = {
            item.finding_id: self._search_text(item).casefold()
            for item in self.findings
        }

    def _search_text(self, finding: Finding) -> str:
        dependency = finding.recommendation.dependency_assessment
        group = self.group_by_id.get(self.group_for_finding.get(finding.finding_id, ""))
        return " ".join(
            (
                finding.finding_id,
                finding.subject.source_id,
                finding.subject.display_hint or "",
                finding.analyzer_id,
                finding.category,
                finding.recommendation.action,
                group.title if group else "",
                *dependency.supporting_subject_ids,
            )
        )

    def query_findings(
        self,
        *,
        search: str = "",
        filters: dict[str, Any] | None = None,
        sort: str = "priority",
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return one bounded page from indexed in-memory data."""
        _validate_page(search, offset, limit)
        options = filters or {}
        include_hidden = (
            options.get("suppression_state") == "suppressed"
            or options.get("review_state") == "snoozed"
            or self.show_suppressed_by_default
            or self.show_snoozed_by_default
        )
        values = [
            finding
            for finding in self.findings
            if (not search or search.casefold() in self._search[finding.finding_id])
            and self._matches_filters(finding, options)
            and (include_hidden or finding.finding_id not in self.hidden_default_ids)
        ]
        values.sort(key=lambda item: self._sort_key(item, sort))
        classification_counts: dict[str, int] = {}
        grouping_counts: dict[str, dict[str, int]] = {
            dimension: {}
            for dimension in (
                "integration",
                "config_entry",
                "device",
                "category",
                "duration",
                "repairability",
                "dependency_status",
                "proposed_action",
            )
        }
        for item in values:
            facts = _facts(item, self.group_for_finding.get(item.finding_id))
            duration, classification, repairability = _finding_decision(item)
            classification_counts[classification] = (
                classification_counts.get(classification, 0) + 1
            )
            dependency = item.recommendation.dependency_assessment
            dimensions = {
                "integration": next(iter(facts["integration_domain"]), "Unknown"),
                "config_entry": next(iter(facts["config_entry_id"]), "Unknown"),
                "device": next(iter(facts["device_id"]), "Unknown"),
                "category": item.category,
                "duration": (
                    "Unknown"
                    if duration is None
                    else "Under 1 hour"
                    if duration < 3_600
                    else "Under 1 day"
                    if duration < 86_400
                    else "1–7 days"
                    if duration < 604_800
                    else "Over 7 days"
                ),
                "repairability": repairability,
                "dependency_status": (
                    "Complete"
                    if dependency.coverage.value == "complete"
                    else "Needs more evidence"
                ),
                "proposed_action": item.recommendation.kind.value,
            }
            for dimension, value in dimensions.items():
                grouping_counts[dimension][value] = (
                    grouping_counts[dimension].get(value, 0) + 1
                )
        return {
            "generation": self.generation,
            "offset": offset,
            "limit": limit,
            "total": len(values),
            "classification_counts": dict(sorted(classification_counts.items())),
            "grouping_counts": {
                dimension: [
                    {"label": label, "count": count}
                    for label, count in sorted(
                        counts.items(), key=lambda value: (-value[1], value[0])
                    )[:50]
                ]
                for dimension, counts in grouping_counts.items()
            },
            "items": [
                self.finding_summary(item) for item in values[offset : offset + limit]
            ],
        }

    def query_groups(
        self, *, search: str = "", offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        """Return a bounded deterministic group page."""
        _validate_page(search, offset, limit)
        groups = [
            group
            for group in self.groups
            if not search
            or search.casefold()
            in f"{group.group_id} {group.title} {group.grouping_reason}".casefold()
        ]
        return {
            "generation": self.generation,
            "offset": offset,
            "limit": limit,
            "total": len(groups),
            "items": [
                _group_dict(
                    group,
                    maximum_visible_members=self.maximum_visible_group_members,
                )
                for group in groups[offset : offset + limit]
            ],
        }

    def overview(self) -> dict[str, Any]:
        """Return bounded explorer overview additions."""
        open_items = [
            item for item in self.findings if item.lifecycle is FindingLifecycle.OPEN
        ]
        return {
            "suppressed_findings": len(self.suppressed_ids),
            "pending_ai_recommendations": sum(
                item.review_state is AIReviewState.NEW and not item.stale
                for item in self.recommendations
            ),
            "root_cause_groups": len(self.groups),
            "highest_priority_groups": [
                _group_dict(
                    item,
                    maximum_visible_members=self.maximum_visible_group_members,
                )
                for item in self.groups[:5]
            ],
            "open_findings": len(open_items),
        }

    def finding_summary(self, finding: Finding) -> dict[str, Any]:
        """Serialize one bounded finding view with provenance distinctions."""
        dependency = finding.recommendation.dependency_assessment
        group_id = self.group_for_finding.get(finding.finding_id)
        facts = _facts(finding, group_id)
        duration_seconds, classification, repairability = _finding_decision(finding)
        ai_records = [
            item
            for item in self.recommendations
            if finding.finding_id in item.finding_ids
        ][-3:]
        audit_records = [
            item for item in self.audits if finding.finding_id in item.target_ids
        ][-5:]
        return {
            "finding_id": finding.finding_id,
            "entity_id": finding.subject.source_id,
            "subject_name": finding.subject.display_hint,
            "friendly_name": finding.subject.display_hint or finding.subject.source_id,
            "severity": finding.severity.value,
            "category": finding.category,
            "analyzer_id": finding.analyzer_id,
            "condition_key": finding.condition_key,
            "exact_condition": finding.condition_key,
            "current_state": (
                "unavailable"
                if finding.condition_key == "current_state_unavailable_after_grace"
                else "Unknown"
            ),
            "lifecycle": finding.lifecycle.value,
            "review_state": finding.review_state.value,
            "first_seen": finding.first_seen.isoformat(),
            "last_seen": finding.last_seen.isoformat(),
            "duration_seconds": duration_seconds,
            "occurrence_count": finding.occurrence_count,
            "content_revision": finding.content_revision,
            "confidence": finding.recommendation.confidence.level.value,
            "recommendation": finding.recommendation.action,
            "recommendation_kind": finding.recommendation.kind.value,
            "risk": finding.recommendation.risk.overall.value,
            "risk_rationale": finding.recommendation.risk.rationale,
            "priority": _priority(
                finding, lowered=finding.finding_id in self.lowered_ids
            ),
            "integration": next(iter(facts["integration_domain"]), None),
            "config_entry": next(iter(facts["config_entry_id"]), None),
            "device": next(iter(facts["device_id"]), None),
            "area": next(iter(facts["area_id"]), None),
            "group_id": group_id,
            "group_membership": [group_id] if group_id else [],
            "classification": classification,
            "dependency_state": (
                "Complete"
                if dependency.coverage.value == "complete"
                else "Needs more evidence"
            ),
            "repairability": repairability,
            "recommended_next_action": finding.recommendation.action,
            "suppression_state": (
                self.suppression_action_by_id[finding.finding_id].value
                if finding.finding_id in self.suppression_action_by_id
                else "visible"
            ),
            "dependency": {
                "coverage": dependency.coverage.value,
                "rationale": dependency.rationale,
                "count": len(dependency.referenced_by),
                "referenced_by": list(
                    dependency.referenced_by[: self.maximum_supporting_objects]
                ),
                "supporting_objects": list(
                    dependency.supporting_subject_ids[: self.maximum_supporting_objects]
                ),
                "safe_to_remove": (
                    dependency.safe_to_remove and not dependency.referenced_by
                ),
            },
            "evidence": [
                {
                    "predicate": item.predicate,
                    "value": (
                        item.value
                        if item.sensitivity is Sensitivity.PUBLIC
                        else "[redacted]"
                    ),
                    "kind": item.kind.value,
                    "source": item.source_id,
                    "source_revision": item.source_revision,
                    "observed_at": item.observed_at.isoformat(),
                }
                for item in finding.evidence[: self.maximum_evidence_items]
                if item.sensitivity is not Sensitivity.NEVER_EXPORT
            ],
            "ai_explanations": [
                {
                    "recommendation_id": item.recommendation_id,
                    "summary": item.summary,
                    "review_state": item.review_state.value,
                    "stale": item.stale,
                    "stale_reasons": list(item.stale_reasons),
                }
                for item in ai_records
            ],
            "audit_history": [
                {
                    "event": item.event,
                    "at": item.at.isoformat(),
                    "actor": item.actor,
                }
                for item in audit_records
            ],
        }

    def advisory_finding_view(self, finding: Finding) -> dict[str, Any]:
        """One compact per-finding view sized for LLM prompt input.

        Unlike finding_summary() (the full UI detail-view payload --
        evidence, audit history, AI-explanation history; several KB per
        finding), this carries only what a model needs to produce
        grounded advisory text, so a real installation's open findings
        can actually fit a bounded prompt budget. Confirmed by direct
        measurement: 50 real finding_summary() payloads alone serialize
        to roughly 90,000 characters against the default 16,000-character
        prompt budget -- over 5x over budget before the provider is even
        called, the root cause of the beta.11 "could not parse the AI
        provider's response as JSON" defect (the request never reached
        the provider at all; a payload-size ValueError from prompt
        construction was mislabeled as a response-parsing failure).
        """
        dependency = finding.recommendation.dependency_assessment
        group_id = self.group_for_finding.get(finding.finding_id)
        facts = _facts(finding, group_id)
        evidence = []
        for item in finding.evidence[:3]:
            if item.sensitivity.value == "never_export":
                continue
            evidence.append(
                {
                    "evidence_id": item.evidence_id,
                    "predicate": item.predicate,
                    "value": (
                        item.value
                        if item.sensitivity.value == "public"
                        else "[redacted]"
                    ),
                    "kind": item.kind.value,
                    "source": item.source_id,
                    "source_revision": item.source_revision,
                    "observed_at": item.observed_at.isoformat(),
                }
            )
        return {
            "finding_id": finding.finding_id,
            "entity_id": finding.subject.source_id,
            "analyzer_id": finding.analyzer_id,
            "condition_key": finding.condition_key,
            "severity": finding.severity.value,
            "category": finding.category,
            "recommendation": finding.recommendation.action,
            "recommendation_rationale": finding.recommendation.rationale,
            "safety_gate": finding.recommendation.safety_gate.value,
            "confidence": finding.recommendation.confidence.level.value,
            "risk": finding.recommendation.risk.overall.value,
            "integration": next(iter(facts["integration_domain"]), None),
            "occurrence_count": finding.occurrence_count,
            "first_seen": finding.first_seen.isoformat(),
            "dependency_safe_to_remove": (
                dependency.safe_to_remove and not dependency.referenced_by
            ),
            "dependency_reference_count": len(dependency.referenced_by),
            "dependency_references": list(dependency.referenced_by[:8]),
            "dependency_coverage": dependency.coverage.value,
            "evidence": evidence,
            "group_id": group_id,
        }

    def plan_ai_evidence(
        self,
        candidates: Sequence[Finding],
        *,
        maximum_characters: int,
        reserved_characters: int = DEFAULT_AI_PROMPT_RESERVED_CHARACTERS,
        maximum_per_condition: int = 3,
    ) -> tuple[list[dict[str, Any]], AIAnalysisCoverage]:
        """Deterministically prioritize, deduplicate, and bound one AI
        evidence batch to a real character budget.

        Ordering matches the existing "priority" explorer sort (severity-
        weighted, then dependency/occurrence/review-state, then
        finding_id for stability) so the highest-value findings are
        always the ones covered first when not everything fits -- never
        an arbitrary insertion-order slice. Findings that share the same
        (analyzer_id, condition_key) -- literally the same repeated
        symptom, e.g. dozens of "entity unavailable" findings from one
        failing integration -- beyond `maximum_per_condition` are skipped
        as duplicates of an already-represented pattern; this is
        deliberately narrower than "same device/integration group", which
        can span genuinely distinct problems. Once the character budget
        is exhausted, every remaining lower-priority finding is recorded
        as skipped rather than opportunistically backfilled with a
        smaller-but-lower-priority one -- coverage stays a crisp,
        predictable priority-ordered prefix, never a silently-incomplete
        claim of full coverage.
        """
        ordered = sorted(candidates, key=lambda item: self._sort_key(item, "priority"))
        budget = max(0, maximum_characters - reserved_characters)
        per_condition: dict[tuple[str, str], int] = {}
        selected: list[dict[str, Any]] = []
        selected_ids: list[str] = []
        skipped_ids: list[str] = []
        used = 2  # the enclosing JSON array's brackets
        for index, finding in enumerate(ordered):
            condition = (finding.analyzer_id, finding.condition_key)
            count = per_condition.get(condition, 0)
            if count >= maximum_per_condition:
                skipped_ids.append(finding.finding_id)
                continue
            view = self.advisory_finding_view(finding)
            encoded = _json_dumps_compact(view)
            added = len(encoded) + (1 if selected else 0)
            if used + added > budget:
                skipped_ids.extend(item.finding_id for item in ordered[index:])
                break
            used += added
            selected.append(view)
            selected_ids.append(finding.finding_id)
            per_condition[condition] = count + 1
        coverage = AIAnalysisCoverage(
            eligible_total=len(candidates),
            selected_finding_ids=tuple(selected_ids),
            skipped_finding_ids=tuple(skipped_ids[:MAX_AI_COVERAGE_IDS]),
            total_findings=len(self.findings),
            root_cause_group_ids=tuple(
                dict.fromkeys(
                    self.group_for_finding[item.finding_id]
                    for item in ordered
                    if item.finding_id in self.group_for_finding
                )
            ),
            analyzed_group_ids=tuple(
                dict.fromkeys(
                    view["group_id"] for view in selected if view.get("group_id")
                )
            ),
        )
        return selected, coverage

    def plan_ai_advisory_groups(
        self,
        candidates: Sequence[Finding],
        *,
        maximum_characters: int,
        maximum_groups: int = 8,
        maximum_findings_per_group: int = 20,
        already_covered_group_ids: frozenset[str] = frozenset(),
    ) -> tuple[tuple[tuple[str, tuple[dict[str, Any], ...]], ...], AIAnalysisCoverage]:
        """Build ranked, bounded provider batches for distinct root causes.

        ``already_covered_group_ids`` (root-cause groups that already have
        a current, non-stale AI recommendation -- see
        ``mark_recommendations_stale``) are skipped when filling this
        run's bounded batch, not merely deprioritized: without this, a
        real installation with more distinct root causes than
        ``maximum_groups`` would have its "Analyze All" action re-analyze
        the exact same top-N groups by priority on every single run,
        forever, while every group past the cap silently never gets
        analyzed no matter how many times the action is repeated. Skipping
        already-covered groups here means each successive run's bounded
        batch is genuinely the *next* uncovered slice, so repeated runs
        converge on covering every eligible group.
        """
        group_limit = max(1, min(maximum_groups, 20))
        finding_limit = max(1, min(maximum_findings_per_group, 50))
        ordered = sorted(candidates, key=lambda item: self._sort_key(item, "priority"))
        buckets: dict[str, list[Finding]] = {}
        for finding in ordered:
            group_id = self.group_for_finding.get(finding.finding_id)
            if group_id is None:
                group_id = stable_digest(
                    "symptom",
                    finding.analyzer_id,
                    finding.condition_key,
                    finding.category,
                )[:24]
                group_id = f"symptom_{group_id}"
            buckets.setdefault(group_id, []).append(finding)

        eligible_buckets = tuple(
            (group_id, group_findings)
            for group_id, group_findings in buckets.items()
            if group_id not in already_covered_group_ids
        )
        batches: list[tuple[str, tuple[dict[str, Any], ...]]] = []
        selected_ids: list[str] = []
        for group_id, group_findings in eligible_buckets[:group_limit]:
            planned, local_coverage = self.plan_ai_evidence(
                group_findings,
                maximum_characters=maximum_characters,
                maximum_per_condition=finding_limit,
            )
            if not planned:
                continue
            batches.append((group_id, tuple(planned)))
            selected_ids.extend(local_coverage.selected_finding_ids)

        selected_set = frozenset(selected_ids)
        skipped_ids = tuple(
            item.finding_id for item in ordered if item.finding_id not in selected_set
        )
        coverage = AIAnalysisCoverage(
            eligible_total=len(candidates),
            selected_finding_ids=tuple(selected_ids[:MAX_AI_COVERAGE_IDS]),
            skipped_finding_ids=skipped_ids[:MAX_AI_COVERAGE_IDS],
            total_findings=len(self.findings),
            root_cause_group_ids=tuple(buckets)[:MAX_AI_COVERAGE_IDS],
            analyzed_group_ids=tuple(group_id for group_id, _planned in batches),
            selection_reason=(
                "ranked root-cause groups by finding priority; bounded by "
                f"{group_limit} groups, {finding_limit} findings per group, "
                f"and {maximum_characters} prompt characters per group"
            ),
        )
        return tuple(batches), coverage

    def _matches_filters(self, finding: Finding, filters: dict[str, Any]) -> bool:
        dependency = finding.recommendation.dependency_assessment
        group_id = self.group_for_finding.get(finding.finding_id)
        facts = _facts(finding, group_id)
        # classification/repairability are the same honest,
        # evidence-only categorization finding_summary() already exposes
        # per finding (_finding_decision) -- filterable here too so the
        # Findings screen's "Actionable / Protected / Needs evidence /
        # Transient" filters (mission redesign) query the real field
        # server-side instead of a client-side approximation.
        _duration, classification, repairability = _finding_decision(finding)
        direct = {
            "severity": finding.severity.value,
            "category": finding.category,
            "analyzer": finding.analyzer_id,
            "review_state": finding.review_state.value,
            "lifecycle": finding.lifecycle.value,
            "dependency_risk": finding.recommendation.risk.overall.value,
            "safe_to_remove": str(
                dependency.safe_to_remove and not dependency.referenced_by
            ).lower(),
            "group_id": group_id or "",
            "classification": classification,
            "repairability": repairability,
            # Additive (mission Part 2/3): lets a caller query a specific
            # RecommendationKind server-side (e.g. the Review screen's
            # Broken Reference tab, which needs exactly the duplicate/
            # migration analyzer's REPAIR-kind findings and none of its
            # other classifications) instead of fetching everything
            # under one category and re-filtering client-side.
            "recommendation_kind": finding.recommendation.kind.value,
        }
        for key, actual in direct.items():
            expected = filters.get(key)
            if expected not in (None, "") and str(expected) != actual:
                return False
        for key, fact_key in (
            ("integration", "integration_domain"),
            ("device", "device_id"),
            ("area", "area_id"),
        ):
            expected = filters.get(key)
            if expected not in (None, "") and str(expected) not in facts[fact_key]:
                return False
        suppression = filters.get("suppression_state")
        is_suppressed = finding.finding_id in self.suppressed_ids
        if suppression == "suppressed" and not is_suppressed:
            return False
        if suppression == "visible" and is_suppressed:
            return False
        ai_state = filters.get("ai_recommendation_state")
        if ai_state not in (None, ""):
            matches = [
                item
                for item in self.recommendations
                if finding.finding_id in item.finding_ids
            ]
            actual = (
                "none"
                if not matches
                else ("stale" if matches[-1].stale else matches[-1].review_state.value)
            )
            if actual != ai_state:
                return False
        for field, value, lower in (
            ("first_seen_from", finding.first_seen, True),
            ("first_seen_to", finding.first_seen, False),
            ("last_seen_from", finding.last_seen, True),
            ("last_seen_to", finding.last_seen, False),
        ):
            raw = filters.get(field)
            if raw in (None, ""):
                continue
            try:
                boundary = require_utc(datetime.fromisoformat(str(raw)), field)
            except (TypeError, ValueError) as err:
                raise ValueError(f"{field} must be an aware ISO timestamp") from err
            if (lower and value < boundary) or (not lower and value > boundary):
                return False
        return True

    def _sort_key(self, finding: Finding, sort: str) -> tuple[Any, ...]:
        dependency = finding.recommendation.dependency_assessment
        confidence = {"low": 0, "medium": 1, "high": 2}[
            finding.recommendation.confidence.level.value
        ]
        risk = {"low": 0, "medium": 1, "high": 2, "critical": 3}[
            finding.recommendation.risk.overall.value
        ]
        group_id = self.group_for_finding[finding.finding_id]
        values: dict[str, int | float] = {
            "priority": _priority(
                finding, lowered=finding.finding_id in self.lowered_ids
            ),
            "severity": {"info": 0, "warning": 1, "error": 2}[finding.severity.value],
            "dependency_risk": risk,
            "affected_objects": len(dependency.referenced_by),
            "confidence": confidence,
            "age": -finding.first_seen.timestamp(),
            "recurrence": finding.occurrence_count,
            "newness": finding.last_seen.timestamp(),
            "group_size": self.group_by_id[group_id].member_count,
            "user_priority": _priority(finding),
            "ai_advisory_priority": max(
                (
                    {"low": 10, "medium": 50, "high": 90}[item.confidence]
                    for item in self.recommendations
                    if finding.finding_id in item.finding_ids and not item.stale
                ),
                default=0,
            ),
        }
        if sort not in values:
            raise ValueError("unsupported explorer sort")
        return (-values[sort], finding.finding_id)

    def dependency_graph(
        self,
        *,
        finding_id: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        """Build one bounded attributed graph without claiming full coverage."""
        if (finding_id is None) == (group_id is None):
            raise ValueError("select exactly one finding or group")
        if group_id is not None:
            group = self.group_by_id.get(group_id)
            if group is None:
                raise KeyError(group_id)
            selected_ids = frozenset(group.member_finding_ids)
        else:
            assert finding_id is not None
            selected_ids = frozenset((finding_id,))
        selected = [item for item in self.findings if item.finding_id in selected_ids]
        if not selected:
            raise KeyError(finding_id)
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        complete = True
        for finding in selected:
            dependency = finding.recommendation.dependency_assessment
            complete &= dependency.coverage.value == "complete"
            subject_id = finding.subject.source_id
            nodes.setdefault(
                subject_id,
                {
                    "node_id": subject_id,
                    "kind": finding.subject.kind,
                    "label": subject_id,
                },
            )
            relationships = (
                *(
                    (item, "supports", subject_id)
                    for item in dependency.supporting_subject_ids
                ),
                *(
                    (item, "references", subject_id)
                    for item in dependency.referenced_by
                ),
            )
            for source_id, relationship, target_id in relationships:
                if len(nodes) >= MAX_GRAPH_NODES or len(edges) >= MAX_GRAPH_EDGES:
                    complete = False
                    break
                nodes.setdefault(
                    source_id,
                    {
                        "node_id": source_id,
                        "kind": source_id.partition(":")[0] or "object",
                        "label": source_id,
                    },
                )
                edges.append(
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "relationship_type": relationship,
                        "source": "home_assistant_operational_source",
                        "source_revision": finding.latest_scan_id,
                        "confidence": finding.recommendation.confidence.level.value,
                        "last_verified": finding.last_seen.isoformat(),
                        "stale": False,
                    }
                )
        has_dependencies = any(
            item.recommendation.dependency_assessment.referenced_by for item in selected
        )
        reference_groups: dict[str, list[str]] = {
            category: []
            for category in (
                "automations",
                "scripts",
                "scenes",
                "dashboards",
                "templates",
                "helpers",
                "groups",
                "blueprints",
                "recorder/statistics",
                "energy dashboard",
                "n8n",
                "HKG",
                "MCP",
                "HAMIE proposals",
                "other",
            )
        }
        direct_references = tuple(
            reference
            for item in selected
            for reference in item.recommendation.dependency_assessment.referenced_by
        )
        reference_category = {
            "automation": "automations",
            "script": "scripts",
            "scene": "scenes",
            "dashboard": "dashboards",
            "template": "templates",
            "helper": "helpers",
            "group": "groups",
            "blueprint": "blueprints",
            "recorder": "recorder/statistics",
            "statistics": "recorder/statistics",
            "energy": "energy dashboard",
            "n8n": "n8n",
            "hkg": "HKG",
            "mcp": "MCP",
            "hamie": "HAMIE proposals",
        }
        for reference in direct_references:
            prefix = reference.partition(":")[0].casefold()
            reference_groups[reference_category.get(prefix, "other")].append(reference)
        primary = selected[0]
        primary_facts = _facts(primary, self.group_for_finding.get(primary.finding_id))
        unresolved_sources = tuple(
            sorted(
                {
                    capability
                    for item in selected
                    for capability in (
                        set(
                            item.recommendation.dependency_assessment.required_capabilities
                        )
                        - set(
                            item.recommendation.dependency_assessment.used_capabilities
                        )
                    )
                }
            )
        )
        safe_to_disable = (
            complete
            and not has_dependencies
            and not unresolved_sources
            and all(
                item.recommendation.dependency_assessment.safe_to_remove
                for item in selected
            )
        )
        recommendation = (
            "Safe to disable"
            if safe_to_disable
            else "Dependency coverage incomplete"
            if not complete or unresolved_sources
            else "Manual review required"
            if has_dependencies
            else "Do not modify"
        )
        return {
            "decision": {
                "target": (
                    primary.subject.source_id
                    if len(selected) == 1
                    else f"{len(selected)} grouped findings"
                ),
                "friendly_name": primary.subject.display_hint
                or primary.subject.source_id,
                "integration": next(iter(primary_facts["integration_domain"]), None),
                "config_entry": next(iter(primary_facts["config_entry_id"]), None),
                "device": next(iter(primary_facts["device_id"]), None),
                "area": next(iter(primary_facts["area_id"]), None),
                "dependency_coverage": "complete" if complete else "partial",
                "direct_references": list(dict.fromkeys(direct_references)),
                "indirect_references": [],
                "unresolved_sources": list(unresolved_sources),
                "safe_to_inspect": True,
                "safe_to_disable": safe_to_disable,
                "safe_to_modify": False,
                "reason": (
                    (
                        "Every required dependency source was checked and "
                        "no references remain."
                    )
                    if safe_to_disable
                    else (
                        "HAMIE fails closed while references or unchecked "
                        "dependency sources remain."
                    )
                ),
                "possible_impact": (
                    (
                        "Changing this target may affect the objects listed "
                        "under Referenced by."
                    )
                    if direct_references
                    else (
                        "No impact claim is available until dependency "
                        "coverage is complete."
                    )
                ),
                "recommendation": recommendation,
                "referenced_by": {
                    category: list(dict.fromkeys(values))
                    for category, values in reference_groups.items()
                    if values
                },
                "belongs_to_or_supports": list(
                    dict.fromkeys(
                        value
                        for item in selected
                        for value in (
                            item.recommendation.dependency_assessment.supporting_subject_ids
                        )
                    )
                ),
            },
            "nodes": list(nodes.values())[:MAX_GRAPH_NODES],
            "edges": edges[:MAX_GRAPH_EDGES],
            "coverage": "complete" if complete else "partial",
            "safe_to_remove": (
                False
                if has_dependencies
                else all(
                    item.recommendation.dependency_assessment.safe_to_remove
                    for item in selected
                )
            ),
            "bounded": True,
        }


def _validate_page(search: str, offset: int, limit: int) -> None:
    if (
        not isinstance(search, str)
        or len(search) > MAX_SEARCH_LENGTH
        or offset < 0
        or not 1 <= limit <= MAX_PAGE_SIZE
    ):
        raise ValueError("explorer query exceeds bounds")


def _group_dict(
    group: FindingGroup, *, maximum_visible_members: int = 100
) -> dict[str, Any]:
    return {
        "group_id": group.group_id,
        "grouping_revision": group.grouping_revision,
        "group_revision": group.group_revision,
        "title": group.title,
        "grouping_reason": group.grouping_reason,
        "member_finding_ids": list(group.member_finding_ids[:maximum_visible_members]),
        "member_list_truncated": group.member_count > maximum_visible_members,
        "member_count": group.member_count,
        "open_count": group.open_count,
        "warning_count": group.warning_count,
        "critical_count": group.critical_count,
        "first_seen": group.first_seen.isoformat(),
        "last_seen": group.last_seen.isoformat(),
        "confidence": group.confidence,
        "representative_subjects": list(group.representative_subjects),
        "common_provider": group.common_provider,
        "common_dependency_root": group.common_dependency_root,
        "coverage_state": group.coverage_state,
        "review_state": group.review_state,
        "suppression_state": group.suppression_state,
        "ai_explanation_state": group.ai_explanation_state,
        "facets": _facets_dict(group.facets),
        "priority": group.priority,
    }


def _facets_dict(facets: tuple[tuple[str, str], ...]) -> dict[str, list[str]]:
    """Serialize a group's flat multimap into ``{field: [values...]}``.

    ``group.facets`` is deliberately a flat ``(field, value)`` multimap so a
    group spanning several devices/config entries can carry more than one
    value per field (see ``FindingGroup.facets``'s own docstring). A bare
    ``dict(facets)`` silently collapses that down to one scalar value per
    field -- the exact production defect this fixes: the frontend's
    `facets.integration_domain?.[0]` (an array-first-element access,
    matching this dict's real contract) was instead indexing into a bare
    string's first *character* (e.g. "dreame"[0] == "d"), which
    `humanizeSlug` then capitalized into the single letter "D" -- an
    observed real Overview defect, not hypothetical. Values are
    deduplicated and sorted for a deterministic response.
    """
    grouped: dict[str, list[str]] = {}
    for field, value in facets:
        grouped.setdefault(field, []).append(value)
    return {field: sorted(set(values)) for field, values in grouped.items()}


def _time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a timestamp")
    return require_utc(datetime.fromisoformat(value.replace("Z", "+00:00")), name)


def encode_grouping_rule(value: GroupingRule) -> dict[str, Any]:
    return {
        "rule_id": value.rule_id,
        "name": value.name,
        "matcher": [list(item) for item in value.matcher],
        "title": value.title,
        "enabled": value.enabled,
        "revision": value.revision,
    }


def decode_grouping_rule(raw: object) -> GroupingRule:
    if not isinstance(raw, dict):
        raise ValueError("grouping rule must be an object")
    return GroupingRule(
        rule_id=raw["rule_id"],
        name=raw["name"],
        matcher=tuple((str(item[0]), str(item[1])) for item in raw["matcher"]),
        title=raw["title"],
        enabled=raw.get("enabled", True),
        revision=raw.get("revision", 1),
    )


def encode_suppression_rule(value: SuppressionRule) -> dict[str, Any]:
    return {
        "rule_id": value.rule_id,
        "name": value.name,
        "enabled": value.enabled,
        "scope": value.scope,
        "matcher": [list(item) for item in value.matcher],
        "reason": value.reason,
        "created_at": _time(value.created_at),
        "created_by": value.created_by,
        "expiration": _time(value.expiration) if value.expiration else None,
        "affected_analyzer_ids": list(value.affected_analyzer_ids),
        "action": value.action.value,
        "preview_count": value.preview_count,
        "last_match_count": value.last_match_count,
        "revision": value.revision,
    }


def decode_suppression_rule(raw: object) -> SuppressionRule:
    if not isinstance(raw, dict):
        raise ValueError("suppression rule must be an object")
    return SuppressionRule(
        rule_id=raw["rule_id"],
        name=raw["name"],
        enabled=raw["enabled"],
        scope=raw["scope"],
        matcher=tuple((str(item[0]), str(item[1])) for item in raw["matcher"]),
        reason=raw["reason"],
        created_at=_parse_time(raw["created_at"], "created_at"),
        created_by=raw["created_by"],
        expiration=(
            _parse_time(raw["expiration"], "expiration")
            if raw.get("expiration")
            else None
        ),
        affected_analyzer_ids=tuple(raw.get("affected_analyzer_ids", [])),
        action=SuppressionAction(raw["action"]),
        preview_count=raw["preview_count"],
        last_match_count=raw["last_match_count"],
        revision=raw.get("revision", 1),
    )


def encode_audit(value: AuditRecord) -> dict[str, Any]:
    return {
        "audit_id": value.audit_id,
        "event": value.event,
        "at": _time(value.at),
        "actor": value.actor,
        "target_ids": list(value.target_ids),
        "details": [list(item) for item in value.details],
    }


def decode_audit(raw: object) -> AuditRecord:
    if not isinstance(raw, dict):
        raise ValueError("audit record must be an object")
    return AuditRecord(
        audit_id=raw["audit_id"],
        event=raw["event"],
        at=_parse_time(raw["at"], "audit at"),
        actor=raw["actor"],
        target_ids=tuple(raw.get("target_ids", [])),
        details=tuple((str(item[0]), str(item[1])) for item in raw.get("details", [])),
    )


def encode_ai_recommendation(value: AIRecommendation) -> dict[str, Any]:
    return {
        "recommendation_id": value.recommendation_id,
        "schema_version": value.schema_version,
        "provider": value.provider,
        "model": value.model,
        "created_at": _time(value.created_at),
        "finding_ids": list(value.finding_ids),
        "group_ids": list(value.group_ids),
        "summary": value.summary,
        "probable_causes": list(value.probable_causes),
        "recommended_checks": list(value.recommended_checks),
        "proposed_repair_plan": list(value.proposed_repair_plan),
        "confidence": value.confidence,
        "assumptions": list(value.assumptions),
        "missing_evidence": list(value.missing_evidence),
        "risk_notes": list(value.risk_notes),
        "do_not_do": list(value.do_not_do),
        "review_state": value.review_state.value,
        "source_revisions": [list(item) for item in value.source_revisions],
        "source_evidence_digests": list(value.source_evidence_digests),
        "group_bindings": [
            {
                "group_id": item.group_id,
                "grouping_revision": item.grouping_revision,
                "member_digest": item.member_digest,
                "suppression_digest": item.suppression_digest,
                "dependency_root": item.dependency_root,
            }
            for item in value.group_bindings
        ],
        "stale": value.stale,
        "stale_reasons": list(value.stale_reasons),
        "generated_at": _time(value.generated_at or value.created_at),
        "analysis_started_at": _time(value.analysis_started_at or value.created_at),
        "analysis_completed_at": _time(value.analysis_completed_at or value.created_at),
        "evidence_first_observed_at": (
            _time(value.evidence_first_observed_at)
            if value.evidence_first_observed_at
            else None
        ),
        "evidence_last_observed_at": (
            _time(value.evidence_last_observed_at)
            if value.evidence_last_observed_at
            else None
        ),
        "source_scan_id": value.source_scan_id,
        "source_scan_completed_at": (
            _time(value.source_scan_completed_at)
            if value.source_scan_completed_at
            else None
        ),
        "source_finding_revision": value.source_finding_revision,
        "recommendation_revision": value.recommendation_revision,
        "analysis_total_findings": value.analysis_total_findings,
        "analysis_eligible_findings": value.analysis_eligible_findings,
        "analysis_selected_findings": value.analysis_selected_findings,
        "analysis_skipped_findings": value.analysis_skipped_findings,
        "root_cause_groups_detected": value.root_cause_groups_detected,
        "root_cause_groups_analyzed": value.root_cause_groups_analyzed,
        "root_cause_groups_skipped": value.root_cause_groups_skipped,
        "selection_reason": value.selection_reason,
        "coverage_state": value.coverage_state,
    }


def decode_ai_recommendation(raw: object) -> AIRecommendation:
    if not isinstance(raw, dict):
        raise ValueError("AI recommendation must be an object")
    return AIRecommendation(
        recommendation_id=raw["recommendation_id"],
        schema_version=raw["schema_version"],
        provider=raw["provider"],
        model=raw["model"],
        created_at=_parse_time(raw["created_at"], "AI created_at"),
        finding_ids=tuple(raw.get("finding_ids", [])),
        group_ids=tuple(raw.get("group_ids", [])),
        summary=raw["summary"],
        probable_causes=tuple(raw.get("probable_causes", [])),
        recommended_checks=tuple(raw.get("recommended_checks", [])),
        proposed_repair_plan=tuple(raw.get("proposed_repair_plan", [])),
        confidence=raw["confidence"],
        assumptions=tuple(raw.get("assumptions", [])),
        missing_evidence=tuple(raw.get("missing_evidence", [])),
        risk_notes=tuple(raw.get("risk_notes", [])),
        do_not_do=tuple(raw.get("do_not_do", [])),
        review_state=AIReviewState(raw["review_state"]),
        source_revisions=tuple(
            (str(item[0]), int(item[1])) for item in raw.get("source_revisions", [])
        ),
        source_evidence_digests=tuple(raw.get("source_evidence_digests", [])),
        group_bindings=tuple(
            GroupSourceBinding(
                group_id=item["group_id"],
                grouping_revision=item["grouping_revision"],
                member_digest=item["member_digest"],
                suppression_digest=item["suppression_digest"],
                dependency_root=item.get("dependency_root", ""),
            )
            for item in raw.get("group_bindings", [])
        ),
        stale=raw.get("stale", False),
        stale_reasons=tuple(raw.get("stale_reasons", [])),
        generated_at=(
            _parse_time(raw["generated_at"], "generated_at")
            if raw.get("generated_at")
            else None
        ),
        analysis_started_at=(
            _parse_time(raw["analysis_started_at"], "analysis_started_at")
            if raw.get("analysis_started_at")
            else None
        ),
        analysis_completed_at=(
            _parse_time(raw["analysis_completed_at"], "analysis_completed_at")
            if raw.get("analysis_completed_at")
            else None
        ),
        evidence_first_observed_at=(
            _parse_time(raw["evidence_first_observed_at"], "evidence_first_observed_at")
            if raw.get("evidence_first_observed_at")
            else None
        ),
        evidence_last_observed_at=(
            _parse_time(raw["evidence_last_observed_at"], "evidence_last_observed_at")
            if raw.get("evidence_last_observed_at")
            else None
        ),
        source_scan_id=raw.get("source_scan_id"),
        source_scan_completed_at=(
            _parse_time(raw["source_scan_completed_at"], "source_scan_completed_at")
            if raw.get("source_scan_completed_at")
            else None
        ),
        source_finding_revision=int(raw.get("source_finding_revision", 1)),
        recommendation_revision=int(raw.get("recommendation_revision", 1)),
        analysis_total_findings=int(raw.get("analysis_total_findings", 0)),
        analysis_eligible_findings=int(raw.get("analysis_eligible_findings", 0)),
        analysis_selected_findings=int(raw.get("analysis_selected_findings", 0)),
        analysis_skipped_findings=int(raw.get("analysis_skipped_findings", 0)),
        root_cause_groups_detected=int(raw.get("root_cause_groups_detected", 0)),
        root_cause_groups_analyzed=int(raw.get("root_cause_groups_analyzed", 0)),
        root_cause_groups_skipped=int(raw.get("root_cause_groups_skipped", 0)),
        selection_reason=str(
            raw.get(
                "selection_reason",
                "highest severity and impact within configured evidence budget",
            )
        ),
        coverage_state=str(raw.get("coverage_state", "unknown")),
    )
