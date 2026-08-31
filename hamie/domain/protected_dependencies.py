"""Protected infrastructure dependencies -- durable, evidence-carrying invariants.

Distinct from ``domain/protection.py``, which answers "is this subject
safety-sensitive?" using domain/device_class/keyword heuristics. This module
answers a different and sharper question:

    "Does this proposed change sever a dependency chain that something we
     depend on -- possibly HAMIE itself -- is standing on?"

The motivating case is real and was proven from live evidence:

    switch.example_inference_host_plug
      -> powers EXAMPLE-HOST / EXAMPLE-DESKTOP-01
      -> which hosts Ollama at 192.0.2.10:11434
      -> which provides HAMIE's local inference

An automation that "helpfully" powers that plug off during a house-empty
sweep removes HAMIE's own reasoning capability. HAMIE must recognise that
before proposing or endorsing such a change, not after.

This is deliberately a *registry*, not a hardcoded exception: chains are
declarative data with rationale and evidence, so new protected dependencies
(NAS powering the recorder database, PoE switch powering cameras, UPS feeding
the HA host) are added as data rather than as new branches in remediation code.

Pure and I/O-free like every other ``domain/`` module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .common import require_non_empty


class ProtectionSeverity(StrEnum):
    """How badly severing the chain hurts."""

    CRITICAL = "critical"  # removes a capability HAMIE or HA depends on
    HIGH = "high"  # major loss of function, recoverable


class ProtectionVerdict(StrEnum):
    """Outcome of evaluating a proposed action against the registry."""

    ALLOWED = "allowed"
    REQUIRES_APPROVAL = "requires_approval"
    BLOCKED = "blocked"


#: Action types understood to remove power/availability from a subject.
#: Anything in this set severs a dependency chain rather than merely reading it.
SEVERING_ACTIONS = frozenset(
    {
        "turn_off",
        "switch.turn_off",
        "homeassistant.turn_off",
        "delete_entity",
        "delete_device",
        "delete_config_entry",
        "disable_entity",
        "remove_registry_entry",
        "power_off",
    }
)

#: Action types that cannot change anything, so they never sever a chain.
READ_ONLY_ACTIONS = frozenset(
    {"", "none", "read_state", "inspect", "investigate", "report", "notify", "monitor"}
)

#: Declared action_type is a weak signal: a proposal typed
#: ``update_automation`` whose text is "create an automation to turn off the AI
#: PC" severs the chain just as surely as a direct ``turn_off``. Intent is
#: therefore scanned as well, and for CRITICAL chains anything that is neither
#: provably read-only nor provably safe is treated as severing -- a false
#: positive costs an approval prompt, a false negative costs HAMIE its own
#: reasoning capability.
SEVERING_INTENT = (
    "turn off",
    "turn_off",
    "turns off",
    "turning off",
    "switch off",
    "power off",
    "power down",
    "shut down",
    "shutdown",
    "cut power",
    "de-energize",
    "deenergize",
    "disable",
    "remove",
    "delete",
    "unplug",
)


def _severs(action_type: str, intent: str) -> bool:
    """True when either the declared action or its stated intent cuts a chain."""
    if action_type in SEVERING_ACTIONS:
        return True
    text = (intent or "").casefold()
    return any(marker in text for marker in SEVERING_INTENT)


@dataclass(frozen=True, slots=True)
class DependencyLink:
    """One hop in a protected chain, with why we believe it."""

    subject: str
    provides: str
    rationale: str
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.subject or self.subject != self.subject.strip():
            raise ValueError("subject must be a non-empty normalized string")
        if not self.provides:
            raise ValueError("provides must be non-empty")


class AliasAuthority(StrEnum):
    """How strongly two entity ids are known to drive the same endpoint.

    Ordered by authority, and deliberately explicit: the difference between
    "the registry proves it" and "they happened to move together" is the
    difference between a protection and a guess.
    """

    #: Provable from registry data alone -- same integration, same device,
    #: same channel/outlet index. No human judgement required.
    REGISTRY_PROVEN = "registry_proven"
    #: An operator asserted the equivalence and recorded why. Required
    #: whenever the proof is cross-integration, because Home Assistant models
    #: two integrations' views of one device as two unrelated devices and
    #: exposes nothing that links them.
    DECLARED = "declared"
    #: The entities were seen changing together. NEVER sufficient on its own
    #: to add an alias: two outlets on one strip switched by the same sweep
    #: also move together, and protecting the whole strip on that basis would
    #: block legitimate power saving.
    OBSERVED = "observed"


@dataclass(frozen=True, slots=True)
class AliasEvidence:
    """Why one entity id is believed to control a protected endpoint."""

    entity_id: str
    integration: str
    unique_id: str
    authority: AliasAuthority
    rationale: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.entity_id, "entity_id"),
            (self.integration, "integration"),
            (self.rationale, "rationale"),
        ):
            require_non_empty(value, name)

    @property
    def is_sufficient_alone(self) -> bool:
        """OBSERVED evidence never justifies an alias by itself."""
        return self.authority is not AliasAuthority.OBSERVED


@dataclass(frozen=True, slots=True)
class ProtectedEndpoint:
    """One controllable physical endpoint and every id that switches it.

    The protection unit is deliberately the ENDPOINT, not the Home Assistant
    device. The Example Smart Plug X1 is one device with six independently
    switched outlets; protecting the device would block legitimate action on
    five unrelated loads. It is also not a single entity id, because one
    outlet can carry several -- that gap is what let a house-empty sweep cut
    AI-PC power on 2026-08-29 through a matter alias while the tplink id sat
    safely on an exclusion list.
    """

    endpoint_id: str
    description: str
    alias_evidence: tuple[AliasEvidence, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.endpoint_id, "endpoint_id")
        require_non_empty(self.description, "description")
        if not self.alias_evidence:
            raise ValueError("a protected endpoint needs at least one alias")
        weak = [e for e in self.alias_evidence if not e.is_sufficient_alone]
        if len(weak) == len(self.alias_evidence):
            raise ValueError(
                "a protected endpoint cannot rest only on observed "
                "synchronisation; record registry or declared evidence"
            )
        object.__setattr__(
            self,
            "alias_evidence",
            tuple(sorted(self.alias_evidence, key=lambda e: e.entity_id)),
        )

    @property
    def entity_aliases(self) -> frozenset[str]:
        """Every entity id that controls this endpoint."""
        return frozenset(e.entity_id for e in self.alias_evidence)


class AliasAuditClass(StrEnum):
    """What a live registry can say about a declared protected alias."""

    #: Declared alias still present, unique_id unchanged.
    CONFIRMED = "confirmed"
    #: Declared alias is gone from the registry, or its unique_id changed.
    #: Protection may now be pointing at nothing.
    STALE = "stale"
    #: Shares a device with a declared alias but is a DIFFERENT endpoint.
    #: Reported so the multi-endpoint context is visible, and explicitly NOT
    #: treated as an alias -- the Example Smart Plug X1 has six independently
    #: switched outlets, and inheriting protection by device would block five
    #: unrelated loads.
    SIBLING_NOT_ALIAS = "sibling_not_alias"


@dataclass(frozen=True, slots=True)
class AliasAuditFinding:
    """One read-only observation about a protected endpoint's aliases."""

    endpoint_id: str
    entity_id: str
    audit_class: AliasAuditClass
    detail: str


