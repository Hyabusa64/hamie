"""Versioned deterministic Unavailable Entity Analyzer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ...application.ports import EntityRecord
from ...domain.common import require_utc, stable_digest
from ...domain.dependencies import DependencyAssessment, DependencyCoverage
from ...domain.dependency_references import EntityReferenceIndex
from ...domain.evidence import EvidenceItem, EvidenceKind, Sensitivity
from ...domain.findings import (
    CandidateFinding,
    Confidence,
    ConfidenceFactor,
    ConfidenceLevel,
    FindingSeverity,
    Recommendation,
    RecommendationKind,
    Risk,
    RiskLevel,
)
from ...domain.identity import SubjectIdentity
from ..contracts import (
    AnalysisPartition,
    AnalyzerDescriptor,
    AnalyzerOutcome,
    AnalyzerOutcomeState,
    CostClass,
)

ANALYZER_ID = "hamie.unavailable_entities"
POLICY_VERSION = "1.1.0"
CAPABILITY_ID = "home_assistant.entity_state@1"
RULE_VERSION = "1.1.0"
UNAVAILABLE_GRACE_SECONDS = 300
IGNORED_DOMAINS = frozenset({"button", "event"})
MAX_PARTITION_SIZE = 128
DEPENDENCY_CAPABILITIES = (
    "home_assistant.automation_references@1",
    "home_assistant.blueprint_references@1",
    "home_assistant.dashboard_references@1",
    "home_assistant.device_relationships@1",
    "home_assistant.group_references@1",
    "home_assistant.helper_references@1",
    "home_assistant.integration_relationships@1",
    "home_assistant.recorder_statistics_references@1",
    "home_assistant.scene_references@1",
    "home_assistant.script_references@1",
    "home_assistant.template_references@1",
)
REGISTRY_RELATIONSHIPS = "home_assistant.entity_registry_relationships@1"
# Maps infrastructure/dependency_source.py's scanned source names to the
# declared capability id each one actually satisfies -- real scanning
# coverage (mission Part 12), not just a hardcoded relationships check.
_SOURCE_CAPABILITY = {
    "automation": "home_assistant.automation_references@1",
    "script": "home_assistant.script_references@1",
    "scene": "home_assistant.scene_references@1",
    "group": "home_assistant.group_references@1",
}


def _duration_text(seconds: int) -> str:
    """Format a measured unavailable-duration for the recommendation text
    at the coarsest unit that keeps it genuinely readable -- never a raw
    second count, which reads as noise past a few minutes."""
    minutes = seconds // 60
    if minutes < 60:
        return f"{max(1, minutes)} minute{'s' if minutes != 1 else ''}"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''}"


@dataclass(frozen=True, slots=True)
class UnavailableEntityPolicy:
    """Central versioned false-positive policy for unavailable entities."""

    version: str = POLICY_VERSION
    grace_seconds: int = UNAVAILABLE_GRACE_SECONDS
    ignored_domains: frozenset[str] = IGNORED_DOMAINS
    ignored_entity_ids: frozenset[str] = frozenset()
    ignored_platforms: frozenset[str] = frozenset({"hamie"})
    include_disabled_entities: bool = False
    include_diagnostic_entities: bool = False

    def __post_init__(self) -> None:
        if self.version != POLICY_VERSION:
            raise ValueError("unsupported unavailable-entity policy version")
        if self.grace_seconds < 0:
            raise ValueError("grace_seconds cannot be negative")
        if any(not domain or "." in domain for domain in self.ignored_domains):
            raise ValueError("ignored domains must be normalized domain names")
        if any("." not in entity_id for entity_id in self.ignored_entity_ids):
            raise ValueError("ignored entity IDs must contain a domain")
        if any(not platform or "." in platform for platform in self.ignored_platforms):
            raise ValueError("ignored platforms must be normalized platform names")


class UnavailableEntityAnalyzer:
    """Find registry-backed entities authoritatively unavailable after grace."""

    descriptor = AnalyzerDescriptor(
        analyzer_id=ANALYZER_ID,
        policy_version=POLICY_VERSION,
        capability_id=CAPABILITY_ID,
        cost_class=CostClass.LIGHT,
        allowed_recommendations=(RecommendationKind.MONITOR,),
        max_partition_size=MAX_PARTITION_SIZE,
    )

    def __init__(
        self,
        policy: UnavailableEntityPolicy | None = None,
        *,
        source_instance: str = "home_assistant",
    ) -> None:
        self.policy = policy or UnavailableEntityPolicy()
        if not source_instance or source_instance != source_instance.strip():
            raise ValueError("source_instance must be non-empty normalized text")
        self.source_instance = source_instance

    def analyze(
        self,
        partition: AnalysisPartition,
        *,
        observed_at: datetime,
        reference_index: EntityReferenceIndex | None = None,
    ) -> AnalyzerOutcome:
        """Analyze one immutable partition without I/O or global state.

        ``reference_index`` is optional and additive: when supplied (a
        pure value already captured by
        ``infrastructure/dependency_source.py``, never fetched here),
        each candidate's dependency assessment reports real
        ``referenced_by`` hits and the capabilities actually checked.
        Omitting it preserves the exact prior conservative behavior
        (empty ``referenced_by``, no capabilities marked used) -- this
        analyzer still never performs I/O itself.
        """
        at = require_utc(observed_at, "observed_at")
        if partition.capability_id != self.descriptor.capability_id:
            raise ValueError("partition capability is not supported by analyzer")

        findings: list[CandidateFinding] = []
        covered: list[str] = []
        excluded: list[str] = []
        uncovered: list[str] = []
        indeterminate: list[str] = []

        for record in partition.records:
            subject_key = record.entity_id
            if (
                record.domain in self.policy.ignored_domains
                or record.entity_id in self.policy.ignored_entity_ids
                or record.platform in self.policy.ignored_platforms
                or (
                    record.disabled is True
                    and not self.policy.include_disabled_entities
                )
                or (
                    record.entity_category == "diagnostic"
                    and not self.policy.include_diagnostic_entities
                )
            ):
                excluded.append(subject_key)
                continue
            if record.registry_id is None or record.disabled is None:
                uncovered.append(subject_key)
                continue
            if record.restored is not False or record.state == "unknown":
                indeterminate.append(subject_key)
                continue
            if record.state != "unavailable":
                covered.append(subject_key)
                continue
            unavailable_seconds = max(
                0, int((at - record.last_changed).total_seconds())
            )
            if unavailable_seconds < self.policy.grace_seconds:
                indeterminate.append(subject_key)
                continue

            covered.append(subject_key)
            findings.append(
                self._candidate(
                    record,
                    observed_at=at,
                    source_revision=self._availability_revision(record),
                    unavailable_seconds=unavailable_seconds,
                    reference_index=reference_index,
                )
            )

        has_gaps = bool(uncovered or indeterminate)
        return AnalyzerOutcome(
            analyzer_id=self.descriptor.analyzer_id,
            policy_version=self.policy.version,
            partition_id=partition.partition_id,
            state=(
                AnalyzerOutcomeState.PARTIAL
                if has_gaps
                else AnalyzerOutcomeState.COMPLETE
            ),
            findings=tuple(findings),
            covered_subjects=tuple(covered),
            excluded_subjects=tuple(excluded),
            uncovered_subjects=tuple(uncovered),
            indeterminate_subjects=tuple(indeterminate),
        )

    def semantic_cache_discriminator(
        self, partition: AnalysisPartition, *, observed_at: datetime
    ) -> str:
        """Key only time-dependent policy transitions, not wall-clock time."""
        at = require_utc(observed_at, "observed_at")
        return stable_digest(
            self.policy.version,
            *(
                stable_digest(
                    record.entity_id,
                    record.state == "unavailable"
                    and (at - record.last_changed).total_seconds()
                    >= self.policy.grace_seconds,
                )
                for record in partition.records
            ),
        )

    @staticmethod
    def _availability_revision(record: EntityRecord) -> str:
        """Revision only fields that support this analyzer's evidence."""
        return stable_digest(
            record.entity_id,
            record.state,
            record.last_changed.isoformat(),
            record.registry_id,
            record.disabled,
            record.restored,
            record.entity_category,
        )

    def _candidate(
        self,
        record: EntityRecord,
        *,
        observed_at: datetime,
        source_revision: str,
        unavailable_seconds: int,
        reference_index: EntityReferenceIndex | None = None,
    ) -> CandidateFinding:
        subject = SubjectIdentity(
            durable_id=record.registry_id or "unreachable",
            kind="home_assistant.entity",
            source_instance=self.source_instance,
            source_id=record.entity_id,
            display_hint=record.friendly_name or record.entity_id,
            aliases=(record.entity_id,),
        )
        evidence = (
            EvidenceItem(
                subject=subject,
                predicate="home_assistant.entity.current_state@1",
                value="unavailable",
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=source_revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.REDACT,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.entity.unavailable_grace_elapsed@1",
                value=True,
                observed_at=observed_at,
                source_id="hamie.unavailable_policy",
                source_revision=self.policy.version,
                kind=EvidenceKind.DERIVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            # Real, measured duration -- not just a boolean "past grace" --
            # so a finding that has been unavailable for 6 months and one
            # that crossed the 5-minute grace period a moment ago are
            # never presented as equivalent. Previously computed
            # (unavailable_seconds) but never actually surfaced anywhere,
            # so every finding's evidence looked identical regardless of
            # how long the real underlying condition had persisted.
            EvidenceItem(
                subject=subject,
                predicate="hamie.entity.unavailable_seconds@1",
                value=unavailable_seconds,
                observed_at=observed_at,
                source_id="hamie.unavailable_policy",
                source_revision=self.policy.version,
                kind=EvidenceKind.DERIVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            # Real Home Assistant entity-registry category ("diagnostic",
            # "config", or absent for a primary/normal entity) --
            # captured here because it is only accessible on the source
            # EntityRecord at capture time; once a Finding exists this is
            # the only place that fact survives. Used downstream (see
            # runtime_projection.py's health-dimension split) to tell
            # optional/diagnostic registry clutter apart from a primary
            # entity actually being unavailable, so a house with hundreds
            # of stale diagnostic sensors is never reported as
            # operationally unhealthy.
            EvidenceItem(
                subject=subject,
                predicate="home_assistant.entity.entity_category@1",
                value=record.entity_category or "primary",
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=source_revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
        )
        supporting = tuple(
            value
            for value in (
                f"device:{record.device_id}" if record.device_id else None,
                (
                    f"config_entry:{record.config_entry_id}"
                    if record.config_entry_id
                    else None
                ),
                f"integration:{record.platform}" if record.platform else None,
            )
            if value is not None
        )
        referenced_by: tuple[str, ...] = ()
        scanned_capabilities: tuple[str, ...] = ()
        rationale = (
            "Entity-registry ownership relationships were inspected. Public "
            "Home Assistant APIs do not expose complete reverse references for "
            "automations, scripts, dashboards, scenes, helpers, templates, "
            "blueprints, Recorder, or statistics, so removal safety is unknown."
        )
        if reference_index is not None:
            hits = reference_index.referenced_by(record.entity_id)
            referenced_by = tuple(
                sorted(f"{hit.source}:{hit.referencing_object_id}" for hit in hits)
            )
            scanned_capabilities = tuple(
                _SOURCE_CAPABILITY[source]
                for source in reference_index.coverage.scanned_sources
                if source in _SOURCE_CAPABILITY
            )
            if reference_index.coverage.scanned_sources:
                scanned_text = ", ".join(
                    sorted(reference_index.coverage.scanned_sources)
                )
                unscanned_text = ", ".join(reference_index.coverage.unscanned_sources)
                found_text = (
                    f"Found {len(referenced_by)} reference(s)."
                    if referenced_by
                    else "No references found among the sources actually scanned."
                )
                rationale = (
                    f"Entity-registry relationships plus {scanned_text} were "
                    f"scanned. {found_text} Not scanned: {unscanned_text}."
                )
        dependency = DependencyAssessment(
            subject=subject,
            required_capabilities=(*DEPENDENCY_CAPABILITIES, REGISTRY_RELATIONSHIPS),
            used_capabilities=(REGISTRY_RELATIONSHIPS, *scanned_capabilities),
            # Never COMPLETE from this analyzer alone: dashboards, templates,
            # helpers, blueprints, recorder/statistics, energy, n8n, HKG, and
            # MCP remain unscanned regardless of what the automation/script/
            # scene/group scan found -- see domain/dependency_references.py.
            coverage=DependencyCoverage.PARTIAL,
            rationale=rationale,
            supporting_subject_ids=supporting,
            referenced_by=referenced_by,
            # Never asserted true by this analyzer -- a higher-level cleanup
            # classifier (domain/cleanup_classifier.py) is the only place
            # "safe to act on" is decided, weighing this partial-coverage
            # signal against the user's configured
            # dependency_coverage_requirement.
            safe_to_remove=False,
        )
        confidence = Confidence(
            level=ConfidenceLevel.HIGH,
            factors=(
                ConfidenceFactor(
                    code="authoritative_current_state",
                    effect=80,
                    rationale="Home Assistant authoritatively reported unavailable.",
                ),
                ConfidenceFactor(
                    code="grace_elapsed",
                    effect=20,
                    rationale="The versioned transient grace period elapsed.",
                ),
            ),
            rule_revision="unavailable-confidence@1",
        )
        risk = Risk(
            likelihood=RiskLevel.LOW,
            impact=RiskLevel.LOW,
            reversible=True,
            affected_scope="HAMIE review state only",
            overall=RiskLevel.LOW,
            rationale="Monitoring is advisory and does not modify Home Assistant.",
        )
        duration_text = _duration_text(unavailable_seconds)
        integration_text = f" ({record.platform})" if record.platform else ""
        recommendation = Recommendation(
            kind=RecommendationKind.MONITOR,
            # Includes the real entity id, its real providing integration
            # (when known), and how long it has actually been unavailable
            # -- previously an identical, unparameterized sentence
            # regardless of which entity or integration was involved,
            # making dozens of genuinely distinct findings read as
            # indistinguishable duplicates.
            action=(
                f"Review {record.entity_id}{integration_text} and its providing "
                f"integration -- unavailable for {duration_text}."
            ),
            rationale=(
                "The entity remains unavailable after the configured transient grace "
                "period; unavailability alone does not prove obsolescence."
            ),
            evidence=evidence,
            confidence=confidence,
            dependency_assessment=dependency,
            risk=risk,
            analyzer_id=ANALYZER_ID,
            rule_revision=RULE_VERSION,
            preconditions=(
                "Confirm the providing integration is expected to be online.",
            ),
            disqualifiers=("Do not infer that the entity is safe to remove.",),
        )
        return CandidateFinding(
            analyzer_id=ANALYZER_ID,
            rule_version=RULE_VERSION,
            condition_key="current_state_unavailable_after_grace",
            subject=subject,
            category="availability",
            title_key="unavailable_entity",
            description_arguments=(("entity_id", record.entity_id),),
            severity=FindingSeverity.WARNING,
            evidence=evidence,
            recommendation=recommendation,
        )
