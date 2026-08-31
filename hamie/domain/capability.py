"""Provider/model capability: does the configured model meet HAMIE's contract?

A reachable connector proves the network works. It says nothing about whether
the model can return the exact structured shape HAMIE's parser requires, keep
opaque identifiers intact, or decline to answer when the evidence does not
support one. Production had already shown the difference: the connector
reported `healthy` while analysis runs produced `semantic_validation_failed`
and zero usable recommendations.

So capability is measured, never assumed and never inferred from model size or
name. A 4B model that reliably returns valid structured output is more useful
here than a 70B model that writes confident prose about entities that do not
exist.

Two rules shape everything below:

1. **Pass/fail is deterministic and computed by HAMIE.** No probe is scored on
   how good the answer sounds. Every expectation is a predicate over the
   parsed response -- an identifier is present or it is not, a confidence
   value is in the enum or it is not.
2. **A probe result is bound to the exact configuration it measured.** Change
   the model, the endpoint, the output limit or the temperature, and the
   previous verdict describes something that no longer exists.

Pure and I/O-free. The runner lives in application/capability_probe.py.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from .common import canonical_json, stable_digest

CAPABILITY_SCHEMA_VERSION = 1

#: How long a probe result stays authoritative. Long enough not to re-probe on
#: every analysis, short enough that a silently swapped model behind the same
#: endpoint is caught within a day.
CAPABILITY_FRESHNESS_SECONDS = 24 * 60 * 60


class ContradictionKind(StrEnum):
    """Whether HAMIE's evidence hierarchy can settle a conflict.

    The distinction is the whole point. A model that always abstains is not
    safe, it is useless; a model that always asserts is not confident, it is
    dangerous. Scoring both kinds with one rule cannot tell those apart, and
    the previous scorer -- which penalised high confidence unconditionally --
    marked the model wrong for correctly resolving toward authoritative
    evidence.
    """

    #: One source has higher authority under HAMIE's evidence hierarchy:
    #: live resolver over stale claim, current reverse references over a
    #: historical assertion, measured effect over description. The safe answer
    #: RESOLVES, and may do so confidently.
    RESOLVABLE = "resolvable"
    #: No deterministic authority exists. The safe answer ACKNOWLEDGES the
    #: conflict and declines to guess.
    UNRESOLVABLE = "unresolvable"


class CapabilityDimension(StrEnum):
    """What is measured. Each is independently pass/fail."""

    CONNECTIVITY = "connectivity"
    STRUCTURED_OUTPUT = "structured_output"
    SEMANTIC_VALIDITY = "semantic_validity"
    INSTRUCTION_FOLLOWING = "instruction_following"
    IDENTIFIER_PRESERVATION = "identifier_preservation"
    ABSTENTION = "abstention"
    CONTRADICTION_HANDLING = "contradiction_handling"
    BOUNDEDNESS = "boundedness"
    REPEATABILITY = "repeatability"


#: Dimensions whose failure means the model cannot do the job at all. Falling
#: below INCAPABLE_PASS_RATE on any of these produces INCAPABLE.
REQUIRED_DIMENSIONS = (
    CapabilityDimension.CONNECTIVITY,
    CapabilityDimension.STRUCTURED_OUTPUT,
    CapabilityDimension.SEMANTIC_VALIDITY,
    CapabilityDimension.IDENTIFIER_PRESERVATION,
    CapabilityDimension.BOUNDEDNESS,
)

#: Judgement dimensions. Failing these is not unsafe -- HAMIE's deterministic
#: layer decides anything that matters, so a model that never abstains
#: produces noise rather than danger. But it is noise HAMIE would pay for
#: across thousands of findings: a model that confidently proposes a repair
#: for every thin-evidence finding turns bulk analysis into a queue of
#: recommendations the deterministic layer then has to reject one by one.
#: So they downgrade to DEGRADED, which does not permit bulk analysis, rather
#: than being recorded as a footnote on a CAPABLE verdict.
JUDGEMENT_DIMENSIONS = (
    CapabilityDimension.ABSTENTION,
    CapabilityDimension.CONTRADICTION_HANDLING,
)

#: Minimum pass rate for a required dimension to count as satisfied. Not 1.0:
#: local models are stochastic and one malformed response in ten is survivable
#: when HAMIE retries and validates every one. Below this, bulk analysis burns
#: hours to produce nothing.
REQUIRED_PASS_RATE = 0.8

#: Below this, the model is not merely unreliable -- it cannot do the job.
INCAPABLE_PASS_RATE = 0.4


class CapabilityVerdict(StrEnum):
    UNKNOWN = "unknown"
    PROBING = "probing"
    CAPABLE = "capable"
    DEGRADED = "degraded"
    INCAPABLE = "incapable"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


#: Verdicts that permit HAMIE to spend a bulk analysis run.
ANALYSIS_PERMITTED_VERDICTS = frozenset({CapabilityVerdict.CAPABLE})


@dataclass(frozen=True, slots=True)
class ProbeExpectation:
    """A deterministic predicate over a parsed response.

    `check` returns (passed, detail). Detail is a short machine-readable
    reason, never prose scoring.
    """

    dimension: CapabilityDimension
    check: Callable[[dict[str, Any], "ProbeCase"], tuple[bool, str]]


@dataclass(frozen=True, slots=True)
class ProbeCase:
    """One controlled fixture with known-correct behaviour."""

    probe_id: str
    description: str
    payload: dict[str, Any]
    expectations: tuple[ProbeExpectation, ...]
    #: Identifiers that must survive verbatim in the response.
    expected_identifiers: tuple[str, ...] = ()
    #: True when the only defensible answer is to decline to recommend.
    requires_abstention: bool = False
    #: For contradiction probes: which behaviour is correct here.
    contradiction_kind: ContradictionKind | None = None
    #: How many times to run it. One valid JSON response is not capability.
    repeats: int = 1


@dataclass(frozen=True, slots=True)
class ProbeRun:
    """The outcome of one execution of one probe."""

    probe_id: str
    attempt: int
    succeeded: bool
    latency_ms: int
    #: HAMIE pipeline error code when the call did not produce a response.
    error_code: str | None = None
    #: Per-dimension results measured on this run.
    dimension_results: tuple[tuple[str, bool, str], ...] = ()
    response_characters: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "attempt": self.attempt,
            "succeeded": self.succeeded,
            "latency_ms": self.latency_ms,
            "error_code": self.error_code,
            "response_characters": self.response_characters,
            "dimensions": [
                {"dimension": name, "passed": passed, "detail": detail}
                for name, passed, detail in self.dimension_results
            ],
        }


@dataclass(frozen=True, slots=True)
class DimensionResult:
    dimension: CapabilityDimension
    attempted: int
    passed: int

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.attempted) if self.attempted else 0.0

    @property
    def satisfied(self) -> bool:
        return self.attempted > 0 and self.pass_rate >= REQUIRED_PASS_RATE

    def as_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "attempted": self.attempted,
            "passed": self.passed,
            "pass_rate": round(self.pass_rate, 3),
            "satisfied": self.satisfied,
        }


def configuration_fingerprint(config: dict[str, Any]) -> str:
    """Identity of the exact provider configuration a probe measured.

    Every field here can change the model's behaviour, so any change to any
    of them invalidates the verdict. Notably includes the response-schema
    version and system instructions: HAMIE changing what it asks for is
    every bit as material as the operator changing the model.
    """
    material = {
        "provider": config.get("provider"),
        "connection_method": config.get("connection_method"),
        "model": config.get("model"),
        "base_url": config.get("base_url"),
        "ai_task_entity_id": config.get("ai_task_entity_id"),
        "temperature": config.get("temperature"),
        "maximum_input_characters": config.get("maximum_input_characters"),
        "maximum_output_tokens": config.get("maximum_output_tokens"),
        "think": config.get("think"),
        "capabilities": sorted(config.get("capabilities") or ()),
        "response_schema_version": config.get("response_schema_version"),
        "system_instructions_digest": config.get("system_instructions_digest"),
        "capability_schema_version": CAPABILITY_SCHEMA_VERSION,
    }
    return stable_digest(canonical_json(material))


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    """A durable, configuration-bound statement about a model's fitness."""

    schema_version: int
    provider: str
    model: str
    configuration_fingerprint: str
    probed_at: datetime
    verdict: CapabilityVerdict
    reasons: tuple[str, ...]
    dimensions: tuple[DimensionResult, ...]
    probes_attempted: int
    probes_passed: int
    latencies_ms: tuple[int, ...] = ()
    last_failure_category: str | None = None
    #: (probe_id, attempted, passed). Bounded and cheap, and the difference
    #: between "contradiction handling is 70%" and "it fails specifically on
    #: stale-cache and predecessor/successor cases" is the difference between
    #: a number and something an operator can act on.
    probe_outcomes: tuple[tuple[str, int, int], ...] = ()
    #: (attempted, passed) per contradiction kind. Reported separately
    #: because an aggregate hides the two failure modes that matter: a model
    #: that always abstains and one that always asserts can share a score.
    contradiction_resolvable: tuple[int, int] = (0, 0)
    contradiction_unresolvable: tuple[int, int] = (0, 0)
    runs: tuple[ProbeRun, ...] = ()

    @property
    def median_latency_ms(self) -> int | None:
        return int(statistics.median(self.latencies_ms)) if self.latencies_ms else None

    @property
    def p95_latency_ms(self) -> int | None:
        """Only reported with enough samples to mean anything."""
        if len(self.latencies_ms) < 5:
            return None
        ordered = sorted(self.latencies_ms)
        index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[index]

    def dimension(self, dimension: CapabilityDimension) -> DimensionResult | None:
        return next((d for d in self.dimensions if d.dimension is dimension), None)

    def rate(self, dimension: CapabilityDimension) -> float:
        found = self.dimension(dimension)
        return found.pass_rate if found else 0.0

    def is_fresh(self, now: datetime) -> bool:
        return (now - self.probed_at).total_seconds() <= CAPABILITY_FRESHNESS_SECONDS

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "model": self.model,
            "configuration_fingerprint": self.configuration_fingerprint,
            "probed_at": self.probed_at.isoformat(),
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
            "dimensions": [item.as_dict() for item in self.dimensions],
            "probes_attempted": self.probes_attempted,
            "probes_passed": self.probes_passed,
            "structured_output_rate": round(
                self.rate(CapabilityDimension.STRUCTURED_OUTPUT), 3
            ),
            "semantic_validation_rate": round(
                self.rate(CapabilityDimension.SEMANTIC_VALIDITY), 3
            ),
            "identifier_preservation_rate": round(
                self.rate(CapabilityDimension.IDENTIFIER_PRESERVATION), 3
            ),
            "abstention_rate": round(self.rate(CapabilityDimension.ABSTENTION), 3),
            "probe_outcomes": [
                {"probe_id": pid, "attempted": a, "passed": pss}
                for pid, a, pss in self.probe_outcomes
            ],
            "failing_probes": [
                pid for pid, a, pss in self.probe_outcomes if a and pss < a
            ],
            "contradiction_resolvable": {
                "attempted": self.contradiction_resolvable[0],
                "passed": self.contradiction_resolvable[1],
                "pass_rate": round(
                    self.contradiction_resolvable[1] / self.contradiction_resolvable[0], 3
                ) if self.contradiction_resolvable[0] else None,
            },
            "contradiction_unresolvable": {
                "attempted": self.contradiction_unresolvable[0],
                "passed": self.contradiction_unresolvable[1],
                "pass_rate": round(
                    self.contradiction_unresolvable[1] / self.contradiction_unresolvable[0], 3
                ) if self.contradiction_unresolvable[0] else None,
            },
            "median_latency_ms": self.median_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "last_failure_category": self.last_failure_category,
        }


