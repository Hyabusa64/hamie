"""Duplicate/migration-leftover group analyzer (mission Part 1a).

Wraps ``analysis/duplicate_group_scan.py``'s whole-installation
``scan_duplicate_groups`` -- itself a thin, already-tested
orchestration of ``domain/duplicate_classifier.py``'s pure
classification rules -- in the same evidence/finding/recommendation
shape every other analyzer in this package produces
(``CandidateFinding``/``Recommendation``/``EvidenceItem``,
``domain/findings.py``), so its results flow through the identical
reconciliation, storage, and presentation pipeline as
``UnavailableEntityAnalyzer``/``OrphanedDefinitionAnalyzer`` findings --
without distorting ``duplicate_group_scan.py``'s deliberate, documented
whole-collection design to fit the ``AnalysisPartition``/
``AnalyzerDescriptor`` per-partition contract those two analyzers use
(see ``duplicate_group_scan.py``'s own module docstring: "Deliberately
**not** built on the ``AnalysisPartition``/``AnalyzerDescriptor``
contract").

**Why not force it into the partition contract.** That contract's
whole point is safe, cache-friendly *partitioning*: each partition is
analyzed independently, and nothing in ``analysis/supervisor.py``'s
``AnalyzerSupervisor._partitions`` guarantees two suffix siblings
(``light.island_lamp``/``light.island_lamp_2``) ever land in the same
batch -- batches are sliced from the sorted entity list at a
profile-dependent fixed size, completely independent of any analyzer's
own preferences (``AnalyzerDescriptor.max_partition_size`` is declared
but never actually consulted by ``AnalyzerSupervisor._partitions``,
which only ever uses the *profile's* ``batch_size``). Forcing suffix
grouping through that contract would silently produce wrong answers
whenever a sibling pair straddles a batch boundary (each half looks
like an ungrouped, solitary entity) rather than an honestly incomplete
one. So this analyzer does **not** implement
``analyze(partition, *, observed_at) -> AnalyzerOutcome`` at all. It
implements a parallel, smaller contract instead --
``analyze_collection(records, *, observed_at, reference_index=None,
source_index=None) -> AnalyzerOutcome`` -- run once over an entire
capture's records by
``analysis/whole_collection_supervisor.WholeCollectionSupervisor``, the
small, honest extension point added alongside ``AnalyzerSupervisor``
for exactly this shape of analyzer (see that module's docstring for
the full reasoning). The returned ``AnalyzerOutcome``/
``CandidateFinding``/``Recommendation`` objects are otherwise built
with the exact same domain types as every other analyzer, so
reconciliation (``application/reconciliation.py``), storage, and every
presentation consumer need zero special-casing for "this analyzer is
whole-collection" -- that distinction only exists at the scheduling
layer.

**Finding subject.** Each finding's ``SubjectIdentity`` represents the
*group*, not any one member entity: ``kind="hamie.duplicate_group"``,
``durable_id``/``source_id`` = the group's key (the suffix-stripped
base entity_id ``group_suffix_siblings`` computed, which is sometimes a
real entity_id and sometimes synthetic -- see that function's
docstring), and every member entity_id is attached both as a
``SubjectIdentity`` alias and as a full ``related_subjects`` entry (real
``home_assistant.entity`` subjects, so presentation consumers can link
straight to each member without re-deriving anything).

**Recommendation-strength discipline (mission Part 1.1).** This
analyzer never emits ``DELETE_CANDIDATE`` or ``DISABLE`` for any
classification, even ``LIKELY_MIGRATION_LEFTOVER``: unlike
``orphaned_definitions.py``, ``duplicate_group_scan.py``'s classifier
has no equivalent "a reference scan actually ran, found zero
references, and every source succeeded" strong-evidence gate collapsed
into one boolean the way ``DependencyAssessment.safe_to_remove``
demands -- a duplicate-group classification is a *relationship*
between 2+ members, not one subject's confirmed-safe-to-remove claim.
So this analyzer stays deliberately one notch more conservative than
the classification names alone might suggest:

- ``LIKELY_MIGRATION_LEFTOVER`` -> ``INVESTIGATE`` (a human should look
  at retiring the dead sibling(s); never an automatic disable/delete
  suggestion).
- ``ACTIVE_OLD_ID_WITH_NEW_SIBLING`` -> ``INVESTIGATE`` (worth a human
  look; explicitly not urgent -- the old id is still working).
- ``BROKEN_REFERENCE_TO_OLD_SIBLING`` -> ``REPAIR`` (an operational
  Issue: a live automation/dashboard/script is pointing at a disabled/
  unavailable entity right now -- the one classification that
  represents an active defect, not just cleanup hygiene; severity
  ``ERROR``, not ``WARNING``).
- ``AMBIGUOUS_DUPLICATE_GROUP`` -> ``REVIEW_DUPLICATE`` (exactly the
  vocabulary this ``RecommendationKind`` member was added for).
- ``LIKELY_DISTINCT_ENTITIES`` -> ``NO_ACTION``, severity ``INFO``
  (actively evaluated and cleared -- recorded for auditability, never
  surfaced as a problem).
"""

