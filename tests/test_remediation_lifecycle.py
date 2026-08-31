"""Post-repair proof: a successful mutation is not a successful remediation.

Every test here exists because the opposite behaviour would look like
success. The whole point of the lifecycle is that writing the bytes is the
easy part, so these cases lean hard on the paths where the write worked and
the problem did not go away.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from hamie.application.incident_remediation import (
    IncidentRemediationPipeline,
    InvestigationDisposition,
)
from hamie.application.investigator import Investigator
from hamie.application.remediation_lifecycle import (
    DEFAULT_STATE_INVARIANTS,
    LifecycleGateway,
    LifecycleStage,
    ReconciliationVerdict,
    RemediationLifecycle,
    RepairPlan,
    compare_plans,
    plan_from_dict,
)
from hamie.application.remediation_tools import (
    FileGateway,
    HaGateway,
    PathPolicy,
    RemediationExecutor,
    ToolRisk,
    authorize,
    classify_risk,
)
from hamie.application.incident_remediation import WorldGateway
from hamie.domain.remediation_execution import (
    UNRESOLVED_REMEDIATION_OUTCOMES,
    RemediationOutcome,
)

OLD = "device_tracker.example_phone_15_2"
NEW = "device_tracker.example_phone_15"
INCIDENT_ID = "inc_test_stale_reference"
ACTOR = "home_assistant_user:abc123"

FILE_A = (
    "automation:\n"
    "  - id: a1\n"
    "    triggers:\n"
    f"      - trigger: state\n        entity_id: {OLD}\n"
    "    actions:\n"
    "      - action: light.turn_on\n"
)
FILE_B = (
    "automation:\n"
    "  - id: b1\n"
    "    conditions:\n"
    f"      - condition: state\n        entity_id: {OLD}\n"
    f"      - condition: state\n        entity_id: {OLD}\n"
    "    actions:\n"
    "      - action: light.turn_on\n"
)


# ---------------------------------------------------------------- harness


class _World:
    """Deterministic facts, backed by a real temporary config tree."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.states: dict[str, str] = {NEW: "home"}
        self.incidents: dict[str, dict] = {}
        self.similar: dict[str, tuple[str, ...]] = {OLD: (NEW,)}

    async def entity_state(self, entity_id: str) -> str | None:
        return self.states.get(entity_id)

    async def search_config(self, needle: str) -> tuple[tuple[str, int], ...]:
        found = []
        for name in sorted(os.listdir(self.root)):
            if not name.endswith(".yaml"):
                continue
            path = os.path.join(self.root, name)
            with open(path, encoding="utf-8") as fh:
                count = fh.read().count(needle)
            if count:
                found.append((path, count))
        return tuple(found)

    async def get_incident(self, incident_id: str) -> dict | None:
        return self.incidents.get(incident_id)

    async def similar_entities(self, entity_id: str) -> tuple[str, ...]:
        return self.similar.get(entity_id, ())

    def gateway(self) -> WorldGateway:
        return WorldGateway(
            self.entity_state, self.search_config, self.get_incident, self.similar_entities
        )


class _Gate:
    def __init__(self) -> None:
        self.scan_id = "scan_pre"
        self.next_scan_id = "scan_post"
        self.scan_state = "completed"
        self.scan_raises: str | None = None
        self.incident_list: list[dict] = []
        self.audits: list[tuple] = []
        self.lifecycle_calls: list[dict] = []
        self.baselines: list = []
        self.on_scan = None

    async def request_scan(self) -> dict:
        if self.scan_raises:
            raise RuntimeError(self.scan_raises)
        if self.on_scan is not None:
            self.on_scan()
        return {"scan_id": self.next_scan_id, "state": self.scan_state}

    async def current_scan_id(self) -> str | None:
        return self.scan_id

    async def incidents(self) -> tuple[dict, ...]:
        return tuple(self.incident_list)

    async def record_audit(self, event, *, actor, target_ids, details) -> None:
        self.audits.append((event, actor, tuple(target_ids), dict(details)))

    async def set_incident_lifecycle(self, **kwargs) -> None:
        self.lifecycle_calls.append(kwargs)

    async def save_remediation_baseline(self, baseline) -> None:
        """A configured deployment persists recovery truth.

        Required checkpoints now fail closed, so a harness without a saver
        would represent a MISCONFIGURED system rather than the real one. The
        unconfigured case is pinned separately in
        tests/test_checkpoint_durability.py.
        """
        self.baselines.append(baseline)

    def gateway(self, *, with_lifecycle: bool = True) -> LifecycleGateway:
        return LifecycleGateway(
            self.request_scan,
            self.current_scan_id,
            self.incidents,
            self.record_audit,
            self.set_incident_lifecycle if with_lifecycle else None,
            self.save_remediation_baseline,
        )


