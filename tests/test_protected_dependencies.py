"""Protected infrastructure dependencies must be deterministic and reusable."""

from __future__ import annotations

import pytest

from hamie.domain.protected_dependencies import (
    DependencyLink,
    ProtectedDependency,
    ProtectedDependencyRegistry,
    ProtectionSeverity,
    ProtectionVerdict,
    default_registry,
)

AI_PC = "switch.example_inference_host_plug"


def test_ai_pc_chain_is_registered_with_full_rationale() -> None:
    reg = default_registry()
    (dep,) = reg.protecting(AI_PC)
    assert dep.id == "hamie-local-inference-power"
    assert dep.severity is ProtectionSeverity.CRITICAL
    # the whole causal chain must be preserved, not just the entity name
    chain = dep.chain_description
    assert AI_PC in chain
    assert "EXAMPLE-HOST" in chain or "EXAMPLE-DESKTOP-01" in chain
    assert "Ollama" in chain
    assert "inference" in chain.lower()
    assert any(link.evidence for link in dep.chain)


@pytest.mark.parametrize(
    "action", ["turn_off", "switch.turn_off", "delete_entity", "disable_entity"]
)
def test_severing_actions_on_ai_pc_are_blocked(action: str) -> None:
    ev = default_registry().evaluate(entity_ids=(AI_PC,), action_type=action)
    assert ev.verdict is ProtectionVerdict.BLOCKED
    assert ev.blocked
    assert ev.matched and ev.matched[0].id == "hamie-local-inference-power"
    assert "sever" in ev.reason


def test_non_severing_action_on_protected_entity_needs_approval() -> None:
    ev = default_registry().evaluate(entity_ids=(AI_PC,), action_type="read_state")
    assert ev.verdict is ProtectionVerdict.REQUIRES_APPROVAL
    assert not ev.blocked


def test_unrelated_entity_is_allowed() -> None:
    ev = default_registry().evaluate(
        entity_ids=("light.kitchen_main_lights",), action_type="turn_off"
    )
    assert ev.verdict is ProtectionVerdict.ALLOWED
    assert ev.matched == ()


def test_registry_is_generic_not_hardcoded() -> None:
    """A second, unrelated invariant must work with no code change."""
    nas = ProtectedDependency(
        id="recorder-db-power",
        name="Recorder database depends on the NAS",
        severity=ProtectionSeverity.CRITICAL,
        protected_entities=frozenset({"switch.nas_power"}),
        rule="Do not power off the NAS; it hosts the recorder database.",
        chain=(
            DependencyLink(
                subject="switch.nas_power",
                provides="power to the NAS",
                rationale="test fixture",
                evidence=("test",),
            ),
        ),
    )
    reg = default_registry().register(nas)
    assert reg.evaluate(
        entity_ids=("switch.nas_power",), action_type="turn_off"
    ).verdict is ProtectionVerdict.BLOCKED
    # original invariant still enforced
    assert reg.evaluate(entity_ids=(AI_PC,), action_type="turn_off").blocked


def test_evaluation_serialises_for_proposals() -> None:
    ev = default_registry().evaluate(entity_ids=(AI_PC,), action_type="turn_off")
    d = ev.as_dict()
    assert d["verdict"] == "blocked"
    assert d["matched_invariants"][0]["chain"]
    assert d["matched_invariants"][0]["evidence"]


def test_empty_registry_allows_everything() -> None:
    ev = ProtectedDependencyRegistry().evaluate(
        entity_ids=(AI_PC,), action_type="turn_off"
    )
    assert ev.verdict is ProtectionVerdict.ALLOWED


# --------------------------------------------------------------------------
# Regression: found by a LIVE run. The local model proposed "create an
# automation to turn off the AI PC plug" but typed it action_type=
# "update_automation", which action-type matching alone let through as merely
# requires_approval. Declared action type is a weak signal; intent must count.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action_type,intent",
    [
        ("update_automation", "Create an automation to turn off switch.example_inference_host_plug"),
        ("create_automation", "power down the office AI PC during house-empty"),
        ("script", "shut down EXAMPLE-HOST to save energy"),
        ("update_script", "disable the AI PC plug overnight"),
        ("automation", "remove the AI PC from the always-on list"),
    ],
)
def test_severing_intent_is_blocked_regardless_of_action_type(
    action_type: str, intent: str
) -> None:
    ev = default_registry().evaluate(
        entity_ids=(AI_PC,), action_type=action_type, intent=intent
    )
    assert ev.verdict is ProtectionVerdict.BLOCKED, (
        f"{action_type!r} with intent {intent!r} must not slip through"
    )


def test_mutating_critical_infra_fails_safe_even_without_severing_words() -> None:
    """An unrecognised mutating action on a CRITICAL chain blocks by default."""
    ev = default_registry().evaluate(
        entity_ids=(AI_PC,), action_type="rewrite_config", intent="tidy things up"
    )
    assert ev.verdict is ProtectionVerdict.BLOCKED


@pytest.mark.parametrize("action_type", ["none", "read_state", "inspect", "report"])
def test_read_only_actions_never_block(action_type: str) -> None:
    ev = default_registry().evaluate(
        entity_ids=(AI_PC,), action_type=action_type, intent="check current draw"
    )
    assert ev.verdict is ProtectionVerdict.REQUIRES_APPROVAL
    assert not ev.blocked


def test_severing_intent_on_unprotected_entity_still_allowed() -> None:
    ev = default_registry().evaluate(
        entity_ids=("light.kitchen_main_lights",),
        action_type="update_automation",
        intent="turn off the kitchen lights when empty",
    )
    assert ev.verdict is ProtectionVerdict.ALLOWED
