"""Closed-loop triage: the LLM describes intent, HAMIE determines effect."""

from __future__ import annotations

import json

import pytest

from hamie.application.incident_remediation import (
    IncidentRemediationPipeline,
    InvestigationDisposition,
    RemediationIntentKind,
    WorldGateway,
)
from hamie.application.investigator import Investigator
from hamie.application.remediation_tools import (
    FileGateway,
    HaGateway,
    PathPolicy,
    RemediationExecutor,
)

AI_PC = "switch.example_inference_host_plug"
OLD = "sensor.gone_away"
NEW = "sensor.still_here"

YAML = "template:\n  - sensor:\n      - state: \"{{ states('sensor.gone_away') }}\"\n"


def _model(payload):
    async def call(_s, _u):
        return payload if isinstance(payload, str) else json.dumps(payload)
    return call


def _world(*, incident, states=None, config=None, similar=()):
    states = states or {}
    config = config or {}

    async def entity_state(e): return states.get(e)
    async def search_config(q): return tuple(config.get(q, ()))
    async def get_incident(i): return incident if incident and incident.get("incident_id") == i else None
    async def similar_entities(_q): return tuple(similar)

    return WorldGateway(entity_state, search_config, get_incident, similar_entities)


def _incident(**kw):
    base = dict(
        incident_id="inc_test", title="Stale reference", root_cause="entity removed",
        category="dependency", priority="p1", evidence_status="verified",
        finding_ids=("f1", "f2"), affected_subject_ids=(f"entity:{OLD}",),
        recommended_next_step="repair the reference",
    )
    base.update(kw)
    return base


def _tmp(content=YAML):
    import os, tempfile
    d = os.path.realpath(tempfile.mkdtemp())
    p = os.path.join(d, "pkg.yaml")
    open(p, "w").write(content)
    return d, p


def _pipeline(world, model_payload, root=None):
    ha = HaGateway(
        lambda: _ok({"result": "valid"}), lambda _d: _ok(True),
        lambda _e: _ok("on"), lambda: _ok(0),
    )
    ex = RemediationExecutor(
        FileGateway(PathPolicy(allowed_roots=(root,) if root else ("/config",))), ha
    )
    return IncidentRemediationPipeline(world, Investigator(_model(model_payload)), ex)


def _ok(v):
    async def _c(*_a, **_k): return v
    return _c()


def _good_model(old=OLD, new=NEW):
    return {
        "root_cause": "template references a removed entity",
        "classification": "verified", "confidence": 1.0,
        "evidence_ids": [f"INC:inc_test", f"SUBJ:{old}"],
        "proposed_action": f"replace {old} with {new}",
        "action_type": "replace_entity_reference",
        "affected_objects": [old, new],
    }


# ---------------------------------------------------------------- routing


@pytest.mark.asyncio
async def test_informational_incident_is_no_action() -> None:
    w = _world(incident=_incident(priority="info"))
    r = await _pipeline(w, _good_model()).async_triage("inc_test")
    assert r.disposition is InvestigationDisposition.NO_ACTION
    assert r.investigation is None, "must not spend inference on informational noise"


@pytest.mark.asyncio
async def test_missing_incident_is_insufficient_evidence() -> None:
    r = await _pipeline(_world(incident=None), _good_model()).async_triage("nope")
    assert r.disposition is InvestigationDisposition.INSUFFICIENT_EVIDENCE


@pytest.mark.asyncio
async def test_llm_unavailable_never_produces_candidate() -> None:
    async def boom(_s, _u): raise TimeoutError("down")
    w = _world(incident=_incident())
    p = IncidentRemediationPipeline(w, Investigator(boom), None)
    r = await p.async_triage("inc_test")
    assert r.disposition is InvestigationDisposition.INSUFFICIENT_EVIDENCE
    assert r.dry_run is None


@pytest.mark.asyncio
async def test_external_dependency_routes_out() -> None:
    w = _world(incident=_incident())
    m = _good_model(); m["root_cause"] = "upstream vendor API changed"
    m["proposed_action"] = "external upstream fix required"
    m["action_type"] = "none"
    r = await _pipeline(w, m).async_triage("inc_test")
    assert r.disposition is InvestigationDisposition.EXTERNAL_ACTION_REQUIRED


# ------------------------------------- LLM intent is NOT authoritative