def compute_verdict(
    dimensions: tuple[DimensionResult, ...], *, connectivity_ok: bool
) -> tuple[CapabilityVerdict, tuple[str, ...]]:
    """Derive the verdict from measured behaviour alone."""
    if not connectivity_ok:
        return CapabilityVerdict.PROVIDER_UNAVAILABLE, (
            "the provider could not be reached",
        )

    by_dimension = {item.dimension: item for item in dimensions}
    reasons: list[str] = []
    incapable = False
    degraded = False

    for required in REQUIRED_DIMENSIONS:
        if required is CapabilityDimension.CONNECTIVITY:
            continue
        result = by_dimension.get(required)
        if result is None or result.attempted == 0:
            degraded = True
            reasons.append(f"{required.value} was not measured")
            continue
        if result.pass_rate < INCAPABLE_PASS_RATE:
            incapable = True
            reasons.append(
                f"{required.value} passed {result.passed}/{result.attempted} "
                f"({result.pass_rate:.0%})"
            )
        elif not result.satisfied:
            degraded = True
            reasons.append(
                f"{required.value} passed {result.passed}/{result.attempted} "
                f"({result.pass_rate:.0%}), below the {REQUIRED_PASS_RATE:.0%} minimum"
            )

    for judgement in JUDGEMENT_DIMENSIONS:
        result = by_dimension.get(judgement)
        if result is not None and result.attempted and not result.satisfied:
            degraded = True
            reasons.append(
                f"{judgement.value} passed {result.passed}/{result.attempted} "
                f"({result.pass_rate:.0%}), below the {REQUIRED_PASS_RATE:.0%} minimum"
            )

    if incapable:
        return CapabilityVerdict.INCAPABLE, tuple(reasons)
    if degraded:
        return CapabilityVerdict.DEGRADED, tuple(reasons)
    return CapabilityVerdict.CAPABLE, tuple(
        reasons or ("every required capability met its minimum pass rate",)
    )