class _Ha:
    def __init__(self, world: _World) -> None:
        self.world = world
        self.config_valid = True
        self.config_plan: list[bool] = []
        self.config_errors: list[str] | None = None
        self.reload_ok = True
        self.signatures: tuple[str, ...] = ()
        self.counts = {
            "automation": {"on": 10, "unavailable": 553},
            "script": {"on": 5, "unavailable": 54},
        }
        self.scope: tuple[str, ...] = ("automation.a1", "automation.b1")
        self.reloaded: list[str] = []

    async def check_config(self) -> dict:
        # config_plan lets a test say "valid before the mutation, invalid
        # after, valid again once rolled back" -- which is the only shape
        # that actually exercises post-mutation validation. A flat
        # config_valid=False would be caught by the pre-state gate instead,
        # which is correct behaviour but a different test.
        valid = self.config_valid
        if self.config_plan:
            valid = self.config_plan.pop(0)
        return {"result": "valid" if valid else "invalid", "errors": self.config_errors}

    async def reload_domain(self, domain: str) -> bool:
        self.reloaded.append(domain)
        return self.reload_ok

    async def entity_state(self, entity_id: str) -> str | None:
        return self.world.states.get(entity_id)

    async def recent_errors(self) -> int:
        return 0

    async def error_signatures(self) -> tuple[str, ...]:
        return self.signatures

    async def domain_state_counts(self, domain: str) -> dict[str, int]:
        return dict(self.counts.get(domain, {}))

    async def config_scope_entities(self, paths: tuple[str, ...]) -> tuple[str, ...]:
        return self.scope

    def gateway(self) -> HaGateway:
        return HaGateway(
            self.check_config,
            self.reload_domain,
            self.entity_state,
            self.recent_errors,
            self.error_signatures,
            self.domain_state_counts,
            self.config_scope_entities,
        )


def _incident(**kw) -> dict:
    base = dict(
        incident_id=INCIDENT_ID,
        title="Stale device_tracker reference",
        root_cause="configuration references an entity that no longer exists",
        category="dependency",
        priority="p1",
        evidence_status="verified",
        lifecycle="new",
        content_revision=3,
        material_digest="digest_v1",
        finding_ids=("f1", "f2"),
        affected_subject_ids=(f"entity:{OLD}",),
        recommended_next_step="repair the reference",
    )
    base.update(kw)
    return base


class _Rig:
    """One temporary installation: files, world, gateways, lifecycle."""

    def __init__(self, *, files: dict[str, str] | None = None, file_gateway=None) -> None:
        self.root = os.path.realpath(tempfile.mkdtemp())
        for name, content in (files or {"a.yaml": FILE_A, "b.yaml": FILE_B}).items():
            with open(os.path.join(self.root, name), "w", encoding="utf-8") as fh:
                fh.write(content)
        self.world = _World(self.root)
        self.world.incidents[INCIDENT_ID] = _incident()
        self.gate = _Gate()
        self.gate.incident_list = [_incident()]
        self.ha = _Ha(self.world)
        policy = PathPolicy(allowed_roots=(self.root,))
        self.files = file_gateway(policy) if file_gateway else FileGateway(policy)
        self.executor = RemediationExecutor(self.files, self.ha.gateway())
        self.lifecycle = RemediationLifecycle(
            self.world.gateway(), self.gate.gateway(), self.executor
        )

    def path(self, name: str) -> str:
        return os.path.join(self.root, name)

    def text(self, name: str) -> str:
        with open(self.path(name), encoding="utf-8") as fh:
            return fh.read()

    def occurrences(self, needle: str = OLD) -> int:
        return sum(
            self.text(n).count(needle)
            for n in os.listdir(self.root)
            if n.endswith(".yaml")
        )

    def backups(self) -> list[str]:
        return [n for n in os.listdir(self.root) if ".hamie_bak_" in n]

    def resolve_after_scan(self) -> None:
        """The fresh scan stops producing the incident (root cause gone)."""

        def _hook() -> None:
            self.gate.incident_list = [_incident(lifecycle="resolved", content_revision=4)]

        self.gate.on_scan = _hook

    async def plan(self) -> RepairPlan:
        _incident_dict, plan, failure = await self.lifecycle.async_derive_plan(INCIDENT_ID)
        assert plan is not None, failure
        return plan

    async def execute(self, plan: RepairPlan | None = None, *, approved_by: str = ACTOR, advisory=None):
        plan = plan or await self.plan()
        return await self.lifecycle.async_execute(
            INCIDENT_ID,
            approved_plan=plan.as_dict(),
            approved_plan_identity=plan.plan_identity,
            approved_by=approved_by,
            advisory=advisory,
        )


# ------------------------------------------------------- 1, 16, 25: success


@pytest.mark.asyncio
async def test_repair_resolves_when_fresh_scan_no_longer_finds_the_root_cause() -> None:
    rig = _Rig()
    rig.resolve_after_scan()
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.RESOLVED
    assert result.stage is LifecycleStage.COMPLETE
    assert rig.occurrences(OLD) == 0
    assert rig.occurrences(NEW) == 3
    assert result.finding_reconciliation["verdict"] == ReconciliationVerdict.ELIMINATED.value
    assert result.rescan["pre_repair_scan_id"] != result.rescan["post_repair_scan_id"]
    assert result.rescan["fresh_scan_completed"] is True


@pytest.mark.asyncio
async def test_resolved_incident_carries_deterministic_resolution_evidence() -> None:
    rig = _Rig()
    rig.resolve_after_scan()
    result = await rig.execute()
    evidence = result.incident_reconciliation["resolution_evidence"]
    assert evidence["old_entity"] == OLD and evidence["new_entity"] == NEW
    assert evidence["occurrences_replaced"] == 3
    assert evidence["stale_reference_occurrences_remaining"] == 0
    assert evidence["pre_repair_scan_id"] == "scan_pre"
    assert evidence["post_repair_scan_id"] == "scan_post"
    assert evidence["config_valid_after"] is True
    assert "no model input" in evidence["verified_by"]
    assert result.incident_reconciliation["incident_remains_open"] is False


# ------------------------------------------- 2, 3, 4, 23: still present


