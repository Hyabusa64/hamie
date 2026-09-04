"""Abandoned bugfix/experiment fork analyzer (mission Part 2, Analyzer 5).

Formalizes the ``water_bill_estimate_2``/``water_cost_today_2``/
``water_flow_gpm_2`` pattern found and manually confirmed safe this
session: a ``_N`` suffix sibling whose own unique_id carries a
distinguishing one-off marker (``_fixed``, ``_v2``, ``_temp``, ...) AND
has zero live source definition anywhere AND zero references anywhere.
Wraps ``domain/duplicate_classifier.py::detect_abandoned_bugfix_fork``
in the standard finding/evidence/recommendation shape -- see that
function's own docstring for the exact required-evidence combination
this analyzer never loosens (mission Part 6: must never trigger on the
suffix pattern alone).

Whole-collection, same reasoning as ``duplicate_migration.py``/
``functional_self_reference.py``: suffix grouping is a cross-entity
comparison.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ...application.ports import EntityRecord
from ...domain.common import require_utc, stable_digest
from ...domain.dependencies import DependencyAssessment, DependencyCoverage
from ...domain.dependency_references import EntityReferenceIndex
from ...domain.duplicate_classifier import (
    detect_abandoned_bugfix_fork,
    group_suffix_siblings,
)
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
from ..duplicate_group_scan import build_duplicate_group_member

ANALYZER_ID = "hamie.abandoned_bugfix_fork"
POLICY_VERSION = "1.0.0"
CAPABILITY_ID = "hamie.abandoned_bugfix_fork_analysis@1"
RULE_VERSION = "1.0.0"
CONDITION_KEY = "abandoned_bugfix_fork"
# mission Part 6: DEBUG-only, per-group evidence -- see
# functional_self_reference.py's identical note on why no prior
# analyzer-module logging convention exists to match.
_LOGGER = logging.getLogger(__name__)


def _has_zero_source_definition(
    record: EntityRecord, raw_files: dict[str, str], *, source_evaluated: bool
) -> bool:
    """Best-effort "no live source definition anywhere" signal.

    ``EntityRecord.source_definition_missing`` (the structured, id-
    indexed answer) only ever gets a real value for automation/script/
    scene entities (see ``infrastructure/source_definition_index.py``'s
    module docstring) -- the confirmed real cases this analyzer targets
    (water_bill_estimate_2 et al.) are ordinary sensor/template
    entities defined inside a package by an arbitrary unique_id field,
    which that structured index does not cover at all. Falling back to
    a plain substring search of the same already-read raw package text
    (mirroring ``functional_self_reference.py``'s own approach) is the
    honest, minimal generalization: if the record's own unique_id
    string appears nowhere in any scanned config file's raw text, no
    live definition currently claims it.
    """
    if record.source_definition_missing is True:
        return True
    if record.source_definition_missing is False:
        return False
    if not record.unique_id or not source_evaluated:
        # No structured answer and no raw text was even scanned this
        # capture (source_index itself was None) -- honestly "not
        # evaluated", never a fabricated "confirmed zero". Distinct
        # from a real, empty raw_files map (source_index present, zero
        # config files considered) below, which is a genuine "found in
        # zero files" answer.
        return False
    return not any(record.unique_id in content for content in raw_files.values())


class AbandonedBugfixForkAnalyzer:
    """Detect a `_N` suffix sibling that is an abandoned one-off fix/test fork."""

    descriptor = AnalyzerDescriptor(
        analyzer_id=ANALYZER_ID,
        policy_version=POLICY_VERSION,
        capability_id=CAPABILITY_ID,
        cost_class=CostClass.MODERATE,
        allowed_recommendations=(
            RecommendationKind.DISABLE_CANDIDATE,
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
        raw_files = getattr(source_index, "raw_files", None) or {}
        source_evaluated = source_index is not None
        by_entity_id = {record.entity_id: record for record in records}
        entity_ids = tuple(record.entity_id for record in records)
        groups = group_suffix_siblings(entity_ids)

        findings: list[CandidateFinding] = []
        covered: list[str] = []
        uncovered: list[str] = []

        for group_key, member_ids in groups.items():
            # Local buffers, merged only after the whole group succeeds
            # -- see functional_self_reference.py's identical comment
            # for why a partial success followed by a mid-group
            # exception must never leave group_key in both covered and
            # uncovered.
            group_findings: list[CandidateFinding] = []
            group_covered: list[str] = []
            try:
                for entity_id in member_ids:
                    if entity_id == group_key:
                        continue
                    record = by_entity_id.get(entity_id)
                    if record is None:
                        continue
                    # Covered as soon as this member is genuinely evaluated,
                    # not only when it produces a finding. Previously a member
                    # entered covered_subjects exclusively alongside its own
                    # finding, so "examined and clean" was indistinguishable
                    # from "never examined" -- and since a finding's subject is
                    # the member entity_id, a fork that was actually cleaned up
                    # could never be retired: its subject stopped being covered
                    # the moment it stopped being a defect.
                    group_covered.append(entity_id)
                    member = build_duplicate_group_member(
                        record, reference_index=reference_index, source_index=source_index
                    )
                    evidence_match = detect_abandoned_bugfix_fork(
                        group_key=group_key,
                        member=member,
                        has_zero_source_definition=_has_zero_source_definition(
                            record, raw_files, source_evaluated=source_evaluated
                        ),
                    )
                    if evidence_match is not None:
                        _LOGGER.debug(
                            "HAMIE abandoned_bugfix_fork match: group=%s "
                            "entity=%s marker=%s",
                            group_key,
                            evidence_match.fork_entity_id,
                            evidence_match.matched_marker,
                        )
                        finding = self._candidate(evidence_match, record, observed_at=at)
                        group_findings.append(finding)
                        # Kept: a finding's subject need not equal entity_id,
                        # and AnalyzerOutcome requires every finding subject to
                        # be covered.
                        group_covered.append(finding.subject.source_id)
                group_covered.append(group_key)
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
        self, evidence_match, record: EntityRecord, *, observed_at: datetime
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
        revision = stable_digest(
            evidence_match.group_key,
            evidence_match.fork_entity_id,
            evidence_match.fork_unique_id,
            evidence_match.matched_marker,
        )
        evidence = (
            EvidenceItem(
                subject=subject,
                predicate="hamie.entity.abandoned_bugfix_fork_marker@1",
                value=evidence_match.matched_marker,
                observed_at=observed_at,
                source_id="hamie.abandoned_bugfix_fork_policy",
                source_revision=POLICY_VERSION,
                kind=EvidenceKind.DERIVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.entity.unique_id@1",
                value=evidence_match.fork_unique_id,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.entity.zero_source_definition@1",
                value=True,
                observed_at=observed_at,
                source_id="hamie.abandoned_bugfix_fork_policy",
                source_revision=POLICY_VERSION,
                kind=EvidenceKind.DERIVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.entity.zero_references@1",
                value=True,
                observed_at=observed_at,
                source_id="hamie.abandoned_bugfix_fork_policy",
                source_revision=POLICY_VERSION,
                kind=EvidenceKind.DERIVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
        )
        rationale = (
            f"{evidence_match.fork_entity_id}'s unique_id "
            f"({evidence_match.fork_unique_id!r}) contains the marker "
            f"{evidence_match.matched_marker!r}, has no live source "
            "definition anywhere in the scanned configuration, and has "
            "zero references among every source HAMIE scanned -- a "
            "one-off fix/experiment fork that was never cleaned up, not "
            "a genuinely distinct entity."
        )
        confidence = Confidence(
            level=ConfidenceLevel.MEDIUM,
            factors=(
                ConfidenceFactor(
                    code="marker_match",
                    effect=30,
                    rationale=f"unique_id contains the marker {evidence_match.matched_marker!r}.",
                ),
                ConfidenceFactor(
                    code="zero_source_and_zero_references",
                    effect=50,
                    rationale=(
                        "Both zero live source definition and zero references "
                        "were confirmed -- never triggered on the marker or "
                        "suffix alone."
                    ),
                ),
            ),
            rule_revision="abandoned-bugfix-fork-confidence@1",
        )
        risk = Risk(
            likelihood=RiskLevel.LOW,
            impact=RiskLevel.LOW,
            reversible=True,
            affected_scope="Home Assistant entity registry (advisory only)",
            overall=RiskLevel.LOW,
            rationale=(
                "HAMIE never disables or deletes anything itself -- this is a "
                "suggestion only."
            ),
        )
        dependency = DependencyAssessment(
            subject=subject,
            required_capabilities=(CAPABILITY_ID,),
            used_capabilities=(CAPABILITY_ID,),
            coverage=DependencyCoverage.PARTIAL,
            rationale=rationale,
            safe_to_remove=False,
        )
        gate = cap_safety_gate_for_protection(
            RemediationSafetyGate.SAFE_TO_FIX_SOURCE, protected=protected
        )
        recommendation = Recommendation(
            kind=RecommendationKind.DISABLE_CANDIDATE,
            action=(
                f"Disable candidate: {evidence_match.fork_entity_id} looks like "
                "an abandoned one-off fix/experiment fork -- confirm by hand, "
                "then remove it via Settings -> Devices & Services -> Entities."
            ),
            rationale=rationale,
            evidence=evidence,
            confidence=confidence,
            dependency_assessment=dependency,
            risk=risk,
            analyzer_id=ANALYZER_ID,
            rule_revision=RULE_VERSION,
            preconditions=(
                "Confirm the marker in the unique_id is genuinely a leftover "
                "fix/test artifact, not a meaningful ongoing name.",
            ),
            disqualifiers=(
                "Do not remove if any reference source HAMIE could not scan "
                "this cycle.",
            ),
            safety_gate=gate,
        )
        return CandidateFinding(
            analyzer_id=ANALYZER_ID,
            rule_version=RULE_VERSION,
            condition_key=CONDITION_KEY,
            subject=subject,
            category="hygiene",
            title_key="abandoned_bugfix_fork",
            description_arguments=(
                ("entity_id", evidence_match.fork_entity_id),
                ("marker", evidence_match.matched_marker),
            ),
            severity=FindingSeverity.INFO,
            evidence=evidence,
            recommendation=recommendation,
        )
