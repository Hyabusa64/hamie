"""Presentation-neutral RC7-RC9 query and command service."""

from __future__ import annotations

import asyncio
import logging

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from ..connectors.base import pipeline_failure_snapshot
from ..connectors.manager import ConnectorManager
from ..domain.common import require_utc, stable_digest
from ..domain.findings import Finding, FindingLifecycle
from ..domain.intelligence import (
    AI_SCHEMA_VERSION,
    MAX_AUDIT_RECORDS,
    MAX_GRAPH_EDGES,
    MAX_GRAPH_NODES,
    MAX_GROUPING_RULES,
    MAX_RECOMMENDATIONS,
    MAX_SUPPRESSION_RULES,
    AIAnalysisCoverage,
    AIRecommendation,
    AIReviewState,
    AuditRecord,
    ExplorerIndex,
    GroupActionPreview,
    GroupingRule,
    GroupSourceBinding,
    SuppressionAction,
    SuppressionRule,
    apply_suppression_reviews,
    mark_recommendations_stale,
    matcher_matches,
)
from ..domain.analysis_state import AnalysisInputs, evaluate
from ..domain.durable_baseline import (
    BASELINE_SCHEMA_VERSION,
    MAX_BASELINE_FINDING_IDS,
    AnalysisBaseline,
)
from ..domain.capability import (
    CapabilityResult,
    CapabilityVerdict,
    configuration_fingerprint,
    evaluate_gate,
)
from ..domain.context_budget import (
    MAX_COMPACT_INCIDENT_CHARACTERS,
    MAX_PROVIDER_INCIDENTS,
    ContextBudget,
    compact_incident,
    fit_payload,
    payload_characters,
)
from ..domain.incidents import (
    ACTIVE_INCIDENT_STATES,
    Incident,
    IncidentLifecycle,
    IncidentPriority,
    set_incident_lifecycle,
)
from ..domain.llm_proposal import parse_llm_proposed_action
from ..domain.remediation_llm_proposal import (
    ProposalRejection,
    validate_llm_proposed_action,
)
from ..domain.reviews import (
    ACTION_STATE,
    ALLOWED_PRIOR_STATES,
    ReviewAction,
    ReviewRecord,
)
from ..domain.security import security_findings
from .application_service import (
    IdempotencyConflictError,
    InvalidReviewTransitionError,
    RevisionConflictError,
)
from .persistence import (
    GenerationConflictError,
    IdempotencyRecord,
    PersistenceUnitOfWorkPort,
    RepositoryState,
)
from .ports import Clock
from .scan_coordinator import ProjectionPort, SystemClock

_LOGGER = logging.getLogger(__name__)



class GroupNotFoundError(KeyError):
    """Requested deterministic group does not exist."""


class GroupPreviewConflictError(RuntimeError):
    """Frozen group preview no longer matches canonical state."""


