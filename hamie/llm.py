"""Home Assistant LLM API exposing HAMIE's read-only investigation layer.

Every tool is narrow, bounded, secret-free, and audited.  There is no shell,
filesystem write, service-call, registry mutation, remediation approval, or
deployment tool in this API.  Consequential changes stay in HAMIE's separate
plan/preview/human-approval execution pipeline.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.llm import APIInstance, LLMContext, ToolInput

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
from .domain.investigation import (
    INVESTIGATION_TOOLS,
    SecurityMode,
    assert_tool_allowed,
)

MAX_TOOL_ITEMS = 50
MAX_TOOL_CHARACTERS = 16_000
_SAFE_STATE_ATTRIBUTES = (
    "friendly_name",
    "device_class",
    "entity_category",
    "unit_of_measurement",
    "supported_features",
)
_SENSITIVE_ENTITY_MARKERS = (
    "blood",
    "glucose",
    "health",
    "medical",
    "medication",
    "sleep",
    "weight",
)
_SENSITIVE_ENTITY_DOMAINS = frozenset(
    {
        "alarm_control_panel",
        "camera",
        "device_tracker",
        "image",
        "lock",
        "person",
        "siren",
    }
)
_SENSITIVE_DEVICE_CLASSES = frozenset(
    {
        "door",
        "garage_door",
        "gas",
        "lock",
        "moisture",
        "motion",
        "occupancy",
        "opening",
        "presence",
        "safety",
        "smoke",
    }
)
_SAFE_AUDIT_DETAIL_KEYS = frozenset(
    {
        "provider",
        "model",
        "mode",
        "outcome",
        "evidence_status",
        "returned_items",
        "lifecycle",
    }
)


def _runtime(hass: HomeAssistant, entry_id: str) -> Any:
    entries = hass.data.get(DOMAIN, {})
    runtime = entries.get(entry_id)
    if runtime is None:
        raise HomeAssistantError("HAMIE runtime is unavailable")
    return runtime


def _safe_entity_state(state: Any) -> dict[str, object]:
    entity_id = str(state.entity_id)
    device_class = str(state.attributes.get("device_class", "")).casefold()
    sensitive = (
        state.domain in _SENSITIVE_ENTITY_DOMAINS
        or device_class in _SENSITIVE_DEVICE_CLASSES
        or any(marker in entity_id.casefold() for marker in _SENSITIVE_ENTITY_MARKERS)
    )
    return {
        "entity_id": entity_id,
        "state": "[redacted-sensitive-value]" if sensitive else str(state.state)[:500],
        "last_changed": state.last_changed.isoformat(),
        "last_updated": state.last_updated.isoformat(),
        "attributes": {
            key: value
            for key in _SAFE_STATE_ATTRIBUTES
            if (value := state.attributes.get(key)) is not None
            and isinstance(value, str | int | float | bool)
        },
        "sensitive_value_redacted": sensitive,
    }


async def _audit(
    hass: HomeAssistant,
    entry_id: str,
    tool_name: str,
    context: LLMContext,
    *,
    outcome: str,
    result: dict[str, Any] | None,
    subject_ids: tuple[str, ...] = (),
) -> None:
    runtime = _runtime(hass, entry_id)
    platform = str(getattr(context, "platform", "unknown"))[:100]
    details = [
        ("provider", platform),
        ("model", "not_exposed_by_home_assistant"),
        ("mode", SecurityMode.INVESTIGATION.value),
        ("outcome", outcome),
    ]
    if result is not None:
        details.append(("evidence_status", str(result.get("evidence_status", "unknown"))[:100]))
        returned = result.get("returned")
        if isinstance(returned, int):
            details.append(("returned_items", str(returned)))
    try:
        await runtime.operations.async_record_audit(
            "ai_investigation_tool_invoked",
            actor=f"llm:{platform}",
            target_ids=(tool_name, *subject_ids)[:50],
            details=tuple(details),
        )
    except Exception:
        # Investigation is auditable or unavailable; it never silently runs
        # outside the evidence ledger.
        raise HomeAssistantError("HAMIE could not persist the investigation audit")


async def _audit_without_masking(
    hass: HomeAssistant,
    entry_id: str,
    tool_name: str,
    context: LLMContext,
    *,
    outcome: str,
    result: dict[str, Any] | None,
    subject_ids: tuple[str, ...] = (),
) -> None:
    """Audit an ALREADY-FAILED call without replacing why it failed.

    The strict rule -- investigation is auditable or it does not run -- is
    right on the success path: a completed investigation that left no ledger
    entry is exactly what the ledger exists to prevent.

    On a failure path it inverts into a bug. The call has already failed for
    a determined reason; if the audit write then raises, that second error
    replaces the first and the operator is told "HAMIE runtime is
    unavailable" when the truth was "output budget exceeded". Diagnosing the
    wrong fault is worse than a gap in the ledger for a call that produced no
    evidence anyway, so here the audit failure is logged and the original
    error survives.
    """
    try:
        await _audit(
            hass,
            entry_id,
            tool_name,
            context,
            outcome=outcome,
            result=result,
            subject_ids=subject_ids,
        )
    except Exception:  # noqa: BLE001 - must not mask the real failure
        _LOGGER.warning(
            "HAMIE could not audit failed investigation tool %s (outcome=%s); "
            "the original failure is being reported unchanged",
            tool_name,
            outcome,
            exc_info=True,
        )


Handler = Callable[
    [HomeAssistant, str, dict[str, Any]], Awaitable[dict[str, Any]]
]


def _audit_subject_ids(
    args: dict[str, Any], result: dict[str, Any] | None
) -> tuple[str, ...]:
    """Identify retrieved subjects without storing query text or values."""
    values: list[str] = []
    for key in ("entity_id", "incident_id"):
        value = args.get(key)
        if isinstance(value, str) and value:
            values.append(value[:255])
    if result is not None:
        items = result.get("items")
        if isinstance(items, list):
            for item in items[:20]:
                if not isinstance(item, dict):
                    continue
                value = item.get("entity_id") or item.get("incident_id")
                if isinstance(value, str) and value:
                    values.append(value[:255])
    return tuple(dict.fromkeys(values))


class _InvestigationTool(llm.Tool):
    """Small adapter enforcing one catalog and one audit path."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        parameters: vol.Schema,
        handler: Handler,
        entry_id: str,
    ) -> None:
        assert_tool_allowed(name, SecurityMode.INVESTIGATION)
        self.name = name
        self.description = description
        self.parameters = parameters
        self._handler = handler
        self._entry_id = entry_id

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: ToolInput,
        llm_context: LLMContext,
    ) -> dict[str, Any]:
        assert_tool_allowed(self.name, SecurityMode.INVESTIGATION)
        arguments = dict(tool_input.tool_args)
        audited = False
        try:
            result = await self._handler(hass, self._entry_id, arguments)
            if len(json.dumps(result, sort_keys=True, default=str)) > MAX_TOOL_CHARACTERS:
                await _audit_without_masking(
                    hass,
                    self._entry_id,
                    self.name,
                    llm_context,
                    outcome="blocked_output_budget",
                    result=result,
                    subject_ids=_audit_subject_ids(arguments, result),
                )
                audited = True
                raise HomeAssistantError("HAMIE investigation result exceeds its output budget")
        except asyncio.CancelledError:
            # Cancellation is not a tool failure and must stay cancellation:
            # converting it into HomeAssistantError would let a cancelled
            # investigation be recorded as one that ran and failed.
            await _audit_without_masking(
                hass,
                self._entry_id,
                self.name,
                llm_context,
                outcome="cancelled",
                result=None,
                subject_ids=_audit_subject_ids(arguments, None),
            )
            raise
        except HomeAssistantError:
            if not audited:
                await _audit_without_masking(
                    hass,
                    self._entry_id,
                    self.name,
                    llm_context,
                    outcome="failed",
                    result=None,
                    subject_ids=_audit_subject_ids(arguments, None),
                )
            raise
        except Exception as err:
            await _audit_without_masking(
                hass,
                self._entry_id,
                self.name,
                llm_context,
                outcome="failed",
                result=None,
                subject_ids=_audit_subject_ids(arguments, None),
            )
            raise HomeAssistantError("HAMIE investigation tool failed") from err
        # Success path keeps the strict rule: a completed investigation that
        # left no ledger entry is precisely what the ledger prevents.
        await _audit(
            hass,
            self._entry_id,
            self.name,
            llm_context,
            outcome="completed",
            result=result,
            subject_ids=_audit_subject_ids(arguments, result),
        )
        return result


