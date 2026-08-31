"""Removed-integration orphan analyzer (mission Part 2, Analyzer 2).

Formalizes the already-proven Lutron pattern (``lutron_caseta_pro``,
found 16x this session) as an explicit, reusable, non-Lutron-specific
check: an entity is orphaned by a *removed integration*, not merely a
broken/renamed entity, when all of these independently-observable facts
line up:

- ``config_entry_id`` is ``None`` and ``device_id`` is ``None`` (the
  registry row has no owning config entry or device left at all);
- its ``platform`` has zero live config entries anywhere in the current
  installation;
- no ``custom_components/<platform>`` directory exists (the
  integration's code itself is gone, not merely unconfigured).

There are two conservative disqualifiers before those tests are allowed
to support a finding:

- known core/YAML/helper platforms are excluded by
  ``InstallationTopology`` because their normal ownership model often
  has neither a config entry nor a custom-components directory;
- an entity whose source definition is positively known to be present
  is excluded.  Missing ownership metadata must never outweigh direct
  evidence that the live definition still exists.

The last two facts come from
``infrastructure/installation_topology.py``'s
``InstallationTopology.platform_has_removed_integration`` -- genuinely
new infrastructure this pass added (see that module's own docstring for
why nothing in HAMIE captured either fact before). Whole-collection
purely for wiring convenience (every whole-collection analyzer already
receives ``installation_topology`` fresh each capture -- see
``analysis/whole_collection_supervisor.py``); the check itself is a
plain per-entity evaluation with no cross-entity comparison.
"""

from __future__ import annotations

import logging
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
    RemediationSafetyGate,
    Risk,
    RiskLevel,
)
from ...domain.identity import SubjectIdentity
from ...domain.protection import cap_safety_gate_for_protection, is_protected_subject
from ..contracts import AnalyzerDescriptor, AnalyzerOutcome, AnalyzerOutcomeState, CostClass

ANALYZER_ID = "hamie.removed_integration_orphan"
POLICY_VERSION = "1.1.0"
CAPABILITY_ID = "hamie.removed_integration_orphan_analysis@1"
RULE_VERSION = "1.1.0"
CONDITION_KEY = "removed_integration_orphan"
REFERENCED_CONDITION_KEY = "removed_integration_broken_reference"
# mission Part 6: DEBUG-only, per-entity evidence -- see
# functional_self_reference.py's note on why no prior analyzer-module
# logging convention exists to match.
_LOGGER = logging.getLogger(__name__)