@pytest.mark.asyncio
async def test_mutation_succeeds_but_original_finding_remains_is_not_success() -> None:
    rig = _Rig()  # incident stays active with its original finding ids
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.STILL_PRESENT
    assert (
        result.finding_reconciliation["verdict"]
        == ReconciliationVerdict.ORIGINAL_FINDING_REMAINS.value
    )
    assert result.incident_reconciliation["incident_remains_open"] is True


@pytest.mark.asyncio
async def test_regenerated_finding_ids_do_not_hide_the_same_root_cause() -> None:
    rig = _Rig()

    def _hook() -> None:
        # New scan, brand-new finding identities, same stable incident id.
        rig.gate.incident_list = [
            _incident(finding_ids=("f9", "f10"), content_revision=4, material_digest="v2")
        ]

    rig.gate.on_scan = _hook
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.STILL_PRESENT
    assert (
        result.finding_reconciliation["verdict"]
        == ReconciliationVerdict.SAME_ROOT_CAUSE_REGENERATED.value
    )
    assert result.finding_reconciliation["overlapping_finding_ids"] == []


@pytest.mark.asyncio
async def test_equivalent_stale_reference_elsewhere_blocks_resolution() -> None:
    rig = _Rig()

    def _hook() -> None:
        rig.gate.incident_list = [_incident(lifecycle="resolved", content_revision=4)]
        # A reference outside the repaired scope -- exactly what location
        # truncation or a concurrent edit produces.
        with open(os.path.join(rig.root, "z_extra.yaml"), "w", encoding="utf-8") as fh:
            fh.write(f"automation:\n  - id: z1\n    conditions:\n      - entity_id: {OLD}\n")

    rig.gate.on_scan = _hook
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.STILL_PRESENT
    assert (
        result.finding_reconciliation["verdict"]
        == ReconciliationVerdict.EQUIVALENT_REFERENCE_REMAINS.value
    )
    assert result.finding_reconciliation["stale_reference_occurrences_remaining"] == 1


@pytest.mark.asyncio
async def test_still_present_reopens_an_incident_hamie_auto_resolved() -> None:
    rig = _Rig()

    def _hook() -> None:
        rig.gate.incident_list = [_incident(lifecycle="resolved", content_revision=4)]
        with open(os.path.join(rig.root, "z_extra.yaml"), "w", encoding="utf-8") as fh:
            fh.write(f"automation:\n  - id: z1\n    conditions:\n      - entity_id: {OLD}\n")

    rig.gate.on_scan = _hook
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.STILL_PRESENT
    assert result.incident_reconciliation["reopened"] is True
    assert rig.gate.lifecycle_calls[0]["incident_id"] == INCIDENT_ID
    assert rig.gate.lifecycle_calls[0]["expected_revision"] == 4


# ------------------------------------------------ 5, 6, 22: validation


@pytest.mark.asyncio
async def test_configuration_validation_failure_rolls_back() -> None:
    rig = _Rig()
    original = rig.text("a.yaml")
    rig.ha.config_plan = [True, False, True]  # pre-valid, post-invalid, restored
    rig.ha.config_errors = ["bad automation"]
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.ROLLED_BACK
    assert result.stage is LifecycleStage.CONFIG_VALIDATION
    assert rig.text("a.yaml") == original
    assert rig.occurrences(OLD) == 3
    assert result.rollback["restoration_proven"] is True


class _LyingRestoreGateway(FileGateway):
    """A restore that returns cleanly without putting the file back."""

    def restore(self, path: str, backup_path: str) -> str:
        self._checked_backup(path, backup_path)
        with open(backup_path, encoding="utf-8") as fh:
            return fh.read()  # deliberately never written to `path`


@pytest.mark.asyncio
async def test_rollback_that_returns_success_without_restoring_is_rollback_failed() -> None:
    rig = _Rig(file_gateway=_LyingRestoreGateway)
    rig.ha.config_plan = [True, False, True]
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.ROLLBACK_FAILED
    assert result.rollback["files_restored"] is False
    assert result.rollback["restoration_proven"] is False
    # The state really is unrestored -- the verdict is not a formality.
    assert rig.occurrences(OLD) == 0


@pytest.mark.asyncio
async def test_rollback_failure_is_escalating_and_never_resolved() -> None:
    rig = _Rig(file_gateway=_LyingRestoreGateway)
    rig.ha.config_plan = [True, False, True]
    result = await rig.execute()
    assert result.outcome in UNRESOLVED_REMEDIATION_OUTCOMES
    assert result.incident_resolved is False


# ------------------------------------------------ 7, 8: runtime + invariants


@pytest.mark.asyncio
async def test_affected_automation_becoming_unavailable_triggers_rollback() -> None:
    rig = _Rig()
    original = rig.text("b.yaml")
    rig.world.states["automation.a1"] = "on"
    rig.world.states["automation.b1"] = "on"

    call = {"n": 0}
    real_reload = rig.ha.reload_domain

    async def reload(domain: str) -> bool:
        call["n"] += 1
        rig.world.states["automation.b1"] = "unavailable"
        return await real_reload(domain)

    rig.ha.reload_domain = reload
    rig.executor = RemediationExecutor(rig.files, rig.ha.gateway())
    rig.lifecycle = RemediationLifecycle(
        rig.world.gateway(), rig.gate.gateway(), rig.executor
    )
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.ROLLED_BACK
    assert result.runtime_validation["scope_newly_unavailable"] == ["automation.b1"]
    assert rig.text("b.yaml") == original