def audit_alias_candidates(
    dependency: ProtectedDependency,
    registry_rows: tuple[dict[str, object], ...],
) -> tuple[AliasAuditFinding, ...]:
    """Report what the registry says about this dependency's aliases.

    Read-only and deterministic. It never adds an alias: Home Assistant
    models two integrations' views of one physical device as two unrelated
    devices and exposes nothing linking them, so a cross-integration
    equivalence is an operator assertion, not something to be inferred here.
    Guessing at this boundary is how a protection becomes a rumour.
    """
    by_entity = {str(row.get("entity_id")): row for row in registry_rows}
    findings: list[AliasAuditFinding] = []
    for endpoint in dependency.endpoints:
        declared_devices: set[str] = set()
        for evidence in endpoint.alias_evidence:
            row = by_entity.get(evidence.entity_id)
            if row is None:
                findings.append(
                    AliasAuditFinding(
                        endpoint.endpoint_id, evidence.entity_id,
                        AliasAuditClass.STALE,
                        "declared alias is not in the entity registry",
                    )
                )
                continue
            if evidence.unique_id and str(row.get("unique_id")) != evidence.unique_id:
                findings.append(
                    AliasAuditFinding(
                        endpoint.endpoint_id, evidence.entity_id,
                        AliasAuditClass.STALE,
                        "declared alias unique_id no longer matches the registry",
                    )
                )
                continue
            device = row.get("device_id")
            if device:
                declared_devices.add(str(device))
            findings.append(
                AliasAuditFinding(
                    endpoint.endpoint_id, evidence.entity_id,
                    AliasAuditClass.CONFIRMED,
                    f"present via {evidence.integration}, unique_id matches",
                )
            )
        aliases = endpoint.entity_aliases
        for entity_id, row in sorted(by_entity.items()):
            if entity_id in aliases:
                continue
            if str(row.get("device_id") or "") not in declared_devices:
                continue
            findings.append(
                AliasAuditFinding(
                    endpoint.endpoint_id, entity_id,
                    AliasAuditClass.SIBLING_NOT_ALIAS,
                    "same device as a declared alias but a different endpoint; "
                    "NOT protected by this dependency",
                )
            )
    return tuple(findings)


