"""Explicit versioned JSON serialization for the Phase 2B remediation domain.

Mirrors ``domain/recommendation_serialization.py``'s conventions exactly
(the same ``_mapping``/``_sequence``/``_enum``/``_time``/``_parse_time``
shape, duplicated locally rather than importing another module's private
helpers).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from .findings import Confidence, ConfidenceFactor, ConfidenceLevel, Risk, RiskLevel
from .remediation import (
    BackupRequirement,
    DataLossRisk,
    IdempotencyClassification,
    RemediationActionStep,
    RemediationDependencySnapshot,
    RemediationPlan,
    RemediationPlanState,
    RemediationRiskAssessment,
    RemediationRollbackStep,
    RemediationVerificationSpec,
    RollbackPlan,
    RollbackSupportStatus,
)
from .remediation_approval import ApprovalRecord, ApprovalScope, ApprovalState
from .remediation_execution import (
    ExecutionLockRecord,
    ExecutionOutcome,
    ExecutionRecord,
    ExecutionReplayToken,
    RollbackOutcome,
    RollbackRecord,
    RollbackStepResult,
    StepExecutionResult,
    VerificationResult,
)
from .serialization import decode_subject, encode_subject

REMEDIATION_SERIALIZATION_VERSION = 1


def _time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _optional_time(value: datetime | None) -> str | None:
    return _time(value) if value is not None else None


def _parse_time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a timestamp string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError(f"{name} is not a valid timestamp") from err


def _parse_optional_time(value: object, name: str) -> datetime | None:
    return _parse_time(value, name) if value is not None else None


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object with string keys")
    return value


def _sequence(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _enum[T: Enum](enum_type: type[T], value: object, name: str) -> T:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{name} has an unsupported value") from err


def _strings(value: object, name: str) -> tuple[str, ...]:
    sequence = _sequence(value, name)
    if not all(isinstance(item, str) for item in sequence):
        raise ValueError(f"{name} must contain strings")
    return tuple(sequence)


def _string_pairs(value: object, name: str) -> tuple[tuple[str, str], ...]:
    sequence = _sequence(value, name)
    pairs: list[tuple[str, str]] = []
    for item in sequence:
        item_mapping = _mapping(item, f"{name} entry")
        key = item_mapping.get("key")
        pair_value = item_mapping.get("value")
        if not isinstance(key, str) or not isinstance(pair_value, str):
            raise ValueError(f"{name} entries must have string key/value")
        pairs.append((key, pair_value))
    return tuple(pairs)


def _encode_string_pairs(pairs: tuple[tuple[str, str], ...]) -> list[dict[str, str]]:
    return [{"key": key, "value": value} for key, value in pairs]


def _encode_risk(value: Risk) -> dict[str, Any]:
    return {
        "likelihood": value.likelihood.value,
        "impact": value.impact.value,
        "reversible": value.reversible,
        "affected_scope": value.affected_scope,
        "overall": value.overall.value,
        "rationale": value.rationale,
    }


def _decode_risk(raw: object) -> Risk:
    data = _mapping(raw, "risk")
    return Risk(
        likelihood=_enum(RiskLevel, data["likelihood"], "risk.likelihood"),
        impact=_enum(RiskLevel, data["impact"], "risk.impact"),
        reversible=data["reversible"],
        affected_scope=data["affected_scope"],
        overall=_enum(RiskLevel, data["overall"], "risk.overall"),
        rationale=data["rationale"],
    )


def _encode_confidence(value: Confidence) -> dict[str, Any]:
    return {
        "level": value.level.value,
        "rule_revision": value.rule_revision,
        "factors": [
            {"code": item.code, "effect": item.effect, "rationale": item.rationale}
            for item in value.factors
        ],
    }


def _decode_confidence(raw: object) -> Confidence:
    data = _mapping(raw, "confidence")
    factors = tuple(
        ConfidenceFactor(
            code=item["code"], effect=item["effect"], rationale=item["rationale"]
        )
        for item in (
            _mapping(raw_item, "confidence.factor")
            for raw_item in _sequence(data["factors"], "confidence.factors")
        )
    )
    return Confidence(
        level=_enum(ConfidenceLevel, data["level"], "confidence.level"),
        factors=factors,
        rule_revision=data["rule_revision"],
    )


def encode_verification_spec(value: RemediationVerificationSpec) -> dict[str, Any]:
    return {
        "method": value.method,
        "expected_outcome_description": value.expected_outcome_description,
        "checks_before_state": value.checks_before_state,
    }


def decode_verification_spec(raw: object) -> RemediationVerificationSpec:
    data = _mapping(raw, "verification_spec")
    return RemediationVerificationSpec(
        method=data["method"],
        expected_outcome_description=data["expected_outcome_description"],
        checks_before_state=data.get("checks_before_state", True),
    )


def encode_rollback_step(value: RemediationRollbackStep) -> dict[str, Any]:
    return {
        "reverses_step_index": value.reverses_step_index,
        "action_type": value.action_type,
        "adapter_id": value.adapter_id,
        "parameters": _encode_string_pairs(value.parameters),
        "verification_description": value.verification_description,
    }


def decode_rollback_step(raw: object) -> RemediationRollbackStep:
    data = _mapping(raw, "rollback_step")
    return RemediationRollbackStep(
        reverses_step_index=data["reverses_step_index"],
        action_type=data["action_type"],
        adapter_id=data["adapter_id"],
        parameters=_string_pairs(
            data.get("parameters", []), "rollback_step.parameters"
        ),
        verification_description=data["verification_description"],
    )


def encode_action_step(value: RemediationActionStep) -> dict[str, Any]:
    return {
        "step_index": value.step_index,
        "action_type": value.action_type,
        "action_version": value.action_version,
        "target": encode_subject(value.target),
        "adapter_id": value.adapter_id,
        "adapter_version": value.adapter_version,
        "parameters": _encode_string_pairs(value.parameters),
        "expected_change_description": value.expected_change_description,
        "destructive": value.destructive,
        "idempotency": value.idempotency.value,
        "reversible": value.reversible,
        "verification": encode_verification_spec(value.verification),
        "required_backup": value.required_backup.value,
        "rollback_step": (
            encode_rollback_step(value.rollback_step) if value.rollback_step else None
        ),
        "timeout_seconds": value.timeout_seconds,
        "max_attempts": value.max_attempts,
        "required_privileges": list(value.required_privileges),
    }


def decode_action_step(raw: object) -> RemediationActionStep:
    data = _mapping(raw, "action_step")
    rollback_raw = data.get("rollback_step")
    return RemediationActionStep(
        step_index=data["step_index"],
        action_type=data["action_type"],
        action_version=data["action_version"],
        target=decode_subject(data["target"]),
        adapter_id=data["adapter_id"],
        adapter_version=data["adapter_version"],
        parameters=_string_pairs(data.get("parameters", []), "action_step.parameters"),
        expected_change_description=data["expected_change_description"],
        destructive=data["destructive"],
        idempotency=_enum(
            IdempotencyClassification, data["idempotency"], "action_step.idempotency"
        ),
        reversible=data["reversible"],
        verification=decode_verification_spec(data["verification"]),
        required_backup=_enum(
            BackupRequirement, data["required_backup"], "action_step.required_backup"
        ),
        rollback_step=decode_rollback_step(rollback_raw) if rollback_raw else None,
        timeout_seconds=data.get("timeout_seconds", 30),
        max_attempts=data.get("max_attempts", 1),
        required_privileges=_strings(
            data.get("required_privileges", []), "required_privileges"
        ),
    )


def encode_rollback_plan(value: RollbackPlan) -> dict[str, Any]:
    return {
        "supported": value.supported,
        "steps": [encode_rollback_step(item) for item in value.steps],
        "required_data_tokens": list(value.required_data_tokens),
        "risk": value.risk.value,
        "preconditions": list(value.preconditions),
        "verification": value.verification,
        "limitations": list(value.limitations),
        "expires_at": _optional_time(value.expires_at),
    }


def decode_rollback_plan(raw: object) -> RollbackPlan:
    data = _mapping(raw, "rollback_plan")
    return RollbackPlan(
        supported=data["supported"],
        steps=tuple(
            decode_rollback_step(item)
            for item in _sequence(data.get("steps", []), "rollback_plan.steps")
        ),
        required_data_tokens=_strings(
            data.get("required_data_tokens", []), "required_data_tokens"
        ),
        risk=_enum(RiskLevel, data.get("risk", "low"), "rollback_plan.risk"),
        preconditions=_strings(data.get("preconditions", []), "preconditions"),
        verification=data.get("verification", "no rollback verification defined"),
        limitations=_strings(data.get("limitations", []), "limitations"),
        expires_at=_parse_optional_time(
            data.get("expires_at"), "rollback_plan.expires_at"
        ),
    )


def encode_dependency_snapshot(value: RemediationDependencySnapshot) -> dict[str, Any]:
    return {
        "dependency_digest": value.dependency_digest,
        "evidence_digest": value.evidence_digest,
        "sources_checked": list(value.sources_checked),
        "unavailable_sources": list(value.unavailable_sources),
        "unresolved_dependencies": list(value.unresolved_dependencies),
        "blocking_dependencies": list(value.blocking_dependencies),
        "preconditions": list(value.preconditions),
        "assumptions": list(value.assumptions),
        "warnings": list(value.warnings),
    }


def decode_dependency_snapshot(raw: object) -> RemediationDependencySnapshot:
    data = _mapping(raw, "dependency_snapshot")
    return RemediationDependencySnapshot(
        dependency_digest=data["dependency_digest"],
        evidence_digest=data["evidence_digest"],
        sources_checked=_strings(data.get("sources_checked", []), "sources_checked"),
        unavailable_sources=_strings(
            data.get("unavailable_sources", []), "unavailable_sources"
        ),
        unresolved_dependencies=_strings(
            data.get("unresolved_dependencies", []), "unresolved_dependencies"
        ),
        blocking_dependencies=_strings(
            data.get("blocking_dependencies", []), "blocking_dependencies"
        ),
        preconditions=_strings(data.get("preconditions", []), "preconditions"),
        assumptions=_strings(data.get("assumptions", []), "assumptions"),
        warnings=_strings(data.get("warnings", []), "warnings"),
    )


def encode_risk_assessment(value: RemediationRiskAssessment) -> dict[str, Any]:
    return {
        "risk": _encode_risk(value.risk),
        "destructive": value.destructive,
        "reversible": value.reversible,
        "rollback_support": value.rollback_support.value,
        "expected_user_visible_impact": value.expected_user_visible_impact,
        "expected_service_interruption": value.expected_service_interruption,
        "expected_data_loss_risk": value.expected_data_loss_risk.value,
        "confidence": _encode_confidence(value.confidence),
        "risk_rationale": value.risk_rationale,
    }


def decode_risk_assessment(raw: object) -> RemediationRiskAssessment:
    data = _mapping(raw, "risk_assessment")
    return RemediationRiskAssessment(
        risk=_decode_risk(data["risk"]),
        destructive=data["destructive"],
        reversible=data["reversible"],
        rollback_support=_enum(
            RollbackSupportStatus,
            data["rollback_support"],
            "risk_assessment.rollback_support",
        ),
        expected_user_visible_impact=data["expected_user_visible_impact"],
        expected_service_interruption=data["expected_service_interruption"],
        expected_data_loss_risk=_enum(
            DataLossRisk,
            data["expected_data_loss_risk"],
            "risk_assessment.expected_data_loss_risk",
        ),
        confidence=_decode_confidence(data["confidence"]),
        risk_rationale=data["risk_rationale"],
    )


def encode_remediation_plan(value: RemediationPlan) -> dict[str, Any]:
    """Encode one canonical remediation plan for durable storage."""
    return {
        "remediation_plan_id": value.remediation_plan_id,
        "plan_fingerprint": value.plan_fingerprint,
        "fingerprint_version": value.fingerprint_version,
        "schema_version": value.schema_version,
        "recommendation_id": value.recommendation_id,
        "recommendation_fingerprint": value.recommendation_fingerprint,
        "recommendation_revision": value.recommendation_revision,
        "installation_id": value.installation_id,
        "created_at": _time(value.created_at),
        "created_by": value.created_by,
        "planner_version": value.planner_version,
        "state": value.state.value,
        "actions": [encode_action_step(item) for item in value.actions],
        "dependency_snapshot": encode_dependency_snapshot(value.dependency_snapshot),
        "risk": encode_risk_assessment(value.risk),
        "rollback_plan": encode_rollback_plan(value.rollback_plan),
        "execution_supported": value.execution_supported,
        "unsupported_reason": value.unsupported_reason,
        "expires_at": _optional_time(value.expires_at),
        "requires_backup": value.requires_backup,
        "requires_manual_confirmation": value.requires_manual_confirmation,
        "approval_scope": value.approval_scope,
        "batch_compatible": value.batch_compatible,
        "preview_digest": value.preview_digest,
        "updated_at": _optional_time(value.updated_at),
        "snoozed_at": _optional_time(value.snoozed_at),
        "snoozed_by": value.snoozed_by,
        "snooze_until": _optional_time(value.snooze_until),
        "snooze_reason": value.snooze_reason,
        "snoozed_from_state": (
            value.snoozed_from_state.value if value.snoozed_from_state else None
        ),
    }


def decode_remediation_plan(raw: object) -> RemediationPlan:
    """Decode and validate one durable canonical remediation plan."""
    data = _mapping(raw, "remediation_plan")
    return RemediationPlan(
        remediation_plan_id=data["remediation_plan_id"],
        plan_fingerprint=data["plan_fingerprint"],
        fingerprint_version=data["fingerprint_version"],
        schema_version=data["schema_version"],
        recommendation_id=data["recommendation_id"],
        recommendation_fingerprint=data["recommendation_fingerprint"],
        recommendation_revision=data["recommendation_revision"],
        installation_id=data["installation_id"],
        created_at=_parse_time(data["created_at"], "created_at"),
        created_by=data["created_by"],
        planner_version=data["planner_version"],
        state=_enum(RemediationPlanState, data["state"], "remediation_plan.state"),
        actions=tuple(
            decode_action_step(item)
            for item in _sequence(data["actions"], "remediation_plan.actions")
        ),
        dependency_snapshot=decode_dependency_snapshot(data["dependency_snapshot"]),
        risk=decode_risk_assessment(data["risk"]),
        rollback_plan=decode_rollback_plan(data["rollback_plan"]),
        execution_supported=data["execution_supported"],
        unsupported_reason=data.get("unsupported_reason"),
        expires_at=_parse_optional_time(data.get("expires_at"), "expires_at"),
        requires_backup=data.get("requires_backup", False),
        requires_manual_confirmation=data.get("requires_manual_confirmation", True),
        approval_scope=data.get("approval_scope", "single"),
        batch_compatible=data.get("batch_compatible", False),
        preview_digest=data.get("preview_digest"),
        updated_at=_parse_optional_time(data.get("updated_at"), "updated_at"),
        snoozed_at=_parse_optional_time(data.get("snoozed_at"), "snoozed_at"),
        snoozed_by=data.get("snoozed_by"),
        snooze_until=_parse_optional_time(data.get("snooze_until"), "snooze_until"),
        snooze_reason=data.get("snooze_reason"),
        snoozed_from_state=(
            _enum(
                RemediationPlanState,
                data["snoozed_from_state"],
                "remediation_plan.snoozed_from_state",
            )
            if data.get("snoozed_from_state") is not None
            else None
        ),
    )


def encode_approval(value: ApprovalRecord) -> dict[str, Any]:
    return {
        "approval_id": value.approval_id,
        "remediation_plan_id": value.remediation_plan_id,
        "plan_fingerprint": value.plan_fingerprint,
        "preview_digest": value.preview_digest,
        "recommendation_id": value.recommendation_id,
        "recommendation_revision": value.recommendation_revision,
        "installation_id": value.installation_id,
        "approved_by": value.approved_by,
        "decided_at": _time(value.decided_at),
        "state": value.state.value,
        "expires_at": _optional_time(value.expires_at),
        "scope": value.scope.value,
        "batch_id": value.batch_id,
        "destructive_acknowledged": value.destructive_acknowledged,
        "backup_acknowledged": value.backup_acknowledged,
        "warnings_acknowledged": list(value.warnings_acknowledged),
        "rejection_reason": value.rejection_reason,
        "revoked_at": _optional_time(value.revoked_at),
        "revoked_by": value.revoked_by,
        "revocation_reason": value.revocation_reason,
    }


def decode_approval(raw: object) -> ApprovalRecord:
    data = _mapping(raw, "approval")
    return ApprovalRecord(
        approval_id=data["approval_id"],
        remediation_plan_id=data["remediation_plan_id"],
        plan_fingerprint=data["plan_fingerprint"],
        preview_digest=data["preview_digest"],
        recommendation_id=data["recommendation_id"],
        recommendation_revision=data["recommendation_revision"],
        installation_id=data["installation_id"],
        approved_by=data["approved_by"],
        decided_at=_parse_time(data["decided_at"], "decided_at"),
        state=_enum(ApprovalState, data["state"], "approval.state"),
        expires_at=_parse_optional_time(data.get("expires_at"), "expires_at"),
        scope=_enum(ApprovalScope, data.get("scope", "single"), "approval.scope"),
        batch_id=data.get("batch_id"),
        destructive_acknowledged=data.get("destructive_acknowledged", False),
        backup_acknowledged=data.get("backup_acknowledged", False),
        warnings_acknowledged=_strings(
            data.get("warnings_acknowledged", []), "warnings_acknowledged"
        ),
        rejection_reason=data.get("rejection_reason"),
        revoked_at=_parse_optional_time(data.get("revoked_at"), "revoked_at"),
        revoked_by=data.get("revoked_by"),
        revocation_reason=data.get("revocation_reason"),
    )


def encode_step_execution_result(value: StepExecutionResult) -> dict[str, Any]:
    return {
        "step_index": value.step_index,
        "adapter_id": value.adapter_id,
        "adapter_version": value.adapter_version,
        "attempt": value.attempt,
        "mutation_occurred": value.mutation_occurred,
        "succeeded": value.succeeded,
        "idempotency_key": value.idempotency_key,
        "started_at": _time(value.started_at),
        "completed_at": _time(value.completed_at),
        "observed_before_state": value.observed_before_state,
        "observed_after_state": value.observed_after_state,
        "rollback_token": value.rollback_token,
        "error": value.error,
    }


def decode_step_execution_result(raw: object) -> StepExecutionResult:
    data = _mapping(raw, "step_execution_result")
    return StepExecutionResult(
        step_index=data["step_index"],
        adapter_id=data["adapter_id"],
        adapter_version=data["adapter_version"],
        attempt=data["attempt"],
        mutation_occurred=data["mutation_occurred"],
        succeeded=data["succeeded"],
        idempotency_key=data["idempotency_key"],
        started_at=_parse_time(data["started_at"], "started_at"),
        completed_at=_parse_time(data["completed_at"], "completed_at"),
        observed_before_state=data.get("observed_before_state"),
        observed_after_state=data.get("observed_after_state"),
        rollback_token=data.get("rollback_token"),
        error=data.get("error"),
    )


def encode_verification_result(value: VerificationResult) -> dict[str, Any]:
    return {
        "step_index": value.step_index,
        "method": value.method,
        "expected_result": value.expected_result,
        "observed_result": value.observed_result,
        "succeeded": value.succeeded,
        "confidence": value.confidence,
        "checked_at": _time(value.checked_at),
        "incomplete_checks": list(value.incomplete_checks),
        "errors": list(value.errors),
        "user_visible_impact": value.user_visible_impact,
        "rollback_recommended": value.rollback_recommended,
    }


def decode_verification_result(raw: object) -> VerificationResult:
    data = _mapping(raw, "verification_result")
    return VerificationResult(
        step_index=data["step_index"],
        method=data["method"],
        expected_result=data["expected_result"],
        observed_result=data["observed_result"],
        succeeded=data["succeeded"],
        confidence=data["confidence"],
        checked_at=_parse_time(data["checked_at"], "checked_at"),
        incomplete_checks=_strings(
            data.get("incomplete_checks", []), "incomplete_checks"
        ),
        errors=_strings(data.get("errors", []), "errors"),
        user_visible_impact=data.get("user_visible_impact", "unknown"),
        rollback_recommended=data.get("rollback_recommended", False),
    )


def encode_execution_record(value: ExecutionRecord) -> dict[str, Any]:
    return {
        "execution_id": value.execution_id,
        "remediation_plan_id": value.remediation_plan_id,
        "plan_fingerprint": value.plan_fingerprint,
        "approval_id": value.approval_id,
        "installation_id": value.installation_id,
        "started_at": _time(value.started_at),
        "started_by": value.started_by,
        "idempotency_token": value.idempotency_token,
        "outcome": value.outcome.value,
        "step_results": [
            encode_step_execution_result(item) for item in value.step_results
        ],
        "verification_results": [
            encode_verification_result(item) for item in value.verification_results
        ],
        "completed_at": _optional_time(value.completed_at),
        "error": value.error,
    }


def decode_execution_record(raw: object) -> ExecutionRecord:
    data = _mapping(raw, "execution_record")
    return ExecutionRecord(
        execution_id=data["execution_id"],
        remediation_plan_id=data["remediation_plan_id"],
        plan_fingerprint=data["plan_fingerprint"],
        approval_id=data["approval_id"],
        installation_id=data["installation_id"],
        started_at=_parse_time(data["started_at"], "started_at"),
        started_by=data["started_by"],
        idempotency_token=data["idempotency_token"],
        outcome=_enum(ExecutionOutcome, data["outcome"], "execution_record.outcome"),
        step_results=tuple(
            decode_step_execution_result(item)
            for item in _sequence(
                data.get("step_results", []), "execution_record.step_results"
            )
        ),
        verification_results=tuple(
            decode_verification_result(item)
            for item in _sequence(
                data.get("verification_results", []),
                "execution_record.verification_results",
            )
        ),
        completed_at=_parse_optional_time(data.get("completed_at"), "completed_at"),
        error=data.get("error"),
    )


def encode_rollback_step_result(value: RollbackStepResult) -> dict[str, Any]:
    return {
        "reverses_step_index": value.reverses_step_index,
        "adapter_id": value.adapter_id,
        "succeeded": value.succeeded,
        "completed_at": _time(value.completed_at),
        "observed_state_after_rollback": value.observed_state_after_rollback,
        "error": value.error,
    }


def decode_rollback_step_result(raw: object) -> RollbackStepResult:
    data = _mapping(raw, "rollback_step_result")
    return RollbackStepResult(
        reverses_step_index=data["reverses_step_index"],
        adapter_id=data["adapter_id"],
        succeeded=data["succeeded"],
        completed_at=_parse_time(data["completed_at"], "completed_at"),
        observed_state_after_rollback=data.get("observed_state_after_rollback"),
        error=data.get("error"),
    )


def encode_rollback_record(value: RollbackRecord) -> dict[str, Any]:
    return {
        "rollback_id": value.rollback_id,
        "execution_id": value.execution_id,
        "remediation_plan_id": value.remediation_plan_id,
        "initiated_at": _time(value.initiated_at),
        "initiated_by": value.initiated_by,
        "reason": value.reason,
        "outcome": value.outcome.value,
        "step_results": [
            encode_rollback_step_result(item) for item in value.step_results
        ],
        "completed_at": _optional_time(value.completed_at),
    }


def decode_rollback_record(raw: object) -> RollbackRecord:
    data = _mapping(raw, "rollback_record")
    return RollbackRecord(
        rollback_id=data["rollback_id"],
        execution_id=data["execution_id"],
        remediation_plan_id=data["remediation_plan_id"],
        initiated_at=_parse_time(data["initiated_at"], "initiated_at"),
        initiated_by=data["initiated_by"],
        reason=data["reason"],
        outcome=_enum(RollbackOutcome, data["outcome"], "rollback_record.outcome"),
        step_results=tuple(
            decode_rollback_step_result(item)
            for item in _sequence(
                data.get("step_results", []), "rollback_record.step_results"
            )
        ),
        completed_at=_parse_optional_time(data.get("completed_at"), "completed_at"),
    )


def encode_execution_lock(value: ExecutionLockRecord) -> dict[str, Any]:
    return {
        "lock_id": value.lock_id,
        "remediation_plan_id": value.remediation_plan_id,
        "target_identity_key": value.target_identity_key,
        "owner_execution_id": value.owner_execution_id,
        "acquired_at": _time(value.acquired_at),
        "expires_at": _time(value.expires_at),
        "released_at": _optional_time(value.released_at),
        "release_reason": value.release_reason,
    }


def decode_execution_lock(raw: object) -> ExecutionLockRecord:
    data = _mapping(raw, "execution_lock")
    return ExecutionLockRecord(
        lock_id=data["lock_id"],
        remediation_plan_id=data["remediation_plan_id"],
        target_identity_key=data["target_identity_key"],
        owner_execution_id=data["owner_execution_id"],
        acquired_at=_parse_time(data["acquired_at"], "acquired_at"),
        expires_at=_parse_time(data["expires_at"], "expires_at"),
        released_at=_parse_optional_time(data.get("released_at"), "released_at"),
        release_reason=data.get("release_reason"),
    )


def encode_replay_token(value: ExecutionReplayToken) -> dict[str, Any]:
    return {
        "token": value.token,
        "remediation_plan_id": value.remediation_plan_id,
        "plan_fingerprint": value.plan_fingerprint,
        "execution_id": value.execution_id,
    }


def decode_replay_token(raw: object) -> ExecutionReplayToken:
    data = _mapping(raw, "replay_token")
    return ExecutionReplayToken(
        token=data["token"],
        remediation_plan_id=data["remediation_plan_id"],
        plan_fingerprint=data["plan_fingerprint"],
        execution_id=data["execution_id"],
    )