@pytest.mark.asyncio
async def test_protected_invariant_violation_prevents_resolution() -> None:
    rig = _Rig()
    rig.world.states["switch.example_inference_host_plug"] = "on"
    rig.world.states["input_number.printer_sustained_idle_minutes"] = "120"
    rig.resolve_after_scan()

    real_reload = rig.ha.reload_domain

    async def reload(domain: str) -> bool:
        rig.world.states["switch.example_inference_host_plug"] = "off"
        return await real_reload(domain)

    rig.ha.reload_domain = reload
    rig.executor = RemediationExecutor(rig.files, rig.ha.gateway())
    rig.lifecycle = RemediationLifecycle(
        rig.world.gateway(), rig.gate.gateway(), rig.executor
    )
    result = await rig.execute()
    assert result.outcome is not RemediationOutcome.RESOLVED
    assert result.outcome is RemediationOutcome.ROLLED_BACK
    assert "ai-pc-remains-powered" in result.invariants["newly_violated"]


@pytest.mark.asyncio
async def test_printer_idle_policy_below_the_floor_is_a_violation() -> None:
    invariant = next(
        i for i in DEFAULT_STATE_INVARIANTS if i.invariant_id == "printer-sustained-idle-policy"
    )
    assert invariant.holds("120") is True
    assert invariant.holds("240") is True
    assert invariant.holds("60") is False
    assert invariant.holds("unavailable") is None


@pytest.mark.asyncio
async def test_pre_existing_invariant_violation_blocks_before_any_mutation() -> None:
    rig = _Rig()
    rig.world.states["switch.example_inference_host_plug"] = "off"
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.BLOCKED
    assert result.stage is LifecycleStage.PRE_STATE_CAPTURE
    assert rig.occurrences(OLD) == 3
    assert rig.backups() == []


# ------------------------------------------------------------ 9: rescan


@pytest.mark.asyncio
async def test_no_fresh_scan_is_inconclusive_never_resolved() -> None:
    rig = _Rig()
    rig.gate.scan_raises = "scan coordinator is cancelling owned work"
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.INCONCLUSIVE
    assert result.stage is LifecycleStage.RESCAN
    # The change validated, so it is kept rather than reverted blindly.
    assert rig.occurrences(OLD) == 0
    assert result.incident_reconciliation["incident_remains_open"] is True


@pytest.mark.asyncio
async def test_repeated_scan_id_is_not_a_fresh_scan() -> None:
    rig = _Rig()
    rig.gate.next_scan_id = "scan_pre"  # same scan, reconciling would be a lie
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.INCONCLUSIVE
    assert result.rescan["fresh_scan_completed"] is False


@pytest.mark.asyncio
async def test_incomplete_scan_state_is_inconclusive() -> None:
    rig = _Rig()
    rig.gate.scan_state = "failed"
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.INCONCLUSIVE


# ------------------------------------------- 10, 11, 12: drift and staleness


@pytest.mark.asyncio
async def test_configuration_drift_after_approval_blocks_execution() -> None:
    rig = _Rig()
    plan = await rig.plan()
    with open(rig.path("a.yaml"), "a", encoding="utf-8") as fh:
        fh.write("\n# edited after approval\n")
    result = await rig.execute(plan)
    assert result.outcome is RemediationOutcome.BLOCKED
    assert result.stage is LifecycleStage.DRIFT_CHECK
    assert result.drift["blocking"] is True
    assert any("file_content_changed" in c["field"] for c in result.drift["changes"])
    assert rig.occurrences(OLD) == 3
    assert rig.backups() == []


@pytest.mark.asyncio
async def test_new_occurrence_after_approval_blocks_execution() -> None:
    rig = _Rig()
    plan = await rig.plan()
    with open(rig.path("c.yaml"), "w", encoding="utf-8") as fh:
        fh.write(f"automation:\n  - id: c1\n    conditions:\n      - entity_id: {OLD}\n")
    result = await rig.execute(plan)
    assert result.outcome is RemediationOutcome.BLOCKED
    assert any("location_added" in c["field"] for c in result.drift["changes"])


@pytest.mark.asyncio
async def test_replacement_disappearing_between_approval_and_execution_blocks() -> None:
    rig = _Rig()
    plan = await rig.plan()
    del rig.world.states[NEW]
    rig.world.similar[OLD] = ()
    result = await rig.execute(plan)
    assert result.outcome is RemediationOutcome.BLOCKED
    assert result.stage is LifecycleStage.DRIFT_CHECK
    assert result.drift["rederivation_failed"]
    assert rig.occurrences(OLD) == 3


@pytest.mark.asyncio
async def test_multiple_plausible_replacements_block_execution() -> None:
    rig = _Rig()
    plan = await rig.plan()
    rig.world.states["device_tracker.example_phone_15_pro"] = "home"
    rig.world.similar[OLD] = (NEW, "device_tracker.example_phone_15_pro")
    result = await rig.execute(plan)
    assert result.outcome is RemediationOutcome.BLOCKED
    assert "plausible replacements" in result.drift["rederivation_failed"]


@pytest.mark.asyncio
async def test_plan_contents_must_hash_to_their_claimed_identity() -> None:
    rig = _Rig()
    plan = await rig.plan()
    doctored = plan.as_dict()
    doctored["new_entity"] = "switch.example_inference_host_plug"
    result = await rig.lifecycle.async_execute(
        INCIDENT_ID,
        approved_plan=doctored,
        approved_plan_identity=plan.plan_identity,
        approved_by=ACTOR,
    )
    assert result.outcome is RemediationOutcome.BLOCKED
    assert "do not hash" in result.reason
    assert rig.occurrences(OLD) == 3


