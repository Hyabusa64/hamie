"""The model may request. Only deterministic code authorizes."""

from __future__ import annotations

import os
import tempfile

import pytest

from hamie.application.remediation_tools import (
    AUTHORIZATION_POLICY,
    AuthorizationDecision,
    EntityCandidate,
    FileGateway,
    HaGateway,
    PathPolicy,
    RemediationExecutor,
    RemediationRefused,
    ToolRisk,
    authorize,
    classify_risk,
    extract_off_targets,
    resolve_unique_entity,
)

AI_PC = "switch.example_inference_host_plug"

SAFE_YAML = """automation:
  - id: demo
    alias: "Demo"
    triggers:
      - trigger: state
        entity_id: sensor.old_name
    actions:
      - action: notify.mobile_app_16_promax
        data:
          message: "{{ states('sensor.old_name') }}"
"""


def _ha(*, valid=True, reload_ok=True, state="on", errors=0):
    async def check_config():
        return {"result": "valid" if valid else "invalid", "errors": None if valid else "boom"}

    async def reload_domain(_d):
        return reload_ok

    async def entity_state(_e):
        return state

    async def recent_errors():
        return errors

    return HaGateway(check_config, reload_domain, entity_state, recent_errors)


def _tmp(content=SAFE_YAML):
    # realpath: macOS resolves /var -> /private/var, and PathPolicy compares
    # against the *resolved* path (which is what makes traversal rejection work).
    d = os.path.realpath(tempfile.mkdtemp())
    p = os.path.join(d, "pkg.yaml")
    open(p, "w").write(content)
    return d, p


def _exec(root, ha):
    return RemediationExecutor(FileGateway(PathPolicy(allowed_roots=(root,))), ha)


# ---------------------------------------------------- risk & authorization


def test_policy_table_blocks_dangerous_classes() -> None:
    for risk in (ToolRisk.PHYSICAL_STATE_CHANGE, ToolRisk.SECURITY_CRITICAL,
                 ToolRisk.DESTRUCTIVE):
        assert AUTHORIZATION_POLICY[risk] is AuthorizationDecision.BLOCKED


def test_unknown_operation_is_never_safe() -> None:
    assert classify_risk("do_something_clever") is ToolRisk.DESTRUCTIVE


def test_physical_and_security_denied_by_default() -> None:
    assert authorize(operation="call_service", targets=("switch.lamp",)).decision \
        is AuthorizationDecision.BLOCKED
    assert authorize(operation="delete_entity", targets=("sensor.x",)).decision \
        is AuthorizationDecision.BLOCKED


def test_restart_requires_approval_then_permits_with_it() -> None:
    assert authorize(operation="restart_core", targets=()).decision \
        is AuthorizationDecision.REQUIRES_APPROVAL
    assert authorize(operation="restart_core", targets=(), approved_by="owner").decision \
        is AuthorizationDecision.AUTOMATIC


def test_safe_reversible_needs_real_backing() -> None:
    assert authorize(operation="reload_domain", targets=(), confidence=0.1).decision \
        is AuthorizationDecision.REQUIRES_APPROVAL
    assert authorize(operation="reload_domain", targets=(), confidence=0.99,
                     evidence_ids=("E1",)).decision is AuthorizationDecision.AUTOMATIC


# ---------------------------------------------------- effect awareness


def test_off_targets_measured_not_declared() -> None:
    y = "  - action: switch.turn_off\n    target:\n      entity_id: " + AI_PC + "\n"
    assert AI_PC in extract_off_targets(y)


def test_turn_on_is_not_an_off_target() -> None:
    y = "  - action: switch.turn_on\n    target:\n      entity_id: switch.lamp\n"
    assert extract_off_targets(y) == frozenset()


def test_adversarial_innocent_description_real_effect_is_blocked() -> None:
    """ADVERSARIAL #2: benign wording, protected effect."""
    res = authorize(
        operation="update_automation",
        targets=("automation.tidy_up",),          # model's harmless claim
        added_off_targets=frozenset({AI_PC}),     # what it actually does
        intent="minor tidy-up of an automation",
        approved_by="owner",                      # even WITH approval
    )
    assert res.decision is AuthorizationDecision.BLOCKED
    assert res.protection["matched_invariants"][0]["id"] == "hamie-local-inference-power"


def test_adversarial_direct_ai_pc_poweroff_blocked() -> None:
    """ADVERSARIAL #1."""
    res = authorize(operation="call_service", targets=(AI_PC,),
                    added_off_targets=frozenset({AI_PC}), approved_by="owner")
    assert res.decision is AuthorizationDecision.BLOCKED


