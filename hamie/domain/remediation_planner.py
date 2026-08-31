"""Deterministic remediation planner (HAMIE Phase 2B).

Turns one ``CanonicalRecommendation`` (``domain/recommendation.py``) into
either a ``RemediationPlan`` or an explicit, typed ``PlanningRejection``.
Never raises for an ordinary "this cannot be planned" outcome -- fail-closed
conditions are data, not exceptions, so a caller can show a precise reason
to a human rather than a stack trace.

Pure and I/O-free, like the rest of ``domain/``: this module never calls
an adapter, never touches Home Assistant, and never persists anything. It
only *selects* a catalog action and *proposes* what a plan for it would
look like; nothing here approves or executes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .common import require_non_empty, stable_digest
from .entity_batch import encode_entity_id_batch
from .findings import Confidence, ConfidenceFactor, ConfidenceLevel, Risk, RiskLevel
from .identity import SubjectIdentity
from .llm_proposal import LlmProposedAction
from .recommendation import (
    CanonicalRecommendation,
    DependencyAnalysisStatus,
    ProvenanceSource,
    RecommendationDisposition,
    RecommendationLifecycleState,
    RecommendationReviewState,
)
from .remediation import (
    BackupRequirement,
    DataLossRisk,
    RemediationActionStep,
    RemediationDependencySnapshot,
    RemediationPlan,
    RemediationPlanState,
    RemediationRiskAssessment,
    RemediationRollbackStep,
    RemediationVerificationSpec,
    RollbackPlan,
    RollbackSupportStatus,
    compute_remediation_plan_fingerprint,
    compute_structural_preview_digest,
)
from .remediation_catalog import (
    ActionCatalogEntry,
    DependencyRequirement,
    get_catalog_entry,
)
from .remediation_llm_proposal import ProposalRejection, validate_llm_proposed_action

PLANNER_VERSION = "hamie.remediation_planner@1"

# Adapter versions are tracked here, not on the catalog entry, because an
# adapter can be re-released independently of the action it implements --
# bumping this without bumping the catalog entry's own ``version`` still
# changes plan identity (adapter-version sensitivity, see
# ``compute_remediation_plan_fingerprint``).
ADAPTER_VERSIONS: dict[str, int] = {
    "manual_action_adapter": 1,
    "recorder_exclusion_patch_adapter": 1,
    "fixture_test_adapter": 1,
    "config_entry_reload_adapter": 1,
    "enable_entity_adapter": 1,
    "disable_unused_entity_adapter": 1,
    "file_mutation_adapter": 1,
    "disable_entity_batch_adapter": 1,
}

# Reserved for future destructive, execution_supported actions -- no
# currently supported catalog entry is destructive, so this threshold is
# not yet exercised by any real plan, but the mechanism is real and
# tested against a synthetic destructive catalog entry.
MINIMUM_CONFIDENCE_FOR_DESTRUCTIVE_EXECUTION = ConfidenceLevel.MEDIUM
_CONFIDENCE_RANK = {
    ConfidenceLevel.LOW: 0,
    ConfidenceLevel.MEDIUM: 1,
    ConfidenceLevel.HIGH: 2,
}

DEFAULT_PLAN_EXPIRY = timedelta(hours=72)


@dataclass(frozen=True, slots=True)
class PlanningRejection:
    """Why one recommendation could not become a remediation plan."""

    recommendation_id: str
    reason_code: str
    message: str

    def __post_init__(self) -> None:
        require_non_empty(self.recommendation_id, "recommendation_id")
        require_non_empty(self.reason_code, "reason_code")
        require_non_empty(self.message, "message")


def _select_action_type(recommendation: CanonicalRecommendation) -> str | None:
    """Deterministically choose a catalog action for a recommendation.

    A fixed, documented policy -- never an LLM choice (see
    ``docs/REMEDIATION_ENGINE.md``): a recommendation whose disposition is
    ``EXCLUDE`` against a real Home Assistant entity gets a proposed
    recorder-exclusion patch; every other recommendation gets the
    universal, always-safe "mark for manual remediation" fallback.
    ``hamie.test_fixture_mutation`` is deliberately never selected here --
    it is reachable only through ``plan_test_fixture_remediation`` below,
    so the normal recommendation-driven planning path can never produce a
    plan against a test-only action.
    """
    if (
        recommendation.execution_action_type
        and recommendation.generated_by is not ProvenanceSource.LLM_ANALYSIS
    ):
        return recommendation.execution_action_type
    if (
        recommendation.disposition is RecommendationDisposition.EXCLUDE
        and recommendation.affected_object.kind == "home_assistant.entity"
    ):
        return "hamie.generate_recorder_exclusion_patch"
    return "hamie.mark_for_manual_remediation"


def _dependency_snapshot(
    recommendation: CanonicalRecommendation,
) -> RemediationDependencySnapshot:
    analysis = recommendation.dependency_analysis
    dependency_digest = stable_digest(
        analysis.status.value,
        analysis.safe_to_delete,
        tuple(sorted(analysis.inbound_references)),
        tuple(sorted(analysis.outbound_references)),
        tuple(sorted(analysis.unknown_dependencies)),
    )
    evidence_digest = stable_digest(
        tuple(sorted(item.evidence_id for item in recommendation.evidence))
    )
    unavailable = tuple(
        sorted(
            item.source
            for item in analysis.sources
            if item.status.value in {"unavailable", "failed"}
        )
    )
    return RemediationDependencySnapshot(
        dependency_digest=dependency_digest,
        evidence_digest=evidence_digest,
        sources_checked=tuple(sorted(item.source for item in analysis.sources)),
        unavailable_sources=unavailable,
        unresolved_dependencies=analysis.unknown_dependencies,
        blocking_dependencies=analysis.inbound_references,
        preconditions=(
            "recommendation.lifecycle_state == active",
            "recommendation.review_state != rejected",
        ),
    )


def _rollback_step_for(
    action_type: str, step_index: int
) -> RemediationRollbackStep | None:
    """Return the deterministic rollback step for one supported action.

    Every currently supported catalog entry is reversible via its own
    adapter's ``rollback()`` method -- see
    ``application/remediation/adapters.py`` -- so the rollback step here
    only needs to identify which step it reverses; the adapter itself
    reads the recorded execution result (its rollback token/before-state)
    to know exactly what to undo.
    """
    descriptions = {
        "hamie.mark_for_manual_remediation": (
            "confirms the manual-remediation mark was removed"
        ),
        "hamie.generate_recorder_exclusion_patch": (
            "confirms the generated patch artifact was discarded"
        ),
        "hamie.test_fixture_mutation": "confirms the fixture value was restored",
        "enable_entity": "confirms the exact previous disabled state was restored",
        "disable_unused_entity": (
            "confirms the exact previous registry state was restored"
        ),
        "hamie.annotate_maintenance_notes": (
            "confirms the maintenance notes file was restored to its exact "
            "previous content"
        ),
    }
    description = descriptions.get(action_type)
    if description is None:
        return None
    return RemediationRollbackStep(
        reverses_step_index=step_index,
        action_type=action_type,
        adapter_id=ACTION_ADAPTER_BY_TYPE[action_type],
        parameters=(),
        verification_description=description,
    )


ACTION_ADAPTER_BY_TYPE: dict[str, str] = {
    "hamie.mark_for_manual_remediation": "manual_action_adapter",
    "hamie.generate_recorder_exclusion_patch": "recorder_exclusion_patch_adapter",
    "hamie.test_fixture_mutation": "fixture_test_adapter",
    "reload_config_entry": "config_entry_reload_adapter",
    "enable_entity": "enable_entity_adapter",
    "disable_unused_entity": "disable_unused_entity_adapter",
    "hamie.annotate_maintenance_notes": "file_mutation_adapter",
    "disable_entity_batch": "disable_entity_batch_adapter",
}


def _build_action_step(
    *,
    entry: ActionCatalogEntry,
    recommendation: CanonicalRecommendation,
    parameters: tuple[tuple[str, str], ...],
    expected_change_description: str,
) -> RemediationActionStep:
    adapter_id = entry.adapter_id
    if adapter_id is None:
        # Guaranteed unreachable: every caller of this helper has already
        # checked entry.execution_supported, and ActionCatalogEntry's own
        # __post_init__ requires adapter_id whenever execution_supported.
        raise RuntimeError(
            f"{entry.action_type} has no adapter_id but was treated as executable"
        )
    adapter_version = ADAPTER_VERSIONS[adapter_id]
    return RemediationActionStep(
        step_index=0,
        action_type=entry.action_type,
        action_version=entry.version,
        target=recommendation.affected_object,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        parameters=parameters,
        expected_change_description=expected_change_description,
        destructive=entry.destructive,
        idempotency=entry.idempotency,
        reversible=entry.reversible,
        verification=RemediationVerificationSpec(
            method=entry.verification_method,
            expected_outcome_description=(
                f"{entry.action_type} completed and passed post-action verification"
            ),
        ),
        required_backup=entry.required_backup,
        rollback_step=_rollback_step_for(entry.action_type, 0),
        timeout_seconds=entry.timeout_seconds,
    )


def _action_parameters(
    entry: ActionCatalogEntry, recommendation: CanonicalRecommendation
) -> tuple[tuple[str, str], ...]:
    """Build fingerprint-safe parameters: stable identifiers only, never prose."""
    if entry.action_type == "reload_config_entry":
        return (
            ("recommendation_id", recommendation.recommendation_id),
            ("current_failure", "true"),
            (
                "cooldown_passed",
                "true"
                if "cooldown_passed" in recommendation.prerequisites
                else "false",
            ),
            ("target_fingerprint", recommendation.content_digest),
            (
                "expected_entity_ids",
                ",".join(
                    item.subject.source_id
                    for item in recommendation.supporting_objects
                    if item.subject.kind == "home_assistant.entity"
                ),
            ),
        )
    if entry.action_type == "enable_entity":
        return (
            ("recommendation_id", recommendation.recommendation_id),
            ("target_fingerprint", recommendation.content_digest),
        )
    if entry.action_type == "disable_unused_entity":
        analysis = recommendation.dependency_analysis
        persistent = any(
            item.evidence_type == "persistent_unavailable"
            for item in recommendation.evidence
        )
        eligible_category = recommendation.subtype in {
            "optional",
            "configuration",
            "diagnostic",
            "feature",
        }
        return (
            ("recommendation_id", recommendation.recommendation_id),
            ("target_fingerprint", recommendation.content_digest),
            ("persistent_unavailable", str(persistent).lower()),
            ("eligible_entity_category", str(eligible_category).lower()),
            ("dependency_coverage", analysis.status.value),
            ("direct_reference_count", str(len(analysis.inbound_references))),
            ("indirect_reference_count", str(len(analysis.outbound_references))),
            ("unresolved_reference_count", str(len(analysis.unknown_dependencies))),
        )
    if entry.action_type == "hamie.generate_recorder_exclusion_patch":
        return (
            ("recommendation_id", recommendation.recommendation_id),
            ("entity_id", recommendation.affected_object.source_id),
        )
    return (("recommendation_id", recommendation.recommendation_id),)


def _risk_assessment(
    entry: ActionCatalogEntry, recommendation: CanonicalRecommendation
) -> RemediationRiskAssessment:
    rollback_support = (
        RollbackSupportStatus.SUPPORTED
        if entry.rollback_capable
        else RollbackSupportStatus.UNSUPPORTED
    )
    data_loss = DataLossRisk.HIGH if entry.destructive else DataLossRisk.NONE
    return RemediationRiskAssessment(
        risk=recommendation.risk.risk,
        destructive=entry.destructive,
        reversible=entry.reversible,
        rollback_support=rollback_support,
        expected_user_visible_impact=(
            "none -- this action only affects HAMIE's own recommendation "
            "metadata or produces an inert artifact for manual review"
            if not entry.destructive
            else "not applicable: this action is not execution_supported"
        ),
        expected_service_interruption="none",
        expected_data_loss_risk=data_loss,
        confidence=recommendation.confidence,
        risk_rationale=(
            f"{entry.action_type} is non-destructive and reversible; no "
            "Home Assistant mutation occurs."
            if not entry.destructive
            else f"{entry.action_type} is destructive and not execution_supported."
        ),
    )


def _rollback_plan(
    entry: ActionCatalogEntry, step: RemediationActionStep
) -> RollbackPlan:
    if not entry.rollback_capable or step.rollback_step is None:
        return RollbackPlan(supported=False)
    return RollbackPlan(
        supported=True,
        steps=(step.rollback_step,),
        risk=entry.risk_class,
        verification=step.rollback_step.verification_description,
    )


def plan_remediation(
    recommendation: CanonicalRecommendation,
    *,
    now: datetime,
    created_by: str = "hamie.remediation_planner",
) -> RemediationPlan | PlanningRejection:
    """Build a deterministic remediation plan for one recommendation.

    Fails closed (returns a ``PlanningRejection``, never raises for an
    ordinary business reason) when: the recommendation is not
    ``ACTIVE``; a human already ``REJECTED`` it in review; no catalog
    action applies; the selected action is not ``execution_supported``;
    dependency analysis is incomplete for an action that requires it; or
    the target object is tombstoned (identity no longer valid to act on).
    """
    if recommendation.lifecycle_state is not RecommendationLifecycleState.ACTIVE:
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code="recommendation_not_active",
            message=(
                "recommendation lifecycle_state is "
                f"{recommendation.lifecycle_state.value}, not active"
            ),
        )
    if recommendation.review_state is RecommendationReviewState.REJECTED:
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code="recommendation_rejected_by_review",
            message="a human reviewer already rejected this recommendation",
        )
    if recommendation.affected_object.tombstoned:
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code="target_ambiguous",
            message="the affected object's identity is tombstoned",
        )

    action_type = _select_action_type(recommendation)
    entry = get_catalog_entry(action_type) if action_type else None
    if entry is None:
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code="no_matching_catalog_action",
            message="no catalog action applies to this recommendation",
        )
    if not entry.supports_target_kind(recommendation.affected_object.kind):
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code="target_ambiguous",
            message=(
                f"{entry.action_type} does not support target kind "
                f"{recommendation.affected_object.kind}"
            ),
        )
    if not entry.execution_supported:
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code="action_not_execution_supported",
            message=entry.unsupported_reason or "action is not execution_supported",
        )
    if entry.dependency_requirement is DependencyRequirement.COMPLETE_REQUIRED:
        dependency_complete = (
            recommendation.dependency_analysis.status
            == DependencyAnalysisStatus.COMPLETE
        )
        if not dependency_complete:
            return PlanningRejection(
                recommendation_id=recommendation.recommendation_id,
                reason_code="dependency_analysis_incomplete",
                message=(
                    "dependency analysis status is "
                    f"{recommendation.dependency_analysis.status.value}, "
                    "not complete"
                ),
            )
        if entry.destructive:
            below_threshold = (
                _CONFIDENCE_RANK[recommendation.confidence.level]
                < _CONFIDENCE_RANK[MINIMUM_CONFIDENCE_FOR_DESTRUCTIVE_EXECUTION]
            )
            if below_threshold:
                return PlanningRejection(
                    recommendation_id=recommendation.recommendation_id,
                    reason_code="confidence_below_threshold",
                    message=(
                        "confidence is below the minimum required for a "
                        "destructive action"
                    ),
                )

    parameters = _action_parameters(entry, recommendation)
    expected_change = _expected_change_description(entry, recommendation)
    step = _build_action_step(
        entry=entry,
        recommendation=recommendation,
        parameters=parameters,
        expected_change_description=expected_change,
    )
    dependency_snapshot = _dependency_snapshot(recommendation)
    risk = _risk_assessment(entry, recommendation)
    rollback_plan = _rollback_plan(entry, step)
    requires_backup = entry.required_backup is BackupRequirement.REQUIRED

    fingerprint = compute_remediation_plan_fingerprint(
        recommendation_id=recommendation.recommendation_id,
        recommendation_fingerprint=recommendation.fingerprint,
        recommendation_revision=recommendation.content_revision,
        installation_id=recommendation.installation_id,
        planner_version=PLANNER_VERSION,
        actions=(step,),
        dependency_snapshot=dependency_snapshot,
        risk=risk,
        requires_backup=requires_backup,
    )
    preview_digest = compute_structural_preview_digest((step,))

    return RemediationPlan(
        remediation_plan_id=f"plan_{fingerprint[:24]}",
        plan_fingerprint=fingerprint,
        fingerprint_version=1,
        schema_version=1,
        recommendation_id=recommendation.recommendation_id,
        recommendation_fingerprint=recommendation.fingerprint,
        recommendation_revision=recommendation.content_revision,
        installation_id=recommendation.installation_id,
        created_at=now,
        created_by=created_by,
        planner_version=PLANNER_VERSION,
        state=RemediationPlanState.READY_FOR_REVIEW,
        actions=(step,),
        dependency_snapshot=dependency_snapshot,
        risk=risk,
        rollback_plan=rollback_plan,
        execution_supported=True,
        expires_at=now + DEFAULT_PLAN_EXPIRY,
        requires_backup=requires_backup,
        requires_manual_confirmation=True,
        approval_scope="single",
        batch_compatible=not entry.destructive,
        preview_digest=preview_digest,
    )


def _expected_change_description(
    entry: ActionCatalogEntry, recommendation: CanonicalRecommendation
) -> str:
    if entry.action_type == "hamie.mark_for_manual_remediation":
        return (
            f"Mark recommendation {recommendation.recommendation_id} for manual "
            "follow-up; no Home Assistant object is changed."
        )
    if entry.action_type == "hamie.generate_recorder_exclusion_patch":
        return (
            "Generate a proposed recorder exclusion patch for "
            f"{recommendation.affected_object.source_id}; the patch is stored "
            "as an artifact and never applied to Home Assistant automatically."
        )
    return f"Apply {entry.action_type} against an isolated test fixture."


def plan_test_fixture_remediation(
    recommendation: CanonicalRecommendation,
    *,
    now: datetime,
    fixture_key: str,
    fixture_value: str,
    created_by: str = "hamie.remediation_planner.test_only",
) -> RemediationPlan | PlanningRejection:
    """Build a plan against the test-only fixture adapter.

    Deliberately a separate entry point from ``plan_remediation`` -- the
    normal recommendation-driven planning path can never select
    ``hamie.test_fixture_mutation``, so this function exists only to let
    tests exercise the full plan/approve/execute/rollback lifecycle
    without ever risking a real Home Assistant target. ``recommendation``
    must still have ``affected_object.kind == "hamie.test_fixture"``.
    """
    entry = get_catalog_entry("hamie.test_fixture_mutation")
    if entry is None:  # pragma: no cover - defensive, catalog is static
        raise RuntimeError("hamie.test_fixture_mutation is missing from the catalog")
    if recommendation.lifecycle_state is not RecommendationLifecycleState.ACTIVE:
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code="recommendation_not_active",
            message="recommendation is not active",
        )
    if not entry.supports_target_kind(recommendation.affected_object.kind):
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code="target_ambiguous",
            message="test fixture action requires a hamie.test_fixture target",
        )
    parameters = (
        ("recommendation_id", recommendation.recommendation_id),
        ("fixture_key", fixture_key),
        ("fixture_value", fixture_value),
    )
    step = _build_action_step(
        entry=entry,
        recommendation=recommendation,
        parameters=parameters,
        expected_change_description=_expected_change_description(entry, recommendation),
    )
    dependency_snapshot = _dependency_snapshot(recommendation)
    risk = _risk_assessment(entry, recommendation)
    rollback_plan = _rollback_plan(entry, step)
    fingerprint = compute_remediation_plan_fingerprint(
        recommendation_id=recommendation.recommendation_id,
        recommendation_fingerprint=recommendation.fingerprint,
        recommendation_revision=recommendation.content_revision,
        installation_id=recommendation.installation_id,
        planner_version=PLANNER_VERSION,
        actions=(step,),
        dependency_snapshot=dependency_snapshot,
        risk=risk,
        requires_backup=False,
    )
    preview_digest = compute_structural_preview_digest((step,))
    return RemediationPlan(
        remediation_plan_id=f"plan_{fingerprint[:24]}",
        plan_fingerprint=fingerprint,
        fingerprint_version=1,
        schema_version=1,
        recommendation_id=recommendation.recommendation_id,
        recommendation_fingerprint=recommendation.fingerprint,
        recommendation_revision=recommendation.content_revision,
        installation_id=recommendation.installation_id,
        created_at=now,
        created_by=created_by,
        planner_version=PLANNER_VERSION,
        state=RemediationPlanState.READY_FOR_REVIEW,
        actions=(step,),
        dependency_snapshot=dependency_snapshot,
        risk=risk,
        rollback_plan=rollback_plan,
        execution_supported=True,
        expires_at=now + DEFAULT_PLAN_EXPIRY,
        requires_backup=False,
        requires_manual_confirmation=True,
        approval_scope="single",
        batch_compatible=True,
        preview_digest=preview_digest,
    )


def plan_llm_proposed_remediation(
    recommendation: CanonicalRecommendation,
    proposal: LlmProposedAction,
    *,
    expected_before_hash: str,
    now: datetime,
    known_evidence_ids: frozenset[str] | None = None,
    created_by: str = "hamie.remediation_planner.llm_proposal",
) -> RemediationPlan | PlanningRejection:
    """Build a deterministic plan from one LLM-proposed action.

    This is the *only* path through which a model's own suggestion can
    ever reach an executable plan (mission Phase 4/15). Critically, this
    never lets the model choose *how* the action executes -- the catalog
    entry, adapter, verification method, and rollback plan all come from
    ``domain/remediation_catalog.py``, exactly like every other planning
    path. Only the resource id and the operation's key/value are taken
    from the (already policy-validated) proposal, and even those are
    re-validated here via ``validate_llm_proposed_action`` -- resource
    allowlist membership, action-type compatibility, and (when
    ``known_evidence_ids`` is supplied) evidence membership -- before
    anything is built.

    ``expected_before_hash`` is supplied by the caller (the application
    layer, which is allowed to perform I/O) rather than computed here:
    this function, like the rest of ``domain/``, never touches a
    filesystem or Home Assistant.

    Fails closed with a ``PlanningRejection`` for every business reason
    ``plan_remediation`` fails closed for, plus: the proposal fails
    policy validation, or the catalog action selected for the proposal's
    resource is not itself ``execution_supported``.
    """
    if recommendation.lifecycle_state is not RecommendationLifecycleState.ACTIVE:
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code="recommendation_not_active",
            message="recommendation is not active",
        )
    if recommendation.review_state is RecommendationReviewState.REJECTED:
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code="recommendation_rejected_by_review",
            message="a human reviewer already rejected this recommendation",
        )
    validated = validate_llm_proposed_action(
        proposal, known_evidence_ids=known_evidence_ids
    )
    if isinstance(validated, ProposalRejection):
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code=f"llm_proposal_{validated.reason_code}",
            message=validated.message,
        )
    action_type = "hamie.annotate_maintenance_notes"
    entry = get_catalog_entry(action_type)
    if (
        entry is None or not entry.execution_supported
    ):  # pragma: no cover - static catalog
        return PlanningRejection(
            recommendation_id=recommendation.recommendation_id,
            reason_code="action_not_execution_supported",
            message="no execution-supported catalog action exists for this proposal",
        )
    operation = dict(validated.operation)
    target = SubjectIdentity(
        durable_id=validated.resource_id,
        kind="hamie.editable_resource",
        source_instance=recommendation.installation_id,
        source_id=validated.resource_id,
        display_hint=f"HAMIE editable resource {validated.resource_id}",
    )
    parameters = (
        ("resource_id", validated.resource_id),
        ("operation_key", operation.get("key", "")),
        ("operation_value", operation.get("value", "")),
        ("expected_before_hash", expected_before_hash),
        ("recommendation_id", recommendation.recommendation_id),
    )
    step = RemediationActionStep(
        step_index=0,
        action_type=entry.action_type,
        action_version=entry.version,
        target=target,
        adapter_id=entry.adapter_id,  # type: ignore[arg-type]
        adapter_version=ADAPTER_VERSIONS[entry.adapter_id],  # type: ignore[index]
        parameters=parameters,
        expected_change_description=(
            f"Set maintenance note {operation.get('key', '')!r} on "
            f"{validated.resource_id} to the LLM-proposed value: {validated.reason}"
        ),
        destructive=entry.destructive,
        idempotency=entry.idempotency,
        reversible=entry.reversible,
        verification=RemediationVerificationSpec(
            method=entry.verification_method,
            expected_outcome_description=(
                f"{entry.action_type} completed and the file content matches "
                "the proposed value"
            ),
        ),
        required_backup=entry.required_backup,
        rollback_step=_rollback_step_for(entry.action_type, 0),
        timeout_seconds=entry.timeout_seconds,
    )
    dependency_snapshot = _dependency_snapshot(recommendation)
    risk = _risk_assessment(entry, recommendation)
    rollback_plan = _rollback_plan(entry, step)
    fingerprint = compute_remediation_plan_fingerprint(
        recommendation_id=recommendation.recommendation_id,
        recommendation_fingerprint=recommendation.fingerprint,
        recommendation_revision=recommendation.content_revision,
        installation_id=recommendation.installation_id,
        planner_version=PLANNER_VERSION,
        actions=(step,),
        dependency_snapshot=dependency_snapshot,
        risk=risk,
        requires_backup=False,
    )
    preview_digest = compute_structural_preview_digest((step,))
    return RemediationPlan(
        remediation_plan_id=f"plan_{fingerprint[:24]}",
        plan_fingerprint=fingerprint,
        fingerprint_version=1,
        schema_version=1,
        recommendation_id=recommendation.recommendation_id,
        recommendation_fingerprint=recommendation.fingerprint,
        recommendation_revision=recommendation.content_revision,
        installation_id=recommendation.installation_id,
        created_at=now,
        created_by=created_by,
        planner_version=PLANNER_VERSION,
        state=RemediationPlanState.READY_FOR_REVIEW,
        actions=(step,),
        dependency_snapshot=dependency_snapshot,
        risk=risk,
        rollback_plan=rollback_plan,
        execution_supported=True,
        expires_at=now + DEFAULT_PLAN_EXPIRY,
        requires_backup=False,
        requires_manual_confirmation=True,
        approval_scope="single",
        batch_compatible=False,
        preview_digest=preview_digest,
    )


def plan_batch_disable_remediation(
    *,
    entity_ids: tuple[str, ...],
    expected_before_digest: str,
    installation_id: str,
    now: datetime,
    batch_label: str = "cleanup batch",
    created_by: str = "hamie.remediation_planner.batch_disable",
) -> RemediationPlan | PlanningRejection:
    """Build a deterministic plan disabling many unused entities at once
    (mission Part 8/22 -- the batch counterpart to ``enable_entity``/
    ``disable_unused_entity``).

    Unlike every other planning path, this one is not driven by a single
    ``CanonicalRecommendation`` -- its candidates come from the cleanup
    classification engine (``domain/cleanup_classifier.py``), which the
    caller has already run and filtered to ``safe_auto_fix``/
    ``safe_with_approval`` entities only. This function only builds the
    deterministic plan shape; it never re-runs classification or
    dependency analysis itself.

    ``expected_before_digest`` (each member entity's current
    ``disabled_by`` fingerprint, hashed together) is supplied by the
    caller -- like every other planner function, this stays I/O-free and
    never reads Home Assistant state itself.
    """
    if not entity_ids:
        return PlanningRejection(
            recommendation_id=batch_label,
            reason_code="empty_batch",
            message="a batch disable plan requires at least one entity",
        )
    entry = get_catalog_entry("disable_entity_batch")
    if (
        entry is None or not entry.execution_supported
    ):  # pragma: no cover - static catalog
        return PlanningRejection(
            recommendation_id=batch_label,
            reason_code="action_not_execution_supported",
            message="disable_entity_batch is not execution_supported",
        )
    try:
        parameters = (
            *encode_entity_id_batch(entity_ids),
            ("expected_before_digest", expected_before_digest),
        )
    except ValueError as err:
        return PlanningRejection(
            recommendation_id=batch_label,
            reason_code="invalid_batch",
            message=str(err),
        )
    adapter_id = entry.adapter_id
    if adapter_id is None:  # pragma: no cover - defensive, catalog is static
        raise RuntimeError(
            f"{entry.action_type} has no adapter_id but was treated as executable"
        )
    target = SubjectIdentity(
        durable_id=stable_digest(*sorted(entity_ids)),
        kind="hamie.entity_batch",
        source_instance=installation_id,
        source_id=batch_label,
        display_hint=f"{batch_label} ({len(entity_ids)} entities)",
    )
    step = RemediationActionStep(
        step_index=0,
        action_type=entry.action_type,
        action_version=entry.version,
        target=target,
        adapter_id=adapter_id,
        adapter_version=ADAPTER_VERSIONS[adapter_id],
        parameters=parameters,
        expected_change_description=(
            f"Disable {len(entity_ids)} unused entities classified safe by "
            "the HAMIE cleanup engine."
        ),
        destructive=entry.destructive,
        idempotency=entry.idempotency,
        reversible=entry.reversible,
        verification=RemediationVerificationSpec(
            method=entry.verification_method,
            expected_outcome_description=(
                f"all {len(entity_ids)} batch member entities are disabled"
            ),
        ),
        required_backup=entry.required_backup,
        rollback_step=RemediationRollbackStep(
            reverses_step_index=0,
            action_type=entry.action_type,
            adapter_id=adapter_id,
            parameters=(),
            verification_description=(
                "confirms every batch member entity's exact previous "
                "disabled_by state was restored"
            ),
        ),
        timeout_seconds=entry.timeout_seconds,
    )
    dependency_snapshot = RemediationDependencySnapshot(
        dependency_digest=stable_digest("batch_disable", *sorted(entity_ids)),
        evidence_digest=stable_digest(expected_before_digest),
        preconditions=(
            "every member entity classified safe_auto_fix or "
            "safe_with_approval by the cleanup classifier",
        ),
    )
    risk = RemediationRiskAssessment(
        risk=Risk(
            likelihood=RiskLevel.LOW,
            impact=RiskLevel.LOW,
            reversible=True,
            affected_scope=f"{len(entity_ids)} entities",
            overall=RiskLevel.LOW,
            rationale=(
                "Disabling is reversible and each member entity was "
                "individually classified safe by the cleanup engine."
            ),
        ),
        destructive=False,
        reversible=True,
        rollback_support=RollbackSupportStatus.SUPPORTED,
        expected_user_visible_impact=(
            f"{len(entity_ids)} entities become disabled and stop updating state"
        ),
        expected_service_interruption="none",
        expected_data_loss_risk=DataLossRisk.NONE,
        confidence=Confidence(
            level=ConfidenceLevel.HIGH,
            factors=(
                ConfidenceFactor(
                    code="deterministic_classification",
                    effect=80,
                    rationale=(
                        "Every member entity passed deterministic cleanup "
                        "eligibility checks before being included."
                    ),
                ),
            ),
            rule_revision="batch_disable@1",
        ),
        risk_rationale=(
            "Registry disable is reversible and scoped to entities the "
            "cleanup classifier already verified are unreferenced and "
            "persistently unavailable."
        ),
    )
    rollback_plan = RollbackPlan(
        supported=True,
        steps=(step.rollback_step,) if step.rollback_step else (),
        risk=RiskLevel.LOW,
        verification=(
            "confirms every batch member entity's exact previous "
            "disabled_by state was restored"
        ),
    )
    fingerprint = compute_remediation_plan_fingerprint(
        recommendation_id=batch_label,
        recommendation_fingerprint=stable_digest("batch_disable", *sorted(entity_ids)),
        recommendation_revision=1,
        installation_id=installation_id,
        planner_version=PLANNER_VERSION,
        actions=(step,),
        dependency_snapshot=dependency_snapshot,
        risk=risk,
        requires_backup=False,
    )
    preview_digest = compute_structural_preview_digest((step,))
    return RemediationPlan(
        remediation_plan_id=f"plan_{fingerprint[:24]}",
        plan_fingerprint=fingerprint,
        fingerprint_version=1,
        schema_version=1,
        recommendation_id=batch_label,
        recommendation_fingerprint=stable_digest("batch_disable", *sorted(entity_ids)),
        recommendation_revision=1,
        installation_id=installation_id,
        created_at=now,
        created_by=created_by,
        planner_version=PLANNER_VERSION,
        state=RemediationPlanState.READY_FOR_REVIEW,
        actions=(step,),
        dependency_snapshot=dependency_snapshot,
        risk=risk,
        rollback_plan=rollback_plan,
        execution_supported=True,
        expires_at=now + DEFAULT_PLAN_EXPIRY,
        requires_backup=False,
        requires_manual_confirmation=True,
        approval_scope="single",
        batch_compatible=False,
        preview_digest=preview_digest,
    )