@dataclass(frozen=True, slots=True)
class ProtectedDependency:
    """A durable invariant over a dependency chain."""

    id: str
    name: str
    severity: ProtectionSeverity
    chain: tuple[DependencyLink, ...]
    rule: str
    #: Entities whose loss severs the chain. Usually the chain head. Kept as
    #: the authorization surface so every existing caller is unchanged; it is
    #: UNIONED with every endpoint alias below, so protection is expressed
    #: per physical endpoint but still answered as a flat id lookup.
    protected_entities: frozenset[str] = field(default_factory=frozenset)
    #: Physical endpoints this dependency rests on. Each carries its own
    #: aliases and the evidence for them.
    endpoints: tuple[ProtectedEndpoint, ...] = ()
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.id or not self.chain:
            raise ValueError("protected dependency needs an id and a chain")
        # Endpoint aliases are part of the protected set by construction, so
        # adding an alias can never be forgotten at the authorization call.
        expanded = set(self.protected_entities)
        for endpoint in self.endpoints:
            expanded |= endpoint.entity_aliases
        object.__setattr__(self, "protected_entities", frozenset(expanded))

    def endpoint_for(self, entity_id: str) -> ProtectedEndpoint | None:
        """Which physical endpoint this entity id controls, if any."""
        for endpoint in self.endpoints:
            if entity_id in endpoint.entity_aliases:
                return endpoint
        return None

    @property
    def chain_description(self) -> str:
        """Human-readable chain, used verbatim in remediation proposals."""
        return " -> ".join(
            [self.chain[0].subject, *[link.provides for link in self.chain]]
        )


@dataclass(frozen=True, slots=True)
class ProtectionEvaluation:
    """Result of checking one proposed action against the registry."""

    verdict: ProtectionVerdict
    matched: tuple[ProtectedDependency, ...] = ()
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return self.verdict is ProtectionVerdict.BLOCKED

    def as_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "matched_invariants": [
                {
                    "id": d.id,
                    "name": d.name,
                    "severity": d.severity.value,
                    "rule": d.rule,
                    "chain": d.chain_description,
                    "evidence": [e for link in d.chain for e in link.evidence],
                }
                for d in self.matched
            ],
        }


