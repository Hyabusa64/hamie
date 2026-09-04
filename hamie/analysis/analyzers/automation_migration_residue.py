"""Automation ID migration-residue analyzer (mission Part 2, Analyzer 4).

Wraps ``domain/automation_residue.py`` in the standard finding shape.
Pairs an old ``automation.*`` registry entity whose YAML ``id:``
genuinely no longer exists in current source
(``EntityRecord.source_definition_missing is True``, the same
structured signal ``orphaned_definitions.py`` already computes) with a
live, current suffix sibling automation, and tags the temporal-
confidence claim honestly -- see ``domain/automation_residue.py``'s
module docstring for the explicitly-disclosed reason this analyzer can
never emit a ``PROVEN`` "genuinely dead, never fires" verdict with
today's infrastructure.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ...application.ports import EntityRecord
from ...domain.automation_residue import (
    AutomationResidueEvidence,
    AutomationResidueTemporalTag,
    classify_automation_residue_temporal_evidence,
)
from ...domain.common import require_utc, stable_digest
from ...domain.dependencies import DependencyAssessment, DependencyCoverage
from ...domain.dependency_references import EntityReferenceIndex
from ...domain.duplicate_classifier import group_suffix_siblings
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

ANALYZER_ID = "hamie.automation_migration_residue"
POLICY_VERSION = "1.0.0"
CAPABILITY_ID = "hamie.automation_migration_residue_analysis@1"
RULE_VERSION = "1.0.0"
CONDITION_KEY = "automation_migration_residue"
# mission Part 6: DEBUG-only, per-group evidence -- see
# functional_self_reference.py's note on why no prior analyzer-module
# logging convention exists to match.
_LOGGER = logging.getLogger(__name__)


class AutomationMigrationResidueAnalyzer:
    """Find automation.* registry rows whose YAML id is confirmed gone,
    alongside a live current sibling -- with honest temporal tagging."""

    descriptor = AnalyzerDescriptor(
        analyzer_id=ANALYZER_ID,
        policy_version=POLICY_VERSION,
        capability_id=CAPABILITY_ID,
        cost_class=CostClass.LIGHT,
        allowed_recommendations=(
            RecommendationKind.NEEDS_EVIDENCE,
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
        by_entity_id = {record.entity_id: record for record in records}
        automation_ids = tuple(
            record.entity_id for record in records if record.domain == "automation"
        )
        groups = group_suffix_siblings(automation_ids)

        findings: list[CandidateFinding] = []
        covered: list[str] = []
        uncovered: list[str] = []

        for group_key, member_ids in groups.items():
            # Built up locally and only merged into `covered`/`findings`
            # after this group's processing succeeds in full -- a
            # partial success followed by a mid-group exception (e.g.
            # `_candidate`'s reference_index lookup raising for a later
            # dead candidate) must never leave group_key in *both*
            # covered and uncovered (AnalyzerOutcome.__post_init__
            # requires them disjoint).
            group_findings: list[CandidateFinding] = []
            group_covered: list[str] = []
            try:
                dead_candidates = [
                    by_entity_id[entity_id]
                    for entity_id in member_ids
                    if by_entity_id.get(entity_id) is not None
                    and by_entity_id[entity_id].source_definition_missing is True
                ]
                live_candidates = [
                    by_entity_id[entity_id]
                    for entity_id in member_ids
                    if by_entity_id.get(entity_id) is not None
                    and by_entity_id[entity_id].source_definition_missing is False
                    and by_entity_id[entity_id].state != "unavailable"
                ]
                # These two emptiness cases mean opposite things and must not
                # share a branch.
                #
                # No LIVE candidate: there is no surviving sibling to compare
                # residue against, so this analyzer genuinely cannot judge the
                # group. Honestly uncovered.
                if not live_candidates:
                    uncovered.append(group_key)
                    continue
                # No DEAD candidate, with a live sibling present: the analyzer
                # examined every member and found no residue. That is a
                # conclusive healthy evaluation, and recording it as
                # "uncovered" -- as this branch used to -- made a group that
                # had actually been cleaned up look like one that was never
                # looked at. Findings can only retire when their subject was
                # covered and no finding was emitted for it, so reporting the
                # fixed case as uncovered is precisely what made residue
                # findings unretirable.
                group_covered.append(group_key)
                # Cover every member whose definition state was determinate,
                # not just the ones that produced findings: a finding's subject
                # is the dead member's own entity_id, so a member that stops
                # being residue must remain covered or it can never retire.
                group_covered.extend(
                    entity_id
                    for entity_id in member_ids
                    if by_entity_id.get(entity_id) is not None
                    and by_entity_id[entity_id].source_definition_missing is not None
                )
                for dead in dead_candidates:
                    _LOGGER.debug(
                        "HAMIE automation_migration_residue match: group=%s "
                        "dead=%s live=%s",
                        group_key,
                        dead.entity_id,
                        live_candidates[0].entity_id,
                    )
                    finding = self._candidate(
                        group_key=group_key,
                        dead=dead,
                        live=live_candidates[0],
                        reference_index=reference_index,
                        observed_at=at,
                    )
                    group_findings.append(finding)
                    # A finding's subject.source_id is the dead member's
                    # own entity_id, which need not equal group_key when
                    # the group has 3+ members -- both must be covered
                    # (AnalyzerOutcome.__post_init__'s invariant).
                    group_covered.append(finding.subject.source_id)
            except Exception:  # noqa: BLE001 -- degrade this group only
                uncovered.append(group_key)
                continue
            findings.extend(group_findings)
            covered.extend(group_covered)

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
            uncovered_subjects=tuple(sorted(uncovered)),
        )

    def _candidate(
        self,
        *,
        group_key: str,
        dead: EntityRecord,
        live: EntityRecord,
        reference_index: EntityReferenceIndex | None,
        observed_at: datetime,
    ) -> CandidateFinding:
        reference_scan_attempted = reference_index is not None
        zero_references_confirmed = False
        referenced_by: tuple[str, ...] = ()
        if reference_index is not None:
            hits = reference_index.referenced_by(dead.entity_id)
            referenced_by = tuple(
                sorted(f"{hit.source}:{hit.referencing_object_id}" for hit in hits)
            )
            zero_references_confirmed = (
                not referenced_by and reference_index.coverage.implemented_sources_succeeded
            )
        temporal_tag = classify_automation_residue_temporal_evidence(
            zero_references_confirmed=zero_references_confirmed,
            reference_scan_attempted=reference_scan_attempted,
        )
        evidence_match = AutomationResidueEvidence(
            group_key=group_key,
            old_automation_entity_id=dead.entity_id,
            live_automation_entity_id=live.entity_id,
            temporal_tag=temporal_tag,
            zero_references_confirmed=zero_references_confirmed,
        )
        protected = is_protected_subject(
            entity_id=dead.entity_id, friendly_name=dead.friendly_name
        )
        subject = SubjectIdentity(
            durable_id=dead.registry_id or dead.entity_id,
            kind="home_assistant.entity",
            source_instance=self.source_instance,
            source_id=dead.entity_id,
            display_hint=dead.friendly_name or dead.entity_id,
            aliases=(dead.entity_id,),
        )
        related_subjects = (
            SubjectIdentity(
                durable_id=live.registry_id or live.entity_id,
                kind="home_assistant.entity",
                source_instance=self.source_instance,
                source_id=live.entity_id,
                display_hint=live.friendly_name or live.entity_id,
                aliases=(live.entity_id,),
            ),
        )
        revision = stable_digest(
            evidence_match.group_key,
            evidence_match.old_automation_entity_id,
            evidence_match.live_automation_entity_id,
            evidence_match.temporal_tag.value,
        )
        evidence = (
            EvidenceItem(
                subject=subject,
                predicate="hamie.entity.source_definition_missing@1",
                value=True,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.automation_residue.live_sibling@1",
                value=live.entity_id,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.automation_residue.temporal_tag@1",
                value=evidence_match.temporal_tag.value,
                observed_at=observed_at,
                source_id="hamie.automation_residue_policy",
                source_revision=POLICY_VERSION,
                kind=EvidenceKind.DERIVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
        )
        is_supported = temporal_tag is AutomationResidueTemporalTag.SUPPORTED
        rationale = (
            f"{dead.entity_id}'s YAML id is confirmed absent from current "
            f"source, while its suffix sibling {live.entity_id} is live and "
            "current -- a migration-leftover automation registration. "
            + (
                "A reference scan ran and confirmed zero references anywhere "
                "-- evidence supports (does not prove) that it never fires."
                if is_supported
                else "HAMIE cannot prove whether it still fires: there is no "
                "live automation_triggered event/last_triggered history reader "
                "in this codebase today (a disclosed infrastructure gap, not "
                "an oversight -- see domain/automation_residue.py), so this "
                "stays an evidence-insufficient claim rather than a false "
                "'confirmed dead.'"
            )
        )
        confidence = Confidence(
            level=ConfidenceLevel.MEDIUM if is_supported else ConfidenceLevel.LOW,
            factors=(
                ConfidenceFactor(
                    code="source_definition_confirmed_missing",
                    effect=40,
                    rationale="The old automation's YAML id is confirmed absent from source.",
                ),
                ConfidenceFactor(
                    code="temporal_evidence",
                    effect=30 if is_supported else -10,
                    rationale=(
                        "Zero references confirmed by a completed reference scan."
                        if is_supported
                        else "No automation_triggered event history reader exists "
                        "to independently confirm dormancy."
                    ),
                ),
            ),
            rule_revision="automation-migration-residue-confidence@1",
        )
        risk = Risk(
            likelihood=RiskLevel.LOW,
            impact=RiskLevel.LOW,
            reversible=True,
            affected_scope="Home Assistant entity registry (advisory only)",
            overall=RiskLevel.LOW,
            rationale="HAMIE never disables or deletes anything itself.",
        )
        dependency = DependencyAssessment(
            subject=subject,
            required_capabilities=(CAPABILITY_ID,),
            used_capabilities=(CAPABILITY_ID,),
            coverage=(
                DependencyCoverage.COMPLETE if is_supported else DependencyCoverage.UNKNOWN
            ),
            rationale=rationale,
            referenced_by=referenced_by,
            safe_to_remove=is_supported,
        )
        if is_supported:
            gate = cap_safety_gate_for_protection(
                RemediationSafetyGate.SAFE_TO_REMOVE_REGISTRY, protected=protected
            )
            kind = RecommendationKind.DELETE_CANDIDATE
            action = (
                f"Delete candidate: {dead.entity_id} -- its YAML id is gone and a "
                f"reference scan found zero references. Still advisory only: "
                "confirm by hand (recorder trigger history is not available to "
                "HAMIE), then remove the orphaned registry row."
            )
            blocked_reason = None
        else:
            gate = RemediationSafetyGate.BLOCKED_INSUFFICIENT_EVIDENCE
            kind = RecommendationKind.NEEDS_EVIDENCE
            action = (
                f"{dead.entity_id} looks like migration residue, but HAMIE "
                "cannot confirm it never fires -- no automation_triggered event "
                "history is available. Check Home Assistant's own Logbook for "
                f"{dead.entity_id} by hand before removing it."
            )
            blocked_reason = (
                "No automation_triggered event/last_triggered history reader "
                "exists in this codebase; a reference scan alone cannot prove "
                "dormancy."
            )
        recommendation = Recommendation(
            kind=kind,
            action=action,
            rationale=rationale,
            evidence=evidence,
            confidence=confidence,
            dependency_assessment=dependency,
            risk=risk,
            analyzer_id=ANALYZER_ID,
            rule_revision=RULE_VERSION,
            preconditions=(
                "Confirm the live sibling automation is genuinely the same "
                "automation re-registered, not a coincidentally similar id.",
            ),
            disqualifiers=(
                "Do not remove if Home Assistant's own Logbook shows recent "
                "trigger activity for the old automation entity.",
            ),
            safety_gate=gate,
            blocked_reason=blocked_reason,
        )
        return CandidateFinding(
            analyzer_id=ANALYZER_ID,
            rule_version=RULE_VERSION,
            condition_key=CONDITION_KEY,
            subject=subject,
            category="hygiene",
            title_key="automation_migration_residue",
            description_arguments=(
                ("entity_id", dead.entity_id),
                ("temporal_tag", evidence_match.temporal_tag.value),
            ),
            severity=FindingSeverity.INFO,
            evidence=evidence,
            recommendation=recommendation,
            related_subjects=related_subjects,
        )
