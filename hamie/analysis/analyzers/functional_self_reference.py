"""Version-bump self-reference regression analyzer (mission Part 2,
Analyzer 1) -- the highest-value new analyzer this pass adds.

Formalizes the pattern this session's manual investigation found three
times by hand (kitchen-cleaning, vacuum-status, water-goal-percentage):
a package's ``unique_id:`` is bumped to a new version string in-place.
Home Assistant registers that as a *new* entity (a changed unique_id
always does), landing the new registration on a ``_2``/``_3`` suffix
entity_id while the *old* unique_id's entity_id (the base slug) goes
dead. The same package file's own Jinja/YAML logic, never updated,
keeps referencing the now-dead base slug -- silently breaking real
functionality (a robot-vacuum dispatch gate, a security-lighting
automation, a usage-alert trigger in the three confirmed cases) because
``is_state()``/``numeric_state`` triggers on an ``unavailable`` entity
fail silently rather than raising or logging anything.

Whole-collection, same shape as ``duplicate_migration.py``: suffix
grouping is inherently a cross-entity comparison (see
``analysis/whole_collection_supervisor.py``'s module docstring for why
that requires this supervisor type, not ``AnalyzerSupervisor``'s
per-partition contract). Built on top of the exact same
``group_suffix_siblings``/``build_duplicate_group_member`` primitives
``duplicate_migration.py`` uses, but this analyzer answers a
structurally different question -- not "is this group a migration
leftover" (a registry-lifecycle question), but "does the *current live
source text* still reference the dead member" (a textual self-reference
question) -- see ``domain/duplicate_classifier.py::
detect_self_reference_regression`` for the actual detection logic this
analyzer only wraps in the finding/evidence/recommendation shape.

Deliberately a distinct finding from ``DuplicateMigrationAnalyzer``'s
own ``LIKELY_MIGRATION_LEFTOVER`` for the same group (different
analyzer_id/condition_key -- both can coexist for the same group without
colliding, see ``CandidateFinding.fingerprint``): that finding says
"this looks like cleanup hygiene"; this one says "this is an active,
currently-running functional bug," a strictly stronger and more urgent
claim that deserves its own evidence trail rather than being folded into
the weaker one.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ...application.ports import EntityRecord
from ...domain.common import require_utc, stable_digest
from ...domain.dependencies import DependencyAssessment, DependencyCoverage
from ...domain.dependency_references import EntityReferenceIndex
from ...domain.duplicate_classifier import (
    detect_self_reference_regression,
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

ANALYZER_ID = "hamie.functional_self_reference"
POLICY_VERSION = "1.0.0"
CAPABILITY_ID = "hamie.functional_self_reference_analysis@1"
RULE_VERSION = "1.0.0"
CONDITION_KEY = "functional_self_reference_regression"
EVIDENCE_PREDICATE = "hamie.duplicate_group.functional_self_reference_regression@1"

# mission Part 6: debug-level, per-group evidence only -- no prior
# logging convention exists in analysis/analyzers/*.py to match (every
# existing analyzer -- duplicate_migration.py, orphaned_definitions.py,
# unavailable_entities.py -- is deliberately I/O-free and never logs;
# only the infrastructure adapters that touch a live hass object log at
# all, e.g. infrastructure/ha_source.py). This is net-new, scoped
# strictly to DEBUG so it never appears at HAMIE's normal operating log
# level (see application/scan_coordinator.py's INFO-level scan-summary
# line for the normal-level counterpart).
_LOGGER = logging.getLogger(__name__)


class FunctionalSelfReferenceAnalyzer:
    """Detect a live source file still referencing its own dead sibling."""

    descriptor = AnalyzerDescriptor(
        analyzer_id=ANALYZER_ID,
        policy_version=POLICY_VERSION,
        capability_id=CAPABILITY_ID,
        cost_class=CostClass.MODERATE,
        allowed_recommendations=(RecommendationKind.REPAIR,),
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
        by_entity_id = {record.entity_id: record for record in records}
        entity_ids = tuple(record.entity_id for record in records)
        groups = group_suffix_siblings(entity_ids)

        findings: list[CandidateFinding] = []
        covered: list[str] = []
        uncovered: list[str] = []

        if not raw_files:
            # Nothing to textually check against -- honestly uncovered,
            # never silently "no findings" (which would read identically
            # to "checked, found nothing").
            return AnalyzerOutcome(
                analyzer_id=ANALYZER_ID,
                policy_version=POLICY_VERSION,
                partition_id=stable_digest("whole_collection", len(records))[:24],
                state=AnalyzerOutcomeState.PARTIAL,
                findings=(),
                covered_subjects=(),
                uncovered_subjects=tuple(sorted(groups.keys())),
            )

        for group_key, member_ids in groups.items():
            if group_key not in by_entity_id:
                # The base slug itself no longer has any registry row at
                # all (fully removed, not merely dead) -- nothing to
                # compare a "current" unique_id against.
                uncovered.append(group_key)
                continue
            # Built up locally and only merged into the shared
            # findings/covered lists after this group's processing
            # succeeds in full -- a partial success followed by a
            # mid-group exception must never leave group_key in both
            # covered and uncovered (AnalyzerOutcome.__post_init__
            # requires the two disjoint).
            group_findings: list[CandidateFinding] = []
            try:
                base_record = by_entity_id[group_key]
                base_member = build_duplicate_group_member(
                    base_record, reference_index=reference_index, source_index=source_index
                )
                for entity_id in member_ids:
                    if entity_id == group_key:
                        continue
                    sibling_record = by_entity_id.get(entity_id)
                    if sibling_record is None:
                        continue
                    evidence_match = detect_self_reference_regression(
                        group_key=group_key,
                        base_entity_id=base_member.entity_id,
                        base_unique_id=base_member.unique_id,
                        sibling_entity_id=sibling_record.entity_id,
                        sibling_unique_id=sibling_record.unique_id,
                        raw_files=raw_files,
                    )
                    if evidence_match is not None:
                        _LOGGER.debug(
                            "HAMIE functional_self_reference match: group=%s "
                            "base=%s(uid=%s) sibling=%s(uid=%s) file=%s",
                            group_key,
                            evidence_match.base_entity_id,
                            evidence_match.base_unique_id,
                            evidence_match.sibling_entity_id,
                            evidence_match.sibling_unique_id,
                            evidence_match.defining_file,
                        )
                        group_findings.append(
                            self._candidate(
                                evidence_match,
                                base_record=base_record,
                                sibling_record=sibling_record,
                                observed_at=at,
                            )
                        )
            except Exception:  # noqa: BLE001 -- one malformed group never
                # aborts the whole scan (mission Part 6 degradation
                # requirement) -- see the analogous per-entity try/except
                # pattern in infrastructure/ha_source.py::_records.
                uncovered.append(group_key)
                continue
            findings.extend(group_findings)
            covered.append(group_key)

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
        evidence_match,
        *,
        base_record: EntityRecord,
        sibling_record: EntityRecord,
        observed_at: datetime,
    ) -> CandidateFinding:
        protected = is_protected_subject(
            entity_id=base_record.entity_id,
            domain=base_record.domain,
            device_class=base_record.device_class,
            friendly_name=base_record.friendly_name,
            unique_id=base_record.unique_id,
            source_file=evidence_match.defining_file,
        )
        subject = SubjectIdentity(
            durable_id=evidence_match.group_key,
            kind="hamie.duplicate_group",
            source_instance=self.source_instance,
            source_id=evidence_match.group_key,
            display_hint=(
                f"Functional self-reference regression: {evidence_match.group_key}"
            ),
            aliases=(evidence_match.base_entity_id, evidence_match.sibling_entity_id),
        )
        related_subjects = tuple(
            SubjectIdentity(
                durable_id=record.registry_id or record.entity_id,
                kind="home_assistant.entity",
                source_instance=self.source_instance,
                source_id=record.entity_id,
                display_hint=record.friendly_name or record.entity_id,
                aliases=(record.entity_id,),
            )
            for record in (base_record, sibling_record)
        )
        revision = stable_digest(
            evidence_match.group_key,
            evidence_match.base_unique_id,
            evidence_match.sibling_unique_id,
            evidence_match.defining_file,
            evidence_match.matched_snippet,
        )
        evidence = (
            EvidenceItem(
                subject=subject,
                predicate=EVIDENCE_PREDICATE,
                value=True,
                observed_at=observed_at,
                source_id="hamie.functional_self_reference_policy",
                source_revision=POLICY_VERSION,
                kind=EvidenceKind.DERIVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.self_reference.defining_file@1",
                value=evidence_match.defining_file,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.self_reference.matched_snippet@1",
                value=evidence_match.matched_snippet,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.REDACT,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.self_reference.base_unique_id@1",
                value=evidence_match.base_unique_id,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.self_reference.sibling_unique_id@1",
                value=evidence_match.sibling_unique_id,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.self_reference.protected_subject@1",
                value=protected,
                observed_at=observed_at,
                source_id="hamie.protection_policy",
                source_revision=POLICY_VERSION,
                kind=EvidenceKind.DERIVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
        )
        rationale = (
            f"{evidence_match.defining_file} currently defines "
            f"{evidence_match.sibling_entity_id} (unique_id "
            f"{evidence_match.sibling_unique_id!r}, a newer version than "
            f"{evidence_match.base_unique_id!r}) but its own text still "
            f"references {evidence_match.base_entity_id} -- the old, now-"
            "dead entity_id. A trigger/condition/template on the dead "
            "entity fails silently (unavailable entities never raise), so "
            "this is an active functional bug, not just registry clutter."
        )
        confidence = Confidence(
            level=ConfidenceLevel.HIGH,
            factors=(
                ConfidenceFactor(
                    code="version_token_ordering",
                    effect=40,
                    rationale=(
                        f"{evidence_match.sibling_unique_id!r}'s version token "
                        f"is numerically newer than {evidence_match.base_unique_id!r}'s."
                    ),
                ),
                ConfidenceFactor(
                    code="textual_self_reference_confirmed",
                    effect=50,
                    rationale=(
                        f"{evidence_match.defining_file} literally contains "
                        f"{evidence_match.base_entity_id!r} alongside the "
                        "sibling's own unique_id, with no separate definition "
                        "of the base's unique_id in the same file."
                    ),
                ),
            ),
            rule_revision="functional-self-reference-confidence@1",
        )
        risk = Risk(
            likelihood=RiskLevel.HIGH,
            impact=RiskLevel.CRITICAL if protected else RiskLevel.HIGH,
            reversible=True,
            affected_scope=(
                f"Home Assistant package source file {evidence_match.defining_file} "
                "(advisory only -- HAMIE never edits configuration itself)"
            ),
            overall=RiskLevel.CRITICAL if protected else RiskLevel.HIGH,
            rationale=(
                "A live automation/template is currently evaluating against a "
                "dead entity_id with no error surfaced -- left unfixed, this "
                "keeps silently failing every time it runs."
                + (
                    " This subject matches a safety/security-relevant domain "
                    "or naming pattern -- treat with elevated priority."
                    if protected
                    else ""
                )
            ),
        )
        dependency = DependencyAssessment(
            subject=subject,
            required_capabilities=(CAPABILITY_ID,),
            used_capabilities=(CAPABILITY_ID,),
            coverage=DependencyCoverage.PARTIAL,
            rationale=rationale,
            supporting_subject_ids=(
                evidence_match.base_entity_id,
                evidence_match.sibling_entity_id,
            ),
            safe_to_remove=False,
        )
        action = (
            f"Repair {evidence_match.defining_file}: it still references "
            f"{evidence_match.base_entity_id}, which is dead after "
            f"{evidence_match.sibling_entity_id} took over its unique_id's "
            "role in a version bump. Update the reference to point at "
            f"{evidence_match.sibling_entity_id} (or the file's own current "
            "logic), then confirm the dependent trigger/condition fires "
            "again. Advisory only -- HAMIE never edits this file itself."
        )
        recommendation = Recommendation(
            kind=RecommendationKind.REPAIR,
            action=action,
            rationale=rationale,
            evidence=evidence,
            confidence=confidence,
            dependency_assessment=dependency,
            risk=risk,
            analyzer_id=ANALYZER_ID,
            rule_revision=RULE_VERSION,
            preconditions=(
                "Confirm the sibling entity is genuinely the version-bumped "
                "replacement, not a coincidentally similar unique_id.",
            ),
            disqualifiers=(
                "Do not edit the file if the base entity_id reference is "
                "intentional (e.g. a deliberate historical/legacy read).",
            ),
            safety_gate=cap_safety_gate_for_protection(
                RemediationSafetyGate.FUNCTIONAL_BUG, protected=protected
            ),
        )
        return CandidateFinding(
            analyzer_id=ANALYZER_ID,
            rule_version=RULE_VERSION,
            condition_key=CONDITION_KEY,
            subject=subject,
            category="functional_bug",
            title_key="functional_self_reference_regression",
            description_arguments=(
                ("group_key", evidence_match.group_key),
                ("defining_file", evidence_match.defining_file),
            ),
            # FindingSeverity has no CRITICAL tier (see report: adding one
            # risked silently under-counting in runtime_projection.py's/
            # domain/intelligence.py's existing exhaustive severity
            # checks) -- ERROR is the highest existing tier, and the
            # additional "critical" escalation this mission asks for is
            # carried honestly via RemediationSafetyGate.PROTECTED and
            # Risk.overall=CRITICAL above instead.
            severity=FindingSeverity.ERROR,
            evidence=evidence,
            recommendation=recommendation,
            related_subjects=related_subjects,
        )
