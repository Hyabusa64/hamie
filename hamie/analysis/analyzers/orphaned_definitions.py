"""Versioned deterministic Orphaned Definition Analyzer.

Sibling of ``unavailable_entities.py`` -- same contract
(``AnalyzerDescriptor`` + ``analyze(partition, observed_at=...)`` ->
``AnalyzerOutcome``), same immutability and I/O-free discipline, same
evidence/finding/recommendation shape. It exists to close the single
largest gap identified against the independent entity-hygiene
benchmark (see ``benchmark/entity_hygiene_dry_run_report.md``): 561
``automation``/``script``/``scene`` entity-registry rows whose backing
YAML (or UI-editor) definition has been deleted, while the registry row
itself was never cleaned up -- a well-known Home Assistant behavior
when a YAML-defined automation/script/scene is removed by hand rather
than through the UI editor. ``unavailable_entities.py`` alone does not
reliably surface these: many of them come back from Home Assistant
restart as a "restored" state-machine entry (last known state replayed
from the database, with no live platform to ever un-restore it), which
that analyzer's own policy treats as ``indeterminate`` forever --
never a plain ``unavailable`` finding, regardless of how long the
definition has actually been gone. Detecting "definition genuinely
absent from live config" needs a different, positive signal
(``EntityRecord.source_definition_missing``) that
``current_state_unavailable_after_grace`` was never designed to
compute.

Population of ``source_definition_missing`` on a real Home Assistant
instance is now implemented, in ``infrastructure/ha_source.py``:
``HomeAssistantOperationalSource`` builds
``infrastructure/source_definition_index.py``'s ``SourceDefinitionIndex``
once per capture from the real live config tree
(``hass.config.path()``, read via ``hass.async_add_executor_job``) and
looks each automation/script/scene entity up against it, exactly the
cross-reference the benchmark's offline audit performed by hand. This
analyzer itself needed no changes to consume that: it was already
written and validated end-to-end against the benchmark's precomputed
``source_definition_missing`` field (``benchmark/run_validation.py``),
and that field's live producer now sits behind the identical
``EntityRecord`` contract.
"""

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

ANALYZER_ID = "hamie.orphaned_definitions"
POLICY_VERSION = "1.0.0"
# A distinct capability from unavailable_entities.py's
# "home_assistant.entity_state@1" -- this analyzer needs the
# definition-presence signal, not merely current state, so it is
# partitioned and scheduled independently by the supervisor.
CAPABILITY_ID = "home_assistant.definition_presence@1"
RULE_VERSION = "1.0.0"
COVERED_DOMAINS = frozenset({"automation", "script", "scene"})
MAX_PARTITION_SIZE = 128


@dataclass(frozen=True, slots=True)
class OrphanedDefinitionPolicy:
    """Central versioned policy for the orphaned-definition analyzer."""

    version: str = POLICY_VERSION
    covered_domains: frozenset[str] = COVERED_DOMAINS
    include_disabled_entities: bool = False

    def __post_init__(self) -> None:
        if self.version != POLICY_VERSION:
            raise ValueError("unsupported orphaned-definition policy version")
        if not self.covered_domains <= COVERED_DOMAINS:
            raise ValueError("covered_domains must be a subset of COVERED_DOMAINS")