@dataclass(frozen=True, slots=True)
class AnalysisGate:
    """May HAMIE spend a bulk analysis run right now?"""

    permitted: bool
    reason: str
    verdict: CapabilityVerdict
    failed_dimensions: tuple[str, ...] = ()
    stale: bool = False
    fingerprint_mismatch: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "permitted": self.permitted,
            "reason": self.reason,
            "verdict": self.verdict.value,
            "failed_dimensions": list(self.failed_dimensions),
            "stale": self.stale,
            "fingerprint_mismatch": self.fingerprint_mismatch,
        }


def evaluate_gate(
    result: CapabilityResult | None,
    *,
    current_fingerprint: str,
    now: datetime,
) -> AnalysisGate:
    """Refuse expensive analysis the configured model cannot deliver.

    Deliberately conservative about identity: a result that measured a
    different configuration is treated as no result at all, not as weak
    evidence. Otherwise swapping a 4B model for a 70B one -- or the reverse
    -- silently inherits the previous verdict.
    """
    if result is None:
        return AnalysisGate(
            False,
            "the configured model has not been capability-probed",
            CapabilityVerdict.UNKNOWN,
        )
    if result.configuration_fingerprint != current_fingerprint:
        return AnalysisGate(
            False,
            "the provider configuration changed since the last capability probe",
            CapabilityVerdict.UNKNOWN,
            fingerprint_mismatch=True,
        )
    if not result.is_fresh(now):
        return AnalysisGate(
            False,
            "the capability probe is stale and must be re-run",
            result.verdict,
            stale=True,
        )
    if result.verdict not in ANALYSIS_PERMITTED_VERDICTS:
        failed = tuple(
            item.dimension.value
            for item in result.dimensions
            if item.dimension in REQUIRED_DIMENSIONS and not item.satisfied
        )
        return AnalysisGate(
            False,
            f"the configured model is {result.verdict.value}: "
            + ("; ".join(result.reasons) or "capability requirements not met"),
            result.verdict,
            failed_dimensions=failed,
        )
    return AnalysisGate(True, "capability verified for this configuration", result.verdict)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def encode_capability(value: CapabilityResult | None) -> dict[str, Any] | None:
    """Encode for the Store. Probe runs are dropped deliberately.

    The per-run detail is useful while reading a probe report and worthless a
    week later; persisting fourteen response transcripts per probe would grow
    without bound and is exactly the sort of thing that turns a state document
    into a log file. The aggregates below are what the gate and the operator
    actually consume.
    """
    if value is None:
        return None
    return {
        "schema_version": value.schema_version,
        "provider": value.provider,
        "model": value.model,
        "configuration_fingerprint": value.configuration_fingerprint,
        "probed_at": value.probed_at.isoformat(),
        "verdict": value.verdict.value,
        "reasons": list(value.reasons),
        "dimensions": [
            {
                "dimension": item.dimension.value,
                "attempted": item.attempted,
                "passed": item.passed,
            }
            for item in value.dimensions
        ],
        "probes_attempted": value.probes_attempted,
        "probes_passed": value.probes_passed,
        "latencies_ms": list(value.latencies_ms),
        "last_failure_category": value.last_failure_category,
        "probe_outcomes": [list(item) for item in value.probe_outcomes],
        "contradiction_resolvable": list(value.contradiction_resolvable),
        "contradiction_unresolvable": list(value.contradiction_unresolvable),
    }


