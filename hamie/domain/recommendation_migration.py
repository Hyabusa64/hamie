"""Migrate legacy ``AIRecommendation`` records into ``CanonicalRecommendation``.

``AIRecommendation`` (``domain/intelligence.py``) is a single-shot, flat
advisory record with no dependency, risk, or structured confidence
representation, and no deterministic identity across multiple finding
citations (it is tied to *several* finding/group IDs, not one affected
object). Migration is deliberately lossless-but-honest: every original
field is preserved verbatim inside the migrated record's evidence and
detailed explanation, and every field this model requires but the old
shape never carried is filled with an explicitly conservative,
migration-labeled default -- never a guessed "real" value.

Nothing here mutates the source ``AIRecommendation``, calls Home
Assistant, or performs I/O.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .common import canonical_json
from .findings import Confidence, ConfidenceFactor, ConfidenceLevel, Risk, RiskLevel
from .identity import SubjectIdentity
from .intelligence import AIRecommendation, AIReviewState
from .recommendation import (
    CanonicalRecommendation,
    DependencyAnalysisResult,
    DependencyAnalysisStatus,
    ProvenanceSource,
    RecommendationDisposition,
    RecommendationEvidence,
    RecommendationLifecycleState,
    RecommendationReviewState,
    RecommendationRisk,
    build_recommendation,
)

MIGRATION_DETECTOR_ID = "hamie.migrated_ai_recommendation"
MIGRATION_CATEGORY = "ai_advisory"

# AIReviewState never distinguished "needs fresh evidence" from "review
# lapsed" -- EXPIRED is the closest existing state to
# NEEDS_MORE_EVIDENCE (both mean "do not trust this without re-checking"),
# and RETAINED (a human explicitly chose to keep acting on it later) maps
# to ACCEPTED_FOR_FUTURE_ACTION, the nearest equivalent in the richer
# review-state model.
_REVIEW_STATE_MAP: dict[AIReviewState, RecommendationReviewState] = {
    AIReviewState.NEW: RecommendationReviewState.UNREVIEWED,
    AIReviewState.ACKNOWLEDGED: RecommendationReviewState.ACKNOWLEDGED,
    AIReviewState.REJECTED: RecommendationReviewState.REJECTED,
    AIReviewState.RETAINED: RecommendationReviewState.ACCEPTED_FOR_FUTURE_ACTION,
    AIReviewState.EXPIRED: RecommendationReviewState.NEEDS_MORE_EVIDENCE,
}

_CONFIDENCE_LEVEL_MAP = {level.value: level for level in ConfidenceLevel}


def _map_confidence(raw: str) -> Confidence:
    """Map AIRecommendation's free-text confidence to a validated level.

    ``AIRecommendation.confidence`` is an unvalidated string an LLM wrote
    -- never trusted as-is. A recognized low/medium/high value is mapped
    directly; anything else is recorded as LOW (never inflated) with a
    factor explaining exactly what the original unrecognized value was,
    so the fact that it could not be mapped is visible, not silently
    dropped.
    """
    level = _CONFIDENCE_LEVEL_MAP.get(raw.strip().casefold())
    if level is not None:
        factor = ConfidenceFactor(
            code="migrated_original_confidence",
            effect=0,
            rationale=f"Original AIRecommendation confidence value: {raw!r}",
        )
        return Confidence(level=level, factors=(factor,), rule_revision="migration@1")
    factor = ConfidenceFactor(
        code="migrated_unrecognized_confidence",
        effect=-20,
        rationale=(
            f"Original AIRecommendation confidence value {raw!r} did not match "
            "a known level; defaulted to low rather than assumed."
        ),
    )
    return Confidence(
        level=ConfidenceLevel.LOW, factors=(factor,), rule_revision="migration@1"
    )


def _bounded(text: str, *, max_length: int = 4_000) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def _build_detailed_explanation(value: AIRecommendation) -> str:
    sections = [
        ("Summary", (value.summary,)),
        ("Probable causes", value.probable_causes),
        ("Recommended checks", value.recommended_checks),
        ("Proposed repair plan", value.proposed_repair_plan),
        ("Assumptions", value.assumptions),
        ("Missing evidence", value.missing_evidence),
        ("Risk notes", value.risk_notes),
        ("Do not do", value.do_not_do),
    ]
    parts: list[str] = []
    for heading, items in sections:
        if not items:
            continue
        parts.append(heading + ":")
        parts.extend(f"- {item}" for item in items)
    return _bounded(
        "\n".join(parts) or "No content was recorded on the original recommendation."
    )


def migrate_ai_recommendation(
    value: AIRecommendation,
    *,
    installation_id: str,
    seen_at: datetime,
) -> CanonicalRecommendation:
    """Convert one legacy ``AIRecommendation`` into a ``CanonicalRecommendation``.

    ``installation_id`` and ``seen_at`` are caller-supplied rather than
    invented here -- this module never fabricates an installation scope
    or a timestamp the source record did not actually carry.

    Fields the old shape never carried get an explicitly conservative
    default, always labeled as migration-inferred in its own rationale
    text rather than presented as a real assessment:

    - ``dependency_analysis``: ``NOT_STARTED`` (no dependency data ever
      existed for this record; never claimed as "no dependencies").
    - ``risk``: ``MEDIUM``/non-reversible (a defensible middle ground --
      never assumed safe, never alarmist) with rollback unavailable.
    - ``disposition``: ``INVESTIGATE`` (always requires human review;
      never a specific committed action the old record never proposed
      in a structured, executable form).
    - ``generated_by``: ``MIGRATION`` (accurately describes how *this
      record* came to exist); the embedded evidence item's own
      provenance is separately recorded as ``LLM_ANALYSIS`` (accurately
      describing where the underlying *content* came from).
    """
    subject = SubjectIdentity(
        durable_id=value.recommendation_id,
        kind="hamie.migrated_ai_recommendation",
        source_instance=installation_id,
        source_id=value.recommendation_id,
        display_hint=f"Migrated recommendation {value.recommendation_id}",
    )
    evidence = RecommendationEvidence(
        evidence_type="ai_recommendation_summary",
        provenance=ProvenanceSource.LLM_ANALYSIS,
        source=f"{value.provider}:{value.model}",
        observed_value=_bounded(
            canonical_json(
                {
                    "recommendation_id": value.recommendation_id,
                    "finding_ids": list(value.finding_ids),
                    "group_ids": list(value.group_ids),
                    "source_revisions": [list(item) for item in value.source_revisions],
                }
            ),
            max_length=1_000,
        ),
        observed_at=value.created_at,
        collection_method="ai_advisory_pipeline",
        explanation=_bounded(value.summary, max_length=1_000),
        confidence="low",
    )
    dependency_analysis = DependencyAnalysisResult(
        status=DependencyAnalysisStatus.NOT_STARTED
    )
    risk = RecommendationRisk(
        risk=Risk(
            likelihood=RiskLevel.MEDIUM,
            impact=RiskLevel.MEDIUM,
            reversible=False,
            affected_scope="unknown_migrated_from_ai_recommendation",
            overall=RiskLevel.MEDIUM,
            rationale=(
                "Risk level defaulted to medium/non-reversible during migration "
                "from AIRecommendation, which carried no structured risk "
                "assessment. Original free-text risk_notes are preserved in "
                "the detailed explanation."
            ),
        ),
        estimated_operational_impact="unknown (not assessed by the original record)",
        estimated_user_visible_impact="unknown (not assessed by the original record)",
    )
    recommendation = build_recommendation(
        detector_id=MIGRATION_DETECTOR_ID,
        category=MIGRATION_CATEGORY,
        subtype=value.provider,
        title=f"Migrated AI recommendation ({value.provider}/{value.model})",
        summary=_bounded(value.summary, max_length=1_000),
        detailed_explanation=_build_detailed_explanation(value),
        installation_id=installation_id,
        affected_object=subject,
        evidence=(evidence,),
        dependency_analysis=dependency_analysis,
        risk=risk,
        confidence=_map_confidence(value.confidence),
        disposition=RecommendationDisposition.INVESTIGATE,
        suggested_action=(
            "Review the migrated recommendation manually; it predates "
            "HAMIE's structured remediation model and has no verified "
            "dependency analysis."
        ),
        generated_by=ProvenanceSource.MIGRATION,
        seen_at=seen_at,
        scan_id=f"migrated_from_{value.recommendation_id}",
    )
    lifecycle_state = (
        RecommendationLifecycleState.INVALIDATED
        if value.stale
        else RecommendationLifecycleState.ACTIVE
    )
    review_state = _REVIEW_STATE_MAP[value.review_state]
    return replace(
        recommendation,
        first_seen_at=value.created_at,
        last_seen_at=value.created_at,
        created_at=value.created_at,
        updated_at=value.created_at,
        lifecycle_state=lifecycle_state,
        review_state=review_state,
        llm_proposed_action=value.llm_proposed_action,
    )