class AIRequestError(RuntimeError):
    """A typed, non-connector AI request failure.

    Raised for conditions `async_request_ai` rejects before ever
    contacting a connector (e.g. no eligible findings exist, or too
    many were selected) -- carrying a stable `.code` so
    `connectors.base.classify_connector_failure`'s existing typed-error
    branch (`getattr(err, "code", None)`) reports it accurately instead
    of falling through to its generic text-matching heuristics, whose
    final fallback is "unreachable". Without this, "no findings to
    analyze yet" and "Ollama is unreachable" were indistinguishable to
    the user -- an unrelated, connector-independent business-logic
    condition must never be reported as a connector reachability
    problem.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


#: Operator-created marker arming Gate H's analysis-failure injection. Absent
#: on every ordinary installation, which is what keeps the hook off by default.
ANALYSIS_FAIL_MARKER = ".hamie_analysis_fail_group"


class InjectedAnalysisFailure(RuntimeError):
    """Deterministic provider failure for ONE named group, operator-armed.

    Gate H needs proof that a group which is selected, attempted, and then
    rejected is excluded from achieved coverage -- and that proof cannot be
    obtained from the real provider, which (correctly) keeps succeeding.
    Sabotaging Ollama or the AI PC to force a failure would break the
    protected invariant HAMIE exists to defend, so the failure is injected
    here instead.

    Deliberately constrained: armed only by an operator-created marker file
    naming one exact group id, raised INSTEAD of the provider call so the real
    connector and the AI PC are never touched, and entering the loop's normal
    exception path so every accounting rule is exercised rather than bypassed.
    Reachable from no WebSocket command, service, or model-facing tool.
    """

    #: Mirrors a connector failure's typed code so classification treats it
    #: exactly like a real provider error.
    code = "provider_execution_failed"


def read_analysis_fail_group(config_dir: str) -> str:
    """Group id whose analysis should be failed, or "" for normal operation.

    BLOCKING: opens a file, so callers must use asyncio.to_thread.
    """
    import os

    try:
        with open(os.path.join(config_dir, ANALYSIS_FAIL_MARKER), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


class MaintenanceOperationsService:
    """Bounded explorer, group, suppression, connector, and AI API."""

    def __init__(
        self,
        repository: PersistenceUnitOfWorkPort,
        projection: ProjectionPort,
        connectors: ConnectorManager,
        *,
        clock: Clock | None = None,
        options: dict[str, Any] | None = None,
        fixture_config_dir: str | None = None,
    ) -> None:
        self._repository = repository
        self._projection = projection
        self._connectors = connectors
        # Gate H's failure-injection hook only ever LOOKS for its marker file
        # here. None disables it outright.
        self._fixture_config_dir = fixture_config_dir
        self._clock = clock or SystemClock()
        self._options = dict(options or {})
        self._ai_analysis_in_flight = False
        self._last_ai_coverage: AIAnalysisCoverage | None = None
        self._last_ai_recommendations: tuple[AIRecommendation, ...] = ()
        self._last_ai_failed_group_ids: tuple[str, ...] = ()
        #: Groups whose provider call actually produced a usable response.
        #: Coverage must be reported from THIS, not from what was planned.
        self._last_ai_succeeded_group_ids: tuple[str, ...] = ()
        #: The scan the last completed analysis ran against, so staleness is
        #: a fact rather than an inference from timestamps.
        self._last_ai_scan_id: str | None = None

    def query_findings(self, **kwargs: Any) -> dict[str, Any]:
        """Query the shared in-memory index without Store I/O."""
        return self._index().query_findings(**kwargs)

    def query_groups(self, **kwargs: Any) -> dict[str, Any]:
        """Query deterministic groups from the shared projection."""
        return self._index().query_groups(**kwargs)

    def suppression_rules(self) -> tuple[dict[str, Any], ...]:
        """Return bounded declarative rule metadata from the in-memory index."""
        return tuple(
            {
                "rule_id": item.rule_id,
                "name": item.name,
                "enabled": item.enabled,
                "scope": item.scope,
                "matcher": dict(item.matcher),
                "reason": item.reason,
                "created_at": item.created_at.isoformat(),
                "created_by": item.created_by,
                "expiration": item.expiration.isoformat() if item.expiration else None,
                "affected_analyzer_ids": list(item.affected_analyzer_ids),
                "action": item.action.value,
                "preview_count": item.preview_count,
                "last_match_count": item.last_match_count,
                "revision": item.revision,
            }
            for item in self._index().suppression_rules
        )

    def overview(self) -> dict[str, Any]:
        """Return bounded operations-center overview data."""
        result = self._index().overview()
        incidents = self._incident_projection()
        active = tuple(item for item in incidents if item.lifecycle in ACTIVE_INCIDENT_STATES)
        priority_order = {
            IncidentPriority.P0: 0,
            IncidentPriority.P1: 1,
            IncidentPriority.P2: 2,
            IncidentPriority.P3: 3,
            IncidentPriority.INFO: 4,
        }
        ordered = sorted(
            active,
            key=lambda item: (priority_order[item.priority], -item.confidence, item.incident_id),
        )
        represented = {finding_id for item in active for finding_id in item.finding_ids}
        open_findings = result.get("open_findings", 0)
        result.update(
            {
                "analysis": self.analysis_status(),
                "capability": self.capability_status(),
                "active_incidents": len(active),
                "incident_priority_counts": {
                    priority.value: sum(item.priority is priority for item in active)
                    for priority in IncidentPriority
                },
                "highest_priority_incidents": [
                    item.public_dict() for item in ordered[:5]
                ],
                "incident_context_reduction": (
                    round(1 - (len(active) / open_findings), 3)
                    if isinstance(open_findings, int) and open_findings
                    else 1.0
                ),
                "incident_represented_findings": len(represented),
            }
        )
        return result

    def query_incidents(
        self,
        *,
        search: str = "",
        lifecycle: str = "active",
        priority: str = "",
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return one bounded incident page from committed memory."""
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("incident page bounds are invalid")
        if lifecycle not in {"active", "all", *(item.value for item in IncidentLifecycle)}:
            raise ValueError("incident lifecycle filter is invalid")
        if priority and priority not in {item.value for item in IncidentPriority}:
            raise ValueError("incident priority filter is invalid")
        values = list(self._incident_projection())
        if lifecycle == "active":
            values = [item for item in values if item.lifecycle in ACTIVE_INCIDENT_STATES]
        elif lifecycle != "all":
            values = [item for item in values if item.lifecycle.value == lifecycle]
        if priority:
            values = [item for item in values if item.priority.value == priority]
        normalized_search = search.strip().casefold()
        if normalized_search:
            values = [
                item
                for item in values
                if normalized_search
                in " ".join(
                    (
                        item.incident_id,
                        item.title,
                        item.category,
                        item.root_cause,
                        *item.affected_subject_ids,
                    )
                ).casefold()
            ]
        priority_order = {"p0": 0, "p1": 1, "p2": 2, "p3": 3, "info": 4}
        values.sort(
            key=lambda item: (
                priority_order[item.priority.value],
                -item.confidence,
                -item.last_seen.timestamp(),
                item.incident_id,
            )
        )
        return {
            "offset": offset,
            "limit": limit,
            "total": len(values),
            "items": [item.public_dict() for item in values[offset : offset + limit]],
        }

    def incident(self, incident_id: str) -> dict[str, Any]:
        """Return one incident with bounded evidence identifiers."""
        value = next(
            (item for item in self._incident_projection() if item.incident_id == incident_id),
            None,
        )
        if value is None:
            raise KeyError(incident_id)
        return value.public_dict(include_evidence_ids=True)

    async def async_set_incident_lifecycle(
        self,
        incident_id: str,
        lifecycle: IncidentLifecycle,
        *,
        expected_revision: int,
        actor: str,
        token: str,
    ) -> dict[str, Any]:
        """Persist one explicit, revision-bound incident decision."""
        state = await self._repository.async_load()
        if self._idempotency(state, token, "incident_lifecycle", incident_id):
            existing = next(
                (item for item in state.incidents if item.incident_id == incident_id),
                None,
            )
            if existing is None:
                raise KeyError(incident_id)
            return existing.public_dict(include_evidence_ids=True)
        current = next(
            (item for item in state.incidents if item.incident_id == incident_id), None
        )
        if current is None:
            raise KeyError(incident_id)
        if current.content_revision != expected_revision:
            raise RevisionConflictError("incident revision changed")
        updated = set_incident_lifecycle(current, lifecycle, at=self._clock.now())
        audit = self._audit(
            "incident_lifecycle_changed",
            actor,
            (incident_id,),
            (("lifecycle", lifecycle.value),),
            token=token,
        )
        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=state.projection_revision + 1,
            incidents=tuple(
                updated if item.incident_id == incident_id else item
                for item in state.incidents
            ),
            idempotency=(
                *state.idempotency,
                IdempotencyRecord(
                    token,
                    "incident_lifecycle",
                    incident_id,
                    state.projection_revision + 1,
                ),
            )[-128:],
            audits=(*state.audits, audit)[-MAX_AUDIT_RECORDS:],
        )
        await self._commit(state, next_state)
        return updated.public_dict(include_evidence_ids=True)

    def dependency_graph(self, **kwargs: Any) -> dict[str, Any]:
        """Return one bounded selected dependency graph."""
        return self._index().dependency_graph(**kwargs)

    async def async_dependency_graph(self, **kwargs: Any) -> dict[str, Any]:
        """Augment the authoritative local graph with bounded optional evidence."""
        graph = self.dependency_graph(**kwargs)
        subject_ids = tuple(
            str(item["node_id"]) for item in graph["nodes"][:32] if item.get("node_id")
        )
        edges = list(graph["edges"])
        nodes = {str(item["node_id"]): item for item in graph["nodes"]}
        partial = graph["coverage"] != "complete"
        for connector_id, operation in (
            ("mcp", self._connectors.async_mcp_evidence),
            ("hkg", self._connectors.async_hkg_relationships),
        ):
            if connector_id not in self._connectors.enabled_ids:
                partial = True
                continue
            try:
                result = await operation(subject_ids)
                relationships = result.get("relationships", [])
                if not isinstance(relationships, list):
                    raise ValueError("connector relationships must be an array")
                for item in relationships[:64]:
                    edge = self._external_edge(connector_id, item)
                    if edge is None:
                        partial = True
                        continue
                    key = (
                        edge["source_id"],
                        edge["target_id"],
                        edge["relationship_type"],
                    )
                    if any(
                        (
                            existing["source_id"],
                            existing["target_id"],
                            existing["relationship_type"],
                        )
                        == key
                        for existing in edges
                    ):
                        continue
                    if len(edges) >= MAX_GRAPH_EDGES:
                        partial = True
                        break
                    for node_id in (edge["source_id"], edge["target_id"]):
                        if node_id not in nodes and len(nodes) < MAX_GRAPH_NODES:
                            nodes[node_id] = {
                                "node_id": node_id,
                                "kind": "supplemental_object",
                                "label": node_id,
                            }
                    if edge["source_id"] in nodes and edge["target_id"] in nodes:
                        edges.append(edge)
                    else:
                        partial = True
                partial |= result.get("coverage") != "complete"
            except Exception as err:
                partial = True
                await self.async_record_audit(
                    "connector_evidence_unavailable",
                    actor="hamie_dependency_projection",
                    target_ids=(connector_id, *subject_ids[:10]),
                    details=(("error", type(err).__name__),),
                )
        return {
            **graph,
            "nodes": list(nodes.values())[:MAX_GRAPH_NODES],
            "edges": edges[:MAX_GRAPH_EDGES],
            "coverage": "partial" if partial else "complete",
            "safe_to_remove": graph["safe_to_remove"]
            and not any(item.get("source") in {"mcp", "hkg"} for item in edges),
        }

    @staticmethod
    def _external_edge(connector_id: str, value: object) -> dict[str, Any] | None:
        """Validate one supplemental edge without trusting connector authority."""
        if not isinstance(value, dict):
            return None
        required = {
            "source_id",
            "target_id",
            "relationship_type",
            "source_revision",
            "confidence",
            "verified_at",
            "stale",
        }
        if not required <= set(value) or not isinstance(value["stale"], bool):
            return None
        texts = {
            key: value[key]
            for key in required - {"stale"}
            if isinstance(value[key], str) and value[key] and len(value[key]) <= 256
        }
        if len(texts) != len(required) - 1:
            return None
        verified_at = texts.pop("verified_at")
        try:
            verified_time = datetime.fromisoformat(verified_at)
        except ValueError:
            return None
        if (
            verified_time.tzinfo is None
            or verified_time.utcoffset() is None
            or texts["confidence"] not in {"low", "medium", "high"}
        ):
            return None
        edge = {
            **texts,
            "source": connector_id,
            "last_verified": verified_at,
            "stale": value["stale"],
        }
        if connector_id == "mcp":
            capability = value.get("capability")
            if not isinstance(capability, str) or not capability:
                return None
            edge["capability"] = capability
        return edge

    def audit_page(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        event_type: str = "",
        actor: str = "",
        target: str = "",
        outcome: str = "",
        date_from: str = "",
        date_to: str = "",
        proposal: str = "",
        finding: str = "",
    ) -> dict[str, Any]:
        """Return newest-first bounded audit records with server-side filters."""
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("audit pagination is outside bounds")
        index = self._index()
        values = tuple(reversed(index.audits))
        lower_bound = (
            require_utc(datetime.fromisoformat(date_from), "date_from")
            if date_from
            else None
        )
        upper_bound = (
            require_utc(datetime.fromisoformat(date_to), "date_to") if date_to else None
        )
        values = tuple(
            item
            for item in values
            if (not event_type or item.event == event_type)
            and (not actor or actor.casefold() in item.actor.casefold())
            and (
                not target
                or any(
                    target.casefold() in value.casefold() for value in item.target_ids
                )
            )
            and (
                not outcome
                or outcome.casefold()
                in dict(item.details).get("outcome", item.event).casefold()
            )
            and (lower_bound is None or item.at >= lower_bound)
            and (upper_bound is None or item.at <= upper_bound)
            and (not proposal or proposal in item.target_ids)
            and (not finding or finding in item.target_ids)
        )
        return {
            "generation": index.generation,
            "revision": index.projection_revision,
            "offset": offset,
            "limit": limit,
            "total": len(values),
            "items": [
                {
                    "audit_id": item.audit_id,
                    "event": item.event,
                    "at": item.at.isoformat(),
                    "actor": item.actor,
                    "target_ids": list(item.target_ids),
                    "details": dict(item.details),
                }
                for item in values[offset : offset + limit]
            ],
        }

    def audit_export(self) -> dict[str, Any]:
        """Return one bounded secret-free export from projection memory."""
        page = self.audit_page(offset=0, limit=100)
        records = list(page["items"])
        offset = len(records)
        while offset < page["total"] and offset < MAX_AUDIT_RECORDS:
            current = self.audit_page(
                offset=offset, limit=min(100, page["total"] - offset)
            )
            records.extend(current["items"])
            offset += len(current["items"])
        return {
            "schema_version": 1,
            "revision": page["revision"],
            "records": records,
        }

    async def async_clear_audit(
        self,
        *,
        expected_revision: int,
        token: str,
        actor: str,
    ) -> dict[str, Any]:
        """Clear history idempotently while retaining a secret-free clear record."""
        state = await self._repository.async_load()
        target = "audit_history"
        replay = self._idempotency(state, token, "clear_audit", target)
        if replay:
            return {
                "cleared": True,
                "revision": state.projection_revision,
                "replayed": True,
            }
        if state.projection_revision != expected_revision:
            raise RevisionConflictError("audit revision changed")
        next_revision = state.projection_revision + 1
        audit = self._audit(
            "audit_history_cleared",
            actor,
            (),
            (("prior_record_count", str(len(state.audits))),),
            token=token,
        )
        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=next_revision,
            audits=(audit,),
            idempotency=(
                *state.idempotency,
                IdempotencyRecord(token, "clear_audit", target, next_revision),
            )[-128:],
        )
        await self._commit(state, next_state)
        return {"cleared": True, "revision": next_revision, "replayed": False}

    def recommendations_page(
        self, *, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        """Return bounded advisory records without executable state."""
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("recommendation pagination is outside bounds")
        index = self._index()
        values = tuple(reversed(index.recommendations))
        return {
            "generation": index.generation,
            "offset": offset,
            "limit": limit,
            "total": len(values),
            "items": [
                {
                    "recommendation_id": item.recommendation_id,
                    "generated_at": (item.generated_at or item.created_at).isoformat(),
                    "evidence_first_observed_at": (
                        item.evidence_first_observed_at.isoformat()
                        if item.evidence_first_observed_at
                        else None
                    ),
                    "evidence_last_observed_at": (
                        item.evidence_last_observed_at.isoformat()
                        if item.evidence_last_observed_at
                        else None
                    ),
                    "analysis_started_at": (
                        item.analysis_started_at or item.created_at
                    ).isoformat(),
                    "analysis_completed_at": (
                        item.analysis_completed_at or item.created_at
                    ).isoformat(),
                    "source_scan_id": item.source_scan_id,
                    "source_scan_completed_at": (
                        item.source_scan_completed_at.isoformat()
                        if item.source_scan_completed_at
                        else None
                    ),
                    "source_finding_revision": item.source_finding_revision,
                    "recommendation_revision": item.recommendation_revision,
                    "finding_ids": list(item.finding_ids),
                    "group_ids": list(item.group_ids),
                    "summary": item.summary,
                    "probable_causes": list(item.probable_causes),
                    "recommended_checks": list(item.recommended_checks),
                    "proposed_repair_plan": list(item.proposed_repair_plan),
                    "confidence": item.confidence,
                    "assumptions": list(item.assumptions),
                    "missing_evidence": list(item.missing_evidence),
                    "risk_notes": list(item.risk_notes),
                    "review_state": item.review_state.value,
                    "stale": item.stale,
                    "status": (
                        "Evidence changed; refresh required"
                        if item.stale
                        else item.review_state.value
                    ),
                    # Request scope: what the run that produced THIS
                    # recommendation selected. Named accordingly so it can
                    # never be mistaken for the authoritative achieved
                    # counts in the analysis state.
                    "coverage": {
                        "scope": "request",
                        "total_findings": item.analysis_total_findings,
                        "request_eligible_findings": item.analysis_eligible_findings,
                        "request_selected_findings": item.analysis_selected_findings,
                        "request_skipped_findings": item.analysis_skipped_findings,
                        "request_groups_detected": item.root_cause_groups_detected,
                        "request_groups_selected": item.root_cause_groups_analyzed,
                        "request_groups_skipped": item.root_cause_groups_skipped,
                        "selection_reason": item.selection_reason,
                        "coverage": item.coverage_state,
                    },
                    "risk": ("review required" if item.risk_notes else "advisory only"),
                    "repairability": (
                        "Manual repair available"
                        if item.proposed_repair_plan
                        else "Advisory only"
                    ),
                }
                for item in values[offset : offset + limit]
            ],
        }

    def security_page(self) -> dict[str, Any]:
        """Return only evidence-backed, redacted security decisions."""
        items = tuple(item.public_dict() for item in security_findings(self._options))
        return {
            "items": list(items),
            "total": len(items),
            "evidence_sources": [
                "HAMIE connector configuration",
            ],
            "unavailable_sources": [
                "Home Assistant access-token inventory",
                "host filesystem secret scanning",
                "backup encryption inventory",
                "network port inventory",
            ],
        }

    # ------------------------------------------------------------------
    # Provider capability (domain/capability.py)
    # ------------------------------------------------------------------

    def provider_configuration(self) -> dict[str, Any]:
        """The material provider settings a capability verdict is bound to.

        Deliberately includes HAMIE's own response-schema and system-prompt
        identity: changing what HAMIE asks for invalidates a verdict just as
        surely as the operator swapping the model, and forgetting that is how
        a stale "capable" survives a contract change.

        Contains no credential: the API key is not a behavioural input and
        must never reach a fingerprint that gets logged or displayed.
        """
        from ..connectors.schemas import SYSTEM_INSTRUCTIONS

        options = self._options
        return {
            "provider": str(options.get("ollama_provider_type", "ollama")),
            "connection_method": str(options.get("ai_connection_method", "direct")),
            "model": str(options.get("ollama_model", "")),
            "base_url": str(options.get("ollama_base_url", "")),
            "ai_task_entity_id": str(options.get("ai_task_entity_id", "")),
            "temperature": float(options.get("ollama_temperature", 0.2) or 0),
            "maximum_input_characters": int(
                options.get("ollama_maximum_input_characters", 16_000)
            ),
            "maximum_output_tokens": int(
                options.get("ollama_maximum_output_tokens", 1_024)
            ),
            "think": bool(options.get("ollama_think", False)),
            "capabilities": tuple(options.get("ollama_capabilities", ()) or ()),
            "response_schema_version": 1,
            "system_instructions_digest": stable_digest(SYSTEM_INSTRUCTIONS)[:16],
        }

    def capability_fingerprint(self) -> str:
        return configuration_fingerprint(self.provider_configuration())

    def capability_status(self) -> dict[str, Any]:
        """Capability evidence plus whether bulk analysis is permitted."""
        config = self.provider_configuration()
        result = self._capability_projection()
        gate = evaluate_gate(
            result,
            current_fingerprint=configuration_fingerprint(config),
            now=self._clock.now(),
        )
        return {
            "provider": config["provider"],
            "connection_method": config["connection_method"],
            "model": config["model"] or None,
            "configuration_fingerprint": configuration_fingerprint(config),
            "result": result.as_dict() if result is not None else None,
            "gate": gate.as_dict(),
            "analysis_permitted": gate.permitted,
        }

    async def async_probe_capability(self, *, actor: str) -> dict[str, Any]:
        """Measure the configured model against HAMIE's contract and persist it.

        Runs the probes through the same analyze path production uses, so a
        pass here means the real contract was satisfied, not a simplified
        stand-in of it.
        """
        from .capability_probe import CapabilityProbeRunner

        config = self.provider_configuration()
        fingerprint = configuration_fingerprint(config)
        runner = CapabilityProbeRunner(self._connectors.async_analyze)
        _LOGGER.info(
            "HAMIE capability probe starting: provider=%s model=%s method=%s",
            config["provider"], config["model"], config["connection_method"],
        )
        result = await runner.async_run(
            provider=str(config["provider"]),
            model=str(config["model"]),
            configuration_fingerprint=fingerprint,
        )
        _LOGGER.info(
            "HAMIE capability probe finished: verdict=%s passed=%d/%d median_latency=%sms",
            result.verdict.value, result.probes_passed, result.probes_attempted,
            result.median_latency_ms,
        )
        await self._async_persist_capability(result, actor=actor)
        return self.capability_status()

    async def _async_persist_capability(
        self, result: CapabilityResult, *, actor: str
    ) -> None:
        state = await self._repository.async_load()
        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=state.projection_revision + 1,
            capability=result,
        )
        await self._commit(state, next_state)
        await self.async_record_audit(
            "ai_capability_probed",
            actor=actor,
            target_ids=(result.model or "unknown_model",),
            details=(
                ("verdict", result.verdict.value),
                ("provider", result.provider),
                ("probes_passed", f"{result.probes_passed}/{result.probes_attempted}"),
                ("fingerprint", result.configuration_fingerprint[:16]),
                ("last_failure", result.last_failure_category or "none"),
            ),
        )

    async def async_reconcile_incidents(
        self, *, priority: str = "", limit: int = 50
    ) -> dict[str, Any]:
        """Re-verify current validity for active incidents. READ-ONLY.

        Answers only Axis A -- is the defect still real now. Repairability is
        a separate question already answered by
        application/incident_remediation (InvestigationDisposition), and the
        two are reported side by side because conflating them is what made a
        queue of 22 genuine defects look like false positives when zero
        repair candidates could be derived from them.
        """
        from ..domain.incident_reconciliation import (
            ReconciliationObservation,
            reconcile,
        )

        scan_id = self._current_scan_id()
        observed_at = self._clock.now()
        incidents = [
            item
            for item in self._incident_projection()
            if item.is_active and (not priority or item.priority.value == priority)
        ][:limit]

        subjects: set[str] = set()
        for item in incidents:
            subjects.update(
                str(s).split(":")[-1]
                for s in item.affected_subject_ids
                if "." in str(s)
            )
        # Fail closed. An unbound reader returns None for every entity, which
        # is indistinguishable from "the entity is absent" -- live, that made
        # 12 incidents confidently report no_longer_present when nothing had
        # been observed at all. Absence of an observer is not observation.
        if not self._world_readers_bound():
            raise AIRequestError(
                "reconciliation_readers_unavailable",
                "deterministic entity/config readers are not bound; "
                "reconciliation cannot establish current truth",
            )
        states = {entity: await self._world_entity_state(entity) for entity in subjects}
        references = {entity: await self._world_config_refs(entity) for entity in subjects}

        rows, tally = [], {}
        for item in incidents:
            public = item.public_dict()
            names = [
                str(s).split(":")[-1]
                for s in item.affected_subject_ids
                if "." in str(s)
            ]
            result = reconcile(
                public,
                ReconciliationObservation(
                    subject_states={n: states.get(n) for n in names},
                    config_references={n: references.get(n, 0) for n in names},
                    scan_id=scan_id,
                    observed_at=observed_at,
                    evidence_ids=(scan_id,) if scan_id else (),
                ),
            )
            tally[result.validity.value] = tally.get(result.validity.value, 0) + 1
            rows.append(
                {
                    "incident_id": item.incident_id,
                    "category": item.category,
                    "priority": item.priority.value,
                    "lifecycle": item.lifecycle.value,
                    "evidence_status": item.evidence_status.value,
                    # Axis A, computed here.
                    "current_validity": result.as_dict(),
                    # Axis B is intentionally NOT computed here: deriving a
                    # repair costs an investigation, and validity must be
                    # answerable without one.
                    "repairability": "see hamie/config_repair/triage_incident",
                }
            )
        return {
            "scan_id": scan_id,
            "observed_at": observed_at.isoformat(),
            "examined": len(rows),
            "validity_counts": tally,
            "actionable": sum(
                1 for r in rows if r["current_validity"]["actionable"]
            ),
            "incidents": rows,
        }

    def _world_readers_bound(self) -> bool:
        return (
            getattr(self, "_entity_state_reader", None) is not None
            and getattr(self, "_config_search_reader", None) is not None
        )

    async def _world_entity_state(self, entity_id: str) -> str | None:
        reader = getattr(self, "_entity_state_reader", None)
        if reader is None:
            raise RuntimeError("entity state reader is not bound")
        return await reader(entity_id)

    async def _world_config_refs(self, entity_id: str) -> int:
        reader = getattr(self, "_config_search_reader", None)
        if reader is None:
            raise RuntimeError("config search reader is not bound")
        found = await reader(entity_id)
        return sum(count for _path, count in found)

    def bind_world_readers(self, entity_state, config_search) -> None:
        """Inject the deterministic readers reconciliation needs.

        Injected rather than imported so the operations service keeps no
        direct Home Assistant dependency, matching how every other
        deterministic fact reaches this layer.
        """
        self._entity_state_reader = entity_state
        self._config_search_reader = config_search

    def _capability_projection(self) -> CapabilityResult | None:
        return getattr(self._projection, "capability", None)

    def _analysis_baseline_projection(self) -> AnalysisBaseline | None:
        return getattr(self._projection, "analysis_baseline", None)

    async def _async_persist_analysis_baseline(
        self, coverage: AIAnalysisCoverage, *, recommendation_ids: tuple[str, ...]
    ) -> None:
        """Make this run's coverage survive a restart.

        Written after the run commits its recommendations, so the store never
        claims coverage for an analysis whose conclusions were not saved.
        """
        now = self._clock.now()
        state = await self._repository.async_load()
        previous = state.analysis_baseline
        baseline = AnalysisBaseline(
            schema_version=BASELINE_SCHEMA_VERSION,
            created_at=previous.created_at if previous is not None else now,
            updated_at=now,
            scan_id=str(self._current_scan_id() or ""),
            eligible_total=coverage.eligible_total,
            analyzed_finding_ids=tuple(
                finding_id
                for finding_id in coverage.selected_finding_ids
                if getattr(self._index(), "group_for_finding", {}).get(finding_id)
                not in set(self._last_ai_failed_group_ids)
            ),
            analyzed_group_ids=tuple(self._last_ai_succeeded_group_ids),
            failed_group_ids=tuple(self._last_ai_failed_group_ids),
            recommendation_ids=recommendation_ids,
            truncated=len(coverage.selected_finding_ids) > MAX_BASELINE_FINDING_IDS,
        )
        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=state.projection_revision + 1,
            analysis_baseline=baseline,
        )
        await self._commit(state, next_state)
        _LOGGER.info(
            "HAMIE analysis baseline saved: scan=%s analyzed=%d/%d groups=%d failed=%d",
            baseline.scan_id, baseline.analyzed_total, baseline.eligible_total,
            len(baseline.analyzed_group_ids), len(baseline.failed_group_ids),
        )

    def _current_scan_id(self) -> str | None:
        snapshot = getattr(self._projection, "snapshot", None)
        return getattr(snapshot, "last_scan_id", None)

    def analysis_status(self) -> dict[str, Any]:
        """The single authoritative answer to "may we say All clear?".

        Derived here, once, from deterministic state. The Recommendations
        page previously decided this itself from zero-recommendations plus a
        healthy connector, which is how production came to display "412
        incidents", "evidence is too large" and "All clear" at the same time:
        the provider WAS healthy, the payload was too large, and nothing in
        the list endpoint could tell "nothing is wrong" from "nothing was
        looked at".
        """
        index = self._index()
        coverage = self._last_ai_coverage
        recommendations = index.recommendations
        incidents = self._incident_projection()
        # Coverage lives in memory during a run and in the store afterwards.
        # Before this existed, a restart left HAMIE holding 18 persisted
        # recommendations while reporting analyzed_total=0 and
        # analyzed_scan_id=None -- the conclusions of an analysis with no
        # record that it had run.
        baseline = self._analysis_baseline_projection()
        if coverage is not None:
            # Planned coverage is not achieved coverage. A run whose provider
            # calls all failed previously still reported its planned findings
            # as analyzed -- live, a failed 16-finding group reported
            # "analyzed 3/16" with zero groups succeeding. Findings belonging
            # to a failed group are not analyzed, and saying otherwise makes a
            # model failure look like progress.
            succeeded = set(self._last_ai_succeeded_group_ids)
            failed = set(self._last_ai_failed_group_ids)
            group_of = getattr(index, "group_for_finding", {})
            analyzed = frozenset(
                finding_id
                for finding_id in coverage.selected_finding_ids
                if group_of.get(finding_id) not in failed
            ) if failed else frozenset(coverage.selected_finding_ids)
            analyzed_scan_id = self._last_ai_scan_id
            eligible = coverage.eligible_total
            # Installation scope, NOT the size of the request that just ran.
            # This branch used to report len(coverage.root_cause_group_ids) --
            # the groups in the last bounded request -- while the two branches
            # below reported the whole installation. The number therefore
            # changed meaning at the next restart.
            groups_total = len(index.groups)
            groups_analyzed = (
                len(succeeded)
                if self._last_ai_succeeded_group_ids or failed
                else len(coverage.analyzed_group_ids)
            )
            failed_groups = len(self._last_ai_failed_group_ids)
            request_groups_total = len(coverage.root_cause_group_ids)
            request_groups_analyzed = groups_analyzed
        elif baseline is not None:
            analyzed = frozenset(baseline.analyzed_finding_ids)
            analyzed_scan_id = baseline.scan_id
            eligible = baseline.eligible_total
            groups_total = len(index.groups)
            groups_analyzed = len(baseline.analyzed_group_ids)
            failed_groups = len(baseline.failed_group_ids)
            request_groups_total = len(baseline.analyzed_group_ids) + len(
                baseline.failed_group_ids
            )
            request_groups_analyzed = len(baseline.analyzed_group_ids)
        else:
            analyzed = frozenset()
            analyzed_scan_id = None
            eligible = len(index.findings)
            groups_total = len(index.groups)
            groups_analyzed = 0
            failed_groups = 0
            request_groups_total = 0
            request_groups_analyzed = 0
        high_priority = tuple(
            item
            for item in incidents
            if item.is_active
            and item.priority in (IncidentPriority.P0, IncidentPriority.P1)
        )
        provider = next(
            (
                item
                for item in self.connector_status()
                if item.get("connector_id") == "ollama"
            ),
            {},
        )
        inputs = AnalysisInputs(
            current_scan_id=self._current_scan_id(),
            analyzed_scan_id=analyzed_scan_id,
            eligible_total=eligible,
            analyzed_total=len(analyzed),
            groups_total=groups_total,
            groups_analyzed=groups_analyzed,
            failed_groups=failed_groups,
            request_groups_total=request_groups_total,
            request_groups_analyzed=request_groups_analyzed,
            recommendation_total=len(recommendations),
            stale_recommendations=sum(1 for item in recommendations if item.stale),
            high_priority_total=len(high_priority),
            high_priority_unanalyzed=sum(
                1
                for item in high_priority
                if not analyzed.intersection(item.finding_ids)
            ),
            provider_status=str(provider.get("status", "unknown")),
            ever_analyzed=(
                coverage is not None or baseline is not None or bool(recommendations)
            ),
        )
        return evaluate(inputs).as_dict()

    def connector_status(self) -> tuple[dict[str, Any], ...]:
        """Return only cached secret-free connector health."""
        return self._connectors.public_status()

    def discovered_ai_models(self) -> tuple[str, ...]:
        """Return the bounded runtime-only Ollama model catalog cached
        from the last successful Test Connection this process lifetime."""
        return self._connectors.discovered_models

    def last_analysis_failure(self) -> dict[str, Any] | None:
        """Return the exact stage/reason/code of the last failed analysis,
        or None if the most recent analysis (if any) succeeded."""
        failure = self._connectors.last_pipeline_failure
        return failure.public_dict() if failure is not None else None

    async def async_scan_started(
        self,
        *,
        scan_id: str,
        trigger: str,
        generation: int,
        projection_revision: int,
    ) -> None:
        """Queue a scan-start event without awaiting connector I/O."""
        self._connectors.schedule_event(
            "scan_started",
            {"scan_id": scan_id, "trigger": trigger},
            generation=generation,
            projection_revision=projection_revision,
            idempotency_key=f"scan_started:{scan_id}",
        )

    async def async_state_committed(
        self, current: RepositoryState, committed: RepositoryState
    ) -> None:
        """Publish a non-scan application transition after its durable commit."""
        await self._publish_transition(current, committed)

    async def async_scan_committed(
        self,
        current: RepositoryState,
        committed: RepositoryState,
        *,
        scan_id: str,
    ) -> None:
        """Publish scan and finding transitions only after reconciliation commits."""
        await self._publish_transition(
            current,
            committed,
            extra_events=(
                (
                    "scan_completed",
                    {"scan_id": scan_id},
                    f"scan_completed:{scan_id}",
                ),
            ),
        )

    async def async_scan_failed(
        self,
        *,
        scan_id: str,
        error_code: str,
        generation: int,
        projection_revision: int,
    ) -> None:
        """Publish a bounded failed-scan outcome without raising to the scan."""
        self._connectors.schedule_event(
            "scan_failed",
            {"scan_id": scan_id, "error_code": error_code},
            generation=generation,
            projection_revision=projection_revision,
            idempotency_key=f"scan_failed:{scan_id}",
        )
        await self._record_delivery_audits(await self._connectors.async_drain_events())

    def preview_group(self, group_id: str, action: str) -> GroupActionPreview:
        """Freeze exact IDs and content revisions for explicit confirmation."""
        index = self._index()
        group = index.group_by_id.get(group_id)
        if group is None:
            raise GroupNotFoundError(group_id)
        if action == "suppress":
            members = tuple(
                (item.finding_id, item.content_revision)
                for item in index.findings
                if item.finding_id in group.member_finding_ids
                and item.lifecycle is FindingLifecycle.OPEN
            )
        else:
            review_action = ReviewAction(action)
            members = tuple(
                (item.finding_id, item.content_revision)
                for item in index.findings
                if item.finding_id in group.member_finding_ids
                and item.lifecycle is FindingLifecycle.OPEN
                and item.review_state in ALLOWED_PRIOR_STATES[review_action]
            )
        return GroupActionPreview(
            group_id=group_id,
            action=action,
            generation=index.generation,
            findings=members,
        )

    async def async_apply_group_review(
        self,
        preview: GroupActionPreview,
        *,
        token: str,
        actor: str,
        snooze_until: datetime | None = None,
    ) -> dict[str, Any]:
        """Apply one confirmed frozen group review atomically to HAMIE state."""
        action = ReviewAction(preview.action)
        state = await self._repository.async_load()
        replay = self._idempotency(
            state, token, f"group_review:{action.value}", preview.group_id
        )
        if replay:
            return {
                "group_id": preview.group_id,
                "count": preview.count,
                "replayed": True,
            }
        self._validate_preview(state, preview)
        at = self._clock.now()
        if action is ReviewAction.SNOOZE:
            snooze_until = snooze_until or at + timedelta(hours=24)
        by_id = {item.finding_id: item for item in state.findings}
        updated: dict[str, Finding] = {}
        reviews: list[ReviewRecord] = []
        for finding_id, _revision in preview.findings:
            finding = by_id[finding_id]
            if finding.review_state not in ALLOWED_PRIOR_STATES[action]:
                raise GroupPreviewConflictError("finding review state changed")
            review = ReviewRecord(
                finding_id=finding_id,
                action=action,
                actor=actor,
                at=at,
                finding_content_revision=finding.content_revision,
                prior_state=finding.review_state,
                resulting_state=ACTION_STATE[action],
                reason=f"group:{preview.group_id}",
                snooze_until=snooze_until if action is ReviewAction.SNOOZE else None,
            )
            reviews.append(review)
            updated[finding_id] = replace(
                finding,
                review_state=ACTION_STATE[action],
                snooze_until=(snooze_until if action is ReviewAction.SNOOZE else None),
            )
        audit = self._audit(
            f"group_{action.value}",
            actor,
            (preview.group_id,),
            (
                ("group_id", preview.group_id),
                ("count", str(len(updated))),
            ),
            token=token,
        )
        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=state.projection_revision + 1,
            findings=tuple(
                updated.get(item.finding_id, item) for item in state.findings
            ),
            reviews=(*state.reviews, *reviews)[-500:],
            idempotency=(
                *state.idempotency,
                IdempotencyRecord(
                    token,
                    f"group_review:{action.value}",
                    preview.group_id,
                    state.projection_revision + 1,
                ),
            )[-128:],
            audits=(*state.audits, audit)[-MAX_AUDIT_RECORDS:],
        )
        await self._commit(state, next_state)
        return {"group_id": preview.group_id, "count": len(updated), "replayed": False}

    async def async_suppress_group(
        self,
        preview: GroupActionPreview,
        *,
        token: str,
        actor: str,
        reason: str,
        expiration: datetime | None = None,
    ) -> SuppressionRule:
        """Create one confirmed group suppression rule without deleting findings."""
        if preview.action != "suppress":
            raise ValueError("preview is not a suppression action")
        state = await self._repository.async_load()
        replay = self._idempotency(state, token, "suppress_group", preview.group_id)
        if replay:
            existing = next(
                (
                    item
                    for item in state.suppression_rules
                    if item.matcher == (("group_id", preview.group_id),)
                ),
                None,
            )
            if existing is None:
                raise IdempotencyConflictError("suppression replay target is missing")
            return existing
        self._validate_preview(state, preview)
        at = self._clock.now()
        rule = SuppressionRule(
            rule_id=f"sup_{stable_digest(preview.group_id, token)[:24]}",
            name=f"Suppress {preview.group_id}",
            enabled=True,
            scope="group",
            matcher=(("group_id", preview.group_id),),
            reason=reason,
            created_at=at,
            created_by=actor,
            expiration=expiration,
            affected_analyzer_ids=(),
            action=SuppressionAction.HIDE_FROM_DEFAULT_VIEW,
            preview_count=preview.count,
            last_match_count=preview.count,
        )
        if len(state.suppression_rules) >= MAX_SUPPRESSION_RULES:
            raise ValueError("suppression rule limit reached")
        audit = self._audit(
            "suppression_rule_created",
            actor,
            (rule.rule_id, preview.group_id),
            (("count", str(preview.count)), ("action", rule.action.value)),
            token=token,
        )
        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=state.projection_revision + 1,
            suppression_rules=(*state.suppression_rules, rule),
            idempotency=(
                *state.idempotency,
                IdempotencyRecord(
                    token,
                    "suppress_group",
                    preview.group_id,
                    state.projection_revision + 1,
                ),
            )[-128:],
            audits=(*state.audits, audit)[-MAX_AUDIT_RECORDS:],
        )
        await self._commit(state, next_state)
        return rule

    async def async_create_grouping_rule(
        self,
        *,
        name: str,
        title: str,
        matcher: tuple[tuple[str, str], ...],
        actor: str,
    ) -> GroupingRule:
        """Persist one deterministic user grouping rule."""
        state = await self._repository.async_load()
        if len(state.grouping_rules) >= MAX_GROUPING_RULES:
            raise ValueError("grouping rule limit reached")
        token = uuid4().hex
        rule = GroupingRule(
            rule_id=f"group_rule_{stable_digest(name, title, *matcher)[:20]}",
            name=name,
            matcher=matcher,
            title=title,
        )
        audit = self._audit(
            "grouping_rule_created",
            actor,
            (rule.rule_id,),
            (("matcher_fields", ",".join(key for key, _ in matcher)),),
            token=token,
        )
        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=state.projection_revision + 1,
            grouping_rules=(*state.grouping_rules, rule),
            audits=(*state.audits, audit)[-MAX_AUDIT_RECORDS:],
        )
        await self._commit(state, next_state)
        return rule

    def preview_suppression(
        self, matcher: tuple[tuple[str, str], ...]
    ) -> dict[str, Any]:
        """Return a frozen suppression match count from indexed state."""
        GroupingRule("preview", "preview", matcher, "preview")
        index = self._index()
        finding_ids = tuple(
            item.finding_id
            for item in index.findings
            if matcher_matches(
                matcher,
                item,
                group_id=index.group_for_finding.get(item.finding_id),
            )
        )
        return {
            "generation": index.generation,
            "matcher": [list(item) for item in matcher],
            "finding_ids": list(finding_ids),
            "count": len(finding_ids),
        }

    async def async_create_suppression_rule(
        self,
        *,
        preview: dict[str, Any],
        name: str,
        reason: str,
        action: SuppressionAction,
        expiration: datetime | None,
        token: str,
        actor: str,
    ) -> SuppressionRule:
        """Create a declarative rule after exact-count confirmation."""
        matcher = tuple(
            (str(item[0]), str(item[1])) for item in preview.get("matcher", [])
        )
        state = await self._repository.async_load()
        target = stable_digest(*matcher)
        replay = self._idempotency(state, token, "create_suppression", target)
        rule_id = f"sup_{stable_digest(target, token)[:24]}"
        if replay:
            return next(
                item for item in state.suppression_rules if item.rule_id == rule_id
            )
        refreshed = self.preview_suppression(matcher)
        if (
            preview.get("generation") != refreshed["generation"]
            or preview.get("finding_ids") != refreshed["finding_ids"]
        ):
            raise GroupPreviewConflictError("suppression preview changed")
        if len(state.suppression_rules) >= MAX_SUPPRESSION_RULES:
            raise ValueError("suppression rule limit reached")
        at = self._clock.now()
        rule = SuppressionRule(
            rule_id=rule_id,
            name=name,
            enabled=True,
            scope="matching_findings",
            matcher=matcher,
            reason=reason,
            created_at=at,
            created_by=actor,
            expiration=expiration,
            affected_analyzer_ids=(),
            action=action,
            preview_count=refreshed["count"],
            last_match_count=refreshed["count"],
        )
        audit = self._audit(
            "suppression_rule_created",
            actor,
            (rule.rule_id,),
            (("count", str(rule.preview_count)), ("action", action.value)),
            token=token,
        )
        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=state.projection_revision + 1,
            suppression_rules=(*state.suppression_rules, rule),
            idempotency=(
                *state.idempotency,
                IdempotencyRecord(
                    token, "create_suppression", target, state.projection_revision + 1
                ),
            )[-128:],
            audits=(*state.audits, audit)[-MAX_AUDIT_RECORDS:],
        )
        await self._commit(state, next_state)
        return rule

    async def async_delete_suppression_rule(
        self,
        rule_id: str,
        *,
        expected_revision: int,
        actor: str,
        token: str | None = None,
    ) -> None:
        """Delete only a HAMIE policy while preserving every finding."""
        state = await self._repository.async_load()
        write_token = token or uuid4().hex
        if self._idempotency(state, write_token, "delete_suppression", rule_id):
            return
        rule = next(
            (item for item in state.suppression_rules if item.rule_id == rule_id),
            None,
        )
        if rule is None:
            raise KeyError(rule_id)
        if rule.revision != expected_revision:
            raise RevisionConflictError("suppression rule revision changed")
        audit = self._audit(
            "suppression_rule_deleted", actor, (rule_id,), (), token=write_token
        )
        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=state.projection_revision + 1,
            suppression_rules=tuple(
                item for item in state.suppression_rules if item.rule_id != rule_id
            ),
            idempotency=(
                *state.idempotency,
                IdempotencyRecord(
                    write_token,
                    "delete_suppression",
                    rule_id,
                    state.projection_revision + 1,
                ),
            )[-128:],
            audits=(*state.audits, audit)[-MAX_AUDIT_RECORDS:],
        )
        await self._commit(state, next_state)

    async def async_update_suppression_rule(
        self,
        rule_id: str,
        *,
        expected_revision: int,
        enabled: bool,
        reason: str,
        action: SuppressionAction,
        expiration: datetime | None,
        actor: str,
        token: str | None = None,
        preview: dict[str, Any] | None = None,
    ) -> SuppressionRule:
        """Update one revisioned HAMIE-only policy and audit the change."""
        state = await self._repository.async_load()
        write_token = token or uuid4().hex
        if self._idempotency(state, write_token, "update_suppression", rule_id):
            replayed = next(
                (item for item in state.suppression_rules if item.rule_id == rule_id),
                None,
            )
            if replayed is None:
                raise KeyError(rule_id)
            return replayed
        current = next(
            (item for item in state.suppression_rules if item.rule_id == rule_id),
            None,
        )
        if current is None:
            raise KeyError(rule_id)
        if current.revision != expected_revision:
            raise RevisionConflictError("suppression rule revision changed")
        refreshed_preview = self.preview_suppression(current.matcher)
        if preview is not None and (
            preview.get("generation") != refreshed_preview["generation"]
            or preview.get("finding_ids") != refreshed_preview["finding_ids"]
        ):
            raise GroupPreviewConflictError("suppression preview changed")
        updated = replace(
            current,
            enabled=enabled,
            reason=reason,
            action=action,
            expiration=expiration,
            last_match_count=refreshed_preview["count"],
            revision=current.revision + 1,
        )
        audit = self._audit(
            "suppression_rule_updated",
            actor,
            (rule_id,),
            (
                ("enabled", str(enabled).lower()),
                ("action", action.value),
                ("count", str(refreshed_preview["count"])),
            ),
            token=write_token,
        )
        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=state.projection_revision + 1,
            suppression_rules=tuple(
                updated if item.rule_id == rule_id else item
                for item in state.suppression_rules
            ),
            idempotency=(
                *state.idempotency,
                IdempotencyRecord(
                    write_token,
                    "update_suppression",
                    rule_id,
                    state.projection_revision + 1,
                ),
            )[-128:],
            audits=(*state.audits, audit)[-MAX_AUDIT_RECORDS:],
        )
        await self._commit(state, next_state)
        return updated

    async def async_test_connector(
        self, connector_id: str, *, actor: str
    ) -> dict[str, Any]:
        """Run one explicit test and write a secret-free audit event."""
        try:
            status = await self._connectors.async_test(connector_id)
        except Exception:
            await self.async_record_audit(
                "connector_test_failed",
                actor=actor,
                target_ids=(connector_id,),
                details=(("error", self._connectors.last_error or "unknown"),),
            )
            raise
        await self.async_record_audit(
            "connector_test_succeeded",
            actor=actor,
            target_ids=(connector_id,),
        )
        return status

    @property
    def last_ai_coverage(self) -> AIAnalysisCoverage | None:
        """Return the eligible/selected/skipped accounting for the most
        recent AI analysis attempt (success or failure), or None if none
        has run yet this process lifetime. Process-local, like
        ConnectorManager.last_pipeline_failure -- not persisted across a
        Home Assistant restart."""
        return self._last_ai_coverage

    @property
    def last_ai_recommendations(self) -> tuple[AIRecommendation, ...]:
        """Return every recommendation created by the most recent AI
        analysis (success case), not just the single primary one
        ``async_request_ai`` returns for backward compatibility.

        "Analyze Scan Summary"/"Analyze All" processes every eligible
        root-cause group in one pass (bounded by
        ``ai_maximum_advisory_groups_per_run``) and persists one
        recommendation per group that met the confidence threshold --
        all of them, via append, never just the first. This property is
        how a caller that cares about the *complete* result of one
        analysis pass (the WS command, in particular) can see all of
        them instead of only the first.
        """
        return self._last_ai_recommendations

    @property
    def last_ai_failed_group_ids(self) -> tuple[str, ...]:
        """Root-cause group ids the most recent AI analysis attempted and
        failed on (a provider error for that specific group), distinct
        from groups this run never attempted at all (deferred by the
        per-run cap or already covered by a current recommendation). A
        caller can retry exactly these by re-issuing
        ``async_request_ai(group_ids=this_tuple, ...)`` -- no separate
        retry command needed.
        """
        return self._last_ai_failed_group_ids

    async def async_request_ai(
        self,
        *,
        finding_ids: tuple[str, ...] = (),
        group_ids: tuple[str, ...] = (),
        actor: str,
    ) -> AIRecommendation:
        """Request, validate, and persist advisory content after deterministic state.

        Exactly one analysis may be in flight at a time: a second call
        made while one is already running is rejected immediately with
        `analysis_already_running` rather than silently queued behind it
        -- a UI click, rerender, or retry can never fan out into several
        real provider requests sharing one user action.
        """
        if self._ai_analysis_in_flight:
            raise AIRequestError(
                "analysis_already_running",
                "an AI analysis is already running for this installation",
            )
        self._ai_analysis_in_flight = True
        try:
            return await self._async_request_ai(
                finding_ids=finding_ids, group_ids=group_ids, actor=actor
            )
        finally:
            self._ai_analysis_in_flight = False

    async def _async_request_ai(
        self,
        *,
        finding_ids: tuple[str, ...],
        group_ids: tuple[str, ...],
        actor: str,
    ) -> AIRecommendation:
        index = self._index()
        scan_summary = not finding_ids and not group_ids
        candidates = (
            tuple(
                item
                for item in index.findings
                if item.lifecycle is FindingLifecycle.OPEN
            )
            if scan_summary
            else tuple(
                item
                for item in index.findings
                if item.finding_id in finding_ids
                or index.group_for_finding.get(item.finding_id) in group_ids
            )
        )
        if not candidates:
            raise AIRequestError(
                "scan_data_unavailable",
                "no eligible findings are available to analyze yet",
            )
        if not scan_summary and len(candidates) > 50:
            raise AIRequestError(
                "ai_request_selection_too_large",
                "AI request must select 1..50 findings",
            )

        # Phase 3E: refuse to spend a BULK run on a model that cannot satisfy
        # the contract. Checked before any evidence is planned, so a refusal
        # costs nothing and -- critically -- never advances coverage or marks a
        # finding analyzed. An unusable model must leave the installation in
        # exactly the state it was in, not one that looks partly examined.
        #
        # Scoped to bulk deliberately. A targeted request is one operator
        # explicitly asking about one group they chose; it is bounded, audited,
        # and it is the only way an operator can judge a DEGRADED model against
        # their own data instead of taking HAMIE's aggregate verdict on faith.
        # Blocking it too would make a degraded model mean "no AI features at
        # all, and no way to see why". The capability verdict is recorded on
        # every such run so the result is never read as an endorsement.
        gate = evaluate_gate(
            self._capability_projection(),
            current_fingerprint=self.capability_fingerprint(),
            now=self._clock.now(),
        )
        if not gate.permitted and not scan_summary:
            _LOGGER.info(
                "HAMIE allowing a targeted analysis on a %s model: %s",
                gate.verdict.value, gate.reason,
            )
            await self.async_record_audit(
                "ai_request_capability_warning",
                actor=actor,
                target_ids=("capability_gate",),
                details=(
                    ("scope", "targeted"),
                    ("verdict", gate.verdict.value),
                    ("reason", gate.reason[:200]),
                ),
            )
        if not gate.permitted and scan_summary:
            _LOGGER.info(
                "HAMIE refused AI analysis: %s (verdict=%s, failed=%s)",
                gate.reason,
                gate.verdict.value,
                ", ".join(gate.failed_dimensions) or "none",
            )
            await self.async_record_audit(
                "ai_request_refused",
                actor=actor,
                target_ids=("capability_gate",),
                details=(
                    ("reason", gate.reason[:200]),
                    ("verdict", gate.verdict.value),
                    ("failed_dimensions", ", ".join(gate.failed_dimensions) or "none"),
                    ("stale", str(gate.stale)),
                    ("fingerprint_mismatch", str(gate.fingerprint_mismatch)),
                ),
            )
            raise AIRequestError("ai_capability_not_verified", gate.reason)

        maximum_characters = int(
            self._options.get("ollama_maximum_input_characters", 16_000)
        )
        maximum_estimated_tokens = int(
            self._options.get("ai_maximum_estimated_tokens", 4_000)
        )
        maximum_characters = min(
            maximum_characters, max(1_000, maximum_estimated_tokens * 4)
        )
        maximum_groups = int(self._options.get("ai_maximum_advisory_groups_per_run", 8))
        maximum_per_group = int(self._options.get("ai_maximum_findings_per_group", 20))
        maximum_response_tokens = int(
            self._options.get("ollama_maximum_output_tokens", 1_024)
        )
        minimum_confidence = str(
            self._options.get("ai_minimum_confidence_threshold", "low")
        )
        if minimum_confidence not in {"low", "medium", "high"}:
            minimum_confidence = "low"

        # "Analyze All" (scan_summary mode) must make genuine forward
        # progress across repeated runs, not silently re-analyze the same
        # top-N-by-priority root-cause groups forever: a group with a
        # current (non-stale) recommendation already reflects this
        # evidence, so it is excluded from this run's bounded batch,
        # letting the next uncovered groups take its place. A targeted
        # request (explicit finding_ids/group_ids -- "Analyze this group")
        # always analyzes exactly what was asked, regardless of freshness.
        already_covered_group_ids = (
            frozenset(
                group_id
                for recommendation in index.recommendations
                if not recommendation.stale
                for group_id in recommendation.group_ids
            )
            if scan_summary
            else frozenset()
        )

        # Budget the WHOLE request, not just the interesting part of it.
        # The previous revision handed `maximum_characters` to the evidence
        # planner and then added the envelope, the coverage id list and up to
        # three full incident public_dicts on top -- measured live at 48,737
        # characters against a 16,000 budget, which is exactly the
        # `evidence_payload_too_large` the operator kept hitting. Raising the
        # configured maximum would only have moved the cliff, because the
        # overhead scales with how many groups the run covers.
        response_reserve = max(512, maximum_response_tokens * 4)
        envelope_probe = {
            "schema_version": 1,
            "request": "incident_analysis",
            "generation": index.generation,
            "findings": [],
            "groups": [""],
            "incidents": [],
            "authority": "advisory_only",
            "budgets": {
                "maximum_prompt_characters": maximum_characters,
                "maximum_estimated_tokens": maximum_estimated_tokens,
                "maximum_response_tokens": maximum_response_tokens,
            },
        }
        # +400 covers the coverage counts block and the provider's own
        # instruction wrapper, which is added outside this payload.
        envelope_characters = payload_characters(envelope_probe) + 400
        incident_reserve = MAX_COMPACT_INCIDENT_CHARACTERS * MAX_PROVIDER_INCIDENTS
        budget = ContextBudget(
            maximum_characters=maximum_characters,
            response_reserve_characters=response_reserve,
            overhead_characters=envelope_characters + incident_reserve,
        )
        if not budget.viable:
            raise AIRequestError(
                "ai_prompt_budget_exhausted",
                "the configured prompt budget leaves no room for evidence once "
                "instructions, coverage and response capacity are reserved",
            )

        batches, coverage = index.plan_ai_advisory_groups(
            candidates,
            maximum_characters=budget.evidence_allowance,
            maximum_groups=maximum_groups,
            maximum_findings_per_group=maximum_per_group,
            already_covered_group_ids=already_covered_group_ids,
        )
        self._last_ai_coverage = coverage
        self._last_ai_scan_id = self._current_scan_id()
        if not batches:
            if already_covered_group_ids:
                raise AIRequestError(
                    "ai_all_groups_current",
                    "every eligible root-cause group already has a current "
                    "AI recommendation; nothing new to analyze",
                )
            raise AIRequestError(
                "ai_prompt_budget_exhausted",
                "the configured prompt budget is too small to analyze any finding",
            )

        selected_ids = frozenset(coverage.selected_finding_ids)
        selected = tuple(item for item in candidates if item.finding_id in selected_ids)
        targets = tuple(item.finding_id for item in selected)
        await self.async_record_audit(
            "ai_request_started",
            actor=actor,
            target_ids=targets,
            details=(
                ("redaction", "applied"),
                ("request_eligible_total", str(coverage.eligible_total)),
                ("request_selected_total", str(len(coverage.selected_finding_ids))),
                ("request_skipped_total", str(len(coverage.skipped_finding_ids))),
                # len(batches) is what was SELECTED, not what succeeded.
                ("request_groups_selected", str(len(batches))),
            ),
        )

        fail_group_id = (
            await asyncio.to_thread(
                read_analysis_fail_group, self._fixture_config_dir
            )
            if self._fixture_config_dir
            else ""
        )
        if fail_group_id:
            _LOGGER.warning(
                "HAMIE analysis-failure injection is armed for group %s. This "
                "is a deliberate test hook, not a provider fault.",
                fail_group_id,
            )

        responses: list[
            tuple[str, tuple[dict[str, Any], ...], dict[str, Any], datetime, datetime]
        ] = []
        failed_group_ids: list[str] = []
        last_failure: Exception | None = None
        confidence_rank = {"low": 0, "medium": 1, "high": 2}
        # Every group's provider call is isolated: one group's failure
        # (a transient provider timeout, a single bad response) must
        # never discard advisories other groups in the same bounded run
        # already produced. Only when every attempted group fails is the
        # real underlying exception re-raised, preserving today's
        # end-to-end error classification for the total-failure case.
        for group_id, planned in batches:
            analysis_started_at = self._clock.now()
            real_group_ids = (group_id,) if group_id in index.group_by_id else ()
            planned_finding_ids = {
                str(item["finding_id"]) for item in planned if item.get("finding_id")
            }
            incident_context = [
                compact_incident(item.public_dict())
                for item in self._incident_projection()
                if item.is_active
                and planned_finding_ids.intersection(item.finding_ids)
            ][:MAX_PROVIDER_INCIDENTS]
            payload = {
                "schema_version": 1,
                "request": "incident_analysis" if incident_context else (
                    "scan_summary" if scan_summary else "advisory_explanation"
                ),
                "generation": index.generation,
                "findings": list(planned),
                "groups": list(real_group_ids),
                "incidents": incident_context,
                "authority": "advisory_only",
                "coverage": coverage.provider_dict(),
                "budgets": {
                    "maximum_prompt_characters": maximum_characters,
                    "maximum_estimated_tokens": maximum_estimated_tokens,
                    "maximum_response_tokens": maximum_response_tokens,
                },
            }
            # Never knowingly send an oversized request. Shrinking is
            # deterministic and always reported; a request that quietly
            # dropped half its evidence and came back confident is worse
            # than one that says it was truncated.
            fitted = fit_payload(payload, maximum_characters - response_reserve)
            if not fitted.within_budget:
                failed_group_ids.append(group_id)
                last_failure = last_failure or AIRequestError(
                    "evidence_payload_too_large",
                    "one root-cause group's evidence cannot be reduced to fit "
                    "the configured prompt budget",
                )
                await self.async_record_audit(
                    "ai_response_rejected",
                    actor=actor,
                    target_ids=(group_id,),
                    details=(
                        ("error_code", "evidence_payload_too_large"),
                        ("stage", "context_budget"),
                        ("group_id", group_id),
                        ("characters", str(fitted.characters)),
                        ("budget", str(maximum_characters - response_reserve)),
                    ),
                )
                continue
            payload = fitted.payload
            try:
                if fail_group_id and group_id == fail_group_id:
                    # Raised INSTEAD of the provider call: the real connector
                    # is never contacted and the AI PC is never touched. From
                    # here on this group takes the ordinary failure path.
                    raise InjectedAnalysisFailure(
                        "analysis failure injected for the armed fixture group"
                    )
                response = await self._connectors.async_analyze(payload)
            except Exception as err:
                last_failure = err
                failed_group_ids.append(group_id)
                # Record the failure IMMEDIATELY. When every group fails the
                # method re-raises before reaching the commit path, so an
                # assignment made only on success left _last_ai_failed_group_ids
                # empty -- and coverage then fell back to reporting PLANNED
                # work. Live, a run whose single group failed reported
                # "analyzed 1/16, failed 0". This is the same defect as the
                # earlier planned-vs-achieved bug, hiding in the total-failure
                # path.
                self._last_ai_failed_group_ids = tuple(failed_group_ids)
                self._last_ai_succeeded_group_ids = tuple(
                    gid for gid, _p in batches if gid not in set(failed_group_ids)
                )
                snapshot = pipeline_failure_snapshot(err)
                provider = snapshot.provider or self._connectors.ai_connection_method
                await self.async_record_audit(
                    "ai_response_rejected",
                    actor=actor,
                    target_ids=tuple(str(item["finding_id"]) for item in planned),
                    details=(
                        ("error_code", snapshot.error_code),
                        ("stage", snapshot.stage or "unknown"),
                        ("provider", provider),
                        ("group_id", group_id),
                    ),
                )
                continue
            analysis_completed_at = self._clock.now()
            if (
                confidence_rank.get(response["confidence"], -1)
                < confidence_rank[minimum_confidence]
            ):
                continue
            responses.append(
                (
                    group_id,
                    planned,
                    response,
                    analysis_started_at,
                    analysis_completed_at,
                )
            )
        if not responses:
            if last_failure is not None:
                raise last_failure
            raise AIRequestError(
                "ai_confidence_below_threshold",
                "no advisory met the configured confidence threshold",
            )

        state = await self._repository.async_load()
        current = {item.finding_id: item for item in state.findings}
        if any(
            item.finding_id not in current
            or current[item.finding_id].content_revision != item.content_revision
            for item in selected
        ):
            raise RevisionConflictError("AI source findings changed during request")

        candidate_by_id = {item.finding_id: item for item in selected}
        recommendations: list[AIRecommendation] = []
        audits: list[AuditRecord] = []
        for (
            group_id,
            planned,
            response,
            analysis_started_at,
            analysis_completed_at,
        ) in responses:
            allowed_finding_ids = tuple(
                str(item["finding_id"])
                for item in planned
                if str(item["finding_id"]) in candidate_by_id
            )
            cited_findings = (
                tuple(
                    item
                    for item in response["supporting_finding_ids"]
                    if item in allowed_finding_ids
                )
                or allowed_finding_ids
            )
            allowed_group_ids = (group_id,) if group_id in index.group_by_id else ()
            cited_groups = (
                tuple(
                    item
                    for item in response["supporting_group_ids"]
                    if item in allowed_group_ids
                )
                or allowed_group_ids
            )
            source_findings = tuple(
                candidate_by_id[item]
                for item in cited_findings
                if item in candidate_by_id
            )
            recommendation_digest = stable_digest(
                analysis_completed_at.isoformat(),
                group_id,
                *cited_findings,
                *cited_groups,
            )
            # Structural parse never raises (an absent or malformed
            # proposal simply yields None); policy validation is a
            # separate step so a rejection reason can be recorded without
            # ever failing the surrounding analysis (mission Phase 15).
            parsed_proposal = parse_llm_proposed_action(response.get("proposed_action"))
            llm_proposed_action = None
            if parsed_proposal is not None:
                validated_proposal = validate_llm_proposed_action(
                    parsed_proposal, known_evidence_ids=frozenset(allowed_finding_ids)
                )
                if isinstance(validated_proposal, ProposalRejection):
                    audits.append(
                        self._audit(
                            "ai_proposed_action_rejected",
                            actor,
                            (group_id,),
                            (
                                ("reason_code", validated_proposal.reason_code),
                                ("message", validated_proposal.message[:200]),
                            ),
                            token=f"{recommendation_digest[:24]}:proposal_rejected",
                        )
                    )
                else:
                    llm_proposed_action = validated_proposal
            recommendation = AIRecommendation(
                recommendation_id=f"air_{recommendation_digest[:24]}",
                schema_version=AI_SCHEMA_VERSION,
                provider=self._connectors.ai_connection_method,
                model=response["model"],
                created_at=analysis_completed_at,
                generated_at=analysis_completed_at,
                analysis_started_at=analysis_started_at,
                analysis_completed_at=analysis_completed_at,
                evidence_first_observed_at=min(
                    item.first_seen for item in source_findings
                ),
                evidence_last_observed_at=max(
                    item.last_seen for item in source_findings
                ),
                source_scan_id=max(
                    source_findings, key=lambda item: item.last_seen
                ).latest_scan_id,
                source_scan_completed_at=max(
                    item.last_seen for item in source_findings
                ),
                source_finding_revision=max(
                    item.content_revision for item in source_findings
                ),
                recommendation_revision=1,
                analysis_total_findings=coverage.total_findings,
                analysis_eligible_findings=coverage.eligible_total,
                analysis_selected_findings=len(coverage.selected_finding_ids),
                analysis_skipped_findings=len(coverage.skipped_finding_ids),
                root_cause_groups_detected=len(coverage.root_cause_group_ids),
                root_cause_groups_analyzed=len(responses),
                root_cause_groups_skipped=max(
                    0, len(coverage.root_cause_group_ids) - len(responses)
                ),
                selection_reason=coverage.selection_reason,
                coverage_state=(
                    "full" if not coverage.skipped_finding_ids else "partial"
                ),
                finding_ids=cited_findings,
                group_ids=cited_groups,
                summary=response["summary"],
                probable_causes=response["probable_causes"],
                recommended_checks=response["recommended_checks"],
                proposed_repair_plan=response["proposed_repair_plan"],
                confidence=response["confidence"],
                assumptions=response["assumptions"],
                missing_evidence=response["missing_evidence"],
                risk_notes=response["risk_notes"],
                do_not_do=response["do_not_do"],
                review_state=AIReviewState.NEW,
                source_revisions=tuple(
                    (item.finding_id, item.content_revision) for item in source_findings
                ),
                source_evidence_digests=tuple(
                    item.material_digest for item in source_findings
                ),
                group_bindings=tuple(
                    GroupSourceBinding(
                        group_id=group.group_id,
                        grouping_revision=group.grouping_revision,
                        member_digest=stable_digest(*group.member_finding_ids),
                        suppression_digest=stable_digest(group.suppression_state),
                        dependency_root=group.common_dependency_root or "",
                    )
                    for cited_group_id in cited_groups
                    if (group := index.group_by_id.get(cited_group_id)) is not None
                ),
                llm_proposed_action=llm_proposed_action,
            )
            recommendations.append(recommendation)
            audits.append(
                self._audit(
                    "ai_recommendation_created",
                    actor,
                    (
                        recommendation.recommendation_id,
                        *cited_findings,
                        *cited_groups,
                    ),
                    (("provider", recommendation.provider),),
                    token=recommendation.recommendation_id,
                )
            )

        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=state.projection_revision + 1,
            recommendations=(
                *state.recommendations,
                *recommendations,
            )[-MAX_RECOMMENDATIONS:],
            audits=(*state.audits, *audits)[-MAX_AUDIT_RECORDS:],
        )
        await self._commit(state, next_state)
        self._last_ai_recommendations = tuple(recommendations)
        self._last_ai_failed_group_ids = tuple(failed_group_ids)
        self._last_ai_succeeded_group_ids = tuple(
            group_id for group_id, _planned in batches if group_id not in set(failed_group_ids)
        )
        # Persist coverage only AFTER the recommendations commit, so the store
        # can never claim an analysis covered work whose conclusions were lost.
        if self._last_ai_coverage is not None:
            await self._async_persist_analysis_baseline(
                self._last_ai_coverage,
                recommendation_ids=tuple(
                    item.recommendation_id for item in recommendations
                ),
            )
        return recommendations[0]

    async def async_review_ai(
        self,
        recommendation_id: str,
        *,
        state_value: AIReviewState,
        actor: str,
    ) -> AIRecommendation:
        """Record human review of advisory content; never execute it."""
        if state_value not in {
            AIReviewState.ACKNOWLEDGED,
            AIReviewState.REJECTED,
            AIReviewState.RETAINED,
            AIReviewState.EXPIRED,
        }:
            raise ValueError("unsupported AI review transition")
        state = await self._repository.async_load()
        current = next(
            (
                item
                for item in state.recommendations
                if item.recommendation_id == recommendation_id
            ),
            None,
        )
        if current is None:
            raise KeyError(recommendation_id)
        updated = replace(current, review_state=state_value)
        audit = self._audit(
            "ai_recommendation_reviewed",
            actor,
            (recommendation_id,),
            (("state", state_value.value),),
            token=uuid4().hex,
        )
        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=state.projection_revision + 1,
            recommendations=tuple(
                updated if item.recommendation_id == recommendation_id else item
                for item in state.recommendations
            ),
            audits=(*state.audits, audit)[-MAX_AUDIT_RECORDS:],
        )
        await self._commit(state, next_state)
        return updated

    async def async_record_audit(
        self,
        event: str,
        *,
        actor: str,
        target_ids: tuple[str, ...],
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        """Commit one bounded secret-free audit event."""
        state = await self._repository.async_load()
        token = uuid4().hex
        audit = self._audit(event, actor, target_ids, details, token=token)
        next_state = replace(
            state,
            generation=state.generation + 1,
            projection_revision=state.projection_revision + 1,
            audits=(*state.audits, audit)[-MAX_AUDIT_RECORDS:],
        )
        await self._commit(state, next_state)

    def _index(self) -> ExplorerIndex:
        index = getattr(self._projection, "explorer", None)
        if not isinstance(index, ExplorerIndex):
            raise RuntimeError("runtime explorer projection is unavailable")
        return index

    def _incident_projection(self) -> tuple[Incident, ...]:
        incidents = getattr(self._projection, "incidents", None)
        if not isinstance(incidents, tuple):
            raise RuntimeError("runtime incident projection is unavailable")
        return incidents

    def _validate_preview(
        self, state: RepositoryState, preview: GroupActionPreview
    ) -> None:
        if state.generation != preview.generation:
            raise GroupPreviewConflictError("state changed after group preview")
        by_id = {item.finding_id: item for item in state.findings}
        if not preview.findings:
            raise InvalidReviewTransitionError("group action has no eligible findings")
        for finding_id, revision in preview.findings:
            finding = by_id.get(finding_id)
            if (
                finding is None
                or finding.lifecycle is not FindingLifecycle.OPEN
                or finding.content_revision != revision
            ):
                raise GroupPreviewConflictError("finding revision changed")

    @staticmethod
    def _idempotency(
        state: RepositoryState, token: str, command: str, target_id: str
    ) -> bool:
        if not token or token != token.strip() or len(token) > 128:
            raise ValueError("idempotency token is invalid")
        replay = next((item for item in state.idempotency if item.token == token), None)
        if replay is None:
            return False
        if replay.command != command or replay.finding_id != target_id:
            raise IdempotencyConflictError("idempotency token already used")
        return True

    async def _commit(
        self, current: RepositoryState, next_state: RepositoryState
    ) -> None:
        findings, reviews, audits = apply_suppression_reviews(
            next_state.findings,
            next_state.reviews,
            next_state.audits,
            grouping_rules=next_state.grouping_rules,
            suppression_rules=next_state.suppression_rules,
            at=self._clock.now(),
        )
        index = ExplorerIndex(
            findings=findings,
            grouping_rules=next_state.grouping_rules,
            suppression_rules=next_state.suppression_rules,
            recommendations=next_state.recommendations,
            audits=audits,
            generation=next_state.generation,
            at=self._clock.now(),
        )
        existing_audit_ids = {item.audit_id for item in current.audits}
        maximum_audits = max(
            50,
            min(
                MAX_AUDIT_RECORDS,
                int(self._options.get("maximum_audit_records", MAX_AUDIT_RECORDS)),
            ),
        )
        audits = tuple(
            item
            for item in audits
            if item.audit_id in existing_audit_ids
            or self._audit_event_enabled(item.event)
            or item.event == "audit_history_cleared"
        )[-maximum_audits:]
        maximum_recommendations = max(
            1,
            min(
                MAX_RECOMMENDATIONS,
                int(
                    self._options.get("maximum_ai_recommendations", MAX_RECOMMENDATIONS)
                ),
            ),
        )
        next_state = replace(
            next_state,
            findings=findings,
            reviews=reviews,
            audits=audits,
            recommendations=mark_recommendations_stale(
                next_state.recommendations, findings, index.groups
            )[-maximum_recommendations:],
        )
        await self._repository.async_commit(
            next_state, expected_generation=current.generation
        )
        await self._projection.async_sync(next_state)
        try:
            await self._publish_transition(current, next_state)
        except Exception:
            pass

    def _audit_event_enabled(self, event: str) -> bool:
        """Apply configured inclusion policy only to future audit records."""
        mappings = (
            (
                event == "connector_test_succeeded",
                "audit_include_successful_connector_tests",
            ),
            (
                event == "connector_test_failed",
                "audit_include_failed_connector_tests",
            ),
            (event.startswith("grouping_"), "audit_include_grouping_changes"),
            (event.startswith("suppression_"), "audit_include_suppression_changes"),
            (
                event.startswith("ai_request_") or event.startswith("ai_response_"),
                "audit_include_ai_request_metadata",
            ),
            (
                event.startswith("n8n_") or event.startswith("connector_delivery_"),
                "audit_include_n8n_delivery_metadata",
            ),
        )
        for matches, option in mappings:
            if matches:
                return bool(self._options.get(option, True))
        return True

    async def _publish_transition(
        self,
        current: RepositoryState,
        committed: RepositoryState,
        *,
        extra_events: tuple[tuple[str, dict[str, Any], str], ...] = (),
    ) -> None:
        """Deliver aggregate authoritative events after the state is durable."""
        current_findings = {item.finding_id: item for item in current.findings}
        committed_findings = {item.finding_id: item for item in committed.findings}
        created = tuple(sorted(set(committed_findings) - set(current_findings)))
        resolved = tuple(
            sorted(
                finding_id
                for finding_id, item in committed_findings.items()
                if finding_id in current_findings
                and current_findings[finding_id].lifecycle is FindingLifecycle.OPEN
                and item.lifecycle is not FindingLifecycle.OPEN
            )
        )
        updated = tuple(
            sorted(
                finding_id
                for finding_id, item in committed_findings.items()
                if finding_id in current_findings
                and finding_id not in resolved
                and item != current_findings[finding_id]
            )
        )
        current_index = ExplorerIndex(
            findings=current.findings,
            grouping_rules=current.grouping_rules,
            suppression_rules=current.suppression_rules,
            recommendations=current.recommendations,
            audits=current.audits,
            generation=current.generation,
            at=self._clock.now(),
        )
        committed_index = ExplorerIndex(
            findings=committed.findings,
            grouping_rules=committed.grouping_rules,
            suppression_rules=committed.suppression_rules,
            recommendations=committed.recommendations,
            audits=committed.audits,
            generation=committed.generation,
            at=self._clock.now(),
        )
        current_groups = {item.group_id: item for item in current_index.groups}
        committed_groups = {item.group_id: item for item in committed_index.groups}
        group_created = tuple(sorted(set(committed_groups) - set(current_groups)))
        group_updated = tuple(
            sorted(
                group_id
                for group_id in set(committed_groups) & set(current_groups)
                if committed_groups[group_id] != current_groups[group_id]
            )
        )
        suppressed = tuple(
            sorted(committed_index.suppressed_ids - current_index.suppressed_ids)
        )
        events = list(extra_events)
        for event_type, ids in (
            ("finding_created", created),
            ("finding_updated", updated),
            ("finding_resolved", resolved),
            ("group_created", group_created),
            ("group_updated", group_updated),
            ("finding_suppressed", suppressed),
        ):
            if ids:
                events.append(
                    (
                        event_type,
                        {"ids": list(ids), "count": len(ids)},
                        f"{event_type}:{committed.generation}:{stable_digest(*ids)}",
                    )
                )
        if len(committed.reviews) > len(current.reviews):
            reviews = committed.reviews[len(current.reviews) :]
            events.append(
                (
                    "review_action",
                    {
                        "finding_ids": [item.finding_id for item in reviews],
                        "actions": [item.action.value for item in reviews],
                    },
                    f"review_action:{committed.generation}",
                )
            )
        if len(committed.recommendations) > len(current.recommendations):
            recommendation_ids = [
                item.recommendation_id
                for item in committed.recommendations[len(current.recommendations) :]
            ]
            events.append(
                (
                    "ai_recommendation_created",
                    {"recommendation_ids": recommendation_ids},
                    f"ai_recommendation_created:{committed.generation}",
                )
            )
        for event_type, payload, key in events[:8]:
            self._connectors.schedule_event(
                event_type,
                payload,
                generation=committed.generation,
                projection_revision=committed.projection_revision,
                idempotency_key=key,
            )
        await self._record_delivery_audits(await self._connectors.async_drain_events())

    async def _record_delivery_audits(
        self, outcomes: tuple[tuple[str, str, str | None], ...]
    ) -> None:
        """Persist bounded delivery outcomes without risking the source transition."""
        if not outcomes:
            return
        for _attempt in range(3):
            state = await self._repository.async_load()
            audits = tuple(
                self._audit(
                    "n8n_event_delivery",
                    "hamie_connector_manager",
                    (event_type,),
                    (
                        ("status", status),
                        ("error", error or "none"),
                    ),
                    token=uuid4().hex,
                )
                for event_type, status, error in outcomes
            )
            next_state = replace(
                state,
                generation=state.generation + 1,
                projection_revision=state.projection_revision + 1,
                audits=(*state.audits, *audits)[-MAX_AUDIT_RECORDS:],
            )
            try:
                await self._repository.async_commit(
                    next_state, expected_generation=state.generation
                )
            except GenerationConflictError:
                continue
            await self._projection.async_sync(next_state)
            return

    @staticmethod
    def _audit(
        event: str,
        actor: str,
        target_ids: tuple[str, ...],
        details: tuple[tuple[str, str], ...],
        *,
        token: str,
    ) -> AuditRecord:
        at = datetime.now(UTC)
        return AuditRecord(
            audit_id=f"aud_{stable_digest(event, token)[:24]}",
            event=event,
            at=at,
            actor=actor,
            target_ids=target_ids,
            details=details,
        )
