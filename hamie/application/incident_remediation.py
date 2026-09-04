"""Closed-loop incident remediation: the layer between an incident and a plan.

HAMIE already had both ends of this pipeline. Incidents carry root cause,
EvidenceStatus, priority and a stable material_digest; RemediationPlanState
already models a 17-state plan lifecycle with approval, execution, rollback.
What did not exist was the middle: turning an *existing incident* into a
deterministically-verified repair candidate.

The governing rule, formalised here because a live run already proved it
matters -- the model once returned action_type=replace_entity_reference while
naming a YAML file as the affected object:

    THE LLM DESCRIBES INTENT. HAMIE DETERMINES EFFECT.

So the model produces a `RemediationIntent` -- a semantic statement of purpose
carrying explicitly advisory hints -- and `TargetRediscovery` then throws those
hints away as authority and re-derives every target from configuration and the
registries. If rediscovery is ambiguous, the pipeline stops at
OPERATOR_DECISION_REQUIRED rather than guessing between plausible candidates.
Three entities in this installation contain "printer" and are different
physical devices; guessing is how you break a house politely.

Reuses rather than reimplements: Incident / EvidenceStatus / IncidentPriority,
RemediationPlanState, Investigator, RemediationExecutor, the protected
dependency registry, and the risk/authorization table.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..domain.incidents import EvidenceStatus, IncidentPriority
from ..domain.protected_dependencies import (
    ProtectedDependencyRegistry,
    ProtectionVerdict,
    default_registry,
)
from .investigator import (
    EvidencePackage,
    InvestigationResult,
    InvestigationStatus,
    Investigator,
)
from .remediation_tools import ToolRisk, authorize, classify_risk

#: Bound on evidence handed to the model for one incident.
MAX_EVIDENCE_ITEMS = 40
#: Bound on config locations reported for one target.
MAX_LOCATIONS = 25

_ENTITY_RE = re.compile(r"\b([a-z_]+)\.([a-z0-9_]+)\b")


class InvestigationDisposition(StrEnum):
    """Where triage routed the incident. The missing routing layer."""

    NO_ACTION = "no_action"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EXTERNAL_ACTION_REQUIRED = "external_action_required"
    OPERATOR_DECISION_REQUIRED = "operator_decision_required"
    REPAIR_CANDIDATE = "repair_candidate"
    BLOCKED = "blocked"


class RemediationIntentKind(StrEnum):
    """Semantic purpose. Never a mutation instruction."""

    REPLACE_STALE_ENTITY_REFERENCE = "replace_stale_entity_reference"
    REMOVE_DEAD_REFERENCE = "remove_dead_reference"
    NO_REMEDIATION_DEVICE_OFFLINE = "no_remediation_device_offline"
    NO_REMEDIATION_INFORMATIONAL = "no_remediation_informational"
    EXTERNAL_DEPENDENCY = "external_dependency"
    UNKNOWN = "unknown"


#: Intents that can produce a deterministic plan at all.
ACTIONABLE_INTENTS = frozenset(
    {
        RemediationIntentKind.REPLACE_STALE_ENTITY_REFERENCE,
        RemediationIntentKind.REMOVE_DEAD_REFERENCE,
    }
)


@dataclass(frozen=True, slots=True)
class RemediationIntent:
    """What the investigation believes should happen, semantically.

    `advisory_*` fields are the model's suggestions. They are recorded for
    provenance and are NEVER used as authoritative execution inputs.
    """

    kind: RemediationIntentKind
    rationale: str = ""
    advisory_old_entity: str | None = None
    advisory_new_entity: str | None = None
    advisory_objects: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    @property
    def actionable(self) -> bool:
        return self.kind in ACTIONABLE_INTENTS

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "rationale": self.rationale,
            "actionable": self.actionable,
            "advisory_only": {
                "old_entity": self.advisory_old_entity,
                "new_entity": self.advisory_new_entity,
                "objects": list(self.advisory_objects),
                "note": "model suggestions; not authoritative execution inputs",
            },
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class ConfigLocation:
    path: str
    occurrences: int


@dataclass(frozen=True, slots=True)
class TargetRediscovery:
    """Deterministically re-derived effect. The authoritative record."""

    old_entity: str | None = None
    new_entity: str | None = None
    locations: tuple[ConfigLocation, ...] = ()
    old_entity_exists: bool = False
    new_entity_exists: bool = False
    new_entity_state: str | None = None
    domains_compatible: bool = False
    candidate_replacements: tuple[str, ...] = ()
    ambiguous: bool = False
    ambiguity_reason: str = ""
    truncated: bool = False

    @property
    def total_occurrences(self) -> int:
        return sum(loc.occurrences for loc in self.locations)

    @property
    def usable(self) -> bool:
        return (
            self.old_entity is not None
            and self.new_entity is not None
            and not self.ambiguous
            and bool(self.locations)
            and self.new_entity_exists
            and self.domains_compatible
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "old_entity": self.old_entity,
            "new_entity": self.new_entity,
            "locations": [
                {"path": l.path, "occurrences": l.occurrences} for l in self.locations
            ],
            "total_occurrences": self.total_occurrences,
            "old_entity_exists": self.old_entity_exists,
            "new_entity_exists": self.new_entity_exists,
            "new_entity_state": self.new_entity_state,
            "domains_compatible": self.domains_compatible,
            "candidate_replacements": list(self.candidate_replacements),
            "ambiguous": self.ambiguous,
            "ambiguity_reason": self.ambiguity_reason,
            "evidence_truncated": self.truncated,
            "usable_for_planning": self.usable,
        }


@dataclass(slots=True)
class IncidentRemediationResult:
    """One triage run. Inert: contains no execution authority."""

    incident_id: str
    disposition: InvestigationDisposition
    priority: str | None = None
    evidence_status: str | None = None
    incident_root_cause: str = ""
    member_finding_count: int = 0
    investigation: dict[str, Any] | None = None
    intent: dict[str, Any] | None = None
    rediscovery: dict[str, Any] | None = None
    risk: str | None = None
    authorization: dict[str, Any] | None = None
    dry_run: dict[str, Any] | None = None
    approval_required: bool = True
    #: The approvable multi-location plan (see remediation_lifecycle.RepairPlan).
    #: Execution binds to plan["plan_identity"], which covers every file, its
    #: pre-mutation hash and occurrence count, the risk class and the
    #: protected-invariant verdict -- so an approval cannot survive a change
    #: to anything that determines the effect.
    plan: dict[str, Any] | None = None
    plan_identity: str | None = None
    blocked_reason: str = ""
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "disposition": self.disposition.value,
            "priority": self.priority,
            "evidence_status": self.evidence_status,
            "incident_root_cause": self.incident_root_cause,
            "member_finding_count": self.member_finding_count,
            "investigation": self.investigation,
            "intent": self.intent,
            "rediscovery": self.rediscovery,
            "risk": self.risk,
            "authorization": self.authorization,
            "dry_run": self.dry_run,
            "approval_required": self.approval_required,
            "plan": self.plan,
            "plan_identity": self.plan_identity,
            "blocked_reason": self.blocked_reason,
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class WorldGateway:
    """Deterministic facts. Injected so triage is testable without HA."""

    #: entity_id -> state string, or None when absent
    entity_state: Callable[[str], Awaitable[str | None]]
    #: substring -> ((path, occurrences), ...) across ACTIVE config only
    search_config: Callable[[str], Awaitable[tuple[tuple[str, int], ...]]]
    #: incident_id -> incident public dict
    get_incident: Callable[[str], Awaitable[dict[str, Any] | None]]
    #: substring -> candidate entity_ids that exist
    similar_entities: Callable[[str], Awaitable[tuple[str, ...]]]


async def rediscover_targets(
    world: WorldGateway, incident: dict[str, Any], intent: RemediationIntent
) -> TargetRediscovery:
    """Re-derive every target from configuration and live state.

    Module-level on purpose: the post-repair lifecycle
    (application/remediation_lifecycle.py) re-derives the very same targets
    at execution time with no investigator and no model in the loop, and
    must run *this* code rather than a second implementation that could
    drift from it.
    """
    # The stale entity is taken from HAMIE's own incident subjects first;
    # the model's hint is only a fallback, and is still verified below.
    subjects = [
        str(s).split(":")[-1] for s in (incident.get("affected_subject_ids") or ())
    ]
    missing: list[str] = []
    for entity_id in subjects:
        if _ENTITY_RE.fullmatch(entity_id) and await world.entity_state(entity_id) is None:
            missing.append(entity_id)
    if not missing and intent.advisory_old_entity:
        hint = intent.advisory_old_entity
        if await world.entity_state(hint) is None:
            missing.append(hint)

    if not missing:
        return TargetRediscovery(
            ambiguous=True,
            ambiguity_reason="no absent entity could be confirmed deterministically",
        )
    if len(missing) > 1:
        return TargetRediscovery(
            old_entity=None,
            candidate_replacements=tuple(sorted(missing)),
            ambiguous=True,
            ambiguity_reason=(
                f"{len(missing)} absent entities in this incident; a single "
                "reference repair cannot be derived unambiguously"
            ),
        )

    old_entity = missing[0]
    raw_locations = await world.search_config(old_entity)
    truncated = len(raw_locations) > MAX_LOCATIONS
    locations = tuple(
        ConfigLocation(path=p, occurrences=n) for p, n in raw_locations[:MAX_LOCATIONS]
    )

    # Replacement: verified independently, never taken on the model's word.
    candidates = await world.similar_entities(old_entity)
    hinted = intent.advisory_new_entity
    chosen: str | None = None
    if hinted and hinted in candidates:
        chosen = hinted
    elif len(candidates) == 1:
        chosen = candidates[0]

    if chosen is None:
        return TargetRediscovery(
            old_entity=old_entity,
            locations=locations,
            old_entity_exists=False,
            candidate_replacements=tuple(candidates[:10]),
            ambiguous=True,
            ambiguity_reason=(
                "no replacement could be uniquely determined"
                if not candidates
                else f"{len(candidates)} plausible replacements exist"
            ),
            truncated=truncated,
        )

    state = await world.entity_state(chosen)
    old_domain = old_entity.split(".", 1)[0]
    new_domain = chosen.split(".", 1)[0]
    return TargetRediscovery(
        old_entity=old_entity,
        new_entity=chosen,
        locations=locations,
        old_entity_exists=False,
        new_entity_exists=state is not None,
        new_entity_state=state,
        domains_compatible=old_domain == new_domain,
        candidate_replacements=tuple(candidates[:10]),
        ambiguous=False,
        truncated=truncated,
    )


#: Operator-created marker arming the advisory-model failure injection for
#: ONE named incident. Absent on every ordinary installation.
TRIAGE_FAIL_MARKER = ".hamie_triage_fail_incident"


def read_triage_fail_incident(config_dir: str) -> str:
    """Incident whose ADVISORY investigation should fail, or "".

    Proves the property that matters after deterministic rediscovery moved
    first: if the advisory model becomes unavailable, HAMIE must still return
    the deterministic disposition rather than degrade to a guess or a retry.
    The real provider is never touched -- the investigator call is simply not
    made for this one incident.

    BLOCKING: opens a file, so callers must use asyncio.to_thread.
    """
    import os

    try:
        with open(os.path.join(config_dir, TRIAGE_FAIL_MARKER), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


class IncidentRemediationPipeline:
    """incident -> evidence -> investigation -> intent -> rediscovery -> dry-run."""

    def __init__(
        self,
        world: WorldGateway,
        investigator: Investigator,
        executor: Any,
        *,
        registry: ProtectedDependencyRegistry | None = None,
        fixture_config_dir: str | None = None,
    ) -> None:
        self._world = world
        self._investigator = investigator
        self._executor = executor
        self._registry = registry if registry is not None else default_registry()
        #: Lets the advisory-failure hook LOOK for its marker. None disables it.
        self._fixture_config_dir = fixture_config_dir

    @property
    def world(self) -> WorldGateway:
        """The deterministic facts this pipeline reads.

        Exposed so the post-approval lifecycle re-derives targets through the
        very same gateway rather than a second, drift-prone construction of
        the same four capabilities.
        """
        return self._world

    # -- Phase 3: bounded, provenance-tagged evidence ---------------------

    async def async_build_evidence(
        self, incident: dict[str, Any]
    ) -> tuple[EvidencePackage, bool]:
        items: list[dict[str, Any]] = [
            {
                "id": f"INC:{incident.get('incident_id')}",
                "kind": "incident",
                "title": incident.get("title"),
                "root_cause": incident.get("root_cause"),
                "category": incident.get("category"),
                "priority": incident.get("priority"),
                "evidence_status": incident.get("evidence_status"),
                "member_findings": len(incident.get("finding_ids") or ()),
                "recommended_next_step": incident.get("recommended_next_step"),
            }
        ]
        subjects = list(incident.get("affected_subject_ids") or ())
        truncated = len(subjects) > MAX_EVIDENCE_ITEMS - 1
        for subject in subjects[: MAX_EVIDENCE_ITEMS - 1]:
            entity_id = str(subject).split(":")[-1]
            state = await self._world.entity_state(entity_id)
            items.append(
                {
                    "id": f"SUBJ:{entity_id}",
                    "kind": "affected_subject",
                    "entity_id": entity_id,
                    "exists": state is not None,
                    "state": state,
                }
            )
        question = (
            f"HAMIE incident {incident.get('incident_id')}: "
            f"{incident.get('title')}. HAMIE's deterministic root cause is: "
            f"{incident.get('root_cause')}. Confirm or contradict it and state "
            "the smallest safe remediation intent."
        )
        return EvidencePackage(question=question, items=tuple(items)), truncated

    # -- Phase 5: normalize model output into semantic intent -------------

    @staticmethod
    def derive_intent(investigation: dict[str, Any]) -> RemediationIntent:
        proposal = investigation.get("proposal") or {}
        action = str(proposal.get("action_type") or "").strip().lower()
        text = f"{proposal.get('proposed_action','')} {investigation.get('root_cause','')}".lower()
        objects = tuple(str(x) for x in (proposal.get("affected_objects") or ()))

        if "replace_entity_reference" in action or "replace" in text:
            kind = RemediationIntentKind.REPLACE_STALE_ENTITY_REFERENCE
        elif "remove" in text or "delete" in text:
            kind = RemediationIntentKind.REMOVE_DEAD_REFERENCE
        elif "offline" in text or "unreachable" in text or "powered off" in text:
            kind = RemediationIntentKind.NO_REMEDIATION_DEVICE_OFFLINE
        elif "informational" in text or "no action" in text:
            kind = RemediationIntentKind.NO_REMEDIATION_INFORMATIONAL
        elif "upstream" in text or "external" in text or "vendor" in text:
            kind = RemediationIntentKind.EXTERNAL_DEPENDENCY
        else:
            kind = RemediationIntentKind.UNKNOWN

        entities = [o for o in objects if _ENTITY_RE.fullmatch(o or "")]
        return RemediationIntent(
            kind=kind,
            rationale=str(investigation.get("root_cause", ""))[:400],
            advisory_old_entity=entities[0] if entities else None,
            advisory_new_entity=entities[1] if len(entities) > 1 else None,
            advisory_objects=objects,
            evidence_ids=tuple(investigation.get("evidence_ids") or ()),
        )

    # -- Phase 6: deterministic rediscovery. Hints are NOT trusted --------

    async def async_rediscover(
        self, incident: dict[str, Any], intent: RemediationIntent
    ) -> TargetRediscovery:
        """Re-derive every target from configuration and live state."""
        return await rediscover_targets(self._world, incident, intent)

    # -- Phases 2/4/7/8: the closed loop ----------------------------------

    async def async_triage(self, incident_id: str) -> IncidentRemediationResult:
        incident = await self._world.get_incident(incident_id)
        if incident is None:
            return IncidentRemediationResult(
                incident_id=incident_id,
                disposition=InvestigationDisposition.INSUFFICIENT_EVIDENCE,
                blocked_reason="incident not found",
            )

        result = IncidentRemediationResult(
            incident_id=incident_id,
            disposition=InvestigationDisposition.INSUFFICIENT_EVIDENCE,
            priority=incident.get("priority"),
            evidence_status=incident.get("evidence_status"),
            incident_root_cause=str(incident.get("root_cause") or ""),
            member_finding_count=len(incident.get("finding_ids") or ()),
        )
        notes: list[str] = []

        # Informational incidents are never repair candidates.
        if incident.get("priority") == IncidentPriority.INFO.value:
            result.disposition = InvestigationDisposition.NO_ACTION
            notes.append("informational priority; no remediation attempted")
            result.notes = tuple(notes)
            return result

        # ---- Deterministic rediscovery FIRST -----------------------------
        #
        # The model used to sit in front of this. derive_intent() classifies
        # the model's PROSE into an intent kind, and an unrecognised phrasing
        # produced kind=UNKNOWN -> "not actionable" -> OPERATOR_DECISION_REQUIRED
        # without ever asking configuration or the state machine anything.
        # Live, identical unchanged inputs needed up to four retries before
        # the same incident was recognised as repairable: the disposition
        # flapped because the wording did. Deterministic rediscovery already
        # proved more reliable than the model, so it runs first and the model
        # can no longer prevent HAMIE from discovering facts.
        neutral = RemediationIntent(
            kind=RemediationIntentKind.REPLACE_STALE_ENTITY_REFERENCE,
            rationale="deterministic rediscovery, no model input",
        )
        rediscovery = await self.async_rediscover(incident, neutral)
        result.rediscovery = rediscovery.as_dict()

        package, truncated = await self.async_build_evidence(incident)
        if truncated:
            notes.append("evidence truncated to bounds")

        fail_incident = (
            await asyncio.to_thread(read_triage_fail_incident, self._fixture_config_dir)
            if self._fixture_config_dir
            else ""
        )
        if fail_incident and fail_incident == incident_id:
            # The investigator is simply not called. Same result the real
            # investigator returns when the provider is unreachable, so the
            # ordinary degraded path is exercised rather than bypassed.
            investigation = InvestigationResult(
                InvestigationStatus.LLM_UNAVAILABLE,
                notes=("advisory model failure injected for the armed fixture incident",),
            )
        else:
            investigation = await self._investigator.async_investigate(package)
        result.investigation = investigation.as_dict()

        # A protected-invariant block is a safety verdict, not a repairability
        # opinion, so it still stops everything.
        if investigation.status is InvestigationStatus.BLOCKED_BY_INVARIANT:
            result.disposition = InvestigationDisposition.BLOCKED
            result.blocked_reason = "; ".join(investigation.notes) or "protected invariant"
            result.notes = tuple(notes)
            return result

        model_usable = investigation.status not in (
            InvestigationStatus.LLM_UNAVAILABLE,
            InvestigationStatus.INVALID_MODEL_OUTPUT,
            InvestigationStatus.NEEDS_MORE_EVIDENCE,
        )
        intent = (
            self.derive_intent(result.investigation)
            if model_usable
            else RemediationIntent(kind=RemediationIntentKind.UNKNOWN)
        )
        result.intent = intent.as_dict()
        if not model_usable:
            notes.append(
                f"advisory analysis degraded ({investigation.status.value}); "
                "deterministic evidence below is unaffected"
            )

        # The model's hint may only NARROW an ambiguous deterministic result,
        # never introduce a target of its own: rediscover_targets accepts a
        # hint solely when it already appears among the candidates it found.
        if not rediscovery.usable and model_usable and (
            intent.advisory_old_entity or intent.advisory_new_entity
        ):
            hinted = await self.async_rediscover(incident, intent)
            if hinted.usable:
                rediscovery = hinted
                result.rediscovery = rediscovery.as_dict()
                notes.append("advisory hint disambiguated the deterministic candidates")

        # ---- Model-informed dispositions apply ONLY when deterministic
        #      evidence could not resolve repairability by itself ----------
        if not rediscovery.usable:
            if not model_usable:
                result.disposition = InvestigationDisposition.INSUFFICIENT_EVIDENCE
                result.blocked_reason = investigation.status.value
                result.notes = tuple(notes)
                return result
            if intent.kind is RemediationIntentKind.EXTERNAL_DEPENDENCY:
                result.disposition = InvestigationDisposition.EXTERNAL_ACTION_REQUIRED
                result.notes = tuple(notes)
                return result
            if intent.kind in (
                RemediationIntentKind.NO_REMEDIATION_DEVICE_OFFLINE,
                RemediationIntentKind.NO_REMEDIATION_INFORMATIONAL,
            ):
                result.disposition = InvestigationDisposition.NO_ACTION
                result.notes = tuple(notes)
                return result
            if not intent.actionable:
                notes.append(
                    "no deterministic remediation primitive matches this intent"
                )

        # Evidence sufficiency is HAMIE's call, not the model's confidence.
        if incident.get("evidence_status") in (
            EvidenceStatus.INSUFFICIENT_EVIDENCE.value,
            EvidenceStatus.POSSIBLE.value,
        ):
            notes.append(
                f"incident evidence_status={incident.get('evidence_status')}; "
                "operator judgement required regardless of model confidence"
            )
            result.disposition = InvestigationDisposition.OPERATOR_DECISION_REQUIRED
            result.notes = tuple(notes)
            return result

        if not rediscovery.usable:
            result.disposition = InvestigationDisposition.OPERATOR_DECISION_REQUIRED
            result.blocked_reason = (
                rediscovery.ambiguity_reason or "targets could not be verified"
            )
            result.notes = tuple(notes)
            return result

        # Deterministic risk + protected invariants over the REAL targets.
        targets = tuple(
            {rediscovery.old_entity, rediscovery.new_entity} - {None}
        )  # type: ignore[arg-type]
        auth = authorize(
            operation="replace_entity_reference",
            targets=targets,
            confidence=0.0,
            evidence_ids=intent.evidence_ids,
            registry=self._registry,
            intent=intent.rationale,
        )
        result.risk = auth.risk.value
        result.authorization = auth.as_dict()
        if not auth.permitted:
            result.disposition = InvestigationDisposition.BLOCKED
            result.blocked_reason = auth.reason
            result.notes = tuple(notes)
            return result

        # Phase 8: automatic, non-mutating dry-run over the largest location.
        primary = max(rediscovery.locations, key=lambda l: l.occurrences)
        txn = await self._executor.async_replace_entity_reference(
            request=f"incident {incident_id}: {incident.get('title')}",
            path=primary.path,
            old_entity=rediscovery.old_entity,
            new_entity=rediscovery.new_entity,
            root_cause=result.incident_root_cause,
            evidence_ids=intent.evidence_ids,
            confidence=0.0,
            dry_run=True,
        )
        result.dry_run = txn.as_dict()
        result.approval_required = True

        # The approvable artifact spans EVERY affected file, not just the
        # previewed one: a stale reference living in ten files cannot be
        # approved one file at a time without leaving a partially repaired
        # configuration on the first failure.
        plan = await self._async_build_plan(incident, rediscovery, auth)
        if plan is not None:
            result.plan = plan.as_dict()
            result.plan_identity = plan.plan_identity

        result.disposition = (
            InvestigationDisposition.REPAIR_CANDIDATE
            if txn.outcome == "dry_run" and plan is not None
            else InvestigationDisposition.OPERATOR_DECISION_REQUIRED
        )
        if txn.outcome != "dry_run":
            result.blocked_reason = txn.error or txn.outcome
        elif plan is None:
            result.blocked_reason = "affected configuration could not be read"
        result.notes = tuple(notes)
        return result

    async def _async_build_plan(
        self, incident: dict[str, Any], rediscovery: TargetRediscovery, auth: Any
    ) -> Any:
        """The multi-location plan an operator approves. Read-only."""
        from .remediation_lifecycle import build_plan

        changes, _added = await self._executor.async_plan_locations(
            tuple(item.path for item in rediscovery.locations),
            rediscovery.old_entity,
            rediscovery.new_entity,
        )
        if any(change.error for change in changes):
            return None
        from datetime import UTC, datetime

        return build_plan(
            incident,
            RemediationIntentKind.REPLACE_STALE_ENTITY_REFERENCE.value,
            rediscovery.old_entity,
            rediscovery.new_entity,
            changes,
            auth.risk.value,
            str(auth.protection.get("verdict") or "allowed"),
            created_at=datetime.now(UTC).isoformat(),
        )