from __future__ import annotations

import re as _re

from collections.abc import Callable
from datetime import datetime

from ...application.ports import EntityRecord
from ...domain.common import require_utc, stable_digest
from ...domain.dependencies import DependencyAssessment, DependencyCoverage
from ...domain.dependency_references import EntityReferenceIndex
from ...domain.duplicate_classifier import (
    DuplicateGroupClassification,
    DuplicateGroupDecision,
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
    Risk,
    RiskLevel,
)
from ...domain.identity import SubjectIdentity
from ...domain.implementation_groups import ImplementationGroup
from ...domain.knowledge_consultation import consult_implementation_group
from ...infrastructure.source_definition_index import SourceDefinitionIndex
from ..contracts import AnalyzerDescriptor, AnalyzerOutcome, AnalyzerOutcomeState, CostClass
from ..duplicate_group_scan import scan_duplicate_groups

ANALYZER_ID = "hamie.duplicate_migration"
POLICY_VERSION = "1.0.0"
# Distinct from every AnalysisPartition capability id -- this analyzer
# is never partitioned by AnalyzerSupervisor, so this id only serves as
# a stable, versioned label for this analyzer's own evidence/rationale
# text and future compatibility checks; it deliberately does not appear
# on any AnalysisPartition.
CAPABILITY_ID = "hamie.duplicate_group_analysis@1"
RULE_VERSION = "1.0.0"

_RECOMMENDATION_KIND: dict[DuplicateGroupClassification, RecommendationKind] = {
    DuplicateGroupClassification.LIKELY_MIGRATION_LEFTOVER: RecommendationKind.INVESTIGATE,
    DuplicateGroupClassification.ACTIVE_OLD_ID_WITH_NEW_SIBLING: RecommendationKind.INVESTIGATE,
    DuplicateGroupClassification.BROKEN_REFERENCE_TO_OLD_SIBLING: RecommendationKind.REPAIR,
    DuplicateGroupClassification.AMBIGUOUS_DUPLICATE_GROUP: RecommendationKind.REVIEW_DUPLICATE,
    DuplicateGroupClassification.LIKELY_DISTINCT_ENTITIES: RecommendationKind.NO_ACTION,
}
_SEVERITY: dict[DuplicateGroupClassification, FindingSeverity] = {
    DuplicateGroupClassification.LIKELY_MIGRATION_LEFTOVER: FindingSeverity.WARNING,
    DuplicateGroupClassification.ACTIVE_OLD_ID_WITH_NEW_SIBLING: FindingSeverity.INFO,
    DuplicateGroupClassification.BROKEN_REFERENCE_TO_OLD_SIBLING: FindingSeverity.ERROR,
    DuplicateGroupClassification.AMBIGUOUS_DUPLICATE_GROUP: FindingSeverity.WARNING,
    DuplicateGroupClassification.LIKELY_DISTINCT_ENTITIES: FindingSeverity.INFO,
}
_RISK_OVERALL: dict[DuplicateGroupClassification, RiskLevel] = {
    DuplicateGroupClassification.LIKELY_MIGRATION_LEFTOVER: RiskLevel.LOW,
    DuplicateGroupClassification.ACTIVE_OLD_ID_WITH_NEW_SIBLING: RiskLevel.LOW,
    DuplicateGroupClassification.BROKEN_REFERENCE_TO_OLD_SIBLING: RiskLevel.MEDIUM,
    DuplicateGroupClassification.AMBIGUOUS_DUPLICATE_GROUP: RiskLevel.LOW,
    DuplicateGroupClassification.LIKELY_DISTINCT_ENTITIES: RiskLevel.LOW,
}