class OrphanedDefinitionAnalyzer:
    """Find automation/script/scene entities whose config definition is gone."""

    descriptor = AnalyzerDescriptor(
        analyzer_id=ANALYZER_ID,
        policy_version=POLICY_VERSION,
        capability_id=CAPABILITY_ID,
        cost_class=CostClass.LIGHT,
        # DISABLE remains the default, weaker-evidence recommendation:
        # HAMIE never deletes or modifies Home Assistant state itself
        # (see mission constraints) regardless of which of these two
        # kinds is chosen -- both are equally advisory. DELETE_CANDIDATE
        # is additionally allowed for the narrower case (see
        # _candidate() below) where a reference scan actually ran,
        # found zero references, and every reference source it
        # attempted succeeded -- strong enough evidence to name the
        # stronger action as a *candidate* for a human to consider, not
        # to perform it. Once confirmed safe, removing the orphaned
        # registry row is still always a manual step in the Home
        # Assistant UI.
        allowed_recommendations=(
            RecommendationKind.DISABLE,
            RecommendationKind.DELETE_CANDIDATE,
        ),
        max_partition_size=MAX_PARTITION_SIZE,
    )

    def __init__(
        self,
        policy: OrphanedDefinitionPolicy | None = None,
        *,
        source_instance: str = "home_assistant",
    ) -> None:
        self.policy = policy or OrphanedDefinitionPolicy()
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
        """Analyze one immutable partition without I/O or global state."""
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
            if record.domain not in self.policy.covered_domains:
                excluded.append(subject_key)
                continue
            if (
                record.disabled is True
                and not self.policy.include_disabled_entities
            ):
                excluded.append(subject_key)
                continue
            if record.registry_id is None or record.disabled is None:
                uncovered.append(subject_key)
                continue
            if record.source_definition_missing is None:
                # The positive signal this analyzer exists to add was
                # never computed for this record -- honestly report
                # "not evaluated", never assume either answer.
                uncovered.append(subject_key)
                continue

            covered.append(subject_key)
            if record.source_definition_missing is not True:
                continue

            findings.append(
                self._candidate(
                    record,
                    observed_at=at,
                    source_revision=self._definition_revision(record),
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
        """Key only the definition-presence signal, not wall-clock time."""
        require_utc(observed_at, "observed_at")
        return stable_digest(
            self.policy.version,
            *(
                stable_digest(record.entity_id, record.source_definition_missing)
                for record in partition.records
            ),
        )

    @staticmethod
    def _definition_revision(record: EntityRecord) -> str:
        return stable_digest(
            record.entity_id,
            record.source_definition_missing,
            record.state,
            record.registry_id,
            record.disabled,
        )

    def _candidate(
        self,
        record: EntityRecord,
        *,
        observed_at: datetime,
        source_revision: str,
        reference_index: EntityReferenceIndex | None,
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
                predicate="hamie.entity.source_definition_missing@1",
                value=True,
                observed_at=observed_at,
                source_id="hamie.orphaned_definitions_policy",
                source_revision=self.policy.version,
                kind=EvidenceKind.DERIVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="home_assistant.entity.current_state@1",
                value=record.state,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=source_revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.REDACT,
            ),
            EvidenceItem(
                subject=subject,
                predicate="home_assistant.entity.domain@1",
                value=record.domain,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=source_revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
        )
        referenced_by: tuple[str, ...] = ()
        rationale = (
            "The entity's config definition was not found in the scanned "
            "configuration tree (automations.yaml/scripts.yaml/scenes.yaml/"
            "packages), but reverse-reference scanning was not additionally "
            "supplied to this analyzer -- removal safety from other "
            "referencing objects is unknown."
        )
        # Strong-evidence path: a reference scan actually ran, every
        # source it attempted succeeded (no failed/unavailable sources
        # -- see DependencyScanCoverage.implemented_sources_succeeded),
        # and it found zero references to this entity anywhere. This is
        # deliberately the same bar DependencyAssessment itself already
        # enforces for safe_to_remove=True (complete coverage, no
        # referenced_by) -- never loosened here.
        reference_scan_complete = False
        if reference_index is not None:
            hits = reference_index.referenced_by(record.entity_id)
            referenced_by = tuple(
                sorted(f"{hit.source}:{hit.referencing_object_id}" for hit in hits)
            )
            found_text = (
                f"Found {len(referenced_by)} reference(s) among scanned sources."
                if referenced_by
                else "No references found among the sources actually scanned."
            )
            rationale = (
                "The entity's config definition was not found in the scanned "
                f"configuration tree. {found_text}"
            )
            reference_scan_complete = (
                not referenced_by and reference_index.coverage.implemented_sources_succeeded
            )
        if reference_scan_complete:
            dependency = DependencyAssessment(
                subject=subject,
                required_capabilities=(CAPABILITY_ID,),
                used_capabilities=(CAPABILITY_ID,),
                coverage=DependencyCoverage.COMPLETE,
                rationale=(
                    f"{rationale} Every reference source HAMIE attempts this "
                    "release succeeded and none found a reference -- strong "
                    "enough evidence to surface DELETE_CANDIDATE, still only "
                    "as an advisory suggestion for a human to confirm."
                ),
                referenced_by=referenced_by,
                safe_to_remove=True,
            )
        else:
            dependency = DependencyAssessment(
                subject=subject,
                required_capabilities=(CAPABILITY_ID,),
                used_capabilities=(CAPABILITY_ID,),
                coverage=DependencyCoverage.PARTIAL,
                rationale=rationale,
                referenced_by=referenced_by,
                safe_to_remove=False,
            )
        confidence = Confidence(
            level=ConfidenceLevel.HIGH,
            factors=(
                ConfidenceFactor(
                    code="definition_absent_from_live_config",
                    effect=80,
                    rationale=(
                        "No matching automation/script/scene definition exists "
                        "anywhere in the scanned live configuration tree."
                    ),
                ),
                ConfidenceFactor(
                    code="registry_row_orphaned",
                    effect=20,
                    rationale=(
                        "The entity registry row persists even though its "
                        "backing definition is gone -- a known Home Assistant "
                        "behavior when YAML config is edited by hand."
                    ),
                ),
            ),
            rule_revision="orphaned-definition-confidence@1",
        )
        risk = Risk(
            likelihood=RiskLevel.LOW,
            impact=RiskLevel.LOW,
            reversible=True,
            affected_scope="Home Assistant entity registry (disable only, no delete)",
            overall=RiskLevel.LOW,
            rationale=(
                "HAMIE never disables or deletes anything itself -- this is a "
                "suggestion only; removing the orphaned registry row remains "
                "a manual step in the Home Assistant UI, gated by a human "
                "decision either way."
            ),
        )
        # DELETE_CANDIDATE only when the strong-evidence path above
        # actually ran a complete, zero-reference dependency scan;
        # otherwise the original, weaker DISABLE recommendation is
        # unchanged -- this never regresses an existing DISABLE outcome
        # into something it has not earned.
        recommendation_kind = (
            RecommendationKind.DELETE_CANDIDATE
            if reference_scan_complete
            else RecommendationKind.DISABLE
        )
        action = (
            (
                f"Delete candidate: {record.entity_id} -- its {record.domain} "
                "definition is no longer present in live configuration, and "
                "every reference source HAMIE scans found no remaining "
                "reference to it. Still advisory only: confirm by hand, then "
                "remove the orphaned registry row via Settings -> Devices & "
                "Services -> Entities."
            )
            if reference_scan_complete
            else (
                f"Disable {record.entity_id} -- its {record.domain} definition "
                "is no longer present in live configuration. Once confirmed "
                "safe, remove the orphaned registry row via Settings -> "
                "Devices & Services -> Entities."
            )
        )
        recommendation = Recommendation(
            kind=recommendation_kind,
            action=action,
            rationale=(
                "The entity's backing YAML/UI definition could not be found "
                "anywhere in the scanned configuration tree, so Home Assistant "
                "can no longer load or run it -- the registry row is "
                "orphaned."
            ),
            evidence=evidence,
            confidence=confidence,
            dependency_assessment=dependency,
            risk=risk,
            analyzer_id=ANALYZER_ID,
            rule_revision=RULE_VERSION,
            preconditions=(
                "Confirm the definition was intentionally removed, not "
                "temporarily commented out or mid-migration.",
            ),
            disqualifiers=(
                "Do not disable if this entity_id is still referenced by "
                "another automation, script, dashboard, or template.",
            ),
        )
        return CandidateFinding(
            analyzer_id=ANALYZER_ID,
            rule_version=RULE_VERSION,
            condition_key="source_definition_missing",
            subject=subject,
            category="hygiene",
            title_key="orphaned_definition",
            description_arguments=(("entity_id", record.entity_id),),
            severity=FindingSeverity.WARNING,
            evidence=evidence,
            recommendation=recommendation,
        )
