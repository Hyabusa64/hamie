"""Post-repair proof: did the repair actually solve the problem?

Phase 7 closed the loop up to a verified repair candidate. This module
closes the half nobody had built: everything that happens *after* an
operator approves one.

    approval -> drift check -> backup -> mutation -> configuration
    validation -> runtime validation -> invariant re-check -> FRESH SCAN
    -> finding reconciliation -> incident reconciliation -> regression
    detection -> durable audit

The single rule the whole module exists to enforce:

    A SUCCESSFUL MUTATION IS NOT A SUCCESSFUL REMEDIATION.

Writing the bytes is the easy part and proves nothing. HAMIE only says
RESOLVED when a genuinely new scan, reconciled against the *stable*
incident identity rather than a finding UUID, no longer produces the
root cause -- and when no equivalent stale reference survived elsewhere,
no protected invariant moved, and nothing attributable regressed.
Anything short of that proof is STILL_PRESENT or INCONCLUSIVE. There is
no path from uncertainty to success.

Reuses rather than reimplements: RemediationExecutor and its
PathPolicy/authorize()/effect analysis (application/remediation_tools.py),
WorldGateway and the deterministic rediscovery in
application/incident_remediation.py, the protected dependency registry,
the incident lifecycle and its stable incident_id in domain/incidents.py,
ScanCoordinator for the rescan, and HAMIE's own AuditRecord history for
durability. No second remediation, incident, scan, approval, rollback or
audit system is introduced.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import logging
import os

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ..domain.common import stable_digest
from ..domain.durable_baseline import (
    BASELINE_SCHEMA_VERSION,
    TERMINAL_RECOVERY_OUTCOMES,
    RecoveryOutcome,
    RecoveryObservation,
    RemediationBaseline,
    reconcile_interrupted_remediation,
)
from ..domain.incidents import ACTIVE_INCIDENT_STATES, IncidentLifecycle
from ..domain.protected_dependencies import (
    ProtectedDependencyRegistry,
    ProtectionVerdict,
    default_registry,
)
from ..domain.remediation_execution import (
    UNRESOLVED_REMEDIATION_OUTCOMES,
    RemediationOutcome,
)
from .incident_remediation import (
    RemediationIntent,
    RemediationIntentKind,
    WorldGateway,
)
from .remediation import audit_events
from .remediation_tools import (
    LocationChange,
    RemediationRefused,
    authorize,
)

#: Domains whose configuration can be reloaded without restarting Home
#: Assistant. Anything not listed here is left alone and recorded as
#: "no supported reload" -- inventing a reload path is how a trivial
#: reference repair turns into a house-wide outage.
RELOADABLE_DOMAINS = ("automation", "script")

#: Config file basenames mapped to the domain that owns them. A package
#: file can define both, so both reloads are attempted for one.
_TOP_LEVEL_DOMAINS = {
    "automations.yaml": ("automation",),
    "scripts.yaml": ("script",),
    "scenes.yaml": (),
}

_LOGGER = logging.getLogger(__name__)


class CheckpointDurabilityError(RuntimeError):
    """Durable recovery truth could not be written before a risky step.

    Raised only at boundaries where continuing would leave HAMIE unable to
    tell, after a restart, whether a mutation landed. Absence of durable
    recovery evidence is not permission to mutate.
    """

    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(f"checkpoint {stage!r} could not be persisted: {detail}")
        self.stage = stage
        self.detail = detail


#: Checkpoints whose persistence MUST succeed before the operation that
#: follows them. Each one is the only durable record that distinguishes two
#: post-restart states which look identical on disk:
#:
#:   pre_state_confirmed -- without the pre-hashes, "unchanged" and "already
#:                          written" are indistinguishable after a restart.
#:   backup_created      -- the write that follows is only reversible because
#:                          a verified backup is bound to this transaction.
#:   write_began         -- the single record that a write was ATTEMPTED. If
#:                          this is missing and the process dies mid-write, a
#:                          partially written tree reads as external
#:                          divergence with no attribution.
#:   rollback_began      -- distinguishes "rolled back deliberately" from
#:                          "never written". Without it, files restored to
#:                          pre-state read as PRE_STATE_CONFIRMED, which
#:                          permits re-applying a repair that just failed
#:                          validation.
REQUIRED_CHECKPOINTS = frozenset(
    {"pre_state_confirmed", "backup_created", "write_began", "rollback_began"}
)

#: Checkpoints that may fail after the fact but must stop any FURTHER
#: mutation. Current file hashes can reconstruct what happened, so the repair
#: is not abandoned -- but nothing else may be written until the truth is
#: durable again.
NO_FURTHER_MUTATION_CHECKPOINTS = frozenset({"write_applied"})

#: Every checkpoint a fixture repair may be deliberately interrupted after.
#: Named explicitly rather than derived, so arming the hook can never reach a
#: boundary this list does not mention.
HALTABLE_CHECKPOINTS = frozenset(
    {
        "pre_state_confirmed",
        "backup_created",
        "write_began",
        "write_applied",
        "validation_complete",
        "rollback_began",
        "rollback_complete",
    }
)

#: Operator-created marker arming the fixture interruption hook. Absent on
#: every ordinary installation, which is what keeps the hook off by default.
FIXTURE_HALT_MARKER = ".hamie_lifecycle_fixture_halt"

#: A repair may only be interrupted when every file it would touch is a
#: lifecycle-fixture file. Production configuration is never haltable.
FIXTURE_PATH_PREFIX = "hamie_lifecycle_fixture"


class FixtureHalt(RuntimeError):
    """Deliberate interruption at a named checkpoint, fixture repairs only.

    Gate K has to prove what survives real process loss, and that cannot be
    shown by a test that never wrote a file: the whole question is whether
    the bytes on disk and the durable record still agree afterwards. This
    hook stops a repair immediately after a named checkpoint has been
    persisted, leaving the installation in exactly the state a crash would
    leave it in, so a genuine Home Assistant restart can then exercise
    recovery against real files.

    Deliberately constrained, because an interruption mechanism is the kind
    of thing that becomes a production defect if it is even slightly more
    capable than its purpose:

    - armed only by an operator-created marker file, absent by default;
    - honoured only when every planned location is a fixture file;
    - it names an existing checkpoint rather than injecting behaviour, so it
      cannot raise an arbitrary exception or run arbitrary code;
    - reachable from no WebSocket command, no service, and no model-facing
      tool -- ``EXECUTION_TOOLS`` is unchanged and stays empty.
    """

    def __init__(self, stage: str) -> None:
        super().__init__(
            f"fixture repair deliberately interrupted after checkpoint {stage!r}"
        )
        self.stage = stage


def read_fixture_halt_stage(plan: RepairPlan, config_dir: str) -> str:
    """Checkpoint this fixture repair should halt after, or "" to run normally.

    BLOCKING: opens a file, so callers must reach it through
    ``asyncio.to_thread`` -- the event loop is shared with the whole house.
    """
    import os

    if not plan.locations:
        return ""
    for location in plan.locations:
        if not os.path.basename(location.path).startswith(FIXTURE_PATH_PREFIX):
            return ""
    try:
        with open(os.path.join(config_dir, FIXTURE_HALT_MARKER), encoding="utf-8") as fh:
            stage = fh.read().strip()
    except OSError:
        return ""
    return stage if stage in HALTABLE_CHECKPOINTS else ""

MAX_AUDIT_DETAIL_VALUE = 240

#: Evaluation states that mean "a scan ran to completion and committed".
#: PARTIAL belongs here: it means some analyzer reported incomplete coverage,
#: which is the steady state on an installation with unreachable cloud
#: integrations -- rejecting it would make resolution unprovable forever.
#: Coverage is recorded instead, and ELIMINATED still additionally requires
#: direct configuration evidence that no stale reference survived, which is
#: independent of any analyzer having run.
COMMITTED_SCAN_STATES = frozenset({"complete", "completed", "partial"})

#: Lifecycle values that mean "this incident is still open", mirrored from
#: domain/incidents.ACTIVE_INCIDENT_STATES so the projection's string form
#: can be tested without importing the enum at every call site.
_ACTIVE_LIFECYCLES = frozenset(item.value for item in ACTIVE_INCIDENT_STATES)


class LifecycleStage(StrEnum):
    """Where a lifecycle run reached. Recorded so a stop is explainable."""

    DRIFT_CHECK = "drift_check"
    AUTHORIZATION = "authorization"
    PRE_STATE_CAPTURE = "pre_state_capture"
    BACKUP = "backup"
    MUTATION = "mutation"
    CONFIG_VALIDATION = "config_validation"
    RUNTIME_VALIDATION = "runtime_validation"
    INVARIANT_RECHECK = "invariant_recheck"
    RESCAN = "rescan"
    FINDING_RECONCILIATION = "finding_reconciliation"
    INCIDENT_RECONCILIATION = "incident_reconciliation"
    REGRESSION_DETECTION = "regression_detection"
    ROLLBACK = "rollback"
    COMPLETE = "complete"


class ReconciliationVerdict(StrEnum):
    """The deterministic answer to 'did the original problem disappear?'"""

    ORIGINAL_FINDING_REMAINS = "original_finding_remains"
    SAME_ROOT_CAUSE_REGENERATED = "same_root_cause_regenerated"
    EQUIVALENT_REFERENCE_REMAINS = "equivalent_reference_remains"
    ELIMINATED = "eliminated"
    INDETERMINATE = "indeterminate"


# ---------------------------------------------------------------------------
# Plan identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlannedLocation:
    """One file the approved plan expects to change, and its exact bytes."""

    path: str
    occurrences: int
    pre_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "occurrences": self.occurrences,
            "pre_hash": self.pre_hash,
        }


@dataclass(frozen=True, slots=True)
class RepairPlan:
    """What was approved, in enough detail to prove it is still true.

    ``plan_identity`` deliberately covers only what determines the EFFECT:
    the incident it serves, the semantic intent, both entities, every file
    with its pre-mutation hash and occurrence count, the expected total,
    the risk class and the protected-invariant verdict. Change any of
    those and the approval no longer describes what would happen, so the
    identity changes and execution refuses.

    ``incident_material_digest`` is recorded and compared but is NOT part
    of the identity: it folds in finding ids and evidence ids, which churn
    on every scan of a live installation while the repair target sits
    perfectly still. Binding execution to it would mean no approval could
    ever survive a scheduled scan. Drift in it is reported; drift in the
    root cause, priority or evidence status blocks.
    """

    incident_id: str
    incident_root_cause: str
    incident_material_digest: str
    incident_priority: str
    incident_evidence_status: str
    intent_kind: str
    old_entity: str
    new_entity: str
    locations: tuple[PlannedLocation, ...]
    expected_occurrences: int
    risk: str
    protection_verdict: str
    created_at: str = ""

    @property
    def plan_identity(self) -> str:
        return stable_digest(
            "hamie-repair-plan@1",
            self.incident_id,
            self.intent_kind,
            self.old_entity,
            self.new_entity,
            tuple(
                (item.path, item.pre_hash, item.occurrences)
                for item in sorted(self.locations, key=lambda x: x.path)
            ),
            self.expected_occurrences,
            self.risk,
            self.protection_verdict,
        )

    @property
    def short_identity(self) -> str:
        return self.plan_identity[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_identity": self.plan_identity,
            "short_identity": self.short_identity,
            "incident_id": self.incident_id,
            "incident_root_cause": self.incident_root_cause,
            "incident_material_digest": self.incident_material_digest,
            "incident_priority": self.incident_priority,
            "incident_evidence_status": self.incident_evidence_status,
            "intent_kind": self.intent_kind,
            "old_entity": self.old_entity,
            "new_entity": self.new_entity,
            "locations": [item.as_dict() for item in self.locations],
            "expected_occurrences": self.expected_occurrences,
            "risk": self.risk,
            "protection_verdict": self.protection_verdict,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class DriftChange:
    field_name: str
    approved: str
    current: str
    blocking: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field_name,
            "approved": self.approved,
            "current": self.current,
            "blocking": self.blocking,
        }


@dataclass(frozen=True, slots=True)
class DriftReport:
    """Is the thing being executed still the thing that was approved?"""

    approved_identity: str
    current_identity: str | None
    changes: tuple[DriftChange, ...] = ()
    rederivation_failed: str = ""

    @property
    def blocking(self) -> bool:
        return bool(self.rederivation_failed) or any(c.blocking for c in self.changes)

    @property
    def stale(self) -> bool:
        return self.approved_identity != (self.current_identity or "")

    def as_dict(self) -> dict[str, Any]:
        return {
            "approved_plan_identity": self.approved_identity,
            "current_plan_identity": self.current_identity,
            "stale": self.stale,
            "blocking": self.blocking,
            "rederivation_failed": self.rederivation_failed,
            "changes": [c.as_dict() for c in self.changes],
        }


def build_plan(
    incident: dict[str, Any],
    intent_kind: str,
    old_entity: str,
    new_entity: str,
    changes: tuple[LocationChange, ...],
    risk: str,
    protection_verdict: str,
    *,
    created_at: str = "",
) -> RepairPlan:
    """Assemble the approvable plan from already-deterministic inputs.

    Occurrence counts and hashes come from the executor's own
    policy-checked read of each file -- the same bytes that will be
    mutated -- not from a separate search pass that could disagree.
    """
    locations = tuple(
        PlannedLocation(
            path=change.path,
            occurrences=change.occurrences,
            pre_hash=change.pre_hash,
        )
        for change in sorted(changes, key=lambda item: item.path)
    )
    return RepairPlan(
        incident_id=str(incident.get("incident_id") or ""),
        incident_root_cause=str(incident.get("root_cause") or ""),
        incident_material_digest=str(incident.get("material_digest") or ""),
        incident_priority=str(incident.get("priority") or ""),
        incident_evidence_status=str(incident.get("evidence_status") or ""),
        intent_kind=intent_kind,
        old_entity=old_entity,
        new_entity=new_entity,
        locations=locations,
        expected_occurrences=sum(item.occurrences for item in locations),
        risk=risk,
        protection_verdict=protection_verdict,
        created_at=created_at,
    )


def plan_from_dict(raw: dict[str, Any]) -> RepairPlan:
    """Rebuild an approved plan from its serialized form.

    The identity is always RECOMPUTED from content by ``plan_identity``;
    any ``plan_identity`` present in ``raw`` is ignored here on purpose so
    a caller cannot submit doctored contents under a borrowed identity.
    """
    return RepairPlan(
        incident_id=str(raw.get("incident_id") or ""),
        incident_root_cause=str(raw.get("incident_root_cause") or ""),
        incident_material_digest=str(raw.get("incident_material_digest") or ""),
        incident_priority=str(raw.get("incident_priority") or ""),
        incident_evidence_status=str(raw.get("incident_evidence_status") or ""),
        intent_kind=str(raw.get("intent_kind") or ""),
        old_entity=str(raw.get("old_entity") or ""),
        new_entity=str(raw.get("new_entity") or ""),
        locations=tuple(
            PlannedLocation(
                path=str(item.get("path") or ""),
                occurrences=int(item.get("occurrences") or 0),
                pre_hash=str(item.get("pre_hash") or ""),
            )
            for item in sorted(
                raw.get("locations") or (), key=lambda x: str(x.get("path") or "")
            )
        ),
        expected_occurrences=int(raw.get("expected_occurrences") or 0),
        risk=str(raw.get("risk") or ""),
        protection_verdict=str(raw.get("protection_verdict") or ""),
        created_at=str(raw.get("created_at") or ""),
    )


def compare_plans(approved: RepairPlan, current: RepairPlan) -> DriftReport:
    """Field-by-field drift, split into blocking and informational."""
    changes: list[DriftChange] = []

    def _cmp(name: str, a: Any, b: Any, *, blocking: bool) -> None:
        if a != b:
            changes.append(
                DriftChange(name, str(a)[:200], str(b)[:200], blocking=blocking)
            )

    _cmp("intent_kind", approved.intent_kind, current.intent_kind, blocking=True)
    _cmp("old_entity", approved.old_entity, current.old_entity, blocking=True)
    _cmp("new_entity", approved.new_entity, current.new_entity, blocking=True)
    _cmp(
        "expected_occurrences",
        approved.expected_occurrences,
        current.expected_occurrences,
        blocking=True,
    )
    _cmp("risk", approved.risk, current.risk, blocking=True)
    _cmp(
        "protection_verdict",
        approved.protection_verdict,
        current.protection_verdict,
        blocking=True,
    )
    _cmp("root_cause", approved.incident_root_cause, current.incident_root_cause, blocking=True)
    _cmp("priority", approved.incident_priority, current.incident_priority, blocking=True)
    _cmp(
        "evidence_status",
        approved.incident_evidence_status,
        current.incident_evidence_status,
        blocking=True,
    )
    # Informational: finding/evidence churn is normal on a live install.
    _cmp(
        "incident_material_digest",
        approved.incident_material_digest,
        current.incident_material_digest,
        blocking=False,
    )

    approved_locs = {item.path: item for item in approved.locations}
    current_locs = {item.path: item for item in current.locations}
    for path in sorted(set(approved_locs) | set(current_locs)):
        a, b = approved_locs.get(path), current_locs.get(path)
        if a is None:
            changes.append(DriftChange(f"location_added:{path}", "-", str(b.occurrences), True))
            continue
        if b is None:
            changes.append(DriftChange(f"location_removed:{path}", str(a.occurrences), "-", True))
            continue
        if a.pre_hash != b.pre_hash:
            changes.append(
                DriftChange(f"file_content_changed:{path}", a.pre_hash[:16], b.pre_hash[:16], True)
            )
        if a.occurrences != b.occurrences:
            changes.append(
                DriftChange(
                    f"occurrences_changed:{path}", str(a.occurrences), str(b.occurrences), True
                )
            )
    return DriftReport(
        approved_identity=approved.plan_identity,
        current_identity=current.plan_identity,
        changes=tuple(changes),
    )


# ---------------------------------------------------------------------------
# Gateways
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LifecycleGateway:
    """Everything beyond WorldGateway that the post-repair proof needs.

    Injected so the whole lifecycle is testable without Home Assistant,
    and so each capability is a named, narrow door rather than a handle
    on the instance.
    """

    #: Run one genuinely new scan; returns at least {"scan_id", "state"}.
    request_scan: Callable[[], Awaitable[dict[str, Any]]]
    #: The scan id currently reflected by the projection, before rescanning.
    current_scan_id: Callable[[], Awaitable[str | None]]
    #: Every incident as a public dict, including resolved ones -- a repair
    #: has to be able to see that HAMIE's own rescan already resolved an
    #: incident, and to reopen it when the evidence disagrees.
    incidents: Callable[[], Awaitable[tuple[dict[str, Any], ...]]]
    #: Persist one bounded audit event through HAMIE's own audit history.
    record_audit: Callable[..., Awaitable[None]]
    #: Apply an existing user-settable incident lifecycle decision.
    set_incident_lifecycle: Callable[..., Awaitable[None]] | None = None
    #: Durably record the truth of an in-flight repair. Absent means the
    #: lifecycle runs in memory only -- which is exactly the defect that made
    #: remediation_baselines 0 and lost every interrupted repair on restart.
    save_remediation_baseline: Callable[..., Awaitable[None]] | None = None


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RemediationLifecycleResult:
    """One complete, reconstructable remediation lifecycle run."""

    incident_id: str
    plan_identity: str
    outcome: RemediationOutcome
    stage: LifecycleStage
    reason: str = ""
    approved_by: str | None = None
    started_at: str = ""
    ended_at: str = ""
    plan: dict[str, Any] | None = None
    drift: dict[str, Any] | None = None
    authorization: dict[str, Any] | None = None
    backup: dict[str, Any] | None = None
    mutation: dict[str, Any] | None = None
    config_validation: dict[str, Any] | None = None
    runtime_validation: dict[str, Any] | None = None
    invariants: dict[str, Any] | None = None
    rescan: dict[str, Any] | None = None
    finding_reconciliation: dict[str, Any] | None = None
    incident_reconciliation: dict[str, Any] | None = None
    regression: dict[str, Any] | None = None
    rollback: dict[str, Any] | None = None
    advisory: dict[str, Any] = field(default_factory=dict)
    audit_events: tuple[str, ...] = ()
    #: The pre-mutation world, kept so a reconciliation that has to be
    #: resumed later (an interrupted run, a restart between mutation and
    #: rescan) compares against the same baseline the run started from
    #: rather than against a moved goalpost.
    baseline_incident_ids: tuple[str, ...] = ()
    baseline_finding_ids: tuple[str, ...] = ()

    @property
    def incident_resolved(self) -> bool:
        return self.outcome not in UNRESOLVED_REMEDIATION_OUTCOMES

    def as_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "plan_identity": self.plan_identity,
            "short_identity": self.plan_identity[:16],
            "outcome": self.outcome.value,
            "incident_resolved": self.incident_resolved,
            "stage": self.stage.value,
            "reason": self.reason,
            "approved_by": self.approved_by,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "plan": self.plan,
            "drift": self.drift,
            "authorization": self.authorization,
            "backup": self.backup,
            "mutation": self.mutation,
            "config_validation": self.config_validation,
            "runtime_validation": self.runtime_validation,
            "invariants": self.invariants,
            "rescan": self.rescan,
            "finding_reconciliation": self.finding_reconciliation,
            "incident_reconciliation": self.incident_reconciliation,
            "regression": self.regression,
            "rollback": self.rollback,
            # Phase 13: the two kinds of evidence never share a bucket.
            "evidence": {
                "deterministic_authoritative": {
                    "note": (
                        "every field outside 'advisory_model_derived' was derived "
                        "by HAMIE from configuration, registries, validation, a "
                        "fresh scan and hash comparison"
                    ),
                    "plan_identity": self.plan_identity,
                    "outcome": self.outcome.value,
                },
                "advisory_model_derived": {
                    "note": (
                        "model output. Never authoritative for targets, "
                        "validation, resolution, rollback or invariants"
                    ),
                    **self.advisory,
                },
            },
            "baseline_incident_count": len(self.baseline_incident_ids),
            "baseline_finding_ids": list(self.baseline_finding_ids[:20]),
            "audit_events": list(self.audit_events),
        }


# ---------------------------------------------------------------------------
# Stateful invariants -- protections that live in Home Assistant state
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateInvariant:
    """A protection expressed as a live state, not as a severing action.

    ProtectedDependencyRegistry answers "may this action sever a chain?".
    Some protections here are instead facts that must keep holding after
    a repair: the AI PC stays powered, the printer's two-hour idle policy
    keeps its minimum. Both are checked before and after every mutation,
    and only a violation that appears *after* is attributed to the repair
    -- a pre-existing violation is reported honestly rather than blamed
    on the change.
    """

    invariant_id: str
    entity_id: str
    description: str
    allowed_states: frozenset[str] = frozenset()
    minimum_numeric: float | None = None

    def holds(self, state: str | None) -> bool | None:
        """True / False, or None when the state cannot be evaluated."""
        if state is None or state in ("unknown", "unavailable"):
            return None
        if self.allowed_states and state not in self.allowed_states:
            return False
        if self.minimum_numeric is not None:
            try:
                return float(state) >= self.minimum_numeric
            except (TypeError, ValueError):
                return None
        return True


#: Shipped protections for this installation. Both were established by
#: earlier live work on this house and must survive every repair.
DEFAULT_STATE_INVARIANTS: tuple[StateInvariant, ...] = (
    StateInvariant(
        invariant_id="ai-pc-remains-powered",
        entity_id="switch.example_inference_host_plug",
        description=(
            "The AI PC plug powers EXAMPLE-HOST, which runs the Ollama backend HAMIE's "
            "own investigation depends on. No repair may leave it off."
        ),
        allowed_states=frozenset({"on"}),
    ),
    StateInvariant(
        invariant_id="printer-sustained-idle-policy",
        entity_id="input_number.printer_sustained_idle_minutes",
        description=(
            "The printer may only be powered down after 120 continuous minutes "
            "of verified inactivity. No repair may lower that floor."
        ),
        minimum_numeric=120.0,
    ),
)


def _audit_detail(value: Any) -> str:
    text = "" if value is None else str(value)
    return text[:MAX_AUDIT_DETAIL_VALUE]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _plan_from_result(result: "RemediationLifecycleResult") -> RepairPlan:
    """Rebuild the approved plan from the result for checkpointing.

    The rollback path does not carry the plan object, and re-deriving it from
    the world there would be wrong: a checkpoint must describe the plan that
    was approved, not whatever the world looks like mid-rollback.
    """
    return plan_from_dict(result.plan or {})


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# The lifecycle
# ---------------------------------------------------------------------------


class RemediationLifecycle:
    """Approval -> mutation -> validation -> fresh scan -> resolution proof.

    Composes existing machinery; owns no storage of its own. Every verdict
    it returns is derived from configuration bytes, Home Assistant state,
    HAMIE's own scan, or a hash comparison -- never from model output, which
    reaches this class only as the inert ``advisory`` bag it copies into the
    audit record.
    """

    def __init__(
        self,
        world: WorldGateway,
        gateway: LifecycleGateway,
        executor: Any,
        *,
        registry: ProtectedDependencyRegistry | None = None,
        state_invariants: tuple[StateInvariant, ...] = DEFAULT_STATE_INVARIANTS,
        rollback_on_post_scan_regression: bool = False,
        fixture_config_dir: str | None = None,
    ) -> None:
        self._world = world
        self._gateway = gateway
        self._executor = executor
        # Gate K's live interruption hook. ``None`` disables it outright; a
        # path only makes the marker file *readable*, and the marker still
        # has to exist and name a haltable checkpoint. Execution is
        # serialized by HAMIE's remediation locks, so one in-flight stage per
        # instance is safe to hold here.
        self._fixture_config_dir = fixture_config_dir
        self._halt_stage = ""
        #: Last recovery classification, keyed by plan identity AND
        #: incident id so either handle finds it.
        self._recovery: dict[str, dict[str, Any]] = {}
        self._registry = registry if registry is not None else default_registry()
        self._invariants = state_invariants
        # A new P0/P1 incident surfaced by a full rescan is not the same
        # evidence as an invalid configuration: it may or may not be caused
        # by this repair, and rolling back automatically on it would itself
        # be an unreviewed mutation driven by a correlation. Default is to
        # report REGRESSED and escalate to the operator. Configuration
        # invalidity, affected-scope breakage, unverifiable or partial
        # mutation and invariant violations DO roll back automatically.
        self._rollback_on_post_scan_regression = rollback_on_post_scan_regression
        self._records: dict[str, RemediationLifecycleResult] = {}

    # -- retrieval -------------------------------------------------------

    def record(self, key: str) -> RemediationLifecycleResult | None:
        """The most recent run for a plan identity or incident id."""
        return self._records.get(key)

    def records(self) -> tuple[RemediationLifecycleResult, ...]:
        return tuple(self._records.values())

    def _remember(self, result: RemediationLifecycleResult) -> None:
        self._records[result.plan_identity] = result
        self._records[result.incident_id] = result

    # -- Phase 2: deterministic re-derivation, with no model in the loop --

    async def async_derive_plan(
        self, incident_id: str
    ) -> tuple[dict[str, Any] | None, RepairPlan | None, str]:
        """Re-derive the repair from evidence alone.

        No investigation runs here: the model is not consulted at execution
        time at all, which is why a model that changes its mind between
        triage and execution cannot change what executes, and why a model
        that is unavailable cannot stop a deterministic repair.
        """
        from .incident_remediation import rediscover_targets

        incident = await self._world.get_incident(incident_id)
        if incident is None:
            return None, None, "incident not found"

        neutral = RemediationIntent(
            kind=RemediationIntentKind.REPLACE_STALE_ENTITY_REFERENCE,
            rationale="deterministic re-derivation; no model input",
        )
        rediscovery = await rediscover_targets(self._world, incident, neutral)
        if not rediscovery.usable:
            return (
                incident,
                None,
                rediscovery.ambiguity_reason or "targets could not be re-derived",
            )

        changes, added_off_targets = await self._executor.async_plan_locations(
            tuple(item.path for item in rediscovery.locations),
            rediscovery.old_entity,
            rediscovery.new_entity,
        )
        unreadable = [c.path for c in changes if c.error]
        if unreadable:
            return incident, None, f"unreadable configuration: {unreadable[:3]}"
        if not any(c.occurrences for c in changes):
            return incident, None, "no occurrence of the stale reference remains"

        auth = authorize(
            operation="replace_entity_reference",
            targets=(rediscovery.old_entity, rediscovery.new_entity),
            added_off_targets=added_off_targets,
            confidence=0.0,
            evidence_ids=(),
            registry=self._registry,
            intent=f"incident {incident_id}",
        )
        plan = build_plan(
            incident,
            RemediationIntentKind.REPLACE_STALE_ENTITY_REFERENCE.value,
            rediscovery.old_entity,
            rediscovery.new_entity,
            changes,
            auth.risk.value,
            str(auth.protection.get("verdict") or ProtectionVerdict.ALLOWED.value),
            created_at=_now(),
        )
        return incident, plan, ""

    # -- state capture ---------------------------------------------------

    def _reload_domains(self, paths: tuple[str, ...], scope: tuple[str, ...]) -> tuple[str, ...]:
        """Which domains to reload, derived from configuration, not guessed.

        Preference order: the automation/script entities the affected files
        actually define (resolved through HAMIE's own source-definition
        index by the adapter), then the file's own top-level identity.
        Nothing outside RELOADABLE_DOMAINS is ever touched, and Home
        Assistant is never restarted to prove a reference repair.
        """
        if scope:
            domains = {
                entity.split(".", 1)[0]
                for entity in scope
                if entity.split(".", 1)[0] in RELOADABLE_DOMAINS
            }
            if domains:
                return tuple(sorted(domains))
        domains = set()
        for path in paths:
            name = _basename(path)
            if name in _TOP_LEVEL_DOMAINS:
                domains.update(_TOP_LEVEL_DOMAINS[name])
            else:
                # A package file may define either or both; both reloads are
                # SAFE_REVERSIBLE and neither restarts anything.
                domains.update(RELOADABLE_DOMAINS)
        return tuple(sorted(domains))

    async def _async_invariants(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for invariant in self._invariants:
            state = await self._world.entity_state(invariant.entity_id)
            holds = invariant.holds(state)
            results.append(
                {
                    "invariant_id": invariant.invariant_id,
                    "entity_id": invariant.entity_id,
                    "state": state,
                    "holds": holds,
                    "description": invariant.description,
                }
            )
        for dependency in self._registry.dependencies:
            for entity_id in sorted(dependency.protected_entities):
                state = await self._world.entity_state(entity_id)
                results.append(
                    {
                        "invariant_id": dependency.id,
                        "entity_id": entity_id,
                        "state": state,
                        "holds": state == "on" if state is not None else None,
                        "description": dependency.rule[:200],
                    }
                )
        return results

    async def _async_capture(
        self, plan: RepairPlan, scope: tuple[str, ...]
    ) -> dict[str, Any]:
        ha = getattr(self._executor, "ha", None)
        capabilities = {
            "error_signatures": getattr(ha, "error_signatures", None) is not None,
            "domain_state_counts": getattr(ha, "domain_state_counts", None) is not None,
            "config_scope_entities": getattr(ha, "config_scope_entities", None)
            is not None,
        }
        config = await self._executor.async_check_config()
        counts: dict[str, dict[str, int]] = {}
        if capabilities["domain_state_counts"]:
            for domain in RELOADABLE_DOMAINS:
                counts[domain] = await ha.domain_state_counts(domain)
        signatures: tuple[str, ...] = ()
        if capabilities["error_signatures"]:
            signatures = tuple(await ha.error_signatures())
        scope_states = {}
        for entity_id in scope:
            scope_states[entity_id] = await self._world.entity_state(entity_id)
        return {
            "at": _now(),
            "config_valid": config.get("result") == "valid",
            "config_errors": config.get("errors"),
            "domain_state_counts": counts,
            "unavailable": {
                domain: int(values.get("unavailable", 0))
                for domain, values in counts.items()
            },
            "scope_entities": list(scope),
            "scope_states": scope_states,
            "scope_unavailable": sorted(
                eid for eid, st in scope_states.items() if st in (None, "unavailable")
            ),
            "error_signatures": list(signatures),
            "invariants": await self._async_invariants(),
            "new_entity_state": await self._world.entity_state(plan.new_entity),
            "old_entity_state": await self._world.entity_state(plan.old_entity),
            "capabilities": capabilities,
        }

    async def _async_scope(self, paths: tuple[str, ...]) -> tuple[str, ...]:
        ha = getattr(self._executor, "ha", None)
        resolver = getattr(ha, "config_scope_entities", None)
        if resolver is None:
            return ()
        try:
            return tuple(await resolver(paths))
        except Exception:  # noqa: BLE001 - absence degrades, never passes
            return ()

    # -- audit -----------------------------------------------------------

    async def _async_audit(
        self,
        event: str,
        *,
        actor: str,
        incident_id: str,
        plan_identity: str,
        details: dict[str, Any],
    ) -> str:
        payload = tuple(
            (key, _audit_detail(value)) for key, value in sorted(details.items())
        )[:30]
        try:
            await self._gateway.record_audit(
                event,
                actor=actor,
                target_ids=(incident_id, plan_identity),
                details=payload,
            )
        except Exception:  # noqa: BLE001 - a repair is not abandoned over audit I/O
            return f"{event}:unrecorded"
        return event

    async def _async_checkpoint(
        self,
        result: RemediationLifecycleResult,
        plan: RepairPlan,
        changes: tuple[LocationChange, ...],
        *,
        stage: str,
        approved_by: str,
        scope: tuple[str, ...] = (),
        pre_scan_id: str | None = None,
        complete: bool = False,
        **flags: Any,
    ) -> None:
        """Persist the truth of this repair at a transaction boundary.

        Written at boundaries rather than on every call: enough durability to
        reconcile after process death, without turning the state document
        into a log. Every flag records that a step was ATTEMPTED; whether it
        took effect is decided after restart by re-hashing the real files.
        """
        required = stage in REQUIRED_CHECKPOINTS
        if self._gateway.save_remediation_baseline is None:
            if required:
                # No durability available at all. That is missing
                # infrastructure, and missing infrastructure must fail as
                # itself rather than passing silently for a boundary whose
                # whole purpose is to be recoverable.
                raise CheckpointDurabilityError(
                    stage, "no remediation-baseline persistence is configured"
                )
            _LOGGER.debug(
                "HAMIE has no baseline persistence configured; skipping "
                "best-effort checkpoint %s", stage,
            )
            return
        baseline = RemediationBaseline(
            schema_version=BASELINE_SCHEMA_VERSION,
            plan_identity=plan.plan_identity,
            incident_id=result.incident_id,
            captured_at=datetime.now(UTC),
            pre_repair_scan_id=pre_scan_id,
            active_incident_ids=result.baseline_incident_ids,
            incident_finding_ids=result.baseline_finding_ids,
            scope_entity_ids=scope,
            stage=stage,
            complete=complete,
            approval_id=stable_digest(plan.plan_identity, approved_by)[:24],
            approved_by=approved_by,
            risk=plan.risk,
            protection_verdict=plan.protection_verdict,
            transaction_id=(result.mutation or {}).get("transaction_id", "") or "",
            file_states=tuple(
                (c.path, c.pre_hash, c.post_hash) for c in changes if c.pre_hash
            ),
            backup_paths=tuple(c.backup_path for c in changes if c.backup_path),
            **flags,
        )
        try:
            await self._gateway.save_remediation_baseline(baseline)
        except Exception as err:  # noqa: BLE001 - classified, never assumed
            # Every failure mode is treated as NOT PERSISTED: an exception, a
            # generation conflict, a timeout, a serialization error. "Unknown"
            # is never collapsed into success, because the whole point of the
            # record is to be readable after a crash.
            detail = f"{type(err).__name__}: {str(err)[:160]}"
            if required:
                _LOGGER.error(
                    "HAMIE refusing to continue remediation: checkpoint %s "
                    "could not be persisted (%s). Continuing would leave the "
                    "outcome of a mutation unknowable after a restart.",
                    stage, detail,
                )
                raise CheckpointDurabilityError(stage, detail) from err
            if stage in NO_FURTHER_MUTATION_CHECKPOINTS:
                # The write already happened. Do NOT write again to make the
                # bookkeeping match -- current file hashes remain the truth.
                _LOGGER.error(
                    "HAMIE could not persist checkpoint %s after a completed "
                    "write (%s). No further mutation will be attempted; "
                    "recovery must proceed from current file state.",
                    stage, detail,
                )
                result.reason = (
                    "the mutation completed but its checkpoint could not be "
                    "persisted; recovery must proceed from current file state"
                )
                return
            _LOGGER.warning(
                "HAMIE could not persist best-effort checkpoint %s (%s); "
                "current state remains reconstructable without it",
                stage, detail,
            )
        else:
            # Placed on the success path on purpose: an interruption is only
            # meaningful once the record of this boundary is actually durable.
            # Halting after a checkpoint that failed to persist would prove
            # nothing about recovery, because there would be nothing to
            # recover from.
            if self._halt_stage and stage == self._halt_stage:
                _LOGGER.warning(
                    "HAMIE lifecycle fixture: halting after checkpoint %s "
                    "(marker file armed). This is a deliberate test "
                    "interruption, not a fault.",
                    stage,
                )
                raise FixtureHalt(stage)

    # -- recovery after process loss -------------------------------------

    async def async_recover_interrupted(
        self, baselines: Sequence[RemediationBaseline]
    ) -> tuple[dict[str, Any], ...]:
        """Classify every interrupted repair against what is true right now.

        The missing half of durable recovery. Checkpoints were already being
        written and reloaded, but nothing ever read them back to ask what the
        interrupted repair may now do -- so an interrupted repair stayed
        interrupted silently, and the durable record proved nothing. Writing
        truth nobody reads is the same failure class as not writing it.

        CLASSIFICATION ONLY. This never writes configuration, never rolls
        back and never resumes: it re-hashes the real files, checks the
        recorded backups, re-derives the plan and re-evaluates protected
        effects, then records the verdict. Resuming a mutation without a
        human is a different decision, and one this method deliberately does
        not make -- ``may_resume``/``may_apply_mutation`` are reported for an
        operator, not acted on.
        """
        decisions: list[dict[str, Any]] = []
        incidents = {i.get("incident_id"): i for i in await self._gateway.incidents()}
        for baseline in baselines:
            if baseline.complete:
                continue
            paths = [path for path, _pre, _post in baseline.file_states]
            current_hashes, absent, reader_ok = await self._async_read_paths(paths)
            backups_present = await self._async_backups_present(baseline.backup_paths)
            referenced = await self._async_material_referenced(baseline)
            try:
                scan_id = await self._gateway.current_scan_id() or ""
            except Exception:  # noqa: BLE001 - no freshness is itself evidence
                scan_id = ""

            incident = incidents.get(baseline.incident_id)
            incident_present = bool(
                incident is not None
                and incident.get("lifecycle") in ACTIVE_INCIDENT_STATES
            )
            current_identity: str | None = None
            current_protection: str = ""
            if incident_present:
                try:
                    _inc, current, _failure = await self.async_derive_plan(
                        baseline.incident_id
                    )
                except Exception:  # noqa: BLE001 - a re-derivation failure is data
                    current = None
                if current is not None:
                    current_identity = current.plan_identity
                    current_protection = current.protection_verdict

            decision = reconcile_interrupted_remediation(
                baseline,
                RecoveryObservation(
                    current_hashes=current_hashes,
                    backups_present=backups_present,
                    incident_present=incident_present,
                    current_plan_identity=current_identity,
                    current_protection_verdict=current_protection or "",
                    paths_confirmed_absent=absent,
                    material_reader_available=reader_ok,
                    material_referenced=referenced,
                    evidence_scan_id=scan_id,
                ),
            )
            record = {
                "incident_id": baseline.incident_id,
                "plan_identity": baseline.plan_identity,
                "stage": baseline.stage,
                "captured_at": baseline.captured_at.isoformat(),
                "outcome": decision.outcome.value,
                "reason": decision.reason,
                "may_resume": decision.may_resume,
                "may_apply_mutation": decision.may_apply_mutation,
                "current_hashes": current_hashes,
                "backups_present": backups_present,
            }
            decisions.append(record)
            self._recovery[baseline.plan_identity] = record
            self._recovery[baseline.incident_id] = record
            if (
                decision.outcome in TERMINAL_RECOVERY_OUTCOMES
                and self._gateway.save_remediation_baseline is not None
            ):
                # Retire it. Nothing further is owed, and leaving it
                # incomplete would reclassify this repair on every restart
                # forever while retention refused to prune it.
                try:
                    await self._gateway.save_remediation_baseline(
                        dataclasses.replace(baseline, complete=True)
                    )
                except Exception:  # noqa: BLE001 - retiring is best-effort
                    _LOGGER.warning(
                        "HAMIE classified an interrupted repair as %s but could "
                        "not retire its baseline; it will be reclassified after "
                        "the next restart",
                        decision.outcome.value,
                    )
            _LOGGER.warning(
                "HAMIE recovered an interrupted repair for incident %s "
                "(checkpoint %s): %s -- %s",
                baseline.incident_id, baseline.stage,
                decision.outcome.value, decision.reason,
            )
            await self._async_audit(
                audit_events.EXECUTION_BLOCKED
                if not decision.may_resume
                else audit_events.EXECUTION_STARTED,
                actor=baseline.approved_by or "hamie:recovery",
                incident_id=baseline.incident_id,
                plan_identity=baseline.plan_identity,
                details={
                    "recovery_outcome": decision.outcome.value,
                    "checkpoint": baseline.stage,
                    "reason": decision.reason[:200],
                },
            )
        return tuple(decisions)

    def recovery_record(self, key: str) -> dict[str, Any] | None:
        """Last recovery classification for a plan identity or incident id."""
        return self._recovery.get(key)

    def recovery_records(self) -> tuple[dict[str, Any], ...]:
        """Every recovery classification from this process's startup pass."""
        return tuple(self._recovery.values())

    async def _async_read_paths(
        self, paths: Sequence[str]
    ) -> tuple[dict[str, str], frozenset[str], bool]:
        """Current hashes, positively-absent paths, and reader availability.

        Three outcomes per path, never two: readable (hash), provably absent
        (FileNotFoundError), or unreadable for some other reason. Collapsing
        "absent" into "not in the mapping" is exactly how a missing reader
        becomes the domain fact "the file is gone" -- the failure mode that
        already produced a wrong live reconciliation once. A path that is
        merely unreadable stays unmatched and reports DIVERGED.

        BLOCKING: file I/O, so every call goes through asyncio.to_thread.
        """
        files = getattr(self._executor, "_files", None)
        if files is None:
            # No reader at all. Nothing may be retired on this evidence.
            return {}, frozenset(), False
        hashes: dict[str, str] = {}
        absent: set[str] = set()
        for path in paths:
            try:
                content = await asyncio.to_thread(files.read, path)
            except FileNotFoundError:
                absent.add(path)
                continue
            except Exception:  # noqa: BLE001 - unreadable is NOT absent
                continue
            hashes[path] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return hashes, frozenset(absent), True

    async def _async_material_referenced(self, baseline: RemediationBaseline) -> bool:
        """Does ACTIVE configuration still reference this repair's material?

        Conservative: any failure to answer reports True (still referenced),
        because "I could not check" must never license retirement.
        """
        needles = [os.path.basename(path) for path, _pre, _post in baseline.file_states]
        for needle in needles:
            if not needle:
                return True
            try:
                found = await self._world.search_config(needle)
            except Exception:  # noqa: BLE001 - unknown means still referenced
                return True
            if found:
                return True
        return False

    async def _async_backups_present(
        self, backup_paths: Sequence[str]
    ) -> dict[str, bool]:
        def _exists(path: str) -> bool:
            import os

            return os.path.isfile(path)

        return {
            path: await asyncio.to_thread(_exists, path) for path in backup_paths
        }

    # -- rollback --------------------------------------------------------

    async def _async_rollback(
        self,
        result: RemediationLifecycleResult,
        changes: tuple[LocationChange, ...],
        reload_domains: tuple[str, ...],
        reason: str,
        actor: str,
    ) -> RemediationOutcome:
        """Restore, then PROVE the restoration. Reuses the executor only."""
        if not any(change.written for change in changes):
            # Nothing reached disk, so there is nothing to restore. Saying
            # "rolled back" here would invent a recovery that never happened.
            result.rollback = {
                "applicable": False,
                "reason": reason,
                "detail": "no file was modified; there was nothing to restore",
            }
            return RemediationOutcome.VALIDATION_FAILED

        await self._async_audit(
            audit_events.ROLLBACK_STARTED,
            actor=actor,
            incident_id=result.incident_id,
            plan_identity=result.plan_identity,
            details={"reason": reason},
        )
        try:
            await self._async_checkpoint(
                result, _plan_from_result(result), changes, stage="rollback_began",
                approved_by=actor, backup_complete=True, write_began=True,
                write_complete=True, rollback_began=True,
            )
        except CheckpointDurabilityError as err:
            # Without this record, files restored to pre-state read as
            # PRE_STATE_CONFIRMED after a restart, which would permit
            # re-applying the very repair that just failed validation.
            report = {
                "reason": reason,
                "applicable": False,
                "detail": (
                    "rollback was not attempted: its intent could not be "
                    f"durably recorded ({err.detail})"
                ),
                "restoration_proven": False,
            }
            result.rollback = report
            _LOGGER.error(
                "HAMIE refusing to roll back: %s. The mutation remains in "
                "place and requires manual review.", report["detail"],
            )
            return RemediationOutcome.ROLLBACK_FAILED
        restored = await self._executor.async_restore_locations(changes)
        report: dict[str, Any] = {
            "reason": reason,
            "files_restored": restored,
            "locations": [c.as_dict() for c in changes],
        }
        # A restore that returned without raising proves nothing on its own;
        # every file was hash-compared above. Configuration and runtime are
        # then re-verified so a "successful" rollback cannot hide a broken
        # tree.
        config = await self._executor.async_check_config()
        report["post_rollback_config_valid"] = config.get("result") == "valid"
        report["post_rollback_config_errors"] = config.get("errors")
        reloads: dict[str, bool] = {}
        for domain in reload_domains:
            reloads[domain] = bool(await self._executor.async_reload_domain(domain))
        report["post_rollback_reloads"] = reloads
        report["post_rollback_invariants"] = await self._async_invariants()

        proven = (
            restored
            and report["post_rollback_config_valid"]
            and all(reloads.values() if reloads else [True])
        )
        report["restoration_proven"] = proven
        result.rollback = report
        await self._async_checkpoint(
            result, _plan_from_result(result), changes, stage="rollback_complete",
            approved_by=actor, backup_complete=True, write_began=True,
            write_complete=True, rollback_began=True, rollback_complete=True,
            rollback_verified=proven, complete=True,
        )
        result.audit_events += (
            await self._async_audit(
                audit_events.ROLLBACK_SUCCEEDED
                if proven
                else audit_events.ROLLBACK_FAILED,
                actor=actor,
                incident_id=result.incident_id,
                plan_identity=result.plan_identity,
                details={
                    "files_restored": restored,
                    "config_valid": report["post_rollback_config_valid"],
                    "reason": reason,
                },
            ),
        )
        return (
            RemediationOutcome.ROLLED_BACK if proven else RemediationOutcome.ROLLBACK_FAILED
        )

    # -- Phases 2-13: the whole post-approval lifecycle -------------------

    async def async_execute(
        self,
        incident_id: str,
        *,
        approved_plan: dict[str, Any],
        approved_plan_identity: str,
        approved_by: str,
        advisory: dict[str, Any] | None = None,
    ) -> RemediationLifecycleResult:
        """Execute one approved repair and prove whether it solved anything."""
        result = RemediationLifecycleResult(
            incident_id=incident_id,
            plan_identity=approved_plan_identity,
            outcome=RemediationOutcome.BLOCKED,
            stage=LifecycleStage.DRIFT_CHECK,
            approved_by=approved_by,
            started_at=_now(),
            advisory=dict(advisory or {}),
        )

        def _finish(
            outcome: RemediationOutcome, stage: LifecycleStage, reason: str = ""
        ) -> RemediationLifecycleResult:
            result.outcome = outcome
            result.stage = stage
            if reason:
                result.reason = reason
            result.ended_at = _now()
            self._remember(result)
            return result

        # ---- Phase 2: is the thing approved still the thing executing? ----
        approved = plan_from_dict(approved_plan)
        if approved.plan_identity != approved_plan_identity:
            result.drift = DriftReport(
                approved_identity=approved_plan_identity,
                current_identity=approved.plan_identity,
                rederivation_failed="submitted plan contents do not match its identity",
            ).as_dict()
            result.audit_events += (
                await self._async_audit(
                    audit_events.EXECUTION_BLOCKED,
                    actor=approved_by,
                    incident_id=incident_id,
                    plan_identity=approved_plan_identity,
                    details={"reason": "plan_identity_mismatch"},
                ),
            )
            return _finish(
                RemediationOutcome.BLOCKED,
                LifecycleStage.DRIFT_CHECK,
                "the approved plan's contents do not hash to its identity",
            )
        if approved.incident_id != incident_id:
            return _finish(
                RemediationOutcome.BLOCKED,
                LifecycleStage.DRIFT_CHECK,
                "the approved plan belongs to a different incident",
            )
        result.plan = approved.as_dict()

        incident, current, failure = await self.async_derive_plan(incident_id)
        self._halt_stage = (
            await asyncio.to_thread(
                read_fixture_halt_stage, current, self._fixture_config_dir
            )
            if current is not None and self._fixture_config_dir
            else ""
        )
        if current is None:
            result.drift = DriftReport(
                approved_identity=approved_plan_identity,
                current_identity=None,
                rederivation_failed=failure or "plan could not be re-derived",
            ).as_dict()
            result.audit_events += (
                await self._async_audit(
                    audit_events.PLAN_DRIFT_BLOCKED,
                    actor=approved_by,
                    incident_id=incident_id,
                    plan_identity=approved_plan_identity,
                    details={"reason": failure},
                ),
            )
            return _finish(
                RemediationOutcome.BLOCKED,
                LifecycleStage.DRIFT_CHECK,
                failure or "plan could not be re-derived",
            )

        drift = compare_plans(approved, current)
        result.drift = drift.as_dict()
        if drift.blocking:
            result.audit_events += (
                await self._async_audit(
                    audit_events.PLAN_DRIFT_BLOCKED,
                    actor=approved_by,
                    incident_id=incident_id,
                    plan_identity=approved_plan_identity,
                    details={
                        "current_identity": drift.current_identity,
                        "changes": ", ".join(
                            c.field_name for c in drift.changes if c.blocking
                        ),
                    },
                ),
            )
            return _finish(
                RemediationOutcome.BLOCKED,
                LifecycleStage.DRIFT_CHECK,
                "the approved plan is stale; re-triage, re-dry-run and re-approve",
            )

        # ---- Phase 2/4: authorization, re-evaluated at execution time -----
        result.stage = LifecycleStage.AUTHORIZATION
        changes, added_off_targets = await self._executor.async_plan_locations(
            tuple(item.path for item in current.locations),
            current.old_entity,
            current.new_entity,
        )
        auth = authorize(
            operation="replace_entity_reference",
            targets=(current.old_entity, current.new_entity),
            added_off_targets=added_off_targets,
            confidence=0.0,
            evidence_ids=(),
            approved_by=approved_by,
            registry=self._registry,
            intent=f"incident {incident_id}",
        )
        result.authorization = auth.as_dict()
        if not auth.permitted or auth.decision.value != "automatic":
            result.audit_events += (
                await self._async_audit(
                    audit_events.EXECUTION_BLOCKED,
                    actor=approved_by,
                    incident_id=incident_id,
                    plan_identity=approved_plan_identity,
                    details={"reason": auth.reason, "risk": auth.risk.value},
                ),
            )
            return _finish(
                RemediationOutcome.BLOCKED, LifecycleStage.AUTHORIZATION, auth.reason
            )

        # ---- Phase 10 baseline: what the house looked like beforehand ----
        result.stage = LifecycleStage.PRE_STATE_CAPTURE
        paths = tuple(item.path for item in current.locations)
        scope = await self._async_scope(paths)
        reload_domains = self._reload_domains(paths, scope)
        pre = await self._async_capture(current, scope)
        pre_scan_id = await self._gateway.current_scan_id()
        all_pre = await self._gateway.incidents()
        pre_incidents = tuple(
            item for item in all_pre if str(item.get("lifecycle")) in _ACTIVE_LIFECYCLES
        )
        pre_incident_ids = {str(i.get("incident_id")) for i in pre_incidents}
        pre["scan_id"] = pre_scan_id
        pre["active_incidents"] = len(pre_incidents)
        pre["incident_finding_ids"] = list(incident.get("finding_ids") or ())
        result.baseline_incident_ids = tuple(sorted(pre_incident_ids))
        result.baseline_finding_ids = tuple(pre["incident_finding_ids"])
        result.invariants = {"pre": pre["invariants"]}

        if not pre["config_valid"]:
            return _finish(
                RemediationOutcome.BLOCKED,
                LifecycleStage.PRE_STATE_CAPTURE,
                "configuration is already invalid; a repair here could not be "
                "distinguished from the existing fault",
            )
        if any(item["holds"] is False for item in pre["invariants"]):
            return _finish(
                RemediationOutcome.BLOCKED,
                LifecycleStage.PRE_STATE_CAPTURE,
                "a protected invariant is already violated; resolve that first",
            )

        try:
            await self._async_checkpoint(
                result, current, changes, stage="pre_state_confirmed",
                approved_by=approved_by, scope=scope, pre_scan_id=pre_scan_id,
            )
        except CheckpointDurabilityError as err:
            return _finish(
                RemediationOutcome.BLOCKED, LifecycleStage.PRE_STATE_CAPTURE,
                f"durable recovery state could not be established: {err.detail}",
            )

        # ---- Phase 3: backup, proven before a single byte changes --------
        result.stage = LifecycleStage.BACKUP
        stamp = _stamp()
        backed_up = await self._executor.async_backup_locations(changes, stamp)
        result.backup = {
            "stamp": stamp,
            "all_verified": backed_up,
            "locations": [c.as_dict() for c in changes],
        }
        result.audit_events += (
            await self._async_audit(
                audit_events.BACKUP_VERIFIED
                if backed_up
                else audit_events.BACKUP_UNAVAILABLE,
                actor=approved_by,
                incident_id=incident_id,
                plan_identity=approved_plan_identity,
                details={"stamp": stamp, "files": len(changes)},
            ),
        )
        try:
            await self._async_checkpoint(
                result, current, changes, stage="backup_created",
                approved_by=approved_by, scope=scope, pre_scan_id=pre_scan_id,
                backup_complete=backed_up,
            )
        except CheckpointDurabilityError as err:
            return _finish(
                RemediationOutcome.BLOCKED, LifecycleStage.BACKUP,
                f"the backup could not be durably recorded: {err.detail}",
            )
        if not backed_up:
            return _finish(
                RemediationOutcome.BLOCKED,
                LifecycleStage.BACKUP,
                "a verified backup could not be produced for every affected file",
            )

        # ---- Phase 4: mutation --------------------------------------------
        result.stage = LifecycleStage.MUTATION
        result.audit_events += (
            await self._async_audit(
                audit_events.EXECUTION_STARTED,
                actor=approved_by,
                incident_id=incident_id,
                plan_identity=approved_plan_identity,
                details={
                    "old_entity": current.old_entity,
                    "new_entity": current.new_entity,
                    "files": len(changes),
                    "occurrences": current.expected_occurrences,
                },
            ),
        )
        # Recorded BEFORE the write, because a process that dies mid-write
        # must leave evidence that a write was attempted at all.
        try:
            await self._async_checkpoint(
                result, current, changes, stage="write_began",
                approved_by=approved_by, scope=scope, pre_scan_id=pre_scan_id,
                backup_complete=True, write_began=True,
            )
        except CheckpointDurabilityError as err:
            # The most important refusal in the lifecycle. Writing now would
            # create a state HAMIE could not classify after a restart: files
            # possibly changed, with no durable record that anything was
            # attempted.
            return _finish(
                RemediationOutcome.BLOCKED, LifecycleStage.MUTATION,
                "refusing to mutate: the intent-to-write checkpoint could not "
                f"be persisted ({err.detail})",
            )
        try:
            applied = await self._executor.async_apply_locations(
                changes,
                current.old_entity,
                current.new_entity,
                added_off_targets=added_off_targets,
                approved_by=approved_by,
                request=f"incident {incident_id}",
            )
        except RemediationRefused as err:
            result.mutation = {"refused": err.code, "detail": err.message}
            return _finish(
                RemediationOutcome.BLOCKED, LifecycleStage.MUTATION, err.message
            )
        result.mutation = {
            "applied": applied,
            "old_entity": current.old_entity,
            "new_entity": current.new_entity,
            "expected_occurrences": current.expected_occurrences,
            "locations": [c.as_dict() for c in changes],
            "measured_off_targets": sorted(added_off_targets),
        }
        await self._async_checkpoint(
            result, current, changes, stage="write_applied",
            approved_by=approved_by, scope=scope, pre_scan_id=pre_scan_id,
            backup_complete=True, write_began=True, write_complete=applied,
        )
        if not applied:
            # Partial application is never success: some files carry the new
            # reference and some the old one, which is worse than either end.
            outcome = await self._async_rollback(
                result, changes, reload_domains, "mutation could not be verified", approved_by
            )
            return _finish(
                outcome,
                LifecycleStage.MUTATION,
                "the mutation did not land as planned in every file",
            )

        return await self._async_validate_and_prove(
            result,
            current,
            changes,
            reload_domains,
            scope,
            pre,
            pre_scan_id,
            pre_incident_ids,
            approved_by,
            _finish,
        )

    # -- Phases 5, 6, 11, 7, 8, 9, 10 ------------------------------------

    async def _async_validate_and_prove(
        self,
        result: RemediationLifecycleResult,
        plan: RepairPlan,
        changes: tuple[LocationChange, ...],
        reload_domains: tuple[str, ...],
        scope: tuple[str, ...],
        pre: dict[str, Any],
        pre_scan_id: str | None,
        pre_incident_ids: set[str],
        actor: str,
        finish: Callable[..., RemediationLifecycleResult],
    ) -> RemediationLifecycleResult:
        """Everything after the bytes changed. Success is earned here, not there."""

        # ---- Phase 5: configuration validation ---------------------------
        result.stage = LifecycleStage.CONFIG_VALIDATION
        config = await self._executor.async_check_config()
        valid = config.get("result") == "valid"
        result.config_validation = {
            "valid": valid,
            "errors": config.get("errors"),
            "checked_at": _now(),
        }
        result.audit_events += (
            await self._async_audit(
                audit_events.CONFIG_VALIDATED if valid else audit_events.VERIFICATION_FAILED,
                actor=actor,
                incident_id=result.incident_id,
                plan_identity=result.plan_identity,
                details={"valid": valid, "errors": config.get("errors")},
            ),
        )
        await self._async_checkpoint(
            result, plan, changes, stage="validation_complete", approved_by=actor,
            scope=scope, pre_scan_id=pre_scan_id, backup_complete=True,
            write_began=True, write_complete=True,
            validation_began=True, validation_complete=True, validation_passed=valid,
        )
        if not valid:
            outcome = await self._async_rollback(
                result, changes, reload_domains, "configuration validation failed", actor
            )
            return finish(
                outcome,
                LifecycleStage.CONFIG_VALIDATION,
                "the mutation produced an invalid Home Assistant configuration",
            )

        # ---- Phase 6: runtime validation ---------------------------------
        result.stage = LifecycleStage.RUNTIME_VALIDATION
        reloads: dict[str, bool] = {}
        for domain in reload_domains:
            reloads[domain] = bool(await self._executor.async_reload_domain(domain))
        post = await self._async_capture(plan, scope)
        new_state = post["new_entity_state"]
        replacement_resolvable = new_state not in (None, "unavailable")

        newly_unavailable = sorted(
            entity_id
            for entity_id in scope
            if post["scope_states"].get(entity_id) in (None, "unavailable")
            and pre["scope_states"].get(entity_id) not in (None, "unavailable")
        )
        new_signatures = tuple(
            sig for sig in post["error_signatures"] if sig not in set(pre["error_signatures"])
        )
        # Attribution, not correlation: an error only counts against this
        # repair if it names something this repair actually touched.
        touched = {plan.old_entity, plan.new_entity, *scope} | {
            _basename(item.path) for item in plan.locations
        }
        attributable = tuple(
            sig for sig in new_signatures if any(token in sig for token in touched if token)
        )
        availability_delta = {
            domain: post["unavailable"].get(domain, 0) - pre["unavailable"].get(domain, 0)
            for domain in set(pre["unavailable"]) | set(post["unavailable"])
        }
        worsened = sorted(d for d, delta in availability_delta.items() if delta > 0)

        result.runtime_validation = {
            "reloads": reloads,
            "reload_domains": list(reload_domains),
            "replacement_entity": plan.new_entity,
            "replacement_state": new_state,
            "replacement_resolvable": replacement_resolvable,
            "affected_scope": list(scope),
            "scope_newly_unavailable": newly_unavailable,
            "availability_delta": availability_delta,
            "domains_worsened": worsened,
            "new_error_signatures": list(new_signatures),
            "attributable_error_signatures": list(attributable),
            "capabilities": post["capabilities"],
            # A drop in a global count is never treated as proof of anything.
            "note": (
                "availability_delta is evidence only when positive; a decrease "
                "does not by itself demonstrate this repair worked"
            ),
        }

        # ---- Phase 11: protected invariants, re-run after the change -----
        result.stage = LifecycleStage.INVARIANT_RECHECK
        newly_violated = [
            item["invariant_id"]
            for item in post["invariants"]
            if item["holds"] is False
            and not any(
                other["invariant_id"] == item["invariant_id"] and other["holds"] is False
                for other in pre["invariants"]
            )
        ]
        result.invariants = {
            "pre": pre["invariants"],
            "post": post["invariants"],
            "newly_violated": newly_violated,
            "measured_off_targets": list(
                (result.mutation or {}).get("measured_off_targets") or ()
            ),
        }
        result.audit_events += (
            await self._async_audit(
                audit_events.INVARIANTS_REVERIFIED,
                actor=actor,
                incident_id=result.incident_id,
                plan_identity=result.plan_identity,
                details={"newly_violated": ", ".join(newly_violated) or "none"},
            ),
        )

        runtime_failures: list[str] = []
        if any(value is False for value in reloads.values()):
            runtime_failures.append("a required reload failed")
        if not replacement_resolvable:
            runtime_failures.append(f"{plan.new_entity} is not resolvable after the change")
        if newly_unavailable:
            runtime_failures.append(
                f"affected objects became unavailable: {newly_unavailable[:5]}"
            )
        if attributable:
            runtime_failures.append(
                f"{len(attributable)} new error(s) naming the changed objects"
            )
        if worsened:
            runtime_failures.append(f"unavailable count rose for: {worsened}")
        if newly_violated:
            runtime_failures.append(f"protected invariant violated: {newly_violated}")

        result.audit_events += (
            await self._async_audit(
                audit_events.RUNTIME_VALIDATED
                if not runtime_failures
                else audit_events.VERIFICATION_FAILED,
                actor=actor,
                incident_id=result.incident_id,
                plan_identity=result.plan_identity,
                details={
                    "reloads": reloads,
                    "replacement_resolvable": replacement_resolvable,
                    "failures": "; ".join(runtime_failures) or "none",
                },
            ),
        )
        if runtime_failures:
            outcome = await self._async_rollback(
                result, changes, reload_domains, "; ".join(runtime_failures), actor
            )
            return finish(
                outcome,
                LifecycleStage.RUNTIME_VALIDATION,
                "; ".join(runtime_failures),
            )

        # ---- Phase 7: a genuinely fresh scan -----------------------------
        result.stage = LifecycleStage.RESCAN
        try:
            scan = await self._gateway.request_scan()
        except Exception as err:  # noqa: BLE001 - a failed scan is INCONCLUSIVE
            scan = {"error": str(err)[:200]}
        result.rescan = self._rescan_report(scan, pre_scan_id)
        fresh = result.rescan["fresh_scan_completed"]
        post_scan_id = result.rescan["post_repair_scan_id"]
        scan_state = result.rescan["state"]
        result.audit_events += (
            await self._async_audit(
                audit_events.RESCAN_COMPLETED,
                actor=actor,
                incident_id=result.incident_id,
                plan_identity=result.plan_identity,
                details={
                    "pre_scan": pre_scan_id,
                    "post_scan": post_scan_id,
                    "fresh": fresh,
                    "state": scan_state,
                },
            ),
        )
        if not fresh:
            # The change validated, so it is kept -- but resolution is
            # unproven, and unproven never becomes success.
            await self._async_reconcile_incident(
                result, plan, RemediationOutcome.INCONCLUSIVE, actor
            )
            return finish(
                RemediationOutcome.INCONCLUSIVE,
                LifecycleStage.RESCAN,
                "no fresh completed scan; resolution cannot be proven",
            )

        # ---- Phase 8: finding reconciliation -----------------------------
        result.stage = LifecycleStage.FINDING_RECONCILIATION
        verdict, detail = await self._async_reconcile_findings(
            plan,
            result.incident_id,
            set(pre["incident_finding_ids"]),
            coverage_complete=bool(result.rescan["coverage_complete"]),
            incomplete_analyzers=tuple(result.rescan["incomplete_analyzers"]),
        )
        result.finding_reconciliation = detail
        result.audit_events += (
            await self._async_audit(
                audit_events.FINDING_RECONCILED,
                actor=actor,
                incident_id=result.incident_id,
                plan_identity=result.plan_identity,
                details={"verdict": verdict.value},
            ),
        )

        # ---- Phase 10: regression detection ------------------------------
        result.stage = LifecycleStage.REGRESSION_DETECTION
        all_post = await self._gateway.incidents()
        post_active = tuple(
            item for item in all_post if str(item.get("lifecycle")) in _ACTIVE_LIFECYCLES
        )
        new_critical = [
            {
                "incident_id": str(item.get("incident_id")),
                "priority": str(item.get("priority")),
                "title": str(item.get("title"))[:120],
            }
            for item in post_active
            if str(item.get("incident_id")) not in pre_incident_ids
            and str(item.get("priority")) in ("p0", "p1")
        ]
        result.regression = {
            "new_p0_p1_incidents": new_critical,
            "availability_delta": availability_delta,
            "attributable_error_signatures": list(attributable),
            "newly_violated_invariants": newly_violated,
            "active_incidents_before": len(pre_incident_ids),
            "active_incidents_after": len(post_active),
            "note": (
                "unrelated global count movement is recorded but never "
                "reconciled against; only scope-correlated evidence counts"
            ),
        }

        if new_critical:
            result.audit_events += (
                await self._async_audit(
                    audit_events.REGRESSION_DETECTED,
                    actor=actor,
                    incident_id=result.incident_id,
                    plan_identity=result.plan_identity,
                    details={
                        "new_p0_p1": ", ".join(i["incident_id"] for i in new_critical)[:200]
                    },
                ),
            )
            if self._rollback_on_post_scan_regression:
                outcome = await self._async_rollback(
                    result,
                    changes,
                    reload_domains,
                    "new P0/P1 incident attributed to this repair",
                    actor,
                )
                await self._async_reconcile_incident(result, plan, outcome, actor)
                return finish(
                    outcome,
                    LifecycleStage.REGRESSION_DETECTION,
                    "rolled back after a new critical incident appeared",
                )
            await self._async_reconcile_incident(
                result, plan, RemediationOutcome.REGRESSED, actor
            )
            return finish(
                RemediationOutcome.REGRESSED,
                LifecycleStage.REGRESSION_DETECTION,
                "the repair validated but a new P0/P1 incident appeared; the "
                "mutation is retained and escalated for operator review rather "
                "than reversed by an unreviewed second mutation",
            )

        # ---- Phase 9: incident reconciliation + verdict ------------------
        if verdict is ReconciliationVerdict.ELIMINATED:
            outcome = RemediationOutcome.RESOLVED
            reason = "the root cause no longer exists in a fresh scan"
        elif verdict is ReconciliationVerdict.INDETERMINATE:
            outcome = RemediationOutcome.INCONCLUSIVE
            reason = detail.get("reason", "correspondence could not be established")
        else:
            outcome = RemediationOutcome.STILL_PRESENT
            reason = detail.get("reason", "the underlying problem is still present")

        result.stage = LifecycleStage.INCIDENT_RECONCILIATION
        await self._async_reconcile_incident(result, plan, outcome, actor)
        # Terminal record. Without it a *successful* repair left its last
        # baseline marked incomplete forever: retention exempts incomplete
        # baselines from pruning, and startup recovery would re-classify a
        # finished repair as interrupted on every restart. "Complete" here
        # means the lifecycle is no longer in flight -- not that the verdict
        # was good; a STILL_PRESENT repair is finished and still needs an
        # operator.
        await self._async_checkpoint(
            result, plan, changes, stage="lifecycle_complete", approved_by=actor,
            scope=scope, pre_scan_id=pre_scan_id, backup_complete=True,
            write_began=True, write_complete=True,
            validation_began=True, validation_complete=True,
            validation_passed=outcome is not RemediationOutcome.VALIDATION_FAILED,
            complete=True,
        )
        return finish(outcome, LifecycleStage.COMPLETE, reason)

    # -- Phases 7-10 on their own: resumable proof ------------------------

    async def async_reconcile(
        self,
        incident_id: str,
        *,
        plan: dict[str, Any],
        plan_identity: str,
        actor: str,
        baseline_incident_ids: tuple[str, ...] = (),
        baseline_finding_ids: tuple[str, ...] = (),
    ) -> RemediationLifecycleResult:
        """Complete the proof for a repair whose mutation already happened.

        Execution and proof are separable in practice: Home Assistant can
        restart between the write and the rescan, or an operator can need to
        re-establish the verdict later. This runs the fresh scan, finding
        reconciliation, regression check and incident reconciliation only --
        it never writes configuration, never backs anything up and never
        rolls anything back. Its verdict is produced by exactly the same
        helpers the execution path uses.
        """
        approved = plan_from_dict(plan)
        result = RemediationLifecycleResult(
            incident_id=incident_id,
            plan_identity=plan_identity,
            outcome=RemediationOutcome.INCONCLUSIVE,
            stage=LifecycleStage.RESCAN,
            approved_by=actor,
            started_at=_now(),
            plan=approved.as_dict(),
        )

        def _finish(outcome: RemediationOutcome, stage: LifecycleStage, reason: str):
            result.outcome, result.stage, result.reason = outcome, stage, reason
            result.ended_at = _now()
            self._remember(result)
            return result

        if approved.plan_identity != plan_identity:
            return _finish(
                RemediationOutcome.BLOCKED,
                LifecycleStage.DRIFT_CHECK,
                "the submitted plan's contents do not hash to its identity",
            )

        prior = self._records.get(plan_identity)
        baseline_ids = set(baseline_incident_ids) or set(
            getattr(prior, "baseline_incident_ids", ()) or ()
        )
        original_findings = set(baseline_finding_ids) or set(
            getattr(prior, "baseline_finding_ids", ()) or ()
        )
        result.baseline_incident_ids = tuple(sorted(baseline_ids))
        result.baseline_finding_ids = tuple(sorted(original_findings))

        pre_scan_id = await self._gateway.current_scan_id()
        try:
            scan = await self._gateway.request_scan()
        except Exception as err:  # noqa: BLE001
            scan = {"error": str(err)[:200]}
        result.rescan = self._rescan_report(scan, pre_scan_id)
        result.audit_events += (
            await self._async_audit(
                audit_events.RESCAN_COMPLETED,
                actor=actor,
                incident_id=incident_id,
                plan_identity=plan_identity,
                details={
                    "pre_scan": pre_scan_id,
                    "post_scan": result.rescan["post_repair_scan_id"],
                    "fresh": result.rescan["fresh_scan_completed"],
                    "resumed": True,
                },
            ),
        )
        if not result.rescan["fresh_scan_completed"]:
            await self._async_reconcile_incident(
                result, approved, RemediationOutcome.INCONCLUSIVE, actor
            )
            return _finish(
                RemediationOutcome.INCONCLUSIVE,
                LifecycleStage.RESCAN,
                "no fresh completed scan; resolution cannot be proven",
            )

        result.stage = LifecycleStage.FINDING_RECONCILIATION
        verdict, detail = await self._async_reconcile_findings(
            approved,
            incident_id,
            original_findings,
            coverage_complete=bool(result.rescan["coverage_complete"]),
            incomplete_analyzers=tuple(result.rescan["incomplete_analyzers"]),
        )
        result.finding_reconciliation = detail
        result.audit_events += (
            await self._async_audit(
                audit_events.FINDING_RECONCILED,
                actor=actor,
                incident_id=incident_id,
                plan_identity=plan_identity,
                details={"verdict": verdict.value, "resumed": True},
            ),
        )

        result.stage = LifecycleStage.REGRESSION_DETECTION
        everything = await self._gateway.incidents()
        active = tuple(
            item for item in everything if str(item.get("lifecycle")) in _ACTIVE_LIFECYCLES
        )
        new_critical = (
            [
                {
                    "incident_id": str(item.get("incident_id")),
                    "priority": str(item.get("priority")),
                    "title": str(item.get("title"))[:120],
                }
                for item in active
                if str(item.get("incident_id")) not in baseline_ids
                and str(item.get("priority")) in ("p0", "p1")
            ]
            if baseline_ids
            else []
        )
        result.regression = {
            "new_p0_p1_incidents": new_critical,
            "baseline_available": bool(baseline_ids),
            "active_incidents_before": len(baseline_ids),
            "active_incidents_after": len(active),
            "note": (
                "resumed reconciliation: regression is only claimed against a "
                "recorded pre-repair baseline, never against a guess"
            ),
        }

        if new_critical:
            await self._async_reconcile_incident(
                result, approved, RemediationOutcome.REGRESSED, actor
            )
            return _finish(
                RemediationOutcome.REGRESSED,
                LifecycleStage.REGRESSION_DETECTION,
                "a new P0/P1 incident appeared against the recorded baseline",
            )

        if verdict is ReconciliationVerdict.ELIMINATED:
            outcome, reason = (
                RemediationOutcome.RESOLVED,
                "the root cause no longer exists in a fresh scan",
            )
        elif verdict is ReconciliationVerdict.INDETERMINATE:
            outcome, reason = (
                RemediationOutcome.INCONCLUSIVE,
                detail.get("reason", "correspondence could not be established"),
            )
        else:
            outcome, reason = (
                RemediationOutcome.STILL_PRESENT,
                detail.get("reason", "the underlying problem is still present"),
            )
        result.stage = LifecycleStage.INCIDENT_RECONCILIATION
        await self._async_reconcile_incident(result, approved, outcome, actor)
        return _finish(outcome, LifecycleStage.COMPLETE, reason)

    # -- Phase 8 helper ---------------------------------------------------

    def _rescan_report(
        self, scan: dict[str, Any], pre_scan_id: str | None
    ) -> dict[str, Any]:
        """Was this a genuinely new, committed scan?

        Requires a KNOWN previous scan id: without one there is no way to
        show the scan is new rather than the same one read twice, and an
        unprovable scan must not be allowed to look fresh.
        """
        post_scan_id = str(scan.get("scan_id") or "") or None
        scan_state = str(scan.get("state") or "")
        incomplete = [str(item) for item in (scan.get("incomplete_analyzers") or ())]
        return {
            "pre_repair_scan_id": pre_scan_id,
            "post_repair_scan_id": post_scan_id,
            "state": scan_state,
            "coverage_complete": scan_state in ("complete", "completed"),
            "incomplete_analyzers": incomplete[:32],
            "fresh_scan_completed": bool(
                pre_scan_id
                and post_scan_id
                and post_scan_id != pre_scan_id
                and scan_state in COMMITTED_SCAN_STATES
            ),
            "error": scan.get("error"),
            "finding_count": scan.get("finding_count"),
        }

    async def _async_reconcile_findings(
        self,
        plan: RepairPlan,
        incident_id: str,
        original_finding_ids: set[str],
        *,
        coverage_complete: bool = True,
        incomplete_analyzers: tuple[str, ...] = (),
    ) -> tuple[ReconciliationVerdict, dict[str, Any]]:
        """Did the ORIGINAL problem disappear, or just its identifier?

        A finding id is not evidence of anything on its own: HAMIE
        regenerates finding identities every scan. Reconciliation therefore
        runs against the stable incident identity (a digest of the engine
        revision and the root key, see domain/incidents._candidate_from_bucket)
        and against the configuration itself, so a root cause that comes back
        under fresh finding ids is still recognised as the same problem.
        """
        try:
            everything = await self._gateway.incidents()
        except Exception as err:  # noqa: BLE001
            return ReconciliationVerdict.INDETERMINATE, {
                "verdict": ReconciliationVerdict.INDETERMINATE.value,
                "reason": f"incident projection unavailable: {str(err)[:120]}",
            }

        by_id = {str(item.get("incident_id")): item for item in everything}
        target = by_id.get(incident_id)
        lifecycle = str(target.get("lifecycle")) if target else "absent"
        active = lifecycle in _ACTIVE_LIFECYCLES

        remaining = await self._world.search_config(plan.old_entity)
        remaining_total = sum(count for _path, count in remaining)

        current_finding_ids = set(
            str(x) for x in ((target or {}).get("finding_ids") or ())
        )
        overlap = sorted(original_finding_ids & current_finding_ids)

        detail: dict[str, Any] = {
            "incident_present": target is not None,
            "incident_lifecycle": lifecycle,
            "incident_active": active,
            "original_finding_count": len(original_finding_ids),
            "current_finding_count": len(current_finding_ids),
            "overlapping_finding_ids": overlap[:20],
            "stale_reference": plan.old_entity,
            "stale_reference_occurrences_remaining": remaining_total,
            "remaining_locations": [
                {"path": path, "occurrences": count} for path, count in remaining[:25]
            ],
            "replacement": plan.new_entity,
            "post_scan_coverage_complete": coverage_complete,
            "incomplete_analyzers": list(incomplete_analyzers[:12]),
        }

        if active and overlap:
            detail["verdict"] = ReconciliationVerdict.ORIGINAL_FINDING_REMAINS.value
            detail["reason"] = (
                f"{len(overlap)} of the original findings are still reported by "
                "the fresh scan"
            )
            return ReconciliationVerdict.ORIGINAL_FINDING_REMAINS, detail
        if active:
            detail["verdict"] = ReconciliationVerdict.SAME_ROOT_CAUSE_REGENERATED.value
            detail["reason"] = (
                "the fresh scan regenerated the same root cause under new "
                "finding identities; the incident identity is unchanged"
            )
            return ReconciliationVerdict.SAME_ROOT_CAUSE_REGENERATED, detail
        if remaining_total:
            detail["verdict"] = ReconciliationVerdict.EQUIVALENT_REFERENCE_REMAINS.value
            detail["reason"] = (
                f"{remaining_total} occurrence(s) of {plan.old_entity} still exist "
                "in active configuration outside the repaired scope"
            )
            return ReconciliationVerdict.EQUIVALENT_REFERENCE_REMAINS, detail

        detail["verdict"] = ReconciliationVerdict.ELIMINATED.value
        detail["reason"] = (
            "the incident is no longer produced by a fresh scan and no "
            "equivalent stale reference remains in active configuration"
        )
        if not coverage_complete:
            # The scan not covering everything is why the second, independent
            # check exists: zero remaining occurrences is direct evidence from
            # the configuration itself, and does not depend on any analyzer
            # having run. The caveat is recorded rather than hidden.
            detail["coverage_caveat"] = (
                "post-repair scan coverage was partial; elimination rests on "
                "direct configuration evidence that no occurrence of "
                f"{plan.old_entity} remains, not on analyzer output alone"
            )
        return ReconciliationVerdict.ELIMINATED, detail

    # -- Phase 9 helper ---------------------------------------------------

    async def _async_reconcile_incident(
        self,
        result: RemediationLifecycleResult,
        plan: RepairPlan,
        outcome: RemediationOutcome,
        actor: str,
    ) -> None:
        """Bind the verdict to HAMIE's existing incident lifecycle.

        No second resolution store: a fresh scan already transitions an
        incident whose root cause disappeared to RESOLVED through
        domain/incidents.reconcile_incidents. This method's job is the
        disagreement case -- when HAMIE's own reconciliation resolved an
        incident but this repair's evidence says the problem is still
        there, the incident is reopened through the existing user-settable
        lifecycle rather than left closed on a false positive.
        """
        report: dict[str, Any] = {
            "outcome": outcome.value,
            "incident_remains_open": outcome in UNRESOLVED_REMEDIATION_OUTCOMES,
            "reopened": False,
            "lifecycle_after": None,
        }
        try:
            everything = await self._gateway.incidents()
        except Exception as err:  # noqa: BLE001
            report["error"] = str(err)[:160]
            result.incident_reconciliation = report
            return

        target = next(
            (
                item
                for item in everything
                if str(item.get("incident_id")) == result.incident_id
            ),
            None,
        )
        lifecycle = str(target.get("lifecycle")) if target else "absent"
        report["lifecycle_after"] = lifecycle

        if outcome is RemediationOutcome.RESOLVED:
            # Deterministic resolution evidence, stored with the incident's
            # own closure so a later reader can re-derive the claim.
            report["resolution_evidence"] = {
                "plan_identity": plan.plan_identity,
                "old_entity": plan.old_entity,
                "new_entity": plan.new_entity,
                "occurrences_replaced": plan.expected_occurrences,
                "files": [item.path for item in plan.locations],
                "pre_repair_scan_id": (result.rescan or {}).get("pre_repair_scan_id"),
                "post_repair_scan_id": (result.rescan or {}).get("post_repair_scan_id"),
                "reconciliation_verdict": (result.finding_reconciliation or {}).get(
                    "verdict"
                ),
                "stale_reference_occurrences_remaining": (
                    result.finding_reconciliation or {}
                ).get("stale_reference_occurrences_remaining"),
                "config_valid_after": (result.config_validation or {}).get("valid"),
                "invariants_newly_violated": (result.invariants or {}).get(
                    "newly_violated"
                ),
                "backup_stamp": (result.backup or {}).get("stamp"),
                "verified_by": "deterministic HAMIE evidence; no model input",
            }
        elif (
            lifecycle == IncidentLifecycle.RESOLVED.value
            and self._gateway.set_incident_lifecycle is not None
            and target is not None
        ):
            # HAMIE closed it; our evidence says otherwise. Reopen.
            try:
                await self._gateway.set_incident_lifecycle(
                    incident_id=result.incident_id,
                    lifecycle=IncidentLifecycle.CONFIRMED,
                    expected_revision=int(target.get("content_revision") or 1),
                    actor=actor,
                    token=stable_digest(
                        "hamie-reopen@1", result.plan_identity, result.incident_id
                    )[:32],
                )
                report["reopened"] = True
                report["lifecycle_after"] = IncidentLifecycle.CONFIRMED.value
                report["reopen_reason"] = (
                    "a fresh scan stopped producing this incident, but "
                    "deterministic evidence shows the problem is still present"
                )
            except Exception as err:  # noqa: BLE001 - reported, never silent
                report["reopen_error"] = str(err)[:160]

        result.incident_reconciliation = report
        result.audit_events += (
            await self._async_audit(
                audit_events.INCIDENT_RECONCILED,
                actor=actor,
                incident_id=result.incident_id,
                plan_identity=result.plan_identity,
                details={
                    "outcome": outcome.value,
                    "lifecycle_after": report["lifecycle_after"],
                    "reopened": report["reopened"],
                },
            ),
            await self._async_audit(
                audit_events.OUTCOME_RECORDED,
                actor=actor,
                incident_id=result.incident_id,
                plan_identity=result.plan_identity,
                details={
                    "outcome": outcome.value,
                    "stage": result.stage.value,
                    "verdict": (result.finding_reconciliation or {}).get("verdict"),
                },
            ),
        )