async def _get_entity(
    hass: HomeAssistant, _entry_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    state = hass.states.get(args["entity_id"])
    if state is None:
        return {"evidence_status": "not_found", "entity_id": args["entity_id"]}
    return {"evidence_status": "observed", "entity": _safe_entity_state(state)}


async def _get_domain_entity(
    hass: HomeAssistant,
    entry_id: str,
    args: dict[str, Any],
    *,
    domain: str,
) -> dict[str, Any]:
    entity_id = str(args["entity_id"])
    if entity_id.partition(".")[0] != domain:
        return {
            "evidence_status": "invalid_subject",
            "entity_id": entity_id,
            "required_domain": domain,
        }
    return await _get_entity(hass, entry_id, args)


async def _get_automation(
    hass: HomeAssistant, entry_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    return await _get_domain_entity(hass, entry_id, args, domain="automation")


async def _get_script(
    hass: HomeAssistant, entry_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    return await _get_domain_entity(hass, entry_id, args, domain="script")


async def _search_entities(
    hass: HomeAssistant, _entry_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    query = args["query"].strip().casefold()
    limit = min(int(args.get("limit", 20)), MAX_TOOL_ITEMS)
    items = []
    for state in hass.states.async_all():
        friendly_name = str(state.attributes.get("friendly_name", ""))
        if query not in f"{state.entity_id} {friendly_name}".casefold():
            continue
        items.append(
            {
                "entity_id": state.entity_id,
                "friendly_name": friendly_name[:200] or None,
                "domain": state.domain,
            }
        )
        if len(items) >= limit:
            break
    return {
        "evidence_status": "observed",
        "items": items,
        "returned": len(items),
        "bounded": True,
    }


def _bounded_incident(value: dict[str, Any]) -> dict[str, Any]:
    """Return incident context sized for one provider tool response."""
    hypotheses = value.get("hypotheses", [])
    return {
        "incident_id": value.get("incident_id"),
        "title": value.get("title"),
        "category": value.get("category"),
        "root_cause": value.get("root_cause"),
        "evidence_status": value.get("evidence_status"),
        "confidence": value.get("confidence"),
        "priority": value.get("priority"),
        "lifecycle": value.get("lifecycle"),
        "finding_count": value.get(
            "finding_count", len(value.get("finding_ids", []))
        ),
        "affected_subject_ids": list(value.get("affected_subject_ids", []))[:25],
        "affected_subject_count": value.get("affected_subject_count", 0),
        "affected_systems": list(value.get("affected_systems", []))[:25],
        "hypotheses": [
            {
                "statement": item.get("statement"),
                "status": item.get("status"),
                "rationale": item.get("rationale"),
                "evidence_count": item.get("evidence_count", 0),
            }
            for item in hypotheses[:3]
            if isinstance(item, dict)
        ],
        "recommended_next_step": value.get("recommended_next_step"),
        "last_seen": value.get("last_seen"),
    }


async def _get_incident(
    hass: HomeAssistant, entry_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    try:
        return {
            "evidence_status": "observed",
            "incident": _bounded_incident(
                _runtime(hass, entry_id).operations.incident(args["incident_id"])
            ),
        }
    except KeyError:
        return {"evidence_status": "not_found", "incident_id": args["incident_id"]}


async def _search_incidents(
    hass: HomeAssistant, entry_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    result = _runtime(hass, entry_id).operations.query_incidents(
        search=args.get("query", ""),
        lifecycle="active",
        priority=args.get("priority", ""),
        limit=min(int(args.get("limit", 20)), MAX_TOOL_ITEMS),
    )
    return {
        "evidence_status": "observed",
        "total": result["total"],
        "returned": len(result["items"]),
        "items": [_bounded_incident(item) for item in result["items"]],
        "bounded": True,
    }


async def _dependencies(
    hass: HomeAssistant, entry_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    entity_id = args["entity_id"]
    result = _runtime(hass, entry_id).operations.query_findings(
        search=entity_id,
        filters={},
        sort="priority",
        offset=0,
        limit=8,
    )
    exact = [item for item in result["items"] if item.get("entity_id") == entity_id]
    evidence = [
        {
            "finding_id": item.get("finding_id"),
            "analyzer_id": item.get("analyzer_id"),
            "condition_key": item.get("condition_key"),
            "dependency_coverage": item.get("dependency_coverage"),
            "dependency_references": list(item.get("dependency_references", []))[:20],
            "safety_gate": item.get("safety_gate"),
        }
        for item in exact
    ]
    return {
        "evidence_status": "observed" if exact else "insufficient_evidence",
        "entity_id": entity_id,
        "finding_evidence": evidence,
        "returned": len(evidence),
        "coverage_note": (
            "References shown are limited to sources HAMIE captured successfully; "
            "absence is not proof of no dependency."
        ),
    }


async def _recent_changes(
    hass: HomeAssistant, entry_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    limit = min(int(args.get("limit", 20)), MAX_TOOL_ITEMS)
    audits = _runtime(hass, entry_id).projection.explorer.audits[-limit:]
    return {
        "evidence_status": "observed",
        "items": [
            {
                "event": item.event,
                "at": item.at.isoformat(),
                "actor": item.actor,
                "target_ids": list(item.target_ids[:20]),
                "details": {
                    key: value
                    for key, value in item.details
                    if key in _SAFE_AUDIT_DETAIL_KEYS
                },
            }
            for item in audits
        ],
        "returned": len(audits),
    }


async def _source_context(
    hass: HomeAssistant, entry_id: str, _args: dict[str, Any]
) -> dict[str, Any]:
    entry = hass.config_entries.async_get_entry(entry_id)
    options = dict(entry.options) if entry is not None else {}
    source = str(options.get("authoritative_source_repository", "")).strip()
    deployment = str(options.get("deployment_target", "")).strip()
    return {
        "evidence_status": (
            "configured_not_verified" if source and deployment else "insufficient_evidence"
        ),
        "authoritative_source_repository": source or None,
        "deployment_target": deployment or None,
        "deployment_adapter_mode": options.get("deployment_adapter_mode", "disabled"),
        "git_status": "not_captured",
        "source_deployment_parity": "not_captured",
        "note": "HAMIE will not infer a source from filesystem timestamps or discovery order.",
    }


async def _validate_change(
    hass: HomeAssistant, entry_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    proposal = args["proposal"]
    if not isinstance(proposal, dict):
        raise HomeAssistantError("proposal must be an object")
    serialized = json.dumps(proposal, sort_keys=True, default=str)

    def _keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return {
                *(str(key).casefold() for key in value),
                *(nested for item in value.values() for nested in _keys(item)),
            }
        if isinstance(value, list):
            return {nested for item in value for nested in _keys(item)}
        return set()

    forbidden = {"approved", "execute", "shell", "ssh", "token", "secret"} & _keys(
        proposal
    )
    source_context = await _source_context(hass, entry_id, {})
    errors = []
    if len(serialized) > 8_000:
        errors.append("proposal exceeds its planning input budget")
    if forbidden:
        errors.append("proposal contains execution or credential-shaped fields")
    required_fields = (
        "incident_id",
        "proposal_id",
        "summary",
        "root_cause",
        "confidence",
        "source_repository",
        "files_to_change",
        "production_targets",
        "blast_radius",
        "validation_plan",
        "rollback_plan",
        "requires_restart",
        "requires_reload",
        "destructive",
        "approval_state",
    )
    for required in required_fields:
        if required not in proposal:
            errors.append(f"missing required field: {required}")
    for key in (
        "files_to_change",
        "production_targets",
        "blast_radius",
        "validation_plan",
        "rollback_plan",
    ):
        value = proposal.get(key)
        if value is not None and (
            not isinstance(value, list)
            or len(value) > 100
            or any(not isinstance(item, str) or not item.strip() for item in value)
        ):
            errors.append(f"{key} must be a bounded list of non-empty strings")
    confidence = proposal.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, int | float) or not 0 <= confidence <= 1
    ):
        errors.append("confidence must be between zero and one")
    for key in ("requires_restart", "requires_reload", "destructive"):
        value = proposal.get(key)
        if value is not None and not isinstance(value, bool):
            errors.append(f"{key} must be boolean")
    if proposal.get("approval_state") not in {None, "pending"}:
        errors.append("approval_state must remain pending during planning")
    if source_context["evidence_status"] != "configured_not_verified":
        errors.append("source/deployment provenance is not configured")
    elif proposal.get("source_repository") != source_context["authoritative_source_repository"]:
        errors.append("proposal source does not match the configured authoritative repository")
    return {
        "evidence_status": "validated" if not errors else "blocked",
        "valid_for_planning_only": not errors,
        "execution_authorized": False,
        "errors": errors,
        "provenance": source_context,
    }


def _tools(entry_id: str) -> list[llm.Tool]:
    bounded_id = vol.All(str, vol.Length(min=1, max=255))
    bounded_query = vol.All(str, vol.Length(min=1, max=200))
    optional_query = vol.All(str, vol.Length(max=200))
    entity_schema = vol.Schema({vol.Required("entity_id"): bounded_id})
    tools: list[llm.Tool] = [
        _InvestigationTool(
            name="hamie_get_entity",
            description="Get one Home Assistant entity using a privacy-bounded state view.",
            parameters=entity_schema,
            handler=_get_entity,
            entry_id=entry_id,
        ),
        _InvestigationTool(
            name="hamie_search_entities",
            description="Search entity identifiers and names without exporting states.",
            parameters=vol.Schema(
                {
                    vol.Required("query"): bounded_query,
                    vol.Optional("limit", default=20): vol.All(int, vol.Range(min=1, max=50)),
                }
            ),
            handler=_search_entities,
            entry_id=entry_id,
        ),
        _InvestigationTool(
            name="hamie_get_automation",
            description="Get one automation entity through the same read-only entity view.",
            parameters=entity_schema,
            handler=_get_automation,
            entry_id=entry_id,
        ),
        _InvestigationTool(
            name="hamie_get_script",
            description="Get one script entity through the same read-only entity view.",
            parameters=entity_schema,
            handler=_get_script,
            entry_id=entry_id,
        ),
        _InvestigationTool(
            name="hamie_get_incident",
            description="Get one durable incident with evidence-qualified hypotheses.",
            parameters=vol.Schema({vol.Required("incident_id"): bounded_id}),
            handler=_get_incident,
            entry_id=entry_id,
        ),
        _InvestigationTool(
            name="hamie_search_incidents",
            description="Search HAMIE's prioritized incident set instead of raw findings.",
            parameters=vol.Schema(
                {
                    vol.Optional("query", default=""): optional_query,
                    vol.Optional("priority", default=""): vol.In({"", "p0", "p1", "p2", "p3", "info"}),
                    vol.Optional("limit", default=20): vol.All(int, vol.Range(min=1, max=50)),
                }
            ),
            handler=_search_incidents,
            entry_id=entry_id,
        ),
        _InvestigationTool(
            name="hamie_get_dependencies",
            description="Get bounded captured references and coverage limits for an entity.",
            parameters=entity_schema,
            handler=_dependencies,
            entry_id=entry_id,
        ),
        _InvestigationTool(
            name="hamie_get_target_writers",
            description="Get captured automation/script writers for one target entity.",
            parameters=entity_schema,
            handler=_dependencies,
            entry_id=entry_id,
        ),
        _InvestigationTool(
            name="hamie_get_recent_changes",
            description="Get recent secret-free HAMIE audit events.",
            parameters=vol.Schema(
                {vol.Optional("limit", default=20): vol.All(int, vol.Range(min=1, max=50))}
            ),
            handler=_recent_changes,
            entry_id=entry_id,
        ),
    ]
    for name, description in (
        ("hamie_get_source", "Get explicitly configured source/deployment roles."),
        ("hamie_get_git_status", "Get configured provenance and honest Git evidence availability."),
        ("hamie_compare_source_deployment", "Get configured source/deployment parity evidence."),
    ):
        tools.append(
            _InvestigationTool(
                name=name,
                description=description,
                parameters=vol.Schema({}),
                handler=_source_context,
                entry_id=entry_id,
            )
        )
    tools.append(
        _InvestigationTool(
            name="hamie_validate_proposed_change",
            description="Validate a proposal envelope for planning only; never approve or execute it.",
            parameters=vol.Schema({vol.Required("proposal"): dict}),
            handler=_validate_change,
            entry_id=entry_id,
        )
    )
    assert {item.name for item in tools} == INVESTIGATION_TOOLS
    return tools


class HamieInvestigationAPI(llm.API):
    """Read-only HAMIE API exposed through Home Assistant's LLM/MCP layer."""

    async def async_get_api_instance(self, llm_context: LLMContext) -> APIInstance:
        return APIInstance(
            api=self,
            api_prompt=(
                "You are in HAMIE Investigation Mode. Use only the bounded tools to "
                "gather evidence. Distinguish verified evidence, inference, missing "
                "evidence, and normal behavior. You cannot approve or execute changes."
            ),
            llm_context=llm_context,
            tools=_tools(self.id.removeprefix("hamie-investigation-")),
        )


#: hass.data key holding the unregister callback per config entry, so a
#: second setup without an intervening unload cannot leave a stale API
#: registered under the same id.
_REGISTERED = f"{DOMAIN}_llm_api_registered"


def api_id_for(entry_id: str) -> str:
    """The stable LLM API id this integration registers for one config entry."""
    return f"hamie-investigation-{entry_id}"


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> None:
    """Home Assistant's `llm` integration-platform hook.

    THIS IS WHY THE HOOK EXISTS AT ALL, and it is not error suppression.

    Home Assistant's `llm` component discovers integration platforms by
    module name: any loaded integration exposing a module called
    `<integration>.llm` is treated as an LLM tools platform, and
    `homeassistant/components/llm/__init__.py::async_get_tools` calls
    `platform.async_get_tools(hass, llm_context, api_id)` on it inside a
    bare `except Exception` that logs
    "Error getting tools from LLM platform %s". This module is named
    `llm.py` because it holds HAMIE's LLM integration, which made HAMIE a
    platform by accident and produced a recurring AttributeError on every
    Assist conversation.

    The protocol's own contract is
    `Return None when the integration has nothing for the given API`, and
    that is the honest answer here. HAMIE's investigation tools are bound to
    a specific config entry and reachable only through the API HAMIE
    registers itself (see `HamieInvestigationAPI`); nothing consumes tools
    contributed through this hook for that API, and contributing them to
    Home Assistant's built-in Assist API would put house-wide diagnostic
    tools in front of every voice conversation. That is a trust-boundary
    decision, not a default.

    Deliberately a `@callback` returning immediately: the caller runs this on
    the event loop, so it must never do I/O.
    """
    return None


async def async_setup_api(hass: HomeAssistant, entry: Any) -> None:
    """Register one config-entry-bound API and its automatic unload callback."""
    registry: dict[str, Any] = hass.data.setdefault(_REGISTERED, {})
    stale = registry.pop(entry.entry_id, None)
    if stale is not None:
        # A previous registration survived without its unload running.
        # Registering a second API under the same id would either raise or
        # shadow the first; releasing the old one first is idempotent.
        try:
            stale()
        except Exception:  # noqa: BLE001 - a stale callback must not block setup
            _LOGGER.debug("HAMIE stale LLM API unregister failed", exc_info=True)

    unregister = llm.async_register_api(
        hass,
        HamieInvestigationAPI(
            hass=hass,
            id=api_id_for(entry.entry_id),
            name="HAMIE Investigation",
        ),
    )
    registry[entry.entry_id] = unregister

    @callback
    def _release() -> None:
        registry.pop(entry.entry_id, None)
        unregister()

    entry.async_on_unload(_release)