def _duplicate_base(entity_id: str) -> str:
    """Suffix-stripped base of a Home Assistant duplicate id, or the id itself.

    Mirrors ``group_suffix_siblings``: only a single trailing _2.._9 is a
    duplicate suffix. Anything looser would claim relevance over unrelated
    entities.
    """
    domain, _, obj = entity_id.partition(".")
    if not obj:
        return entity_id
    match = _re.match(r"^(.*)_([2-9])$", obj)
    return f"{domain}.{match.group(1)}" if match else entity_id


class DuplicateMigrationAnalyzer:
    """Whole-collection suffix-duplicate / migration-leftover analyzer."""

    descriptor = AnalyzerDescriptor(
        analyzer_id=ANALYZER_ID,
        policy_version=POLICY_VERSION,
        capability_id=CAPABILITY_ID,
        cost_class=CostClass.MODERATE,
        allowed_recommendations=(
            RecommendationKind.NO_ACTION,
            RecommendationKind.INVESTIGATE,
            RecommendationKind.REPAIR,
            RecommendationKind.REVIEW_DUPLICATE,
        ),
        # Not consulted for partitioning (this analyzer is never
        # partitioned -- see module docstring); kept generously large
        # only so AnalyzerDescriptor's own "must be positive" validation
        # never becomes a false ceiling for a whole-collection analyzer.
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
        source_index: SourceDefinitionIndex | None = None,
        installation_topology: object | None = None,
        known_implementation_groups: tuple[ImplementationGroup, ...] = (),
        skipped_subjects: frozenset[str] = frozenset(),
    ) -> AnalyzerOutcome:
        """Analyze the entire captured entity collection at once.

        ``installation_topology`` (mission Part 2) is accepted for
        interface parity with ``WholeCollectionSupervisor``'s uniform
        call shape (every whole-collection analyzer now receives it) but
        unused here -- this analyzer's classification never needed
        installation-topology facts and stays exactly as before.

        ``known_implementation_groups`` (mission Part 11/48) is
        additive and optional -- every existing caller that does not
        pass it gets byte-identical behavior to before. When a group's
        exact member set matches a known, currently-active
        ``ImplementationGroup`` (``domain/knowledge_consultation.py``),
        the finding gains one extra evidence item citing it and its
        action text mentions the recorded unresolved decision, instead
        of presenting an already-investigated parallel/versioned
        implementation as though it were being seen for the first
        time. ``kind``/``severity``/``risk``/``confidence`` are never
        changed by a match -- this is annotation only, never a
        classification override; live registry evidence still drives
        the classification itself (mission Part 52).

        Never partial for a structural reason: ``scan_duplicate_groups``
        either finds and classifies a suffix group, or the group does
        not exist at all -- there is no notion of "some groups
        uncovered" the way an entity-level analyzer can have unscanned
        subjects. Every group ``group_suffix_siblings`` finds gets
        exactly one ``DuplicateGroupDecision`` and exactly one finding
        here (including the informational, no-problem
        ``LIKELY_DISTINCT_ENTITIES`` case), so this analyzer's coverage
        universe -- see ``requested_subjects`` on the
        ``WholeCollectionSupervisor``-built ``CoverageAssessment`` -- is
        deliberately just "the duplicate groups found," not "every
        entity in the house" (that broader universe is
        ``UnavailableEntityAnalyzer``/``OrphanedDefinitionAnalyzer``'s
        job, not this one's).
        """
        at = require_utc(observed_at, "observed_at")
        scan = scan_duplicate_groups(
            records, reference_index=reference_index, source_index=source_index
        )
        by_entity_id = {record.entity_id: record for record in records}
        # A finding means "something worth reporting". LIKELY_DISTINCT_ENTITIES
        # is the classifier explicitly saying the opposite -- "a name collision
        # between genuinely separate entities, not a duplicate to clean up" --
        # so emitting a finding for it made a HEALTHY group indistinguishable
        # from a defective one at the lifecycle layer.
        #
        # That indistinguishability was the whole bug. This analyzer's
        # condition_key is the constant "duplicate_group_classification", so
        # every classification of a group shares ONE finding id; and because a
        # finding was emitted for every covered group, covered_subjects was
        # exactly the set of emitted finding subjects. Reconciliation retires a
        # finding only when its subject was covered AND no finding was emitted
        # for it, and that state was unreachable here by construction: live,
        # zero duplicate_migration findings had ever reached `resolved` while
        # 147 unavailable-entity findings had.
        #
        # Covering the group while emitting nothing for it is the fresh,
        # deterministic evidence that the defect is gone: the analyzer ran, it
        # examined this exact group, and it found no duplicate worth reporting.
        findings = tuple(
            self._candidate(
                decision,
                by_entity_id,
                observed_at=at,
                known_implementation_groups=known_implementation_groups,
            )
            for decision in scan.decisions
            if decision.classification
            is not DuplicateGroupClassification.LIKELY_DISTINCT_ENTITIES
        )
        # Every group the scan classified is covered, including the benign ones
        # that deliberately emit no finding.
        covered = tuple(sorted({decision.group_key for decision in scan.decisions}))
        # Skipped material that could belong to one of THIS analyzer's groups
        # is reported as indeterminate. Relevance is deliberately narrow: a
        # thermostat that failed to normalize says nothing about whether two
        # unrelated registry entities still form a migration pair, and marking
        # every analyzer partial because some unrelated entity was unreadable
        # would make coverage meaningless.
        indeterminate = tuple(
            sorted(
                entity_id
                for entity_id in skipped_subjects
                if entity_id not in covered
                and (
                    _duplicate_base(entity_id) in set(covered)
                    or entity_id in set(covered)
                )
            )
        )
        return AnalyzerOutcome(
            analyzer_id=ANALYZER_ID,
            policy_version=POLICY_VERSION,
            partition_id=stable_digest("whole_collection", len(records))[:24],
            state=AnalyzerOutcomeState.COMPLETE,
            findings=findings,
            covered_subjects=covered,
            indeterminate_subjects=indeterminate,
        )

    @staticmethod
    def _member_subject(
        entity_id: str, record: EntityRecord | None, *, source_instance: str
    ) -> SubjectIdentity:
        return SubjectIdentity(
            durable_id=(record.registry_id if record is not None else None)
            or entity_id,
            kind="home_assistant.entity",
            source_instance=source_instance,
            source_id=entity_id,
            display_hint=(record.friendly_name if record is not None else None)
            or entity_id,
            aliases=(entity_id,),
        )

    def _candidate(
        self,
        decision: DuplicateGroupDecision,
        by_entity_id: dict[str, EntityRecord],
        *,
        observed_at: datetime,
        known_implementation_groups: tuple[ImplementationGroup, ...] = (),
    ) -> CandidateFinding:
        group_subject = SubjectIdentity(
            durable_id=decision.group_key,
            kind="hamie.duplicate_group",
            source_instance=self.source_instance,
            source_id=decision.group_key,
            display_hint=f"Duplicate group: {decision.group_key}",
            aliases=decision.member_entity_ids,
        )
        related_subjects = tuple(
            self._member_subject(
                entity_id,
                by_entity_id.get(entity_id),
                source_instance=self.source_instance,
            )
            for entity_id in decision.member_entity_ids
        )
        group_revision = stable_digest(
            decision.group_key,
            decision.classification.value,
            decision.member_entity_ids,
            decision.primary_entity_id,
        )
        evidence = (
            EvidenceItem(
                subject=group_subject,
                predicate="hamie.duplicate_group.classification@1",
                value=decision.classification.value,
                observed_at=observed_at,
                source_id="hamie.duplicate_migration_policy",
                source_revision=POLICY_VERSION,
                kind=EvidenceKind.DERIVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=group_subject,
                predicate="hamie.duplicate_group.members@1",
                value=",".join(decision.member_entity_ids),
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=group_revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=group_subject,
                predicate="hamie.duplicate_group.rationale@1",
                value=decision.rationale,
                observed_at=observed_at,
                source_id="hamie.duplicate_migration_policy",
                source_revision=POLICY_VERSION,
                kind=EvidenceKind.DERIVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=group_subject,
                predicate="hamie.duplicate_group.primary_entity_id@1",
                value=decision.primary_entity_id,
                observed_at=observed_at,
                source_id="hamie.duplicate_migration_policy",
                source_revision=POLICY_VERSION,
                kind=EvidenceKind.DERIVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
        )
        known_group = consult_implementation_group(
            decision.member_entity_ids, known_implementation_groups
        )
        if known_group is not None:
            evidence = (
                *evidence,
                EvidenceItem(
                    subject=group_subject,
                    predicate="hamie.knowledge.known_implementation_group@1",
                    value=known_group.group_record_id,
                    observed_at=observed_at,
                    source_id="hamie.knowledge_store",
                    source_revision=known_group.fingerprint,
                    kind=EvidenceKind.ASSERTED,
                    sensitivity=Sensitivity.PUBLIC,
                ),
            )
        recommendation_kind = _RECOMMENDATION_KIND[decision.classification]
        severity = _SEVERITY[decision.classification]
        dependency = DependencyAssessment(
            subject=group_subject,
            required_capabilities=(CAPABILITY_ID,),
            used_capabilities=(CAPABILITY_ID,),
            # Never COMPLETE/safe_to_remove from this analyzer -- see
            # module docstring's recommendation-strength discipline.
            # This never asserts a group member is safe to remove;
            # DependencyAssessment.safe_to_remove stays False for
            # every classification this analyzer produces.
            coverage=DependencyCoverage.PARTIAL,
            rationale=decision.rationale,
            supporting_subject_ids=decision.member_entity_ids,
            safe_to_remove=False,
        )
        confidence = Confidence(
            level=(
                ConfidenceLevel.HIGH
                if decision.classification
                is not DuplicateGroupClassification.AMBIGUOUS_DUPLICATE_GROUP
                else ConfidenceLevel.LOW
            ),
            factors=(
                ConfidenceFactor(
                    code="duplicate_group_classification_rule",
                    effect=(
                        70
                        if decision.classification
                        is not DuplicateGroupClassification.AMBIGUOUS_DUPLICATE_GROUP
                        else 10
                    ),
                    rationale=decision.rationale,
                ),
            ),
            rule_revision="duplicate-migration-confidence@1",
        )
        risk = Risk(
            likelihood=RiskLevel.LOW,
            impact=_RISK_OVERALL[decision.classification],
            reversible=True,
            affected_scope="Home Assistant entity registry (advisory only, no changes)",
            overall=_RISK_OVERALL[decision.classification],
            rationale=(
                "HAMIE never disables, deletes, or repairs anything itself -- "
                "this is a suggestion only; any action remains a manual step "
                "for a human, gated by their own decision."
            ),
        )
        action = _ACTION_TEXT[decision.classification](decision)
        if known_group is not None and known_group.unresolved_decision is not None:
            action = (
                f"{action} This exact group already matches a known, "
                f"previously investigated implementation group "
                f"({known_group.group_id}); automatic cleanup is not "
                f"authorized for it. Open question: "
                f"{known_group.unresolved_decision.question}"
            )
        recommendation = Recommendation(
            kind=recommendation_kind,
            action=action,
            rationale=decision.rationale,
            evidence=evidence,
            confidence=confidence,
            dependency_assessment=dependency,
            risk=risk,
            analyzer_id=ANALYZER_ID,
            rule_revision=RULE_VERSION,
            preconditions=(
                "Confirm the group's membership and classification against "
                "the live entity registry before acting.",
            ),
            disqualifiers=(
                "Do not disable or delete any member still referenced by "
                "another automation, script, dashboard, or template.",
            ),
        )
        return CandidateFinding(
            analyzer_id=ANALYZER_ID,
            rule_version=RULE_VERSION,
            condition_key="duplicate_group_classification",
            subject=group_subject,
            category="duplicate_migration",
            title_key=f"duplicate_group_{decision.classification.value}",
            description_arguments=(
                ("group_key", decision.group_key),
                ("member_count", str(len(decision.member_entity_ids))),
            ),
            severity=severity,
            evidence=evidence,
            recommendation=recommendation,
            related_subjects=related_subjects,
        )


def _migration_leftover_action(decision: DuplicateGroupDecision) -> str:
    primary = decision.primary_entity_id or "the active member"
    others = ", ".join(
        entity_id
        for entity_id in decision.member_entity_ids
        if entity_id != decision.primary_entity_id
    )
    return (
        f"Investigate the duplicate group {decision.group_key}: {primary} looks "
        f"actively in use while {others} looks like a migration leftover. "
        "Confirm by hand, then consider disabling the leftover member(s) via "
        "Settings -> Devices & Services -> Entities."
    )


def _active_old_id_action(decision: DuplicateGroupDecision) -> str:
    return (
        f"Investigate the duplicate group {decision.group_key}: the oldest "
        f"member ({decision.primary_entity_id}) is still actively in use "
        "even though a newer sibling exists. Do not assume the older id is "
        "safe to retire without confirming what still depends on it."
    )


def _broken_reference_action(decision: DuplicateGroupDecision) -> str:
    return (
        f"Repair the duplicate group {decision.group_key}: a disabled or "
        "unavailable member still has live references pointing at it while "
        "a sibling is the one actually working -- likely a rename left a "
        "dangling reference. Update the referencing automation/script/"
        "dashboard to point at the active sibling."
    )


def _ambiguous_action(decision: DuplicateGroupDecision) -> str:
    return (
        f"Review the duplicate group {decision.group_key} by hand -- "
        "availability, reference, and device/area signals did not agree "
        "confidently on a single classification."
    )


def _distinct_entities_action(decision: DuplicateGroupDecision) -> str:
    return (
        f"No action needed for {decision.group_key}: these entities share a "
        "name collision but are backed by distinct devices, config entries, "
        "or areas -- genuinely separate entities, not a duplicate to clean up."
    )


_ACTION_TEXT: dict[
    DuplicateGroupClassification, Callable[[DuplicateGroupDecision], str]
] = {
    DuplicateGroupClassification.LIKELY_MIGRATION_LEFTOVER: _migration_leftover_action,
    DuplicateGroupClassification.ACTIVE_OLD_ID_WITH_NEW_SIBLING: _active_old_id_action,
    DuplicateGroupClassification.BROKEN_REFERENCE_TO_OLD_SIBLING: _broken_reference_action,
    DuplicateGroupClassification.AMBIGUOUS_DUPLICATE_GROUP: _ambiguous_action,
    DuplicateGroupClassification.LIKELY_DISTINCT_ENTITIES: _distinct_entities_action,
}
