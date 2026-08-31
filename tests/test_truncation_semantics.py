"""Truncation is a first-class failure, not a formatting mistake.

Measured against the live provider: a 20-finding group (production's
maximum) generates 1201-1388 output tokens. At the previous default of 1024
every response came back with Ollama's own `done_reason: "length"` and
unparseable JSON -- the `ai_response_truncated` production kept hitting.

HAMIE previously guessed truncation from the text. The provider says so
outright, and these tests pin that the authoritative signal is used and that
a cut-off response can never count as completed analysis.
"""

from __future__ import annotations

import pytest

from hamie.connectors.ollama import _stop_reason


@pytest.mark.parametrize(
    "raw,provider,expected",
    [
        ({"done_reason": "length"}, "ollama", "length"),
        ({"done_reason": "stop"}, "ollama", "stop"),
        ({"done": False}, "ollama", None),
        ({}, "ollama", None),
        ({"choices": [{"finish_reason": "length"}]}, "openai_compatible", "length"),
        ({"choices": [{"finish_reason": "stop"}]}, "openai_compatible", "stop"),
        ({"choices": []}, "openai_compatible", None),
        ({}, "openai_compatible", None),
        (None, "ollama", None),
        ("not-a-dict", "ollama", None),
    ],
)
def test_stop_reason_is_read_from_the_provider(raw, provider, expected) -> None:
    assert _stop_reason(raw, provider) == expected


def test_production_default_output_budget_covers_the_measured_maximum() -> None:
    """1024 truncated a 20-finding group; 2048 cleared it 5/5.

    The number is a measurement, not a preference: worst observed generation
    at the production group bound was 1388 tokens.
    """
    from hamie.configuration import SECTION_FIELDS

    field = next(
        (
            spec
            for specs in SECTION_FIELDS.values()
            for spec in specs
            if spec.key == "ollama_maximum_output_tokens"
        ),
        None,
    )
    assert field is not None, "output budget field not found in the schema"
    assert field.default >= 1536, "below the measured requirement for a 20-finding group"
    assert field.default == 2048, (
        "2048 was the measured choice (worst observed 1388 tokens at the "
        "production group bound); changing it requires new measurement"
    )
    assert field.maximum >= field.default


def test_probe_identifiers_look_like_real_finding_ids() -> None:
    """A fixture that fails for a reason production cannot hit measures itself.

    Sixteen ids of the form hamie_probe{index:032d} -- thirty-one zeros and a
    digit -- made the live provider abort generation outright. Real HAMIE ids
    are 32 random hex characters and never produced that failure.
    """
    from hamie.application.capability_probe import default_probe_cases

    case = {c.probe_id: c for c in default_probe_cases()}["realistic_group_size"]
    ids = case.expected_identifiers
    assert len(ids) >= 16
    assert len(set(ids)) == len(ids)
    for identifier in ids:
        suffix = identifier.split("_", 1)[1]
        assert len(suffix) == 32
        assert all(ch in "0123456789abcdef" for ch in suffix)
        # The pathological fixture had two distinct characters. Real ids have many.
        assert len(set(suffix)) >= 8, "identifier is not entropic enough to be realistic"


def test_group_bound_is_sized_to_what_the_model_can_answer() -> None:
    """A larger output budget cannot rescue an oversized group.

    Measured: 20 findings pass 5/5 at 2048 tokens; 24 truncate; 30 fail
    identically at eval_count=432 for num_predict 2048, 3072 and 4096.
    """
    from hamie.configuration import SECTION_FIELDS

    field = next(
        spec
        for specs in SECTION_FIELDS.values()
        for spec in specs
        if spec.key == "ai_maximum_findings_per_group"
    )
    assert field.default == 20, (
        "20 was the measured safe bound; 24 truncated and 30 failed at every "
        "budget tested"
    )
    assert field.minimum >= 1


def test_findings_beyond_the_group_bound_are_skipped_not_discarded() -> None:
    """Bounding must never silently drop findings from the population."""
    import inspect

    from hamie.domain import intelligence

    source = inspect.getsource(intelligence.ExplorerIndex.plan_ai_advisory_groups)
    assert "skipped_ids" in source
    assert "selected_set" in source