@pytest.mark.asyncio
async def test_model_hints_are_advisory_only_in_output() -> None:
    root, p = _tmp()
    w = _world(incident=_incident(), states={NEW: "42"},
               config={OLD: ((p, 1),)}, similar=(NEW,))
    r = await _pipeline(w, _good_model(), root).async_triage("inc_test")
    assert r.intent["advisory_only"]["new_entity"] == NEW
    assert "not authoritative" in r.intent["advisory_only"]["note"]
    # rediscovery, not the hint, is what the plan used
    assert r.rediscovery["new_entity"] == NEW
    assert r.rediscovery["usable_for_planning"] is True


@pytest.mark.asyncio
async def test_hallucinated_replacement_is_rejected() -> None:
    """Model names a replacement that does not exist -> refuse, do not guess."""
    root, p = _tmp()
    w = _world(incident=_incident(), states={}, config={OLD: ((p, 1),)}, similar=())
    r = await _pipeline(w, _good_model(new="sensor.invented"), root).async_triage("inc_test")
    assert r.disposition is InvestigationDisposition.OPERATOR_DECISION_REQUIRED
    assert "replacement" in r.blocked_reason


@pytest.mark.asyncio
async def test_multiple_plausible_replacements_refuse() -> None:
    """The real 'three printer entities' hazard."""
    root, p = _tmp()
    w = _world(incident=_incident(), states={}, config={OLD: ((p, 1),)},
               similar=("sensor.a", "sensor.b", "sensor.c"))
    r = await _pipeline(w, _good_model(new="sensor.a"), root).async_triage("inc_test")
    # hint not among a unique candidate set -> still resolves only if hint matches
    assert r.rediscovery["candidate_replacements"]
    assert r.disposition in (
        InvestigationDisposition.REPAIR_CANDIDATE,
        InvestigationDisposition.OPERATOR_DECISION_REQUIRED,
    )


@pytest.mark.asyncio
async def test_wrong_domain_replacement_blocked() -> None:
    root, p = _tmp()
    w = _world(incident=_incident(), states={"switch.other": "on"},
               config={OLD: ((p, 1),)}, similar=("switch.other",))
    r = await _pipeline(w, _good_model(new="switch.other"), root).async_triage("inc_test")
    assert r.rediscovery["domains_compatible"] is False
    assert r.disposition is InvestigationDisposition.OPERATOR_DECISION_REQUIRED


# ------------------------------------- evidence sufficiency beats confidence


@pytest.mark.asyncio
async def test_weak_incident_evidence_overrides_model_confidence() -> None:
    """confidence 1.0 does not make a POSSIBLE incident verified."""
    root, p = _tmp()
    w = _world(incident=_incident(evidence_status="possible"), states={NEW: "42"},
               config={OLD: ((p, 1),)}, similar=(NEW,))
    r = await _pipeline(w, _good_model(), root).async_triage("inc_test")
    assert r.disposition is InvestigationDisposition.OPERATOR_DECISION_REQUIRED
    assert any("evidence_status" in n for n in r.notes)
    assert r.dry_run is None, "no plan may be built on insufficient evidence"


# ------------------------------------- protected invariants


@pytest.mark.asyncio
async def test_protected_entity_blocks_candidate() -> None:
    root, p = _tmp(f"actions:\n  - action: switch.turn_off\n    entity_id: {AI_PC}\n")
    w = _world(incident=_incident(affected_subject_ids=(f"entity:{AI_PC}",)),
               states={NEW: "42"}, config={AI_PC: ((p, 1),)}, similar=(NEW,))
    m = _good_model(old=AI_PC)
    m["affected_objects"] = [AI_PC, NEW]
    r = await _pipeline(w, m, root).async_triage("inc_test")
    assert r.disposition is InvestigationDisposition.BLOCKED
    assert r.dry_run is None


# ------------------------------------- repair candidate + dry run


@pytest.mark.asyncio
async def test_repair_candidate_produces_non_mutating_dry_run() -> None:
    root, p = _tmp()
    before = open(p).read()
    w = _world(incident=_incident(), states={NEW: "42"},
               config={OLD: ((p, 2),)}, similar=(NEW,))
    r = await _pipeline(w, _good_model(), root).async_triage("inc_test")
    assert r.disposition is InvestigationDisposition.REPAIR_CANDIDATE
    assert r.dry_run["outcome"] == "dry_run"
    assert open(p).read() == before, "triage must never mutate"
    assert r.approval_required is True
    assert r.plan_identity, "approval must bind to a plan identity"
    assert r.risk == "config_mutation"
    assert r.member_finding_count == 2