class RemovedIntegrationOrphanAnalyzer:
    """Find entities orphaned by a fully-removed custom integration."""

    descriptor = AnalyzerDescriptor(
        analyzer_id=ANALYZER_ID,
        policy_version=POLICY_VERSION,
        capability_id=CAPABILITY_ID,
        cost_class=CostClass.LIGHT,
        allowed_recommendations=(
            RecommendationKind.INVESTIGATE,
            RecommendationKind.DELETE_CANDIDATE,
        ),
        max_partition_size=100_000,
    )

    def __init__(self, *, source_instance: str = "home_assistant") -> None:
        if not source_instance or source_instance != source_instance.strip():
            raise ValueError("source_instance must be non-empty normalized text")
        self.source_instance = source_instance

    def analyze_collection(
        self,
        records: tuple[EntityRecord, ...],
        *,
        observed_at: datetime,
        reference_index: EntityReferenceIndex | None = None,
        source_index: object | None = None,
        installation_topology: object | None = None,
        # Accepted for the whole-collection call contract. This analyzer does
        # not use it: relevance is analyzer-specific, and marking an outcome
        # partial for an unrelated unreadable entity would make coverage
        # meaningless.
        skipped_subjects: frozenset[str] = frozenset(),
    ) -> AnalyzerOutcome:
        at = require_utc(observed_at, "observed_at")
        findings: list[CandidateFinding] = []
        covered: list[str] = []
        excluded: list[str] = []
        uncovered: list[str] = []

        if installation_topology is None:
            return AnalyzerOutcome(
                analyzer_id=ANALYZER_ID,
                policy_version=POLICY_VERSION,
                partition_id=stable_digest("whole_collection", len(records))[:24],
                state=AnalyzerOutcomeState.PARTIAL,
                findings=(),
                covered_subjects=(),
                uncovered_subjects=tuple(sorted(item.entity_id for item in records)),
            )

        for record in records:
            try:
                if record.config_entry_id is not None or record.device_id is not None:
                    excluded.append(record.entity_id)
                    continue
                if record.source_definition_missing is False:
                    # A successful source-index lookup is stronger evidence
                    # than the absence of registry ownership metadata.  This
                    # hard guard prevents live YAML/UI definitions from ever
                    # becoming registry-removal candidates in this analyzer.
                    excluded.append(record.entity_id)
                    continue
                if not record.platform:
                    # No platform captured at all -- genuinely not
                    # evaluable, never guessed either way.
                    uncovered.append(record.entity_id)
                    continue
                if not installation_topology.platform_has_removed_integration(
                    record.platform
                ):
                    covered.append(record.entity_id)
                    continue
                # Built, then only committed to `findings`/`covered`
                # together below -- if `_candidate` itself raised
                # partway through, record.entity_id must never end up
                # in both `covered` (added early) and `uncovered`
                # (added by the except clause) at once
                # (AnalyzerOutcome.__post_init__ requires them disjoint).
                _LOGGER.debug(
                    "HAMIE removed_integration_orphan match: entity=%s platform=%s",
                    record.entity_id,
                    record.platform,
                )
                finding = self._candidate(
                    record, observed_at=at, reference_index=reference_index
                )
                findings.append(finding)
                covered.append(record.entity_id)
            except Exception:  # noqa: BLE001 -- one malformed entity never
                # aborts the scan (mission Part 6).
                uncovered.append(record.entity_id)
                continue

        has_gaps = bool(uncovered)
        return AnalyzerOutcome(
            analyzer_id=ANALYZER_ID,
            policy_version=POLICY_VERSION,
            partition_id=stable_digest("whole_collection", len(records))[:24],
            state=(
                AnalyzerOutcomeState.PARTIAL if has_gaps else AnalyzerOutcomeState.COMPLETE
            ),
            findings=tuple(findings),
            covered_subjects=tuple(sorted(covered)),
            excluded_subjects=tuple(sorted(excluded)),
            uncovered_subjects=tuple(sorted(uncovered)),
        )

    def _candidate(
        self,
        record: EntityRecord,
        *,
        observed_at: datetime,
        reference_index: EntityReferenceIndex | None,
    ) -> CandidateFinding:
        protected = is_protected_subject(
            entity_id=record.entity_id,
            domain=record.domain,
            device_class=record.device_class,
            friendly_name=record.friendly_name,
            unique_id=record.unique_id,
        )
        subject = SubjectIdentity(
            durable_id=record.registry_id or record.entity_id,
            kind="home_assistant.entity",
            source_instance=self.source_instance,
            source_id=record.entity_id,
            display_hint=record.friendly_name or record.entity_id,
            aliases=(record.entity_id,),
        )
        referenced_by: tuple[str, ...] = ()
        reference_coverage_complete = False
        if reference_index is not None:
            hits = reference_index.referenced_by(record.entity_id)
            referenced_by = tuple(
                sorted(f"{hit.source}:{hit.referencing_object_id}" for hit in hits)
            )
            reference_coverage_complete = (
                reference_index.coverage.implemented_sources_succeeded
            )
        safe_to_remove = reference_coverage_complete and not referenced_by
        revision = stable_digest(
            record.entity_id,
            record.platform,
            record.config_entry_id,
            record.device_id,
            reference_coverage_complete,
            referenced_by,
        )
        evidence = (
            EvidenceItem(
                subject=subject,
                predicate="hamie.entity.platform@1",
                value=record.platform,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.entity.config_entry_id_present@1",
                value=False,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.entity.device_id_present@1",
                value=False,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.installation_topology.platform_has_live_config_entries@1",
                value=False,
                observed_at=observed_at,
                source_id="hamie.installation_topology",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.installation_topology.custom_component_dir_present@1",
                value=False,
                observed_at=observed_at,
                source_id="hamie.installation_topology",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.dependency.reference_scan_complete@1",
                value=reference_coverage_complete,
                observed_at=observed_at,
                source_id="hamie.reference_index",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.dependency.referenced_by_count@1",
                value=len(referenced_by),
                observed_at=observed_at,
                source_id="hamie.reference_index",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
        ) + tuple(
            # One scalar observation per reference.  The previous single item
            # carried the whole tuple as `value`, which violates the scalar
            # EvidenceValue contract and made the persisted document
            # unreadable.  Emitting one item per reference keeps machine
            # readable provenance (each reference remains individually
            # addressable by evidence_id) instead of flattening it into a
            # lossy joined string.  `referenced_by` is already sorted, so the
            # emitted order -- and every resulting evidence_id -- is
            # deterministic.  The complete tuple also remains available in
            # DependencyAssessment.referenced_by below.
            EvidenceItem(
                subject=subject,
                predicate="hamie.dependency.referenced_by@1",
                value=reference,
                observed_at=observed_at,
                source_id="hamie.reference_index",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            )
            for reference in referenced_by
        )
        topology_rationale = (
            f"{record.entity_id} has no config_entry_id and no device_id, its "
            f"platform ({record.platform}) has zero live config entries "
            "anywhere in this installation, and no custom_components/"
            f"{record.platform} directory exists -- the integration that once "
            "backed this entity has been fully removed, not merely "
            "unconfigured or renamed."
        )
        if referenced_by:
            rationale = (
                f"{topology_rationale} It is still targeted by "
                f"{len(referenced_by)} captured reference(s), so registry cleanup "
                "would break or conceal an active dependency."
            )
        elif not reference_coverage_complete:
            rationale = (
                f"{topology_rationale} Dependency capture was incomplete, so HAMIE "
                "cannot determine whether registry cleanup is safe."
            )
        else:
            rationale = topology_rationale
        confidence = Confidence(
            level=ConfidenceLevel.HIGH,
            factors=(
                ConfidenceFactor(
                    code="orphaned_registry_row",
                    effect=40,
                    rationale="No config_entry_id and no device_id on the registry row.",
                ),
                ConfidenceFactor(
                    code="platform_fully_removed",
                    effect=40,
                    rationale=(
                        "Zero live config entries for this platform, and its "
                        "custom_components source directory is gone."
                    ),
                ),
            ),
            rule_revision="removed-integration-orphan-confidence@1",
        )
        risk = Risk(
            likelihood=RiskLevel.LOW,
            impact=RiskLevel.MEDIUM if referenced_by else RiskLevel.LOW,
            reversible=True,
            affected_scope="Home Assistant entity registry (advisory only)",
            overall=RiskLevel.MEDIUM if referenced_by else RiskLevel.LOW,
            rationale="HAMIE never disables or deletes anything itself.",
        )
        dependency = DependencyAssessment(
            subject=subject,
            required_capabilities=(CAPABILITY_ID,),
            used_capabilities=(CAPABILITY_ID,),
            coverage=(
                DependencyCoverage.COMPLETE
                if reference_coverage_complete
                else DependencyCoverage.PARTIAL
            ),
            rationale=rationale,
            referenced_by=referenced_by,
            supporting_subject_ids=(f"integration:{record.platform}",),
            safe_to_remove=safe_to_remove,
        )
        recommendation_kind = (
            RecommendationKind.DELETE_CANDIDATE
            if safe_to_remove
            else RecommendationKind.INVESTIGATE
        )
        gate = cap_safety_gate_for_protection(
            (
                RemediationSafetyGate.SAFE_TO_REMOVE_REGISTRY
                if safe_to_remove
                else RemediationSafetyGate.FUNCTIONAL_BUG
                if referenced_by
                else RemediationSafetyGate.BLOCKED_INSUFFICIENT_EVIDENCE
            ),
            protected=protected,
        )
        if referenced_by:
            action = (
                f"Do not remove {record.entity_id}. Investigate and migrate its "
                f"{len(referenced_by)} captured reference(s) to verified live "
                "targets through a source-backed remediation proposal first."
            )
        elif not reference_coverage_complete:
            action = (
                f"Do not remove {record.entity_id}. Complete dependency capture "
                "and confirm there are no target writers before proposing cleanup."
            )
        else:
            action = (
                f"Review removal of {record.entity_id} -- its integration "
                f"({record.platform}) is absent and the implemented dependency "
                "scan found no references. Any registry change still requires a "
                "separate approved remediation."
            )
        recommendation = Recommendation(
            kind=recommendation_kind,
            action=action,
            rationale=rationale,
            evidence=evidence,
            confidence=confidence,
            dependency_assessment=dependency,
            risk=risk,
            analyzer_id=ANALYZER_ID,
            rule_revision=RULE_VERSION,
            preconditions=(
                "Confirm the integration is genuinely gone, not simply "
                "reloading or mid-update.",
            ),
            disqualifiers=(
                "Do not remove if this entity_id is still referenced by "
                "another automation, script, dashboard, or template.",
            ),
            safety_gate=gate,
            blocked_reason=(
                "Captured dependencies still target this entity."
                if referenced_by
                else "Dependency evidence is incomplete."
                if not reference_coverage_complete
                else None
            ),
        )
        return CandidateFinding(
            analyzer_id=ANALYZER_ID,
            rule_version=RULE_VERSION,
            condition_key=(
                REFERENCED_CONDITION_KEY if referenced_by else CONDITION_KEY
            ),
            subject=subject,
            category="hygiene",
            title_key="removed_integration_orphan",
            description_arguments=(
                ("entity_id", record.entity_id),
                ("platform", record.platform or "unknown"),
            ),
            severity=(
                FindingSeverity.ERROR if referenced_by else FindingSeverity.WARNING
            ),
            evidence=evidence,
            recommendation=recommendation,
        )
