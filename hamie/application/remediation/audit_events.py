"""Remediation audit event name constants (HAMIE Phase 2B).

``AuditRecord.event`` (``domain/intelligence.py``) is deliberately a
free-form string, not a closed enum -- the existing convention
throughout HAMIE (see ``operations_service.py``'s ``group_{action}``,
``suppression_rule_created``, etc.). These constants exist only so every
Phase 2B call site spells the same event the same way; they are not a
new enum type and ``AuditRecord`` itself is unchanged.
"""

from __future__ import annotations

PLAN_CREATED = "remediation_plan_created"
PLAN_INVALIDATED = "remediation_plan_invalidated"
PREVIEW_GENERATED = "remediation_preview_generated"
PROPOSAL_SNOOZED = "remediation_proposal_snoozed"
PROPOSAL_RESUMED = "remediation_proposal_resumed"
PROPOSAL_SNOOZE_EXPIRED = "remediation_proposal_snooze_expired"

APPROVAL_GRANTED = "remediation_approval_granted"
APPROVAL_REJECTED = "remediation_approval_rejected"
APPROVAL_REVOKED = "remediation_approval_revoked"
APPROVAL_EXPIRED = "remediation_approval_expired"

BACKUP_VERIFIED = "remediation_backup_verified"
BACKUP_UNAVAILABLE = "remediation_backup_unavailable"

EXECUTION_BLOCKED = "remediation_execution_blocked"
EXECUTION_STARTED = "remediation_execution_started"
EXECUTION_SUCCEEDED = "remediation_execution_succeeded"
EXECUTION_PARTIALLY_SUCCEEDED = "remediation_execution_partially_succeeded"
EXECUTION_FAILED = "remediation_execution_failed"

ACTION_STARTED = "remediation_action_started"
ACTION_SUCCEEDED = "remediation_action_succeeded"
ACTION_FAILED = "remediation_action_failed"

VERIFICATION_SUCCEEDED = "remediation_verification_succeeded"
VERIFICATION_FAILED = "remediation_verification_failed"

ROLLBACK_STARTED = "remediation_rollback_started"
ROLLBACK_SUCCEEDED = "remediation_rollback_succeeded"
ROLLBACK_FAILED = "remediation_rollback_failed"

LOCK_ACQUIRED = "remediation_lock_acquired"
LOCK_RELEASED = "remediation_lock_released"
REPLAY_BLOCKED = "remediation_replay_blocked"

BATCH_STARTED = "remediation_batch_started"
BATCH_COMPLETED = "remediation_batch_completed"

LLM_PROPOSAL_ACCEPTED = "remediation_llm_proposal_accepted"
LLM_PROPOSAL_REJECTED = "remediation_llm_proposal_rejected"

# Post-repair lifecycle (application/remediation_lifecycle.py). Same
# convention as above: constants, not a new enum, so every stage of one
# run spells its event identically and `hamie/audit/list` filtered by the
# plan identity reconstructs the whole lifecycle.
PLAN_DRIFT_BLOCKED = "remediation_plan_drift_blocked"
CONFIG_VALIDATED = "remediation_config_validated"
RUNTIME_VALIDATED = "remediation_runtime_validated"
INVARIANTS_REVERIFIED = "remediation_invariants_reverified"
RESCAN_COMPLETED = "remediation_rescan_completed"
FINDING_RECONCILED = "remediation_finding_reconciled"
INCIDENT_RECONCILED = "remediation_incident_reconciled"
REGRESSION_DETECTED = "remediation_regression_detected"
OUTCOME_RECORDED = "remediation_outcome_recorded"