@pytest.mark.asyncio
async def test_material_digest_churn_alone_does_not_block() -> None:
    rig = _Rig()
    plan = await rig.plan()
    rig.world.incidents[INCIDENT_ID] = _incident(
        material_digest="digest_v2", finding_ids=("f1", "f2", "f3")
    )
    rig.resolve_after_scan()
    result = await rig.execute(plan)
    assert result.outcome is RemediationOutcome.RESOLVED
    changed = {c["field"]: c for c in result.drift["changes"]}
    assert changed["incident_material_digest"]["blocking"] is False


@pytest.mark.asyncio
async def test_root_cause_change_blocks_even_though_files_match() -> None:
    rig = _Rig()
    plan = await rig.plan()
    rig.world.incidents[INCIDENT_ID] = _incident(root_cause="a different problem entirely")
    result = await rig.execute(plan)
    assert result.outcome is RemediationOutcome.BLOCKED
    assert any(c["field"] == "root_cause" and c["blocking"] for c in result.drift["changes"])


# ------------------------------------------- 13, 14, 15: the model has no vote


@pytest.mark.asyncio
async def test_model_suggestion_cannot_change_the_authoritative_target() -> None:
    rig = _Rig()
    plan_a = await rig.plan()
    # The model "changes its mind" -- the execution path never asks it.
    result = await rig.execute(
        plan_a,
        advisory={
            "classification": "verified",
            "confidence": 1.0,
            "suggested_new_entity": "switch.example_inference_host_plug",
            "suggested_old_entity": "sensor.something_else",
        },
    )
    assert result.plan["new_entity"] == NEW
    assert result.mutation["new_entity"] == NEW
    assert "switch.example_inference_host_plug" not in rig.text("a.yaml")


@pytest.mark.asyncio
async def test_model_confidence_one_does_not_make_an_unresolved_repair_resolved() -> None:
    rig = _Rig()  # incident stays active -> STILL_PRESENT
    result = await rig.execute(advisory={"classification": "verified", "confidence": 1.0})
    assert result.outcome is RemediationOutcome.STILL_PRESENT
    assert result.advisory["confidence"] == 1.0
    assert result.incident_resolved is False


@pytest.mark.asyncio
async def test_deterministic_resolution_needs_no_model_at_all() -> None:
    rig = _Rig()
    rig.resolve_after_scan()
    result = await rig.execute()  # no investigator was ever constructed
    assert result.outcome is RemediationOutcome.RESOLVED
    assert result.advisory == {}


# ---------------------------------------------------- 17, 18: regression


@pytest.mark.asyncio
async def test_new_attributable_p1_incident_is_a_regression() -> None:
    rig = _Rig()

    def _hook() -> None:
        rig.gate.incident_list = [
            _incident(lifecycle="resolved", content_revision=4),
            _incident(
                incident_id="inc_brand_new",
                priority="p1",
                lifecycle="new",
                title="template error introduced",
            ),
        ]

    rig.gate.on_scan = _hook
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.REGRESSED
    assert result.regression["new_p0_p1_incidents"][0]["incident_id"] == "inc_brand_new"
    assert result.incident_reconciliation["incident_remains_open"] is True


@pytest.mark.asyncio
async def test_unrelated_global_movement_does_not_affect_reconciliation() -> None:
    rig = _Rig()

    def _hook() -> None:
        # Unrelated P3 noise appears and unavailable counts drop for reasons
        # that have nothing to do with this repair.
        rig.gate.incident_list = [
            _incident(lifecycle="resolved", content_revision=4),
            _incident(incident_id="inc_noise_1", priority="p3", lifecycle="new"),
            _incident(incident_id="inc_noise_2", priority="info", lifecycle="new"),
        ]

    rig.gate.on_scan = _hook
    rig.ha.counts["automation"]["unavailable"] = 540
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.RESOLVED
    assert result.regression["new_p0_p1_incidents"] == []


@pytest.mark.asyncio
async def test_availability_decrease_is_never_treated_as_proof() -> None:
    rig = _Rig()
    real_reload = rig.ha.reload_domain

    async def reload(domain: str) -> bool:
        rig.ha.counts["automation"]["unavailable"] = 552
        return await real_reload(domain)

    rig.ha.reload_domain = reload
    rig.executor = RemediationExecutor(rig.files, rig.ha.gateway())
    rig.lifecycle = RemediationLifecycle(
        rig.world.gateway(), rig.gate.gateway(), rig.executor
    )
    result = await rig.execute()  # incident still active
    assert result.outcome is RemediationOutcome.STILL_PRESENT
    assert result.runtime_validation["availability_delta"]["automation"] == -1
    assert result.runtime_validation["domains_worsened"] == []


@pytest.mark.asyncio
async def test_availability_increase_in_the_affected_domain_rolls_back() -> None:
    rig = _Rig()
    original = rig.text("a.yaml")
    real_reload = rig.ha.reload_domain

    async def reload(domain: str) -> bool:
        rig.ha.counts["automation"]["unavailable"] = 554
        return await real_reload(domain)

    rig.ha.reload_domain = reload
    rig.executor = RemediationExecutor(rig.files, rig.ha.gateway())
    rig.lifecycle = RemediationLifecycle(
        rig.world.gateway(), rig.gate.gateway(), rig.executor
    )
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.ROLLED_BACK
    assert result.runtime_validation["domains_worsened"] == ["automation"]
    assert rig.text("a.yaml") == original


