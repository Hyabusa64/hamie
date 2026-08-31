"""Wrong-domain migrated action target analyzer (mission Part 2,
Analyzer 3).

Found 1x this session, a real security bug: a porch-light automation's
action still called ``light.turn_on`` against an entity_id that, after
an integration migration, is now a ``switch.*`` entity -- the old light
entity_id is a class-2 removed-integration orphan (see
``removed_integration_orphan.py``), but the *additional* bug is that
even fixing just the entity_id would still be broken, because the
service call's own verb domain (``light.turn_on``) does not match the
replacement's real domain (needs ``switch.turn_on``).

Structurally the most novel of the six new analyzers (explicitly flagged
as such in the mission): ``infrastructure/dependency_source.py``'s
existing reference scanning (``capture_automation_references`` et al.)
only ever captures *that* an automation references an entity, via HA's
own ``referenced_entities`` -- it never captures the service call's own
verb domain alongside the target, so it cannot answer this question no
matter how it is queried. This analyzer therefore does not extend
``dependency_source.py`` at all; it implements the minimal parsing the
mission explicitly permits (``domain/action_target_scanner.py``'s
regex/structural-YAML scan over already-read raw config text) rather
than a full HA service-schema validator.

Whole-collection: needs the raw config text (``source_index.raw_files``)
plus a same-object_id-different-domain sibling search across the whole
captured collection.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ...application.ports import EntityRecord
from ...domain.action_target_scanner import (
    detect_wrong_domain_action_target,
    scan_action_service_calls,
)
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

ANALYZER_ID = "hamie.wrong_domain_action_target"
POLICY_VERSION = "1.0.0"
CAPABILITY_ID = "hamie.wrong_domain_action_target_analysis@1"
RULE_VERSION = "1.0.0"
CONDITION_KEY = "wrong_domain_action_target"
# mission Part 6: DEBUG-only, per-call evidence -- see
# functional_self_reference.py's note on why no prior analyzer-module
# logging convention exists to match.
_LOGGER = logging.getLogger(__name__)

_ALIVE_STATES = frozenset({"unavailable", "unknown"})


def _is_alive(record: EntityRecord | None) -> bool:
    return (
        record is not None
        and record.disabled is not True
        and record.state not in _ALIVE_STATES
    )


def _is_orphaned(
    record: EntityRecord | None, *, installation_topology: object | None
) -> bool:
    if record is None:
        return True
    if record.state == "unavailable" or record.disabled is True:
        return True
    if (
        record.config_entry_id is None
        and record.device_id is None
        and installation_topology is not None
        and record.platform
        and getattr(
            installation_topology, "platform_has_removed_integration", lambda _p: False
        )(record.platform)
    ):
        return True
    return False


class WrongDomainActionAnalyzer:
    """Find automation/script actions whose verb domain no longer matches
    their migrated target entity's real domain."""

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

        if not raw_files:
            return AnalyzerOutcome(
                analyzer_id=ANALYZER_ID,
                policy_version=POLICY_VERSION,
                partition_id=stable_digest("whole_collection", len(records))[:24],
                state=AnalyzerOutcomeState.PARTIAL,
                findings=(),
                covered_subjects=(),
                uncovered_subjects=tuple(sorted(raw_files.keys())),
            )

        try:
            from ...infrastructure.source_definition_index import parse_config_yaml
        except Exception:  # noqa: BLE001 -- infra import failure, degrade honestly
            return AnalyzerOutcome(
                analyzer_id=ANALYZER_ID,
                policy_version=POLICY_VERSION,
                partition_id=stable_digest("whole_collection", len(records))[:24],
                state=AnalyzerOutcomeState.PARTIAL,
                findings=(),
                covered_subjects=(),
                uncovered_subjects=tuple(sorted(raw_files.keys())),
            )

        covered: list[str] = []
        uncovered: list[str] = []
        documents: dict[str, object] = {}
        for path, content in raw_files.items():
            try:
                documents[path] = parse_config_yaml(content)
                if documents[path] is None:
                    uncovered.append(path)
                else:
                    covered.append(path)
            except Exception:  # noqa: BLE001 -- one bad file never aborts the rest
                documents[path] = None
                uncovered.append(path)

        findings: list[CandidateFinding] = []
        for call in scan_action_service_calls(documents):
            try:
                target_record = by_entity_id.get(call.target_entity_id)
                orphaned = _is_orphaned(
                    target_record, installation_topology=installation_topology
                )
                replacement_id = self._find_replacement(
                    call.target_entity_id, call.verb_domain, by_entity_id
                )
                evidence_match = detect_wrong_domain_action_target(
                    call,
                    target_is_orphaned=orphaned,
                    replacement_entity_id=replacement_id,
                )
                if evidence_match is not None:
                    _LOGGER.debug(
                        "HAMIE wrong_domain_action_target match: file=%s "
                        "call=%s.%s target=%s replacement=%s",
                        evidence_match.defining_file,
                        evidence_match.verb_domain,
                        evidence_match.verb_action,
                        evidence_match.target_entity_id,
                        evidence_match.replacement_entity_id,
                    )
                    finding = self._candidate(evidence_match, observed_at=at)
                    findings.append(finding)
                    # Coverage here tracks scanned *files*; a finding's
                    # subject.source_id is the target entity_id it is
                    # about, a different key space -- both must appear
                    # in covered_subjects to satisfy
                    # AnalyzerOutcome.__post_init__'s "every finding
                    # subject must be covered" invariant.
                    covered.append(finding.subject.source_id)
            except Exception:  # noqa: BLE001 -- one malformed call never
                # aborts the scan (mission Part 6).
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
            uncovered_subjects=tuple(sorted(uncovered)),
        )

    @staticmethod
    def _find_replacement(
        target_entity_id: str,
        verb_domain: str,
        by_entity_id: dict[str, EntityRecord],
    ) -> str | None:
        """Find exactly one live, alive sibling with the same object_id in
        a genuinely different domain -- never guesses among multiple
        candidates (ambiguous evidence is treated as no evidence)."""
        object_id = target_entity_id.partition(".")[2]
        if not object_id:
            return None
        candidates = [
            record
            for entity_id, record in by_entity_id.items()
            if entity_id.partition(".")[2] == object_id
            and entity_id.partition(".")[0] != verb_domain
            and _is_alive(record)
        ]
        if len(candidates) != 1:
            return None
        return candidates[0].entity_id

    def _candidate(self, evidence_match, *, observed_at: datetime) -> CandidateFinding:
        protected = is_protected_subject(
            entity_id=evidence_match.target_entity_id,
            source_file=evidence_match.defining_file,
        ) or is_protected_subject(entity_id=evidence_match.replacement_entity_id)
        subject = SubjectIdentity(
            durable_id=stable_digest(
                evidence_match.defining_file,
                evidence_match.target_entity_id,
                evidence_match.verb_domain,
                evidence_match.verb_action,
            )[:32],
            kind="hamie.action_target",
            source_instance=self.source_instance,
            source_id=evidence_match.target_entity_id,
            display_hint=(
                f"Wrong-domain action target in {evidence_match.defining_file}"
            ),
            aliases=(evidence_match.target_entity_id, evidence_match.replacement_entity_id),
        )
        revision = stable_digest(
            evidence_match.defining_file,
            evidence_match.verb_domain,
            evidence_match.verb_action,
            evidence_match.target_entity_id,
            evidence_match.replacement_entity_id,
        )
        evidence = (
            EvidenceItem(
                subject=subject,
                predicate="hamie.action_call.service@1",
                value=f"{evidence_match.verb_domain}.{evidence_match.verb_action}",
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.action_call.target_entity_id@1",
                value=evidence_match.target_entity_id,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.action_call.defining_file@1",
                value=evidence_match.defining_file,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
            EvidenceItem(
                subject=subject,
                predicate="hamie.action_call.replacement_entity_id@1",
                value=evidence_match.replacement_entity_id,
                observed_at=observed_at,
                source_id="home_assistant",
                source_revision=revision,
                kind=EvidenceKind.OBSERVED,
                sensitivity=Sensitivity.PUBLIC,
            ),
        )
        rationale = (
            f"{evidence_match.defining_file} calls "
            f"{evidence_match.verb_domain}.{evidence_match.verb_action} against "
            f"{evidence_match.target_entity_id}, but that entity is orphaned "
            f"and a live sibling with the same object_id now exists as "
            f"{evidence_match.replacement_entity_id} (domain "
            f"{evidence_match.replacement_domain!r}). Fixing only the "
            "entity_id would still be broken: the service call's own verb "
            f"domain must also change to {evidence_match.replacement_domain}."
        )
        confidence = Confidence(
            level=ConfidenceLevel.MEDIUM,
            factors=(
                ConfidenceFactor(
                    code="target_orphaned",
                    effect=35,
                    rationale="The literal target entity_id is confirmed orphaned.",
                ),
                ConfidenceFactor(
                    code="exactly_one_cross_domain_sibling",
                    effect=35,
                    rationale=(
                        "Exactly one live, alive entity shares the same object_id "
                        "in a different domain -- never guessed among multiple "
                        "candidates."
                    ),
                ),
            ),
            rule_revision="wrong-domain-action-confidence@1",
        )
        risk = Risk(
            likelihood=RiskLevel.HIGH,
            impact=RiskLevel.CRITICAL if protected else RiskLevel.HIGH,
            reversible=True,
            affected_scope=(
                f"{evidence_match.defining_file} (advisory only -- HAMIE never "
                "edits configuration itself)"
            ),
            overall=RiskLevel.CRITICAL if protected else RiskLevel.HIGH,
            rationale=(
                "This action call currently does nothing (its target no longer "
                "exists in a working state) every time the automation/script "
                "runs, with no error surfaced."
                + (
                    " This subject matches a safety/security-relevant domain or "
                    "naming pattern -- treat with elevated priority."
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
                evidence_match.target_entity_id,
                evidence_match.replacement_entity_id,
            ),
            safe_to_remove=False,
        )
        action = (
            f"Repair {evidence_match.defining_file}: change "
            f"{evidence_match.verb_domain}.{evidence_match.verb_action} to "
            f"{evidence_match.replacement_domain}.{evidence_match.verb_action} "
            f"and update the target entity_id from "
            f"{evidence_match.target_entity_id} to "
            f"{evidence_match.replacement_entity_id}. Both changes are required "
            "-- fixing only the entity_id leaves the wrong service domain in "
            "place. Advisory only -- HAMIE never edits this file itself."
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
                "Confirm the replacement entity is genuinely the same physical "
                "device/functionality, not a coincidental object_id match.",
            ),
            disqualifiers=(
                "Do not edit if the automation intentionally targets both "
                "entities across a real migration transition period.",
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
            title_key="wrong_domain_action_target",
            description_arguments=(
                ("defining_file", evidence_match.defining_file),
                ("target_entity_id", evidence_match.target_entity_id),
            ),
            severity=FindingSeverity.ERROR,
            evidence=evidence,
            recommendation=recommendation,
        )