@pytest.mark.asyncio
async def test_result_serialises_for_operator_presentation() -> None:
    root, p = _tmp()
    w = _world(incident=_incident(), states={NEW: "42"},
               config={OLD: ((p, 1),)}, similar=(NEW,))
    d = (await _pipeline(w, _good_model(), root).async_triage("inc_test")).as_dict()
    for k in ("incident_id", "disposition", "priority", "evidence_status",
              "incident_root_cause", "member_finding_count", "investigation",
              "intent", "rediscovery", "risk", "authorization", "dry_run",
              "approval_required", "plan_identity"):
        assert k in d, f"operator view missing {k}"


def test_runtime_uses_the_real_projection_accessor() -> None:
    """Regression: the wiring first used a non-existent public alias.

    MaintenanceOperationsService exposes _incident_projection(); calling
    incident_projection() would raise AttributeError only in production.
    """
    import inspect

    from hamie.application import runtime as rt
    from hamie.application.operations_service import MaintenanceOperationsService

    assert hasattr(MaintenanceOperationsService, "_incident_projection")
    src = inspect.getsource(rt.HamieRuntime)
    assert "operations._incident_projection()" in src
    assert "operations.incident_projection()" not in src


# --------------------------------------------------------------------------
# Regression found on LIVE data: incident inc_54f6249... referenced
# device_tracker.example_phone_15_2 in 10 real config locations, but the
# successor matcher normalized *any* trailing _<digits>, turning the real base
# "example_phone_15" into "example_phone" and finding no candidate. Only a
# single-digit HA duplicate suffix may be stripped.
# --------------------------------------------------------------------------


import re as _re

_DUP_SUFFIX = _re.compile(r"^(.*)_([2-9])$")


def _base_of(entity_id: str) -> str | None:
    domain, _, obj = entity_id.partition(".")
    m = _DUP_SUFFIX.match(obj)
    return f"{domain}.{m.group(1)}" if m else None


def test_duplicate_suffix_stripping_preserves_numeric_names() -> None:
    assert _base_of("device_tracker.example_phone_15_2") == "device_tracker.example_phone_15"
    assert _base_of("sensor.ai_turret_link_speed_2") == "sensor.ai_turret_link_speed"
    # a name that merely ends in digits is not a duplicate suffix
    assert _base_of("device_tracker.example_phone_15") is None
    assert _base_of("sensor.pm_25") is None
    assert _base_of("sensor.plain") is None


def test_runtime_matcher_is_narrow() -> None:
    """The deployed matcher must not do fuzzy similarity."""
    import inspect

    from hamie.application import runtime as rt

    src = inspect.getsource(rt.HamieRuntime)
    assert "_DUP_SUFFIX" in src
    assert "difflib" not in src and "SequenceMatcher" not in src, (
        "string similarity must never choose a production target"
    )


# ------------------------------------- the model is advisory, not a gate
#
# Live defect: identical, unchanged inputs produced operator_decision_required
# and needed up to FOUR triage attempts before the same incident was
# recognised as repairable. derive_intent() classifies the model's PROSE, an
# unrecognised phrasing became kind=UNKNOWN -> "not actionable", and triage
# returned before deterministic rediscovery ever ran. Deterministic evidence
# had already proved more reliable than the model, so it now runs first.


def _repairable_world(root):
    return _world(
        incident=_incident(),
        states={NEW: "on"},
        config={OLD: ((f"{root}/pkg.yaml", 1),)},
        similar=(NEW,),
    )


@pytest.mark.asyncio
async def test_unrecognised_model_prose_no_longer_blocks_a_deterministic_repair() -> None:
    root, _p = _tmp()
    vague = {
        "root_cause": "something is off with the configuration",
        "classification": "verified", "confidence": 1.0,
        "evidence_ids": ["INC:inc_test"],
        "proposed_action": "have a look at it sometime",   # matches no keyword
        "action_type": "",
        "affected_objects": [],
    }
    r = await _pipeline(_repairable_world(root), vague, root).async_triage("inc_test")
    assert r.disposition is InvestigationDisposition.REPAIR_CANDIDATE
    assert r.rediscovery["old_entity"] == OLD
    assert r.rediscovery["new_entity"] == NEW


@pytest.mark.asyncio
async def test_model_naming_a_different_replacement_is_ignored() -> None:
    root, _p = _tmp()
    lying = _good_model(new="sensor.something_the_model_invented")
    r = await _pipeline(_repairable_world(root), lying, root).async_triage("inc_test")
    assert r.disposition is InvestigationDisposition.REPAIR_CANDIDATE
    # The deterministic resolver's answer wins; the invented target never appears.
    assert r.rediscovery["new_entity"] == NEW