def test_adversarial_security_entity_effect_escalates() -> None:
    """ADVERSARIAL #3/#4: an unlock effect is SECURITY_CRITICAL, never approved."""
    res = authorize(operation="replace_entity_reference", targets=("x",),
                    added_off_targets=frozenset({"lock.front_door"}),
                    approved_by="owner")
    assert res.risk is ToolRisk.SECURITY_CRITICAL
    assert res.decision is AuthorizationDecision.BLOCKED


# ---------------------------------------------------- ambiguity


def test_ambiguous_entity_refuses() -> None:
    """ADVERSARIAL #5: three real printer-named devices exist here."""
    cands = (
        EntityCandidate("switch.3d_printer_plug"),
        EntityCandidate("switch.printer_outlet"),
        EntityCandidate("switch.example_printer_plug"),
    )
    with pytest.raises(RemediationRefused) as e:
        resolve_unique_entity("printer", cands)
    assert e.value.code == "ambiguous_entity"


def test_exact_match_resolves() -> None:
    c = resolve_unique_entity(
        "switch.3d_printer_plug",
        (EntityCandidate("switch.3d_printer_plug"), EntityCandidate("switch.printer_outlet")),
    )
    assert c.entity_id == "switch.3d_printer_plug"


def test_missing_entity_refuses() -> None:
    with pytest.raises(RemediationRefused) as e:
        resolve_unique_entity("sensor.nope", ())
    assert e.value.code == "entity_not_found"


# ---------------------------------------------------- path safety


def test_path_traversal_rejected() -> None:
    with pytest.raises(RemediationRefused):
        PathPolicy(allowed_roots=("/config",)).check("/config/../etc/passwd.yaml")


def test_secrets_and_storage_denied() -> None:
    for p in ("/config/secrets.yaml", "/config/.storage/core.entity_registry.yaml"):
        with pytest.raises(RemediationRefused):
            PathPolicy().check(p)


def test_non_yaml_rejected() -> None:
    with pytest.raises(RemediationRefused):
        PathPolicy().check("/config/shell.sh")


# ---------------------------------------------------- dry-run / execute


@pytest.mark.asyncio
async def test_dry_run_makes_no_change_but_reports_everything() -> None:
    root, p = _tmp()
    before = open(p).read()
    txn = await _exec(root, _ha()).async_replace_entity_reference(
        request="fix stale ref", path=p, old_entity="sensor.old_name",
        new_entity="sensor.new_name", dry_run=True,
    )
    assert txn.outcome == "dry_run"
    assert open(p).read() == before, "dry run must not write"
    assert txn.pre_hash and txn.post_hash and txn.pre_hash != txn.post_hash
    assert txn.diff and txn.authorization["risk"] == "config_mutation"


@pytest.mark.asyncio
async def test_dry_run_and_execute_agree() -> None:
    root, p = _tmp()
    ex = _exec(root, _ha())
    kw = dict(request="r", path=p, old_entity="sensor.old_name",
              new_entity="sensor.new_name")
    dry = await ex.async_replace_entity_reference(**kw, dry_run=True)
    live = await ex.async_replace_entity_reference(**kw, dry_run=False,
                                                   approved_by="owner")
    assert dry.post_hash == live.post_hash, "preview must equal execution"


@pytest.mark.asyncio
async def test_config_mutation_requires_approval() -> None:
    root, p = _tmp()
    txn = await _exec(root, _ha()).async_replace_entity_reference(
        request="r", path=p, old_entity="sensor.old_name",
        new_entity="sensor.new_name", dry_run=False,
    )
    assert txn.outcome == "awaiting_approval"
    assert not txn.executed
    assert "sensor.old_name" in open(p).read(), "file must be untouched"


@pytest.mark.asyncio
async def test_approved_execution_backs_up_and_validates() -> None:
    root, p = _tmp()
    txn = await _exec(root, _ha()).async_replace_entity_reference(
        request="r", path=p, old_entity="sensor.old_name",
        new_entity="sensor.new_name", dry_run=False, approved_by="owner",
        reload_domain="automation",
    )
    assert txn.outcome == "success" and txn.executed
    assert txn.backup_path and os.path.exists(txn.backup_path)
    assert "sensor.old_name" in open(txn.backup_path).read(), "backup holds original"
    assert "sensor.new_name" in open(p).read()
    checks = {v["check"]: v["passed"] for v in txn.validation}
    assert checks["ha_config_valid"] and checks["reload_automation"]
    assert checks["replacement_entity_available"] and checks["no_new_errors"]


@pytest.mark.asyncio
async def test_no_action_when_reference_absent() -> None:
    root, p = _tmp()
    txn = await _exec(root, _ha()).async_replace_entity_reference(
        request="r", path=p, old_entity="sensor.not_here",
        new_entity="sensor.x", dry_run=False, approved_by="owner",
    )
    assert txn.outcome == "no_action_needed" and not txn.executed