def decode_capability(raw: object) -> CapabilityResult | None:
    """Decode a stored capability result, refusing anything unreadable.

    A capability record HAMIE cannot parse must not silently become "no
    probe has run" -- that reads as a fresh installation and quietly invites
    a re-probe, hiding whatever corrupted it. It raises instead.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("capability record must be an object")
    try:
        dimensions = tuple(
            DimensionResult(
                CapabilityDimension(item["dimension"]),
                int(item["attempted"]),
                int(item["passed"]),
            )
            for item in raw["dimensions"]
        )
        return CapabilityResult(
            schema_version=int(raw["schema_version"]),
            provider=str(raw["provider"]),
            model=str(raw["model"]),
            configuration_fingerprint=str(raw["configuration_fingerprint"]),
            probed_at=datetime.fromisoformat(str(raw["probed_at"])),
            verdict=CapabilityVerdict(raw["verdict"]),
            reasons=tuple(str(item) for item in raw.get("reasons") or ()),
            dimensions=dimensions,
            probes_attempted=int(raw["probes_attempted"]),
            probes_passed=int(raw["probes_passed"]),
            latencies_ms=tuple(int(item) for item in raw.get("latencies_ms") or ()),
            last_failure_category=(
                str(raw["last_failure_category"])
                if raw.get("last_failure_category") is not None
                else None
            ),
            probe_outcomes=tuple(
                (str(a), int(b), int(c)) for a, b, c in (raw.get("probe_outcomes") or ())
            ),
            contradiction_resolvable=tuple(
                raw.get("contradiction_resolvable") or (0, 0)
            )[:2] or (0, 0),
            contradiction_unresolvable=tuple(
                raw.get("contradiction_unresolvable") or (0, 0)
            )[:2] or (0, 0),
        )
    except (KeyError, TypeError, ValueError) as err:
        raise ValueError(f"capability record is unreadable: {err}") from err