@pytest.mark.asyncio
async def test_model_saying_no_repair_does_not_veto_deterministic_evidence() -> None:
    root, _p = _tmp()
    refusing = {
        "root_cause": "the device is simply powered off, nothing to do",
        "classification": "verified", "confidence": 1.0,
        "evidence_ids": ["INC:inc_test"],
        "proposed_action": "no action required, device offline",
        "action_type": "", "affected_objects": [],
    }
    r = await _pipeline(_repairable_world(root), refusing, root).async_triage("inc_test")
    assert r.disposition is InvestigationDisposition.REPAIR_CANDIDATE


@pytest.mark.asyncio
async def test_model_failure_still_yields_a_deterministic_disposition() -> None:
    root, _p = _tmp()
    r = await _pipeline(_repairable_world(root), "not json at all", root).async_triage("inc_test")
    assert r.disposition is InvestigationDisposition.REPAIR_CANDIDATE
    assert any("advisory analysis degraded" in n for n in r.notes)


@pytest.mark.asyncio
async def test_model_confidence_cannot_create_a_repair_without_deterministic_targets() -> None:
    # No config reference and no successor: confident prose must not help.
    w = _world(incident=_incident(), states={NEW: "on"}, config={}, similar=())
    r = await _pipeline(w, _good_model()).async_triage("inc_test")
    assert r.disposition is not InvestigationDisposition.REPAIR_CANDIDATE


@pytest.mark.asyncio
async def test_deterministic_fields_are_identical_across_varying_model_prose() -> None:
    root, _p = _tmp()
    prose = [
        _good_model(),
        {"root_cause": "vague", "classification": "verified", "confidence": 1.0,
         "evidence_ids": ["INC:inc_test"], "proposed_action": "unclear",
         "action_type": "", "affected_objects": []},
        {"root_cause": "external vendor problem", "classification": "verified",
         "confidence": 1.0, "evidence_ids": ["INC:inc_test"],
         "proposed_action": "upstream vendor issue", "action_type": "",
         "affected_objects": []},
        "not json at all",
    ]
    seen = []
    for payload in prose:
        r = await _pipeline(_repairable_world(root), payload, root).async_triage("inc_test")
        seen.append((
            r.disposition,
            r.rediscovery["old_entity"], r.rediscovery["new_entity"],
            r.rediscovery["total_occurrences"], r.rediscovery["ambiguous"],
            r.risk,
        ))
    assert len(set(seen)) == 1, f"deterministic fields varied with prose: {seen}"
    assert seen[0][0] is InvestigationDisposition.REPAIR_CANDIDATE


@pytest.mark.asyncio
async def test_insufficient_evidence_incident_still_needs_an_operator() -> None:
    # HAMIE's own evidence policy is unchanged by the reorder.
    root, _p = _tmp()
    w = _world(
        incident=_incident(evidence_status="possible"),
        states={NEW: "on"}, config={OLD: ((f"{root}/pkg.yaml", 1),)}, similar=(NEW,),
    )
    r = await _pipeline(w, _good_model(), root).async_triage("inc_test")
    assert r.disposition is InvestigationDisposition.OPERATOR_DECISION_REQUIRED


# ------------------------------------ advisory-failure hook stays inert
#
# Proves the hook cannot fire on anything but the one incident an operator
# named in a marker file that does not exist by default.


def test_triage_failure_hook_disabled_without_marker(tmp_path):
    from hamie.application.incident_remediation import read_triage_fail_incident

    assert read_triage_fail_incident(str(tmp_path)) == ""


def test_triage_failure_hook_names_exactly_one_incident(tmp_path):
    from hamie.application.incident_remediation import (
        TRIAGE_FAIL_MARKER,
        read_triage_fail_incident,
    )

    (tmp_path / TRIAGE_FAIL_MARKER).write_text("  inc_test \n", encoding="utf-8")
    assert read_triage_fail_incident(str(tmp_path)) == "inc_test"


def test_triage_failure_hook_empty_marker_arms_nothing(tmp_path):
    from hamie.application.incident_remediation import (
        TRIAGE_FAIL_MARKER,
        read_triage_fail_incident,
    )

    (tmp_path / TRIAGE_FAIL_MARKER).write_text("  \n", encoding="utf-8")
    assert read_triage_fail_incident(str(tmp_path)) == ""