@pytest.mark.asyncio
async def test_new_error_naming_a_changed_object_is_attributed_and_rolled_back() -> None:
    rig = _Rig()
    real_reload = rig.ha.reload_domain

    async def reload(domain: str) -> bool:
        rig.ha.signatures = (f"ERROR automation: unknown entity {NEW}",)
        return await real_reload(domain)

    rig.ha.reload_domain = reload
    rig.executor = RemediationExecutor(rig.files, rig.ha.gateway())
    rig.lifecycle = RemediationLifecycle(
        rig.world.gateway(), rig.gate.gateway(), rig.executor
    )
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.ROLLED_BACK
    assert result.runtime_validation["attributable_error_signatures"]


@pytest.mark.asyncio
async def test_unrelated_new_error_is_recorded_but_not_attributed() -> None:
    rig = _Rig()
    rig.resolve_after_scan()
    real_reload = rig.ha.reload_domain

    async def reload(domain: str) -> bool:
        rig.ha.signatures = ("ERROR zwave_js: node 42 is dead",)
        return await real_reload(domain)

    rig.ha.reload_domain = reload
    rig.executor = RemediationExecutor(rig.files, rig.ha.gateway())
    rig.lifecycle = RemediationLifecycle(
        rig.world.gateway(), rig.gate.gateway(), rig.executor
    )
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.RESOLVED
    assert result.runtime_validation["new_error_signatures"]
    assert result.runtime_validation["attributable_error_signatures"] == []


# --------------------------------------------------- 19, 20, 21: backup


class _FailingBackupGateway(FileGateway):
    def backup(self, path: str, stamp: str) -> str:
        raise OSError("read-only file system")


class _CorruptBackupGateway(FileGateway):
    def backup(self, path: str, stamp: str) -> str:
        real = self.policy.check(path)
        target = f"{real}.hamie_bak_{stamp}"
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("# not the file it claims to preserve\n")
        return target


@pytest.mark.asyncio
async def test_backup_failure_prevents_mutation() -> None:
    rig = _Rig(file_gateway=_FailingBackupGateway)
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.BLOCKED
    assert result.stage is LifecycleStage.BACKUP
    assert rig.occurrences(OLD) == 3
    assert result.backup["all_verified"] is False


@pytest.mark.asyncio
async def test_backup_verification_failure_prevents_mutation() -> None:
    rig = _Rig(file_gateway=_CorruptBackupGateway)
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.BLOCKED
    assert result.stage is LifecycleStage.BACKUP
    assert rig.occurrences(OLD) == 3
    assert any(
        loc["error"] == "backup_content_mismatch" for loc in result.backup["locations"]
    )


@pytest.mark.asyncio
async def test_partial_mutation_is_never_reported_as_success() -> None:
    rig = _Rig()
    os.chmod(rig.path("b.yaml"), 0o444)
    try:
        result = await rig.execute()
    finally:
        os.chmod(rig.path("b.yaml"), 0o644)
    assert result.outcome in (
        RemediationOutcome.ROLLED_BACK,
        RemediationOutcome.ROLLBACK_FAILED,
    )
    assert result.mutation["applied"] is False
    assert rig.occurrences(OLD) == 3, "the partially written file must be restored"


# -------------------------------------------- 24, 26, 27, 28, 29, 30


@pytest.mark.asyncio
async def test_incident_remains_open_on_inconclusive() -> None:
    rig = _Rig()
    rig.gate.scan_raises = "no scan"
    result = await rig.execute()
    assert result.outcome is RemediationOutcome.INCONCLUSIVE
    assert result.incident_resolved is False
    assert result.incident_reconciliation["incident_remains_open"] is True


@pytest.mark.asyncio
async def test_audit_separates_advisory_from_deterministic_evidence() -> None:
    rig = _Rig()
    rig.resolve_after_scan()
    result = await rig.execute(
        advisory={"classification": "verified", "confidence": 1.0, "model": "gemma4:12b"}
    )
    payload = result.as_dict()
    advisory = payload["evidence"]["advisory_model_derived"]
    deterministic = payload["evidence"]["deterministic_authoritative"]
    assert advisory["confidence"] == 1.0
    assert "Never authoritative" in advisory["note"]
    assert deterministic["outcome"] == RemediationOutcome.RESOLVED.value
    assert "confidence" not in deterministic
    events = [event for event, *_ in rig.gate.audits]
    for required in (
        "remediation_execution_started",
        "remediation_backup_verified",
        "remediation_config_validated",
        "remediation_runtime_validated",
        "remediation_invariants_reverified",
        "remediation_rescan_completed",
        "remediation_finding_reconciled",
        "remediation_incident_reconciled",
        "remediation_outcome_recorded",
    ):
        assert required in events, required
    for _event, _actor, targets, _details in rig.gate.audits:
        assert INCIDENT_ID in targets
        assert result.plan_identity in targets


@pytest.mark.asyncio
async def test_execution_requires_an_explicit_approver() -> None:
    rig = _Rig()
    result = await rig.execute(approved_by="")
    assert result.outcome is RemediationOutcome.BLOCKED
    assert result.stage is LifecycleStage.AUTHORIZATION
    assert rig.occurrences(OLD) == 3
    assert rig.backups() == []


