"""Durable baselines: what HAMIE must still know after a restart.

Two defects, both measured on the live installation rather than assumed:

* after a restart the Recommendations state reported `analyzed_total: 0`,
  `analyzed_scan_id: None` and `groups_analyzed: 0` while 18 recommendations
  sat persisted in the store. Coverage lived only in memory, so HAMIE held
  the *conclusions* of an analysis and none of the evidence that it had run.
* the remediation lifecycle reported `baseline_available: false` after a
  restart between mutation and reconciliation, so a repair could no longer
  be compared against the world as it stood before the repair.

Both are the same mistake: state that materially changes what HAMIE claims,
kept somewhere a reboot erases. Computers remain committed to rebooting at
inconvenient times.

What is deliberately NOT persisted: anything reconstructable from the next
scan. Findings, incidents and groups are already durable and are rebuilt
deterministically; copying them into a baseline would double the store to
answer a question the store already answers. A baseline holds identities and
counts -- enough to perform a deterministic comparison, not a second copy of
Home Assistant.

Pure and I/O-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from .common import canonical_json, stable_digest

BASELINE_SCHEMA_VERSION = 1

#: Identity bounds. Large enough to reconcile a real installation, small
#: enough that the store does not become a log file.
MAX_BASELINE_FINDING_IDS = 2_000
MAX_BASELINE_INCIDENT_IDS = 1_000
MAX_BASELINE_GROUP_IDS = 500

#: How many completed remediation baselines to retain. Unfinished ones are
#: never pruned -- see prune_remediation_baselines.
MAX_RETAINED_REMEDIATION_BASELINES = 25


class BaselineStatus(StrEnum):
    """Why a baseline is or is not usable. Never collapsed into a bool.

    "corrupt" and "absent" must stay distinguishable: silently treating an
    unreadable baseline as "none was ever captured" is how a restart turns a
    storage fault into an apparently clean slate.
    """

    ABSENT = "absent"
    LOADED = "loaded"
    CORRUPT = "corrupt"
    INCOMPATIBLE = "incompatible"
    FOREIGN_PLAN = "foreign_plan"
    STALE = "stale"


def _bounded(values: tuple[str, ...] | list[str], limit: int) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values))[:limit]


@dataclass(frozen=True, slots=True)
class AnalysisBaseline:
    """What one completed analysis covered, durably.

    `truncated` is explicit: an installation with more findings than
    MAX_BASELINE_FINDING_IDS still gets a usable baseline, and callers can
    see that the identity list is a sample rather than silently reasoning
    over a partial set as if it were complete.
    """

    schema_version: int
    created_at: datetime
    updated_at: datetime
    scan_id: str
    eligible_total: int
    analyzed_finding_ids: tuple[str, ...]
    analyzed_group_ids: tuple[str, ...]
    failed_group_ids: tuple[str, ...] = ()
    recommendation_ids: tuple[str, ...] = ()
    truncated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "analyzed_finding_ids",
            _bounded(self.analyzed_finding_ids, MAX_BASELINE_FINDING_IDS),
        )
        object.__setattr__(
            self, "analyzed_group_ids",
            _bounded(self.analyzed_group_ids, MAX_BASELINE_GROUP_IDS),
        )
        object.__setattr__(
            self, "failed_group_ids",
            _bounded(self.failed_group_ids, MAX_BASELINE_GROUP_IDS),
        )
        object.__setattr__(
            self, "recommendation_ids",
            _bounded(self.recommendation_ids, MAX_BASELINE_GROUP_IDS),
        )

    @property
    def analyzed_total(self) -> int:
        return len(self.analyzed_finding_ids)

    @property
    def digest(self) -> str:
        """Identity of what this baseline asserts was covered."""
        return stable_digest(
            canonical_json(
                {
                    "scan_id": self.scan_id,
                    "findings": sorted(self.analyzed_finding_ids),
                    "groups": sorted(self.analyzed_group_ids),
                }
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "scan_id": self.scan_id,
            "eligible_total": self.eligible_total,
            "analyzed_total": self.analyzed_total,
            "analyzed_group_ids": list(self.analyzed_group_ids),
            "failed_group_ids": list(self.failed_group_ids),
            "recommendation_ids": list(self.recommendation_ids),
            "truncated": self.truncated,
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class RemediationBaseline:
    """The world as it stood immediately before one approved repair.

    Bound to BOTH the plan identity and the incident, so a baseline can never
    be applied to a different repair. Reusing one across plans would compare a
    repair against a world it never ran in, which is worse than having no
    baseline at all -- it produces a confident, wrong regression verdict.
    """

    schema_version: int
    plan_identity: str
    incident_id: str
    captured_at: datetime
    pre_repair_scan_id: str | None
    active_incident_ids: tuple[str, ...]
    incident_finding_ids: tuple[str, ...]
    unavailable_counts: tuple[tuple[str, int], ...] = ()
    scope_entity_ids: tuple[str, ...] = ()
    stage: str = "captured"
    complete: bool = False

    # --- recovery truth -------------------------------------------------
    # Enough to reconcile an interrupted repair from CURRENT state, without
    # ever trusting the stage field alone. Every boolean below records that
    # a step was *attempted*; whether it took effect is decided after
    # restart by re-hashing the real files.
    approval_id: str = ""
    approved_by: str = ""
    risk: str = ""
    protection_verdict: str = ""
    transaction_id: str = ""
    #: (path, pre_hash, expected_post_hash). The two hashes are what makes
    #: "did the write land?" answerable without replaying anything.
    file_states: tuple[tuple[str, str, str], ...] = ()
    backup_paths: tuple[str, ...] = ()
    backup_complete: bool = False
    write_began: bool = False
    write_complete: bool = False
    validation_began: bool = False
    validation_complete: bool = False
    validation_passed: bool | None = None
    rollback_began: bool = False
    rollback_complete: bool = False
    rollback_verified: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "active_incident_ids",
            _bounded(self.active_incident_ids, MAX_BASELINE_INCIDENT_IDS),
        )
        object.__setattr__(
            self, "incident_finding_ids",
            _bounded(self.incident_finding_ids, MAX_BASELINE_FINDING_IDS),
        )
        object.__setattr__(
            self, "scope_entity_ids",
            _bounded(self.scope_entity_ids, MAX_BASELINE_FINDING_IDS),
        )
        object.__setattr__(
            self, "unavailable_counts", tuple(sorted(self.unavailable_counts))
        )
        object.__setattr__(
            self,
            "file_states",
            tuple(sorted((str(a), str(b), str(c)) for a, b, c in self.file_states)),
        )
        object.__setattr__(self, "backup_paths", tuple(sorted(set(self.backup_paths))))

    def matches(self, *, plan_identity: str, incident_id: str) -> bool:
        return self.plan_identity == plan_identity and self.incident_id == incident_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_identity": self.plan_identity,
            "incident_id": self.incident_id,
            "captured_at": self.captured_at.isoformat(),
            "pre_repair_scan_id": self.pre_repair_scan_id,
            "active_incident_count": len(self.active_incident_ids),
            "incident_finding_count": len(self.incident_finding_ids),
            "unavailable_counts": dict(self.unavailable_counts),
            "scope_entity_count": len(self.scope_entity_ids),
            "stage": self.stage,
            "complete": self.complete,
            "approval_id": self.approval_id,
            "approved_by": self.approved_by,
            "risk": self.risk,
            "protection_verdict": self.protection_verdict,
            "transaction_id": self.transaction_id,
            "file_count": len(self.file_states),
            "backup_complete": self.backup_complete,
            "write_began": self.write_began,
            "write_complete": self.write_complete,
            "validation_began": self.validation_began,
            "validation_complete": self.validation_complete,
            "validation_passed": self.validation_passed,
            "rollback_began": self.rollback_began,
            "rollback_complete": self.rollback_complete,
            "rollback_verified": self.rollback_verified,
        }


@dataclass(frozen=True, slots=True)
class BaselineLoad:
    """The outcome of trying to use a persisted baseline."""

    status: BaselineStatus
    baseline: Any = None
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.status is BaselineStatus.LOADED and self.baseline is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "usable": self.usable,
            "detail": self.detail,
            "baseline": self.baseline.as_dict() if self.baseline is not None else None,
        }


def load_remediation_baseline(
    baselines: tuple[RemediationBaseline, ...],
    *,
    plan_identity: str,
    incident_id: str,
) -> BaselineLoad:
    """Find the baseline for exactly this repair, or explain why there is none."""
    exact = next(
        (b for b in baselines if b.matches(plan_identity=plan_identity, incident_id=incident_id)),
        None,
    )
    if exact is not None:
        if exact.schema_version != BASELINE_SCHEMA_VERSION:
            return BaselineLoad(
                BaselineStatus.INCOMPATIBLE,
                detail=f"baseline schema {exact.schema_version} is not readable",
            )
        return BaselineLoad(BaselineStatus.LOADED, exact, "baseline recovered")

    same_plan = next((b for b in baselines if b.plan_identity == plan_identity), None)
    if same_plan is not None:
        return BaselineLoad(
            BaselineStatus.FOREIGN_PLAN,
            detail=(
                "a baseline exists for this plan identity but a different "
                "incident; it will not be reused"
            ),
        )
    return BaselineLoad(BaselineStatus.ABSENT, detail="no baseline was captured")


def prune_remediation_baselines(
    baselines: tuple[RemediationBaseline, ...],
    *,
    limit: int = MAX_RETAINED_REMEDIATION_BASELINES,
) -> tuple[RemediationBaseline, ...]:
    """Bound retention without ever discarding live remediation evidence.

    An incomplete baseline is the only record of the world before a repair
    that has not finished reconciling. Pruning one would leave the repair
    permanently unverifiable, so incomplete records are exempt from the limit
    entirely rather than merely sorted to the front.
    """
    incomplete = tuple(b for b in baselines if not b.complete)
    complete = tuple(
        sorted((b for b in baselines if b.complete), key=lambda b: b.captured_at, reverse=True)
    )
    keep = max(0, limit - len(incomplete))
    return (*incomplete, *complete[:keep])


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def encode_analysis_baseline(value: AnalysisBaseline | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "schema_version": value.schema_version,
        "created_at": value.created_at.isoformat(),
        "updated_at": value.updated_at.isoformat(),
        "scan_id": value.scan_id,
        "eligible_total": value.eligible_total,
        "analyzed_finding_ids": list(value.analyzed_finding_ids),
        "analyzed_group_ids": list(value.analyzed_group_ids),
        "failed_group_ids": list(value.failed_group_ids),
        "recommendation_ids": list(value.recommendation_ids),
        "truncated": value.truncated,
    }


def decode_analysis_baseline(raw: object) -> AnalysisBaseline | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("analysis baseline must be an object")
    try:
        return AnalysisBaseline(
            schema_version=int(raw["schema_version"]),
            created_at=datetime.fromisoformat(str(raw["created_at"])),
            updated_at=datetime.fromisoformat(str(raw["updated_at"])),
            scan_id=str(raw["scan_id"]),
            eligible_total=int(raw["eligible_total"]),
            analyzed_finding_ids=tuple(raw.get("analyzed_finding_ids") or ()),
            analyzed_group_ids=tuple(raw.get("analyzed_group_ids") or ()),
            failed_group_ids=tuple(raw.get("failed_group_ids") or ()),
            recommendation_ids=tuple(raw.get("recommendation_ids") or ()),
            truncated=bool(raw.get("truncated", False)),
        )
    except (KeyError, TypeError, ValueError) as err:
        raise ValueError(f"analysis baseline is unreadable: {err}") from err


def encode_remediation_baseline(value: RemediationBaseline) -> dict[str, Any]:
    return {
        "schema_version": value.schema_version,
        "plan_identity": value.plan_identity,
        "incident_id": value.incident_id,
        "captured_at": value.captured_at.isoformat(),
        "pre_repair_scan_id": value.pre_repair_scan_id,
        "active_incident_ids": list(value.active_incident_ids),
        "incident_finding_ids": list(value.incident_finding_ids),
        "unavailable_counts": [list(item) for item in value.unavailable_counts],
        "scope_entity_ids": list(value.scope_entity_ids),
        "stage": value.stage,
        "complete": value.complete,
        "approval_id": value.approval_id,
        "approved_by": value.approved_by,
        "risk": value.risk,
        "protection_verdict": value.protection_verdict,
        "transaction_id": value.transaction_id,
        "file_states": [list(item) for item in value.file_states],
        "backup_paths": list(value.backup_paths),
        "backup_complete": value.backup_complete,
        "write_began": value.write_began,
        "write_complete": value.write_complete,
        "validation_began": value.validation_began,
        "validation_complete": value.validation_complete,
        "validation_passed": value.validation_passed,
        "rollback_began": value.rollback_began,
        "rollback_complete": value.rollback_complete,
        "rollback_verified": value.rollback_verified,
    }


def decode_remediation_baseline(raw: object) -> RemediationBaseline:
    if not isinstance(raw, dict):
        raise ValueError("remediation baseline must be an object")
    try:
        return RemediationBaseline(
            schema_version=int(raw["schema_version"]),
            plan_identity=str(raw["plan_identity"]),
            incident_id=str(raw["incident_id"]),
            captured_at=datetime.fromisoformat(str(raw["captured_at"])),
            pre_repair_scan_id=(
                str(raw["pre_repair_scan_id"])
                if raw.get("pre_repair_scan_id") is not None
                else None
            ),
            active_incident_ids=tuple(raw.get("active_incident_ids") or ()),
            incident_finding_ids=tuple(raw.get("incident_finding_ids") or ()),
            unavailable_counts=tuple(
                (str(k), int(v)) for k, v in (raw.get("unavailable_counts") or ())
            ),
            scope_entity_ids=tuple(raw.get("scope_entity_ids") or ()),
            stage=str(raw.get("stage", "captured")),
            complete=bool(raw.get("complete", False)),
            approval_id=str(raw.get("approval_id", "")),
            approved_by=str(raw.get("approved_by", "")),
            risk=str(raw.get("risk", "")),
            protection_verdict=str(raw.get("protection_verdict", "")),
            transaction_id=str(raw.get("transaction_id", "")),
            file_states=tuple(
                (str(a), str(b), str(c)) for a, b, c in (raw.get("file_states") or ())
            ),
            backup_paths=tuple(str(x) for x in (raw.get("backup_paths") or ())),
            backup_complete=bool(raw.get("backup_complete", False)),
            write_began=bool(raw.get("write_began", False)),
            write_complete=bool(raw.get("write_complete", False)),
            validation_began=bool(raw.get("validation_began", False)),
            validation_complete=bool(raw.get("validation_complete", False)),
            validation_passed=raw.get("validation_passed"),
            rollback_began=bool(raw.get("rollback_began", False)),
            rollback_complete=bool(raw.get("rollback_complete", False)),
            rollback_verified=raw.get("rollback_verified"),
        )
    except (KeyError, TypeError, ValueError) as err:
        raise ValueError(f"remediation baseline is unreadable: {err}") from err


# ---------------------------------------------------------------------------
# Interrupted-remediation reconciliation
# ---------------------------------------------------------------------------


class RecoveryOutcome(StrEnum):
    """What a restart found, decided from CURRENT state.

    The persisted stage is a hint about what was *attempted*. It is never
    evidence about what happened: a process that died immediately after
    writing "write_began" may or may not have written anything, and the only
    way to know is to hash the files that exist now.
    """

    NOT_STARTED = "not_started"
    PRE_STATE_CONFIRMED = "pre_state_confirmed"
    BACKUP_CREATED = "backup_created"
    WRITE_APPLIED_UNVALIDATED = "write_applied_unvalidated"
    POST_STATE_CONFIRMED = "post_state_confirmed"
    VALIDATED_SUCCESS = "validated_success"
    ROLLBACK_REQUIRED = "rollback_required"
    ROLLED_BACK = "rolled_back"
    DIVERGED = "diverged"
    STALE_PLAN = "stale_plan"
    APPROVAL_INVALID = "approval_invalid"
    INCIDENT_NO_LONGER_PRESENT = "incident_no_longer_present"
    PROTECTED_EFFECT_CHANGED = "protected_effect_changed"
    RECOVERY_REQUIRED = "recovery_required"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    #: The transaction happened, and its ENTIRE target scope has since been
    #: deliberately removed and independently proven irrelevant. Distinct
    #: from DIVERGED (material still exists, changed unexpectedly, and could
    #: still be overwritten), from ROLLED_BACK (the pre-state was restored),
    #: from NOT_STARTED (a write was attempted) and from success (nothing was
    #: proven to work). Terminal: there is nothing left to repair, resume or
    #: roll back, because there is nothing left.
    MATERIAL_RETIRED = "material_retired"


#: Outcomes from which HAMIE may continue an approved repair without asking
#: again. Deliberately small: everything else needs a human or a fresh plan.
RESUMABLE_OUTCOMES = frozenset(
    {
        RecoveryOutcome.PRE_STATE_CONFIRMED,
        RecoveryOutcome.BACKUP_CREATED,
        RecoveryOutcome.WRITE_APPLIED_UNVALIDATED,
        RecoveryOutcome.POST_STATE_CONFIRMED,
    }
)

#: Outcomes where the mutation must NOT be applied again under any
#: circumstance, because it either already landed or must never land.
NO_MUTATION_OUTCOMES = frozenset(
    {
        # A repair awaiting rollback must certainly not re-apply itself.
        RecoveryOutcome.ROLLBACK_REQUIRED,
        RecoveryOutcome.POST_STATE_CONFIRMED,
        RecoveryOutcome.VALIDATED_SUCCESS,
        RecoveryOutcome.ROLLED_BACK,
        RecoveryOutcome.DIVERGED,
        RecoveryOutcome.STALE_PLAN,
        RecoveryOutcome.APPROVAL_INVALID,
        RecoveryOutcome.INCIDENT_NO_LONGER_PRESENT,
        RecoveryOutcome.PROTECTED_EFFECT_CHANGED,
        RecoveryOutcome.RECOVERY_REQUIRED,
        RecoveryOutcome.MANUAL_REVIEW_REQUIRED,
        RecoveryOutcome.MATERIAL_RETIRED,
    }
)


@dataclass(frozen=True, slots=True)
class RecoveryObservation:
    """What HAMIE can see right now, independent of what it remembered."""

    #: path -> sha256 of the file as it exists at this moment. A path absent
    #: from the mapping means the file could not be read.
    current_hashes: dict[str, str] = field(default_factory=dict)
    #: path -> whether its backup still exists on disk.
    backups_present: dict[str, bool] = field(default_factory=dict)
    #: Does current authoritative evidence still show the incident?
    incident_present: bool = True
    #: Plan identity re-derived from current state; None when underivable.
    current_plan_identity: str | None = None
    #: Protected-invariant verdict re-evaluated now.
    current_protection_verdict: str = ""
    #: Paths the reader POSITIVELY confirmed do not exist. Deliberately
    #: separate from "missing from current_hashes": a path is missing from
    #: that mapping both when it is genuinely gone and when it could not be
    #: read, and collapsing those two is how missing infrastructure
    #: masquerades as a domain fact.
    paths_confirmed_absent: frozenset[str] = frozenset()
    #: False when the filesystem reader itself was unavailable. Nothing may
    #: be retired on the strength of evidence that was never gathered.
    material_reader_available: bool = True
    #: Does ACTIVE configuration still reference this repair's material?
    material_referenced: bool = True
    #: Scan/observation identity proving this evidence is fresh. Empty means
    #: no freshness could be established.
    evidence_scan_id: str = ""


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    outcome: RecoveryOutcome
    reason: str
    may_resume: bool
    may_apply_mutation: bool
    matched_pre: tuple[str, ...] = ()
    matched_post: tuple[str, ...] = ()
    unmatched: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "reason": self.reason,
            "may_resume": self.may_resume,
            "may_apply_mutation": self.may_apply_mutation,
            "matched_pre": list(self.matched_pre),
            "matched_post": list(self.matched_post),
            "unmatched": list(self.unmatched),
        }


#: Outcomes after which nothing further is owed for this repair, so its
#: baseline may be retired. Everything NOT listed here -- POST_STATE_CONFIRMED,
#: ROLLBACK_REQUIRED, RECOVERY_REQUIRED, MANUAL_REVIEW_REQUIRED, DIVERGED,
#: APPROVAL_INVALID, PROTECTED_EFFECT_CHANGED, STALE_PLAN -- stays incomplete
#: on purpose: an operator still has to see it after the next restart.
#:
#: Without this, an interrupted repair was reclassified on every startup
#: forever and could never be pruned, because retention deliberately exempts
#: incomplete baselines. That is the same "incomplete is never retired" defect
#: that left successful repairs marked in-flight.
TERMINAL_RECOVERY_OUTCOMES = frozenset(
    {
        RecoveryOutcome.INCIDENT_NO_LONGER_PRESENT,
        RecoveryOutcome.ROLLED_BACK,
        RecoveryOutcome.VALIDATED_SUCCESS,
        RecoveryOutcome.MATERIAL_RETIRED,
    }
)


def reconcile_interrupted_remediation(
    baseline: RemediationBaseline, observation: RecoveryObservation
) -> RecoveryDecision:
    """Decide what an interrupted repair may do next, from current evidence.

    Ordered so the conditions that forbid action are evaluated before the
    ones that permit it. A repair that must not proceed for two reasons
    should report the one that makes continuation unsafe, not the one that
    happens to be checked first.
    """

    def _decide(outcome: RecoveryOutcome, reason: str, **kw: Any) -> RecoveryDecision:
        return RecoveryDecision(
            outcome=outcome,
            reason=reason,
            may_resume=outcome in RESUMABLE_OUTCOMES,
            may_apply_mutation=outcome not in NO_MUTATION_OUTCOMES,
            **kw,
        )

    # Classify the FILES FIRST. Ordering discovered live: a repair that was
    # interrupted between the write and validation reported STALE_PLAN,
    # because the plan can no longer be re-derived once the stale reference
    # it targeted is gone -- the plan becomes underivable BECAUSE the write
    # succeeded. Asking "is the approval still derivable?" before "what do
    # the bytes actually say?" turns a completed mutation into a stale
    # approval, refuses to finish validating it, and leaves the mutation
    # unvalidated and unreconciled. The bytes on disk are the strongest
    # evidence available and are now read first.
    pre_matched: list[str] = []
    post_matched: list[str] = []
    unmatched: list[str] = []
    for path, pre_hash, post_hash in baseline.file_states:
        current = observation.current_hashes.get(path)
        if current is None:
            unmatched.append(path)
        elif current == pre_hash:
            pre_matched.append(path)
        elif post_hash and current == post_hash:
            post_matched.append(path)
        else:
            unmatched.append(path)

    counts = (tuple(sorted(pre_matched)), tuple(sorted(post_matched)), tuple(sorted(unmatched)))
    total = len(baseline.file_states)

    # Material retirement, checked before DIVERGED but deliberately narrower.
    # DIVERGED is the right answer whenever material still exists in an
    # unexpected state, because remediation or rollback could still overwrite
    # it. It is the WRONG answer when the entire target scope was deliberately
    # deleted: nothing can be overwritten, nothing can be resumed, and
    # retention exempts incomplete baselines from pruning -- so such a record
    # became immortal, reclassified on every restart forever.
    #
    # Every condition below must hold. Any single missing proof falls through
    # to the ordinary DIVERGED path.
    all_paths = [path for path, _pre, _post in baseline.file_states]
    if (
        all_paths
        # 9. Removal was OBSERVED, never inferred from a reader that failed.
        and observation.material_reader_available
        # 1/2. Every target path is positively confirmed absent, and none of
        #      them came back readable with unexpected content.
        and all(path in observation.paths_confirmed_absent for path in all_paths)
        and not any(path in observation.current_hashes for path in all_paths)
        # 3. Active configuration no longer references the material.
        and not observation.material_referenced
        # 4/5/6/7. The incident is no longer active, so no plan derived from
        #          it is executable and no approval bound to it is reusable.
        and not observation.incident_present
        # 10. Freshness: this evidence belongs to an identified observation.
        and observation.evidence_scan_id
    ):
        # 8. No rollback is possible or desirable: restoring a file the
        #    operator deliberately deleted would be an unreviewed mutation.
        return _decide(
            RecoveryOutcome.MATERIAL_RETIRED,
            f"every target of this repair ({len(all_paths)} file(s)) has been "
            "removed, active configuration no longer references it, and the "
            "incident is no longer active; there is nothing left to repair, "
            "resume or roll back",
        )

    if unmatched:
        # Something other than this repair changed these files, or they are
        # unreadable. Either way continuation cannot be proven safe, and that
        # outranks every question about the approval.
        return _decide(
            RecoveryOutcome.DIVERGED,
            f"{len(unmatched)} file(s) match neither the pre-state nor the "
            "expected post-state",
            matched_pre=counts[0], matched_post=counts[1], unmatched=counts[2],
        )

    if pre_matched and post_matched:
        # Partially applied. Neither resuming nor rolling back is provable
        # without a human deciding which half is authoritative.
        return _decide(
            RecoveryOutcome.RECOVERY_REQUIRED,
            f"partially applied: {len(post_matched)} of {total} file(s) were "
            "written and the rest were not",
            matched_pre=counts[0], matched_post=counts[1],
        )

    if post_matched and len(post_matched) == total:
        # The mutation is already on disk, so no FURTHER mutation is owed --
        # only validation, rollback or reconciliation, all of which proceed
        # from current state. The approval-derivability questions below are
        # deliberately not asked here: they gate applying a change, and there
        # is no change left to apply.
        if baseline.rollback_began:
            return _decide(
                RecoveryOutcome.ROLLBACK_REQUIRED,
                "rollback was started but the files remain in the post-state",
                matched_post=counts[1],
            )
        if baseline.validation_complete and baseline.validation_passed:
            return _decide(
                RecoveryOutcome.VALIDATED_SUCCESS,
                "the mutation is present and validation had already passed",
                matched_post=counts[1],
            )
        return _decide(
            RecoveryOutcome.POST_STATE_CONFIRMED,
            "the mutation is already present; validation still owed",
            matched_post=counts[1],
        )

    # Every file is at the pre-state, so a mutation could still be applied.
    # Only now do the questions that gate APPLYING one matter.

    # 1. Never repair a defect that is gone.
    if not observation.incident_present:
        return _decide(
            RecoveryOutcome.INCIDENT_NO_LONGER_PRESENT,
            "current evidence no longer shows the incident this repair targeted",
            matched_pre=counts[0],
        )

    # 2. Protected effects are re-evaluated, never inherited -- and are asked
    #    about BEFORE plan identity. RepairPlan.plan_identity folds in
    #    protection_verdict, so a changed verdict always changes the identity
    #    too: checking identity first made PROTECTED_EFFECT_CHANGED
    #    unreachable in the deployed system and reported "the plan changed"
    #    for what is really "protected infrastructure is now in scope". Both
    #    refuse the mutation; only one tells the operator why.
    if (
        baseline.protection_verdict
        and observation.current_protection_verdict
        and observation.current_protection_verdict != baseline.protection_verdict
    ):
        return _decide(
            RecoveryOutcome.PROTECTED_EFFECT_CHANGED,
            f"protected-invariant verdict changed from "
            f"{baseline.protection_verdict!r} to "
            f"{observation.current_protection_verdict!r}",
            matched_pre=counts[0],
        )

    # 3. An approval is bound to one exact plan. A changed identity means the
    #    approved effect is not the effect that would now occur.
    if observation.current_plan_identity is None:
        return _decide(
            RecoveryOutcome.STALE_PLAN,
            "the plan could not be re-derived from current state",
            matched_pre=counts[0],
        )
    if observation.current_plan_identity != baseline.plan_identity:
        return _decide(
            RecoveryOutcome.APPROVAL_INVALID,
            "the plan changed after approval; the prior approval does not "
            "describe what would now happen",
            matched_pre=counts[0],
        )

    # Every file is at the pre-state.
    if baseline.rollback_began:
        return _decide(
            RecoveryOutcome.ROLLED_BACK,
            "every file was restored to its pre-mutation content",
            matched_pre=counts[0],
        )
    if baseline.write_began:
        # A write was attempted and nothing landed. Safe to retry, but only
        # because the files provably never changed.
        #
        # This deliberately ignores write_complete. A record claiming the
        # write finished while every file still hashes to its pre-state is a
        # contradiction, and the files win: what is on disk is what is true.
        return _decide(
            RecoveryOutcome.PRE_STATE_CONFIRMED,
            "a write was attempted but no file changed"
            + (
                " (the record claimed completion; the file contents disagree)"
                if baseline.write_complete
                else ""
            ),
            matched_pre=counts[0],
        )
    if baseline.backup_complete:
        missing = [p for p, ok in observation.backups_present.items() if not ok]
        if missing:
            return _decide(
                RecoveryOutcome.MANUAL_REVIEW_REQUIRED,
                f"{len(missing)} recorded backup(s) are no longer present",
                matched_pre=counts[0],
            )
        return _decide(
            RecoveryOutcome.BACKUP_CREATED,
            "backups exist and no file has been modified",
            matched_pre=counts[0],
        )
    return _decide(
        RecoveryOutcome.NOT_STARTED,
        "no mutation was attempted and no file has changed",
        matched_pre=counts[0],
    )