class ProtectedDependencyRegistry:
    """Deterministic evaluation of proposed actions against protected chains.

    Intentionally NOT LLM-driven: the model may explain an invariant
    failure, but it must never be able to define reality or argue its way
    past one.
    """

    def __init__(self, dependencies: tuple[ProtectedDependency, ...] = ()) -> None:
        self._dependencies = tuple(dependencies)

    def register(self, dependency: ProtectedDependency) -> "ProtectedDependencyRegistry":
        """Return a new registry with one more invariant (immutable style)."""
        return ProtectedDependencyRegistry((*self._dependencies, dependency))

    @property
    def dependencies(self) -> tuple[ProtectedDependency, ...]:
        return self._dependencies

    def protecting(self, entity_id: str) -> tuple[ProtectedDependency, ...]:
        """Every enabled invariant that protects this entity."""
        return tuple(
            d
            for d in self._dependencies
            if d.enabled and entity_id in d.protected_entities
        )

    def evaluate(
        self,
        *,
        entity_ids: tuple[str, ...],
        action_type: str,
        intent: str = "",
    ) -> ProtectionEvaluation:
        """Decide whether a proposed action may touch these entities.

        ``intent`` is the human-readable proposed action. It is inspected
        because a model may type an action ``update_automation`` while
        describing something that cuts power to protected infrastructure.
        """
        normalized = (action_type or "").strip().casefold()
        severing = _severs(normalized, intent)
        matched: list[ProtectedDependency] = []
        for entity_id in entity_ids:
            for dependency in self.protecting(entity_id):
                if dependency not in matched:
                    matched.append(dependency)

        if not matched:
            return ProtectionEvaluation(ProtectionVerdict.ALLOWED)

        if not severing:
            critical_now = [
                d for d in matched if d.severity is ProtectionSeverity.CRITICAL
            ]
            if critical_now and normalized not in READ_ONLY_ACTIONS:
                # Mutating a CRITICAL chain without provably read-only intent:
                # fail safe rather than trusting an unrecognised action label.
                names = ", ".join(d.id for d in critical_now)
                return ProtectionEvaluation(
                    ProtectionVerdict.BLOCKED,
                    tuple(matched),
                    f"action '{action_type}' mutates protected infrastructure "
                    f"and could sever: {names}",
                )
            # Reading or non-severing changes are fine; still surfaced so the
            # proposal shows the operator that protected infrastructure is
            # in scope.
            return ProtectionEvaluation(
                ProtectionVerdict.REQUIRES_APPROVAL,
                tuple(matched),
                "action touches protected infrastructure but does not sever it",
            )

        critical = [d for d in matched if d.severity is ProtectionSeverity.CRITICAL]
        if critical:
            names = ", ".join(d.id for d in critical)
            return ProtectionEvaluation(
                ProtectionVerdict.BLOCKED,
                tuple(matched),
                f"action '{action_type}' would sever protected dependency: {names}",
            )
        return ProtectionEvaluation(
            ProtectionVerdict.REQUIRES_APPROVAL,
            tuple(matched),
            f"action '{action_type}' affects protected infrastructure",
        )


# ---------------------------------------------------------------------------
# Default registry -- declarative data, proven from this installation.
# ---------------------------------------------------------------------------