@pytest.mark.asyncio
async def test_triage_and_dry_run_remain_non_mutating() -> None:
    rig = _Rig()

    async def model(_system, _user):
        return (
            '{"root_cause": "stale reference", "classification": "verified", '
            '"confidence": 1.0, "evidence_ids": ["INC:' + INCIDENT_ID + '"], '
            '"proposed_action": "replace the reference", '
            '"action_type": "replace_entity_reference", '
            '"affected_objects": ["' + OLD + '", "' + NEW + '"]}'
        )

    pipeline = IncidentRemediationPipeline(
        rig.world.gateway(), Investigator(model), rig.executor
    )
    before = {n: rig.text(n) for n in os.listdir(rig.root) if n.endswith(".yaml")}
    result = await pipeline.async_triage(INCIDENT_ID)
    assert result.disposition is InvestigationDisposition.REPAIR_CANDIDATE
    assert result.dry_run["outcome"] == "dry_run"
    assert result.dry_run["executed"] is False
    assert result.approval_required is True
    assert {n: rig.text(n) for n in os.listdir(rig.root) if n.endswith(".yaml")} == before
    assert rig.backups() == []
    # And the plan it hands the operator is the multi-file one.
    assert result.plan["expected_occurrences"] == 3
    assert len(result.plan["locations"]) == 2
    assert result.plan_identity == plan_from_dict(result.plan).plan_identity


@pytest.mark.asyncio
async def test_protected_security_and_destructive_operations_remain_blocked() -> None:
    assert classify_risk("delete_entity") is ToolRisk.DESTRUCTIVE
    assert classify_risk("call_service") is ToolRisk.PHYSICAL_STATE_CHANGE
    assert classify_risk("a_brand_new_operation") is ToolRisk.DESTRUCTIVE
    blocked = authorize(
        operation="replace_entity_reference",
        targets=("switch.example_inference_host_plug",),
        added_off_targets=frozenset({"switch.example_inference_host_plug"}),
        approved_by=ACTOR,
    )
    assert blocked.permitted is False, "approval must not override a protected invariant"
    lock = authorize(
        operation="replace_entity_reference",
        targets=("lock.front_door",),
        added_off_targets=frozenset({"lock.front_door"}),
        approved_by=ACTOR,
    )
    assert lock.permitted is False
    assert lock.risk is ToolRisk.SECURITY_CRITICAL


@pytest.mark.asyncio
async def test_execution_blocked_when_a_mutation_would_add_an_off_target() -> None:
    poisoned = (
        "automation:\n"
        "  - id: p1\n"
        "    actions:\n"
        "      - action: switch.turn_off\n"
        f"        entity_id: {OLD}\n"
    )
    rig = _Rig(files={"p.yaml": poisoned})
    rig.world.similar[OLD] = ("switch.example_inference_host_plug",)
    rig.world.states["switch.example_inference_host_plug"] = "on"
    _incident_dict, plan, failure = await rig.lifecycle.async_derive_plan(INCIDENT_ID)
    # Domains differ (device_tracker -> switch), so rediscovery refuses first.
    assert plan is None and failure


# ---------------------------------------------------------------- plumbing


def test_plan_identity_covers_everything_that_determines_the_effect() -> None:
    base = RepairPlan(
        incident_id="inc_1",
        incident_root_cause="rc",
        incident_material_digest="d1",
        incident_priority="p1",
        incident_evidence_status="verified",
        intent_kind="replace_stale_entity_reference",
        old_entity=OLD,
        new_entity=NEW,
        locations=(),
        expected_occurrences=3,
        risk="config_mutation",
        protection_verdict="allowed",
    )
    from dataclasses import replace as dc_replace

    assert dc_replace(base, incident_material_digest="d2").plan_identity == base.plan_identity
    assert dc_replace(base, created_at="later").plan_identity == base.plan_identity
    for field_name, value in (
        ("old_entity", "sensor.other"),
        ("new_entity", "sensor.other"),
        ("expected_occurrences", 4),
        ("risk", "destructive"),
        ("protection_verdict", "blocked"),
        ("intent_kind", "remove_dead_reference"),
        ("incident_id", "inc_2"),
    ):
        assert dc_replace(base, **{field_name: value}).plan_identity != base.plan_identity, field_name


def test_compare_plans_marks_only_effect_fields_blocking() -> None:
    base = RepairPlan(
        incident_id="inc_1",
        incident_root_cause="rc",
        incident_material_digest="d1",
        incident_priority="p1",
        incident_evidence_status="verified",
        intent_kind="replace_stale_entity_reference",
        old_entity=OLD,
        new_entity=NEW,
        locations=(),
        expected_occurrences=0,
        risk="config_mutation",
        protection_verdict="allowed",
    )
    from dataclasses import replace as dc_replace

    report = compare_plans(base, dc_replace(base, incident_material_digest="d2"))
    assert report.stale is False
    assert report.blocking is False
    report = compare_plans(base, dc_replace(base, incident_priority="p0"))
    assert report.blocking is True


@pytest.mark.asyncio
async def test_apply_locations_refuses_without_an_approver() -> None:
    """The gate lives at the last point before bytes change, not upstream."""
    rig = _Rig()
    changes, added = await rig.executor.async_plan_locations(
        (rig.path("a.yaml"),), OLD, NEW
    )
    assert await rig.executor.async_backup_locations(changes, "20260101T000000Z")
    from hamie.application.remediation_tools import RemediationRefused

    with pytest.raises(RemediationRefused) as err:
        await rig.executor.async_apply_locations(
            changes, OLD, NEW, added_off_targets=added, approved_by=None
        )
    assert err.value.code == "not_authorized_for_execution"
    assert rig.occurrences(OLD) == 3


@pytest.mark.asyncio
async def test_apply_locations_refuses_without_verified_backups() -> None:
    rig = _Rig()
    changes, added = await rig.executor.async_plan_locations(
        (rig.path("a.yaml"),), OLD, NEW
    )
    from hamie.application.remediation_tools import RemediationRefused

    with pytest.raises(RemediationRefused) as err:
        await rig.executor.async_apply_locations(
            changes, OLD, NEW, added_off_targets=added, approved_by=ACTOR
        )
    assert err.value.code == "unverified_backup"
    assert rig.occurrences(OLD) == 3


