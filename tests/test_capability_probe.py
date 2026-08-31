"""Capability probing: measured behaviour, never assumed competence.

Production had a connector reporting `healthy` while analysis produced
`semantic_validation_failed` and zero usable recommendations. Reachability is
not capability, and these tests pin the difference.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hamie.application.capability_probe import (
    CapabilityProbeRunner,
    default_probe_cases,
)
from hamie.domain.capability import (
    CAPABILITY_FRESHNESS_SECONDS,
    INCAPABLE_PASS_RATE,
    REQUIRED_DIMENSIONS,
    REQUIRED_PASS_RATE,
    CapabilityDimension,
    CapabilityVerdict,
    DimensionResult,
    compute_verdict,
    configuration_fingerprint,
    evaluate_gate,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
FP = "fingerprint-a"


class _Err(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _good(case_payload) -> dict:
    """A response that satisfies every dimension for any probe."""
    ids = [f["finding_id"] for f in case_payload["findings"]]
    return {
        "schema_version": 1,
        "summary": "Reviewed the supplied evidence.",
        "confidence": "low",
        "model": "test-model",
        "generated_at": "2026-08-28T12:00:00+00:00",
        # An ideal model both RESOLVES (states a cause) and ACKNOWLEDGES
        # (records what is missing). The corrected scorer requires the first
        # on resolvable contradictions and the second on unresolvable ones,
        # so a fixture representing "satisfies every expectation" must do both.
        "probable_causes": ["the authoritative source indicates a stale reference"],
        "recommended_checks": [],
        "proposed_repair_plan": [],
        "supporting_finding_ids": ids,
        "supporting_group_ids": [],
        "assumptions": ["registry evidence may be incomplete"],
        "missing_evidence": ["no deterministic ownership evidence was supplied"],
        "risk_notes": [],
        "do_not_do": [],
        "proposed_action": None,
    }


def _runner(behaviour, **kw) -> CapabilityProbeRunner:
    async def analyze(payload):
        return behaviour(payload)

    return CapabilityProbeRunner(analyze, clock=lambda: NOW, **kw)


async def _run(behaviour, **kw):
    return await _runner(behaviour, **kw).async_run(
        provider="ollama", model="test-model", configuration_fingerprint=FP
    )


# ------------------------------------------------------------ verdicts


@pytest.mark.asyncio
async def test_a_model_satisfying_every_expectation_is_capable() -> None:
    expected = sum(case.repeats for case in default_probe_cases())
    result = await _run(_good)
    assert result.verdict is CapabilityVerdict.CAPABLE
    assert result.probes_attempted == expected
    assert result.probes_passed == expected
    for dimension in REQUIRED_DIMENSIONS:
        assert result.dimension(dimension).satisfied, dimension


@pytest.mark.asyncio
async def test_a_model_that_cannot_produce_json_is_incapable() -> None:
    def broken(_payload):
        raise _Err("invalid_response")

    result = await _run(broken)
    assert result.verdict is CapabilityVerdict.INCAPABLE
    assert result.rate(CapabilityDimension.STRUCTURED_OUTPUT) == 0.0
    assert result.last_failure_category == "invalid_response"


@pytest.mark.asyncio
async def test_semantic_failures_are_attributed_separately_from_format() -> None:
    """Valid JSON violating a safety rule is a different problem."""

    def semantic(_payload):
        raise _Err("semantic_validation_failed")

    result = await _run(semantic)
    assert result.rate(CapabilityDimension.SEMANTIC_VALIDITY) == 0.0
    # Structured output was never falsified by these runs.
    structured = result.dimension(CapabilityDimension.STRUCTURED_OUTPUT)
    assert structured is None or structured.attempted == 0
    assert result.verdict is CapabilityVerdict.INCAPABLE


@pytest.mark.asyncio
async def test_a_single_timeout_does_not_look_like_a_formatting_failure() -> None:
    calls = {"n": 0}

    def flaky(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _Err("timeout")
        return _good(payload)

    expected = sum(case.repeats for case in default_probe_cases())
    result = await _run(flaky)
    assert result.rate(CapabilityDimension.STRUCTURED_OUTPUT) == 1.0
    assert result.dimension(CapabilityDimension.CONNECTIVITY).passed == expected - 1


@pytest.mark.asyncio
async def test_unreachable_provider_is_not_blamed_on_the_model() -> None:
    def down(_payload):
        raise _Err("timeout")

    result = await _run(down)
    assert result.verdict is CapabilityVerdict.PROVIDER_UNAVAILABLE
    assert "could not be reached" in result.reasons[0]


# ---------------------------------------------- deterministic scoring


@pytest.mark.asyncio
async def test_invented_identifiers_fail_even_when_the_prose_is_perfect() -> None:
    def inventive(payload):
        response = _good(payload)
        response["supporting_finding_ids"] = ["hamie_totally_made_up_identifier"]
        response["summary"] = "A beautifully written and entirely confident analysis."
        return response

    result = await _run(inventive)
    assert result.rate(CapabilityDimension.IDENTIFIER_PRESERVATION) == 0.0
    assert result.verdict is CapabilityVerdict.INCAPABLE


@pytest.mark.asyncio
async def test_citing_nothing_is_not_identifier_preservation() -> None:
    def silent(payload):
        response = _good(payload)
        response["supporting_finding_ids"] = []
        return response

    result = await _run(silent)
    assert result.rate(CapabilityDimension.IDENTIFIER_PRESERVATION) == 0.0


@pytest.mark.asyncio
async def test_failing_to_abstain_on_thin_evidence_is_measured() -> None:
    def overconfident(payload):
        response = _good(payload)
        response["missing_evidence"] = []
        response["proposed_action"] = {"reason": "just do it", "operation": {}}
        return response

    result = await _run(overconfident)
    assert result.rate(CapabilityDimension.ABSTENTION) == 0.0
    # Abstention is a quality signal, not a safety gate -- it degrades.
    assert result.verdict is CapabilityVerdict.DEGRADED


@pytest.mark.asyncio
async def test_proposing_a_repair_for_a_live_entity_fails_semantics() -> None:
    def eager(payload):
        response = _good(payload)
        response["proposed_action"] = {"reason": "replace it", "operation": {}}
        return response

    result = await _run(eager)
    assert result.rate(CapabilityDimension.SEMANTIC_VALIDITY) < 1.0


@pytest.mark.asyncio
async def test_high_confidence_fails_only_where_nothing_can_resolve_it() -> None:
    """The corrected contract: confidence is wrong only when unearned.

    The previous scorer penalised high confidence unconditionally, which
    marked the model wrong for correctly resolving toward authoritative
    evidence in four of twenty classes.
    """
    def confident(payload):
        response = _good(payload)
        response["confidence"] = "high"
        return response

    result = await _run(confident)
    attempted_u, passed_u = result.contradiction_unresolvable
    assert attempted_u > 0
    assert passed_u == 0, "high confidence must fail every unresolvable case"
    attempted_r, passed_r = result.contradiction_resolvable
    assert passed_r == attempted_r, "confident resolution must not be penalised"


@pytest.mark.asyncio
async def test_malformed_schema_version_fails_instruction_following() -> None:
    def sloppy(payload):
        response = _good(payload)
        response["schema_version"] = "one"
        return response

    result = await _run(sloppy)
    assert result.rate(CapabilityDimension.INSTRUCTION_FOLLOWING) == 0.0


@pytest.mark.asyncio
async def test_an_oversized_response_fails_boundedness() -> None:
    def verbose(payload):
        response = _good(payload)
        response["summary"] = "x" * 20_000
        return response

    result = await _run(verbose)
    assert result.rate(CapabilityDimension.BOUNDEDNESS) == 0.0
    assert result.verdict is CapabilityVerdict.INCAPABLE


# --------------------------------------------------------- repeatability


@pytest.mark.asyncio
async def test_one_lucky_response_is_not_capability() -> None:
    """Alternating success and failure must not average into competence."""
    calls = {"n": 0}

    def coin_flip(payload):
        calls["n"] += 1
        if calls["n"] % 2:
            raise _Err("invalid_response")
        return _good(payload)

    result = await _run(coin_flip)
    repeat = result.dimension(CapabilityDimension.REPEATABILITY)
    assert repeat.attempted > 0
    assert repeat.passed == 0, "inconsistent probes must not count as repeatable"
    assert result.verdict is not CapabilityVerdict.CAPABLE


@pytest.mark.asyncio
async def test_consistent_failure_is_still_repeatable() -> None:
    """Repeatability measures agreement, not success."""

    def always_bad(_payload):
        raise _Err("invalid_response")

    result = await _run(always_bad)
    repeat = result.dimension(CapabilityDimension.REPEATABILITY)
    assert repeat.passed == repeat.attempted


# ------------------------------------------------------------ latency


@pytest.mark.asyncio
async def test_latency_is_recorded_but_never_implies_correctness() -> None:
    def fast_and_wrong(payload):
        response = _good(payload)
        response["supporting_finding_ids"] = ["invented"]
        return response

    result = await _run(fast_and_wrong)
    assert result.median_latency_ms is not None
    assert result.verdict is CapabilityVerdict.INCAPABLE


def test_p95_needs_enough_samples_to_mean_anything() -> None:
    from hamie.domain.capability import CapabilityResult

    def _result(n: int) -> CapabilityResult:
        return CapabilityResult(
            schema_version=1, provider="p", model="m", configuration_fingerprint=FP,
            probed_at=NOW, verdict=CapabilityVerdict.CAPABLE, reasons=(),
            dimensions=(), probes_attempted=n, probes_passed=n,
            latencies_ms=tuple(range(100, 100 + n)),
        )

    assert _result(3).p95_latency_ms is None
    assert _result(20).p95_latency_ms is not None


# -------------------------------------------------------- verdict math


def test_verdict_thresholds() -> None:
    def dims(rate: float) -> tuple[DimensionResult, ...]:
        return tuple(
            DimensionResult(d, 10, int(rate * 10))
            for d in REQUIRED_DIMENSIONS
            if d is not CapabilityDimension.CONNECTIVITY
        )

    assert compute_verdict(dims(1.0), connectivity_ok=True)[0] is CapabilityVerdict.CAPABLE
    assert compute_verdict(dims(REQUIRED_PASS_RATE), connectivity_ok=True)[0] is CapabilityVerdict.CAPABLE
    assert compute_verdict(dims(0.6), connectivity_ok=True)[0] is CapabilityVerdict.DEGRADED
    assert compute_verdict(dims(INCAPABLE_PASS_RATE - 0.01), connectivity_ok=True)[0] is CapabilityVerdict.INCAPABLE
    assert compute_verdict(dims(1.0), connectivity_ok=False)[0] is CapabilityVerdict.PROVIDER_UNAVAILABLE


def test_an_unmeasured_required_dimension_is_not_a_pass() -> None:
    verdict, reasons = compute_verdict((), connectivity_ok=True)
    assert verdict is CapabilityVerdict.DEGRADED
    assert any("not measured" in r for r in reasons)


# ------------------------------------------------------- fingerprinting


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "other-model"),
        ("base_url", "http://10.0.0.9:11434"),
        ("temperature", 0.9),
        ("maximum_output_tokens", 2048),
        ("maximum_input_characters", 32000),
        ("connection_method", "ha_ai_task"),
        ("think", True),
        ("response_schema_version", 2),
        ("system_instructions_digest", "different"),
    ],
)
def test_every_material_setting_change_invalidates_the_fingerprint(field, value) -> None:
    base = {
        "provider": "ollama", "connection_method": "direct", "model": "qwen",
        "base_url": "http://10.0.0.1:11434", "temperature": 0.1,
        "maximum_input_characters": 16000, "maximum_output_tokens": 1024,
        "think": False, "capabilities": ("analysis",), "response_schema_version": 1,
        "system_instructions_digest": "abc",
    }
    assert configuration_fingerprint(base) != configuration_fingerprint({**base, field: value})


def test_fingerprint_is_stable_for_the_same_configuration() -> None:
    base = {"provider": "ollama", "model": "qwen", "capabilities": ("b", "a")}
    assert configuration_fingerprint(base) == configuration_fingerprint(
        {"model": "qwen", "provider": "ollama", "capabilities": ("a", "b")}
    )


# --------------------------------------------------------------- gate


def _result(verdict: CapabilityVerdict, *, at: datetime = NOW, fp: str = FP):
    from hamie.domain.capability import CapabilityResult

    return CapabilityResult(
        schema_version=1, provider="ollama", model="m", configuration_fingerprint=fp,
        probed_at=at, verdict=verdict, reasons=("measured",),
        dimensions=tuple(
            DimensionResult(d, 10, 10 if verdict is CapabilityVerdict.CAPABLE else 2)
            for d in REQUIRED_DIMENSIONS
        ),
        probes_attempted=10, probes_passed=10,
    )


def test_never_probed_blocks_bulk_analysis() -> None:
    gate = evaluate_gate(None, current_fingerprint=FP, now=NOW)
    assert not gate.permitted
    assert gate.verdict is CapabilityVerdict.UNKNOWN


def test_capable_and_fresh_permits_analysis() -> None:
    gate = evaluate_gate(_result(CapabilityVerdict.CAPABLE), current_fingerprint=FP, now=NOW)
    assert gate.permitted


@pytest.mark.parametrize(
    "verdict",
    [CapabilityVerdict.INCAPABLE, CapabilityVerdict.DEGRADED,
     CapabilityVerdict.PROVIDER_UNAVAILABLE, CapabilityVerdict.UNKNOWN],
)
def test_only_a_capable_verdict_permits_analysis(verdict) -> None:
    gate = evaluate_gate(_result(verdict), current_fingerprint=FP, now=NOW)
    assert not gate.permitted
    assert gate.failed_dimensions


def test_a_changed_configuration_is_treated_as_no_evidence_at_all() -> None:
    """Swapping the model must not inherit the previous verdict."""
    gate = evaluate_gate(
        _result(CapabilityVerdict.CAPABLE, fp="old"), current_fingerprint="new", now=NOW
    )
    assert not gate.permitted
    assert gate.fingerprint_mismatch
    assert gate.verdict is CapabilityVerdict.UNKNOWN


def test_a_stale_probe_must_be_re_run() -> None:
    old = NOW - timedelta(seconds=CAPABILITY_FRESHNESS_SECONDS + 60)
    gate = evaluate_gate(_result(CapabilityVerdict.CAPABLE, at=old), current_fingerprint=FP, now=NOW)
    assert not gate.permitted
    assert gate.stale


def test_a_probe_just_inside_the_freshness_window_still_counts() -> None:
    recent = NOW - timedelta(seconds=CAPABILITY_FRESHNESS_SECONDS - 60)
    gate = evaluate_gate(_result(CapabilityVerdict.CAPABLE, at=recent), current_fingerprint=FP, now=NOW)
    assert gate.permitted


def test_gate_serialization_names_the_failed_dimensions() -> None:
    gate = evaluate_gate(_result(CapabilityVerdict.INCAPABLE), current_fingerprint=FP, now=NOW)
    data = gate.as_dict()
    assert data["permitted"] is False
    assert data["verdict"] == "incapable"
    assert data["failed_dimensions"]


def test_probe_fixtures_have_deterministic_expectations() -> None:
    """No probe may be scored on prose."""
    for case in default_probe_cases():
        assert case.expectations, case.probe_id
        assert case.payload["hamie_capability_probe"] is True
        if case.requires_abstention:
            assert any(
                e.dimension is CapabilityDimension.ABSTENTION for e in case.expectations
            )


# ------------------------------------------------------- persistence


def _sample_result():
    from hamie.domain.capability import CapabilityResult

    return CapabilityResult(
        schema_version=1, provider="ollama", model="qwen3.5:4b-q4_K_M",
        configuration_fingerprint=FP, probed_at=NOW,
        verdict=CapabilityVerdict.DEGRADED, reasons=("structured_output 6/10 (60%)",),
        dimensions=(
            DimensionResult(CapabilityDimension.STRUCTURED_OUTPUT, 10, 6),
            DimensionResult(CapabilityDimension.SEMANTIC_VALIDITY, 10, 9),
        ),
        probes_attempted=10, probes_passed=6, latencies_ms=(120, 340, 900),
        last_failure_category="schema_validation_failed",
    )


def test_capability_round_trips_through_storage() -> None:
    from hamie.domain.capability import decode_capability, encode_capability

    original = _sample_result()
    restored = decode_capability(encode_capability(original))
    assert restored.model == original.model
    assert restored.verdict is original.verdict
    assert restored.configuration_fingerprint == original.configuration_fingerprint
    assert restored.probed_at == original.probed_at
    assert restored.rate(CapabilityDimension.STRUCTURED_OUTPUT) == 0.6
    assert restored.last_failure_category == "schema_validation_failed"
    assert restored.median_latency_ms == 340


def test_absent_capability_round_trips_as_none() -> None:
    from hamie.domain.capability import decode_capability, encode_capability

    assert encode_capability(None) is None
    assert decode_capability(None) is None


def test_an_unreadable_capability_record_raises_rather_than_looking_unprobed() -> None:
    """Corruption must not read as a fresh installation."""
    from hamie.domain.capability import decode_capability

    with pytest.raises(ValueError):
        decode_capability({"provider": "ollama"})  # missing everything else
    with pytest.raises(ValueError):
        decode_capability("not-an-object")
    with pytest.raises(ValueError):
        decode_capability({**_encoded(), "verdict": "brilliant"})


def _encoded() -> dict:
    from hamie.domain.capability import encode_capability

    return encode_capability(_sample_result())


def test_capability_survives_a_full_store_document_round_trip() -> None:
    from hamie.application.persistence import RepositoryState
    from hamie.infrastructure.storage import decode_document, encode_document

    state = RepositoryState(capability=_sample_result())
    restored = decode_document(encode_document(state))
    assert restored.capability is not None
    assert restored.capability.model == "qwen3.5:4b-q4_K_M"
    assert restored.capability.verdict is CapabilityVerdict.DEGRADED


def test_a_v9_document_migrates_forward_without_inventing_a_verdict() -> None:
    """Migration must never manufacture capability for an unprobed model."""
    from copy import deepcopy

    from hamie.application.persistence import RepositoryState
    from hamie.domain.common import canonical_json, stable_digest
    from hamie.infrastructure.storage import decode_document, encode_document

    current = encode_document(RepositoryState())
    v9 = deepcopy(current)
    v9["schema_version"] = 9
    v9["compatibility"] = {"minimum_reader": 9, "maximum_reader": 9}
    del v9["payload"]["capability"]
    v9["checksum"] = stable_digest(canonical_json(v9["payload"]))

    state = decode_document(v9)
    assert state.capability is None
    assert any("9->10" in entry for entry in state.migration_history)

    # And the gate reads that absence as "not permitted until probed".
    gate = evaluate_gate(state.capability, current_fingerprint=FP, now=NOW)
    assert not gate.permitted
    assert gate.verdict is CapabilityVerdict.UNKNOWN


# ------------------------------------------------- gate scope (Phase 3E)


def test_gate_scope_is_documented_as_bulk_only() -> None:
    """A degraded model must not mean 'no AI features and no way to see why'.

    Phase 3E gates *bulk* analysis. A targeted request is one operator asking
    about one group they chose: bounded, audited, and the only way to judge a
    degraded model against real data rather than on HAMIE's aggregate verdict.
    The allowance is recorded, never silent.
    """
    import inspect

    from hamie.application import operations_service

    source = inspect.getsource(operations_service)
    assert "not gate.permitted and scan_summary" in source, "bulk must still be gated"
    assert "ai_request_capability_warning" in source, "targeted runs must be audited"
    assert "ai_capability_not_verified" in source


def test_probe_set_exercises_a_realistic_group_size() -> None:
    """Small fixtures do not exercise the output budget.

    The first live targeted analysis failed with ai_response_truncated on a
    16-finding group while every 1-3 finding probe passed boundedness. A probe
    suite that cannot reproduce the production failure is not measuring the
    production contract.
    """
    cases = {case.probe_id: case for case in default_probe_cases()}
    realistic = cases["realistic_group_size"]
    assert len(realistic.payload["findings"]) >= 16
    assert len(realistic.expected_identifiers) >= 16


@pytest.mark.asyncio
async def test_truncated_output_is_attributed_to_boundedness_not_format() -> None:
    """A cut-off response is an output-budget problem, not bad JSON."""

    def truncated(_payload):
        raise _Err("ai_response_truncated")

    result = await _run(truncated)
    assert result.rate(CapabilityDimension.BOUNDEDNESS) == 0.0
    structured = result.dimension(CapabilityDimension.STRUCTURED_OUTPUT)
    assert structured is None or structured.attempted == 0


# ------------------------------------------- contradiction suite (Phase 4)


def test_contradiction_suite_is_large_enough_to_mean_something() -> None:
    """n=4 gave 25% on one run and 75% on the next.

    A verdict that flips on a single sample is not a measurement.
    """
    from hamie.application.capability_probe import (
        CONTRADICTION_CLASSES,
        contradiction_probe_cases,
    )

    cases = contradiction_probe_cases()
    assert len(cases) >= 20
    assert len({case.probe_id for case in cases}) == len(cases), "duplicate classes"
    assert len({label for label, *_ in CONTRADICTION_CLASSES}) == len(CONTRADICTION_CLASSES)


def test_every_contradiction_case_is_scored_deterministically() -> None:
    from hamie.application.capability_probe import contradiction_probe_cases

    for case in contradiction_probe_cases():
        dimensions = {e.dimension for e in case.expectations}
        assert CapabilityDimension.CONTRADICTION_HANDLING in dimensions, case.probe_id
        assert case.expected_identifiers, case.probe_id
        assert len(case.payload["findings"][0]["evidence"]) >= 3, case.probe_id


@pytest.mark.asyncio
async def test_a_model_that_always_asserts_fails_the_unresolvable_half() -> None:
    """Guessing here would be guessing about a real house."""

    def decisive(payload):
        response = _good(payload)
        response["confidence"] = "high"
        response["assumptions"] = []
        response["missing_evidence"] = []
        return response

    result = await _run(decisive)
    assert result.contradiction_unresolvable[1] == 0
    assert result.verdict is not CapabilityVerdict.CAPABLE


@pytest.mark.asyncio
async def test_a_model_that_always_abstains_fails_the_resolvable_half() -> None:
    """Abstention is not safety when the evidence settles the question.

    Without this, a model that answers "I cannot tell" to everything would
    score perfectly on contradiction handling while being useless.
    """

    def timid(payload):
        response = _good(payload)
        response["confidence"] = "low"
        response["summary"] = ""
        response["probable_causes"] = []
        response["missing_evidence"] = ["everything is uncertain"]
        return response

    result = await _run(timid)
    attempted_r, passed_r = result.contradiction_resolvable
    assert attempted_r > 0
    assert passed_r == 0, "abstaining on resolvable contradictions must not score"


@pytest.mark.asyncio
async def test_per_probe_outcomes_identify_which_class_failed() -> None:
    """An aggregate percentage is not something an operator can act on."""
    from hamie.application.capability_probe import contradiction_probe_cases

    from hamie.domain.capability import ContradictionKind

    target = next(
        c.probe_id
        for c in contradiction_probe_cases()
        if c.contradiction_kind is ContradictionKind.UNRESOLVABLE
    )

    def selective(payload):
        response = _good(payload)
        # Fail exactly one class by answering it over-confidently.
        if payload["findings"][0]["finding_id"] == _probe_id_for(target):
            response["confidence"] = "high"
            response["missing_evidence"] = []
            response["assumptions"] = []
        return response

    result = await _run(selective)
    data = result.as_dict()
    assert target in data["failing_probes"]
    assert len(data["probe_outcomes"]) == len(default_probe_cases())


def _probe_id_for(probe_id: str) -> str:
    from hamie.application.capability_probe import contradiction_probe_cases

    case = next(c for c in contradiction_probe_cases() if c.probe_id == probe_id)
    return case.expected_identifiers[0]