HAMIE_INFERENCE_DEPENDENCY = ProtectedDependency(
    id="hamie-local-inference-power",
    name="HAMIE local inference depends on the AI PC",
    severity=ProtectionSeverity.CRITICAL,
    # BOTH entity ids for ONE physical outlet. The Example Smart Plug X1 strip is
    # integrated twice -- via tplink and via matter -- so protecting a single
    # entity id protected a name, not the dependency. Live incident
    # 2026-08-29T12:31:20Z: a house-empty sweep that had already been taught to
    # exclude switch.example_inference_host_plug cut inference power anyway, through
    # switch.example_inference_host_plug_matter, the matter twin of the very same
    # outlet. Same-outlet verified live: turning either id on flips both.
    endpoints=(
        ProtectedEndpoint(
            endpoint_id="office-tapo-p316m:outlet-1",
            description="Example Smart Plug X1 outlet 1 -- mains power to the AI PC",
            alias_evidence=(
                AliasEvidence(
                    entity_id="switch.example_inference_host_plug",
                    integration="tplink",
                    unique_id="TPLINKEXAMPLE00000000000000000000000000001",
                    authority=AliasAuthority.DECLARED,
                    rationale=(
                        "The originally configured protected entity. TP-Link "
                        "X1 outlet index 00 on device 'Example Smart Plug'."
                    ),
                ),
                AliasEvidence(
                    entity_id="switch.example_inference_host_plug_matter",
                    integration="matter",
                    unique_id=(
                        "MATTEREXAMPLE001-0000000000000001-"
                        "MatterNodeDevice-1-MatterPlug-6-0"
                    ),
                    authority=AliasAuthority.DECLARED,
                    rationale=(
                        "The same strip is integrated twice, and Home "
                        "Assistant models the two views as unrelated devices, "
                        "so this equivalence cannot be registry-proven and is "
                        "declared. Evidence: matter node index correlates "
                        "exactly with the tplink outlet index across all six "
                        "outlets, both ids went off in the same millisecond "
                        "on 2026-08-29T12:31:20Z, and turning the tplink id "
                        "on was observed to flip this one on too."
                    ),
                ),
            ),
        ),
    ),
    rule=(
        "No automatic action may power off, delete, or disable the AI PC "
        "outlet under ANY of its entity ids "
        "(switch.example_inference_host_plug via tplink, "
        "switch.example_inference_host_plug_matter via matter). Doing so removes "
        "the Ollama backend that HAMIE's own local investigation depends on."
    ),
    chain=(
        DependencyLink(
            subject="switch.example_inference_host_plug",
            provides="mains power to EXAMPLE-HOST / EXAMPLE-DESKTOP-01",
            rationale=(
                "TP-Link X1 outlet 00 (unique_id ...EXAMPLE00) on device "
                "'Example Smart Plug'; the sibling monitoring device 'Example-Monitor' "
                "carries the same identifier."
            ),
            evidence=(
                "entity_registry:switch.example_inference_host_plug",
                "unique_id:TPLINKEXAMPLE00000000000000000000000000001",
            ),
        ),
        DependencyLink(
            subject="switch.example_inference_host_plug_matter",
            provides="the same mains outlet, reached through the matter integration",
            rationale=(
                "Matter node 1 on the same X1. Outlet indices correlate "
                "exactly with the tplink ids (matter node N <-> ...EXAMPLE0[N-1]), "
                "and toggling either id was observed to move both."
            ),
            evidence=(
                "entity_registry:switch.example_inference_host_plug_matter",
                "unique_id:MATTEREXAMPLE001-0000000000000001-MatterNodeDevice-1-MatterPlug-6-0",
                "observed:2026-08-29T21:21Z turning on the tplink id flipped the matter id",
            ),
        ),
        DependencyLink(
            subject="EXAMPLE-HOST / EXAMPLE-DESKTOP-01",
            provides="Ollama inference service on 192.0.2.10:11434",
            rationale="ollama process observed running on that host",
            evidence=("host:EXAMPLE-DESKTOP-01", "endpoint:192.0.2.10:11434"),
        ),
        DependencyLink(
            subject="Ollama on 192.0.2.10:11434",
            provides="HAMIE local LLM investigation capability",
            rationale=(
                "HAMIE's configured local provider; without it HAMIE keeps "
                "deterministic detection but loses all reasoning."
            ),
            evidence=("hamie.connectors.ollama",),
        ),
    ),
)


def default_registry() -> ProtectedDependencyRegistry:
    """The invariants shipped with HAMIE for this installation."""
    return ProtectedDependencyRegistry((HAMIE_INFERENCE_DEPENDENCY,))