@pytest.mark.asyncio
async def test_backups_are_only_readable_for_the_file_they_belong_to() -> None:
    rig = _Rig()
    changes, _added = await rig.executor.async_plan_locations(
        (rig.path("a.yaml"), rig.path("b.yaml")), OLD, NEW
    )
    await rig.executor.async_backup_locations(changes, "20260101T000000Z")
    a_backup = next(c.backup_path for c in changes if c.path.endswith("a.yaml"))
    from hamie.application.remediation_tools import RemediationRefused

    with pytest.raises(RemediationRefused) as err:
        rig.files.read_backup(rig.path("b.yaml"), a_backup)
    assert err.value.code == "invalid_backup_path"
    with pytest.raises(RemediationRefused):
        rig.files.read_backup(rig.path("a.yaml"), rig.path("a.yaml") + ".hamie_bak_evil")
    with pytest.raises(RemediationRefused):
        rig.files.read(a_backup)  # backups are not configuration


# ------------------------------------------------- resumable reconciliation


@pytest.mark.asyncio
async def test_reconcile_completes_the_proof_after_an_interrupted_run() -> None:
    """Execution and proof are separable; the verdict must still be earned."""
    rig = _Rig()
    rig.gate.scan_raises = "coordinator busy"
    first = await rig.execute()
    assert first.outcome is RemediationOutcome.INCONCLUSIVE
    assert rig.occurrences(OLD) == 0, "the mutation itself landed"

    # Later: the scan works, and the root cause is genuinely gone.
    rig.gate.scan_raises = None
    rig.gate.scan_id = "scan_post"
    rig.gate.next_scan_id = "scan_post_2"
    rig.gate.incident_list = [_incident(lifecycle="resolved", content_revision=5)]
    plan = first.plan
    second = await rig.lifecycle.async_reconcile(
        INCIDENT_ID, plan=plan, plan_identity=first.plan_identity, actor=ACTOR
    )
    assert second.outcome is RemediationOutcome.RESOLVED
    assert second.mutation is None, "reconciliation must never mutate"
    assert second.backup is None and second.rollback is None
    assert second.finding_reconciliation["verdict"] == ReconciliationVerdict.ELIMINATED.value
    assert second.incident_reconciliation["resolution_evidence"]["plan_identity"] == (
        first.plan_identity
    )


@pytest.mark.asyncio
async def test_reconcile_uses_the_recorded_baseline_not_the_current_world() -> None:
    rig = _Rig()
    rig.gate.scan_raises = "coordinator busy"
    first = await rig.execute()
    assert first.baseline_incident_ids == (INCIDENT_ID,)

    rig.gate.scan_raises = None
    rig.gate.scan_id = "scan_post"
    rig.gate.next_scan_id = "scan_post_2"
    rig.gate.incident_list = [
        _incident(lifecycle="resolved", content_revision=5),
        _incident(incident_id="inc_new_p1", priority="p1", lifecycle="new"),
    ]
    second = await rig.lifecycle.async_reconcile(
        INCIDENT_ID, plan=first.plan, plan_identity=first.plan_identity, actor=ACTOR
    )
    assert second.outcome is RemediationOutcome.REGRESSED
    assert second.regression["baseline_available"] is True
    assert second.regression["new_p0_p1_incidents"][0]["incident_id"] == "inc_new_p1"


@pytest.mark.asyncio
async def test_reconcile_refuses_a_plan_that_does_not_hash_to_its_identity() -> None:
    rig = _Rig()
    plan = await rig.plan()
    doctored = plan.as_dict()
    doctored["old_entity"] = "sensor.something_else"
    result = await rig.lifecycle.async_reconcile(
        INCIDENT_ID, plan=doctored, plan_identity=plan.plan_identity, actor=ACTOR
    )
    assert result.outcome is RemediationOutcome.BLOCKED


@pytest.mark.asyncio
async def test_a_partial_coverage_scan_can_still_prove_elimination() -> None:
    """Partial coverage is this installation's steady state.

    Elimination still requires the independent configuration check, so the
    claim never rests on an analyzer that may not have run.
    """
    rig = _Rig()
    rig.gate.scan_state = "partial"
    rig.resolve_after_scan()
    result = await rig.execute()
    assert result.rescan["fresh_scan_completed"] is True
    assert result.rescan["coverage_complete"] is False
    assert result.outcome is RemediationOutcome.RESOLVED
    assert "coverage_caveat" in result.finding_reconciliation


@pytest.mark.asyncio
async def test_a_failed_scan_is_never_treated_as_fresh() -> None:
    rig = _Rig()
    rig.gate.scan_state = "failed"
    rig.resolve_after_scan()
    result = await rig.execute()
    assert result.rescan["fresh_scan_completed"] is False
    assert result.outcome is RemediationOutcome.INCONCLUSIVE


@pytest.mark.asyncio
async def test_an_unknown_previous_scan_id_cannot_look_fresh() -> None:
    """Without a known baseline scan there is no way to show the scan is new."""
    rig = _Rig()

    async def no_scan_id() -> str | None:
        return None

    rig.gate.current_scan_id = no_scan_id
    rig.lifecycle = RemediationLifecycle(
        rig.world.gateway(), rig.gate.gateway(), rig.executor
    )
    rig.resolve_after_scan()
    result = await rig.execute()
    assert result.rescan["fresh_scan_completed"] is False
    assert result.outcome is RemediationOutcome.INCONCLUSIVE