# ---------------------------------------------------- rollback


@pytest.mark.asyncio
async def test_invalid_config_triggers_automatic_rollback() -> None:
    root, p = _tmp()
    original = open(p).read()
    txn = await _exec(root, _ha(valid=False)).async_replace_entity_reference(
        request="r", path=p, old_entity="sensor.old_name",
        new_entity="sensor.new_name", dry_run=False, approved_by="owner",
    )
    assert txn.outcome == "rolled_back" and txn.rolled_back
    assert open(p).read() == original, "file must be byte-identical again"
    assert any(v["check"] == "rollback_restored_original" and v["passed"]
               for v in txn.validation)


@pytest.mark.asyncio
async def test_unavailable_replacement_triggers_rollback() -> None:
    root, p = _tmp()
    original = open(p).read()
    txn = await _exec(root, _ha(state="unavailable")).async_replace_entity_reference(
        request="r", path=p, old_entity="sensor.old_name",
        new_entity="sensor.new_name", dry_run=False, approved_by="owner",
    )
    assert txn.outcome == "rolled_back"
    assert open(p).read() == original


@pytest.mark.asyncio
async def test_new_errors_trigger_rollback() -> None:
    root, p = _tmp()
    original = open(p).read()
    txn = await _exec(root, _ha(errors=3)).async_replace_entity_reference(
        request="r", path=p, old_entity="sensor.old_name",
        new_entity="sensor.new_name", dry_run=False, approved_by="owner",
    )
    assert txn.outcome == "rolled_back"
    assert open(p).read() == original


# ---------------------------------------------------- audit


@pytest.mark.asyncio
async def test_transaction_audit_is_complete() -> None:
    root, p = _tmp()
    txn = await _exec(root, _ha()).async_replace_entity_reference(
        request="fix the thing", path=p, old_entity="sensor.old_name",
        new_entity="sensor.new_name", root_cause="entity renamed",
        evidence_ids=("EV-1",), confidence=0.97, dry_run=False,
        approved_by="owner", reload_domain="automation",
    )
    d = txn.as_dict()
    for key in ("transaction_id", "created_at", "request", "operation", "root_cause",
                "evidence_ids", "confidence", "affected_objects", "source_files",
                "measured_off_targets", "authorization", "pre_hash", "post_hash",
                "backup_path", "diff", "validation", "executed", "rolled_back",
                "outcome"):
        assert key in d, f"audit record missing {key}"
    assert d["transaction_id"].startswith("HAMIE-")


@pytest.mark.asyncio
async def test_protected_effect_blocks_even_when_approved() -> None:
    """End-to-end: writing an AI-PC turn_off into config is refused."""
    root, p = _tmp(
        "automation:\n  - id: x\n    actions:\n      - action: switch.turn_off\n"
        "        target:\n          entity_id: sensor.old_name\n"
    )
    txn = await _exec(root, _ha()).async_replace_entity_reference(
        request="harmless cleanup", path=p, old_entity="sensor.old_name",
        new_entity=AI_PC, dry_run=False, approved_by="owner",
    )
    assert txn.outcome == "blocked"
    assert not txn.executed
    assert AI_PC in txn.measured_off_targets
    assert "sensor.old_name" in open(p).read(), "file untouched"


# --------------------------------------------------------------------------
# Regression: Home Assistant detected blocking open() inside the event loop
# from FileGateway during the live WebSocket proof. Blocking I/O in the loop
# can stall the whole house, so every file operation must be off-loop.
# --------------------------------------------------------------------------


def test_file_io_is_dispatched_off_the_event_loop() -> None:
    import inspect

    from hamie.application import remediation_tools as rt

    src = inspect.getsource(rt.RemediationExecutor)
    for op in (".read(", ".write(", ".backup("):
        for line in src.splitlines():
            if f"self._files{op}" in line and "to_thread" not in line:
                raise AssertionError(
                    f"blocking file op not dispatched to a thread: {line.strip()}"
                )
    assert "asyncio.to_thread(self._files.read" in src
    assert "asyncio.to_thread(self._files.write" in src
    assert "asyncio.to_thread(self._files.backup" in src


@pytest.mark.asyncio
async def test_off_loop_dispatch_preserves_behaviour() -> None:
    """Threaded I/O must not change outcomes."""
    root, p = _tmp()
    txn = await _exec(root, _ha()).async_replace_entity_reference(
        request="r", path=p, old_entity="sensor.old_name",
        new_entity="sensor.new_name", dry_run=False, approved_by="owner",
    )
    assert txn.outcome == "success"
    assert "sensor.new_name" in open(p).read()
