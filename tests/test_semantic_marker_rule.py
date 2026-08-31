"""The executable-content rule must reject YAML, not reference citations.

Root cause of a 5/5 reproducible production failure on the real
lutron_caseta_pro group: HAMIE's own payload carried

    "dependency_references": ["automation:automation.n8n_habit_logger_..."]

and the validator then rejected the model for citing that reference back,
because it matched the substring "automation:". The model was being punished
for being faithful to the evidence it was given.

These tests pin both halves: real executable configuration is still rejected,
and HAMIE's own reference notation is not.
"""

from __future__ import annotations

import pytest

from hamie.connectors.schemas import (
    SemanticValidationError,
    validate_ai_response_semantics,
)


def _response(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "summary": "An advisory summary.",
        "confidence": "low",
        "model": "test",
        "generated_at": "2026-08-28T00:00:00+00:00",
        "probable_causes": [],
        "recommended_checks": [],
        "proposed_repair_plan": [],
        "supporting_finding_ids": [],
        "supporting_group_ids": [],
        "assumptions": [],
        "missing_evidence": [],
        "risk_notes": [],
        "do_not_do": [],
        "proposed_action": None,
    }
    base.update(overrides)
    return base


# ------------------------------------------- still rejected (safety intact)


@pytest.mark.parametrize(
    "text",
    [
        "automation:\n  - trigger: state\n    entity_id: light.x",
        "script:\n  sequence:\n    - service: light.turn_on",
        "service: light.turn_on",
        "target:\n  entity_id: switch.pump",
        "shell_command: rm -rf /config",
        "Run this:\nautomation:\n  alias: bad",
        "service:   light.turn_on",
        "automation:\t- trigger: x",
    ],
)
def test_executable_yaml_is_still_rejected(text: str) -> None:
    with pytest.raises(SemanticValidationError):
        validate_ai_response_semantics(_response(summary=text))


def test_executable_content_in_the_repair_plan_is_rejected() -> None:
    with pytest.raises(SemanticValidationError):
        validate_ai_response_semantics(
            _response(proposed_repair_plan=["Apply this:", "automation:\n  alias: x"])
        )


def test_executable_content_in_do_not_do_is_rejected() -> None:
    with pytest.raises(SemanticValidationError):
        validate_ai_response_semantics(_response(do_not_do=["service: lock.unlock"]))


def test_executable_content_inside_proposed_action_is_rejected() -> None:
    with pytest.raises(SemanticValidationError):
        validate_ai_response_semantics(
            _response(
                proposed_action={
                    "reason": "harmless looking",
                    "operation": {"body": "automation:\n  - alias: x"},
                }
            )
        )


def test_the_error_names_the_offending_key() -> None:
    with pytest.raises(SemanticValidationError, match="automation"):
        validate_ai_response_semantics(_response(summary="automation:\n  alias: x"))


# ------------------------------------ no longer rejected (the real defect)


@pytest.mark.parametrize(
    "text",
    [
        "The entity is referenced by automation:automation.n8n_habit_logger_discrete_events.",
        "Referenced by script:script.morning_routine and nothing else.",
        "dependency_references: automation:automation.foo",
        "Cited automation:automation.a and automation:automation.b.",
    ],
)
def test_hamie_reference_notation_is_not_executable_content(text: str) -> None:
    """`<domain>:<entity_id>` is HAMIE's own citation format, not YAML."""
    assert validate_ai_response_semantics(_response(summary=text))


def test_the_exact_production_response_shape_now_validates() -> None:
    """Reconstructed from the real 5/5 failure on the Lutron group."""
    result = validate_ai_response_semantics(
        _response(
            summary=(
                "light.front_foyer_chandelier has no config_entry_id or device_id, "
                "yet it remains referenced by an automation "
                "('automation:automation.n8n_habit_logger_discrete_events'). "
                "Removing it would break that reference."
            ),
            proposed_repair_plan=[
                "Identify the content and logic of the automation "
                "'automation:automation.n8n_habit_logger_discrete_events'.",
                "Confirm whether the reference is still required.",
            ],
            do_not_do=[
                "Do not remove light.front_foyer_chandelier without first "
                "resolving its dependency on "
                "'automation:automation.n8n_habit_logger_discrete_events'."
            ],
        )
    )
    assert result["confidence"] == "low"


def test_a_reference_citation_next_to_real_yaml_is_still_rejected() -> None:
    """Citing a reference must not launder an executable block beside it."""
    with pytest.raises(SemanticValidationError):
        validate_ai_response_semantics(
            _response(
                summary=(
                    "Referenced by automation:automation.foo. Apply:\n"
                    "automation:\n  - alias: bad"
                )
            )
        )
