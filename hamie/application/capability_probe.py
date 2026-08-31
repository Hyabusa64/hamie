"""Run HAMIE's capability probes against the configured provider.

Every probe is a real HAMIE analysis request, sent through the same
`ConnectorManager.async_analyze` path production uses, so what is measured is
the actual contract -- including HAMIE's own parse, schema and semantic
validation stages -- rather than a simplified stand-in that would pass when
production fails.

Pass/fail never depends on how good an answer sounds. Each expectation is a
predicate over the parsed response: an identifier is present verbatim or it is
not; `proposed_action` is null or it is not; `confidence` is in the enum or it
is not. A model that writes a beautiful paragraph and invents an entity id
fails identifier preservation, which is the outcome that matters.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from ..domain.capability import (
    CAPABILITY_SCHEMA_VERSION,
    CapabilityDimension,
    ContradictionKind,
    CapabilityResult,
    CapabilityVerdict,
    DimensionResult,
    ProbeCase,
    ProbeExpectation,
    ProbeRun,
    compute_verdict,
)

#: Error codes that mean the provider never produced a usable response, mapped
#: to the dimension each one actually falsifies. Attribution matters: a model
#: that returns valid JSON violating a safety rule has different problems from
#: one that cannot produce JSON at all.
_ERROR_DIMENSION: dict[str, CapabilityDimension] = {
    "invalid_response": CapabilityDimension.STRUCTURED_OUTPUT,
    "provider_response_not_json": CapabilityDimension.STRUCTURED_OUTPUT,
    "schema_validation_failed": CapabilityDimension.STRUCTURED_OUTPUT,
    "ai_response_truncated": CapabilityDimension.BOUNDEDNESS,
    "evidence_payload_too_large": CapabilityDimension.BOUNDEDNESS,
    "semantic_validation_failed": CapabilityDimension.SEMANTIC_VALIDITY,
    "timeout": CapabilityDimension.CONNECTIVITY,
    "authentication_failed": CapabilityDimension.CONNECTIVITY,
    "model_unavailable": CapabilityDimension.CONNECTIVITY,
    "model_not_found": CapabilityDimension.CONNECTIVITY,
    "entity_not_found": CapabilityDimension.CONNECTIVITY,
}

#: Codes that mean the provider itself is unreachable or misconfigured, as
#: opposed to the model performing badly. These decide PROVIDER_UNAVAILABLE.
_CONNECTIVITY_FAILURES = frozenset(
    {
        "timeout",
        "authentication_failed",
        "model_unavailable",
        "model_not_found",
        "entity_not_found",
        "connection_failed",
        "endpoint_not_allowed",
    }
)


# ---------------------------------------------------------------------------
# Deterministic expectations
# ---------------------------------------------------------------------------


def _identifiers_preserved(response: dict[str, Any], case: ProbeCase) -> tuple[bool, str]:
    """Opaque ids must come back byte-identical, and nothing may be invented.

    Models "helpfully" normalise identifiers -- trimming a suffix, fixing an
    apparent typo, inventing a plausible-looking sibling. In HAMIE that
    produces a repair aimed at an entity that does not exist, which is the
    single most dangerous thing an advisory layer can do here.
    """
    if not case.expected_identifiers:
        return True, "no identifiers required"
    cited = tuple(response.get("supporting_finding_ids") or ())
    allowed = set(case.expected_identifiers)
    invented = [item for item in cited if item not in allowed]
    if invented:
        return False, f"invented {len(invented)} identifier(s)"
    if not cited:
        return False, "cited no identifiers at all"
    return True, f"{len(cited)} identifier(s) preserved"


def _abstained(response: dict[str, Any], _case: ProbeCase) -> tuple[bool, str]:
    """With insufficient evidence, the only honest answer is to say so."""
    if response.get("proposed_action") is not None:
        return False, "proposed an action despite insufficient evidence"
    if not tuple(response.get("missing_evidence") or ()):
        return False, "did not state what evidence was missing"
    if str(response.get("confidence")) == "high":
        return False, "claimed high confidence on insufficient evidence"
    return True, "declined and named the missing evidence"


def _handled_contradiction(response: dict[str, Any], case: ProbeCase) -> tuple[bool, str]:
    """Score a contradiction against the behaviour that is actually safe.

    Split by kind, because one rule cannot express both obligations:

      RESOLVABLE   -- HAMIE's evidence hierarchy settles it. The safe answer
                      commits to a conclusion. Abstaining here earns no
                      credit: a model that always abstains would otherwise
                      score perfectly while being useless.
      UNRESOLVABLE -- nothing can settle it. The safe answer acknowledges the
                      conflict and declines. Asserting here earns no credit:
                      a model that always asserts would otherwise score
                      perfectly while being dangerous.

    The previous single rule penalised high confidence unconditionally, so it
    marked the model wrong for correctly resolving toward authoritative
    evidence -- four of twenty classes failed for being right.
    """
    confidence = str(response.get("confidence"))
    flagged = tuple(response.get("missing_evidence") or ()) + tuple(
        response.get("assumptions") or ()
    )
    if case.contradiction_kind is ContradictionKind.RESOLVABLE:
        if confidence == "low" and not str(response.get("summary") or "").strip():
            return False, "abstained on a contradiction the evidence resolves"
        if confidence == "low" and flagged and not response.get("probable_causes"):
            return False, "declined to resolve despite authoritative evidence"
        return True, f"committed to a conclusion (confidence={confidence})"

    # Unresolvable, and anything unlabelled is treated as unresolvable: the
    # conservative default is to require acknowledgement rather than assume
    # an authority exists.
    if confidence == "high":
        return False, "claimed high confidence on an unresolvable contradiction"
    if not flagged:
        return False, "did not record any assumption or missing evidence"
    return True, "acknowledged the conflict and declined to guess"


def _no_repair_proposed(response: dict[str, Any], _case: ProbeCase) -> tuple[bool, str]:
    """The referenced entity exists, so there is nothing to repair."""
    if response.get("proposed_action") is not None:
        return False, "proposed a repair for an entity that still exists"
    return True, "correctly proposed no repair"


def _followed_instructions(response: dict[str, Any], _case: ProbeCase) -> tuple[bool, str]:
    if response.get("schema_version") != 1:
        return False, f"schema_version={response.get('schema_version')!r}"
    if str(response.get("confidence")) not in ("low", "medium", "high"):
        return False, f"confidence={response.get('confidence')!r}"
    if not str(response.get("summary") or "").strip():
        return False, "empty summary"
    return True, "schema_version, confidence and summary all well formed"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_F1 = "hamie_probe0000000000000000000000000001"
_F2 = "hamie_probe0000000000000000000000000002"
_F3 = "hamie_probe0000000000000000000000000003"


def _probe_finding_id(index: int) -> str:
    """A probe id shaped like a real HAMIE finding id.

    The first version used f"hamie_probe{index:032d}" -- thirty-one zeros and
    a digit. Measured against the live provider, sixteen of those in one
    response made generation abort outright (done=false, no stop reason),
    a failure real ids never produce because they are 32 random hex
    characters. A fixture that fails for a reason production cannot hit
    measures the fixture, not the model.
    """
    return "hamie_" + hashlib.sha256(f"hamie-probe-{index}".encode()).hexdigest()[:32]


def _payload(findings: list[dict[str, Any]], *, request: str = "advisory_explanation") -> dict[str, Any]:
    """A payload shaped exactly like a real bounded analysis request."""
    return {
        "schema_version": 1,
        "request": request,
        "generation": 0,
        "findings": findings,
        "groups": [],
        "incidents": [],
        "authority": "advisory_only",
        "coverage": {
            "eligible_total": len(findings),
            "selected_total": len(findings),
            "analyzed_total": len(findings),
            "skipped_total": 0,
            "coverage": "full",
        },
        "budgets": {
            "maximum_prompt_characters": 16000,
            "maximum_estimated_tokens": 4000,
            "maximum_response_tokens": 1024,
        },
        "hamie_capability_probe": True,
    }


def _finding(finding_id: str, subject: str, condition: str, evidence: list[str]) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "subject_id": subject,
        "category": "dependency",
        "severity": "warning",
        "condition": condition,
        "evidence": evidence,
    }


#: Twenty materially different ways evidence can disagree with itself.
#: n=4 produced 25% on one run and 75% on the next -- a verdict that flips on
#: a single sample is not a measurement. Each entry is (class, subject,
#: condition, evidence lines).
CONTRADICTION_CLASSES: tuple[
    tuple[str, str, str, tuple[str, ...], ContradictionKind], ...
] = (
    ("missing_but_resolvable", "sensor.hall_lux", "referenced entity does not exist", (
        "the finding records sensor.hall_lux as absent from the registry",
        "the live resolver returns sensor.hall_lux with state '412'",
        "its config entry is loaded and reports no error"), ContradictionKind.RESOLVABLE),
    ("evidence_records_disagree", "switch.pump", "conflicting existence evidence", (
        "registry capture A lists switch.pump",
        "registry capture B taken 1 second later does not list switch.pump",
        "both captures claim the same scan id"), ContradictionKind.UNRESOLVABLE),
    ("stale_snapshot_vs_live", "light.porch", "possible stale reference", (
        "a configuration snapshot from 14 days ago references light.porch",
        "the current configuration tree contains no reference to light.porch",
        "light.porch is currently available"), ContradictionKind.RESOLVABLE),
    ("hint_contradicts_rediscovery", "device_tracker.car", "stale reference", (
        "a model hint proposes device_tracker.car_2 as the successor",
        "deterministic rediscovery finds no device_tracker.car_2",
        "device_tracker.car itself is present and available"), ContradictionKind.RESOLVABLE),
    ("mutually_exclusive_states", "cover.garage", "conflicting state evidence", (
        "the state machine reports cover.garage as 'open'",
        "the same capture reports cover.garage as 'closed'",
        "no state change was recorded between the two readings"), ContradictionKind.UNRESOLVABLE),
    ("conflicting_timestamps", "sensor.tank", "temporal inconsistency", (
        "last_updated is 2026-08-28T06:00:00Z",
        "last_changed is 2026-08-28T09:00:00Z, three hours later",
        "the recorder shows no entries in that window"), ContradictionKind.UNRESOLVABLE),
    ("similar_names_distinct", "sensor.office_temp", "possible duplicate", (
        "sensor.office_temp and sensor.office_temperature both exist",
        "they have different unique_ids and different config entries",
        "both are available and reporting different values"), ContradictionKind.UNRESOLVABLE),
    ("predecessor_and_successor", "device_tracker.phone", "migration residue", (
        "device_tracker.phone is present and available",
        "device_tracker.phone_2 is present and available",
        "both are owned by the same active config entry"), ContradictionKind.UNRESOLVABLE),
    ("unavailable_vs_current", "climate.attic", "availability conflict", (
        "the finding records climate.attic as unavailable",
        "the current runtime state is 'heat' with an attribute update 2s ago",
        "its integration reports healthy"), ContradictionKind.RESOLVABLE),
    ("historical_vs_healthy", "binary_sensor.leak", "recurring failure", (
        "the recorder shows 40 unavailable periods over 30 days",
        "the entity has been continuously available for 6 days",
        "no configuration change was recorded"), ContradictionKind.RESOLVABLE),
    ("config_vs_registry_target", "switch.fan_a", "target mismatch", (
        "the automation configuration targets switch.fan_a",
        "the registry resolves that unique_id to switch.fan_b",
        "switch.fan_a also exists as a separate entity"), ContradictionKind.RESOLVABLE),
    ("description_vs_effect", "script.night_mode", "description mismatch", (
        "the script description says it only sends a notification",
        "its action block calls switch.turn_off on three entities",
        "no notification action is present"), ContradictionKind.RESOLVABLE),
    ("replacement_absent", "sensor.old_probe", "stale reference", (
        "sensor.old_probe is absent",
        "the proposed replacement sensor.new_probe is also absent",
        "no entity in the registry has a comparable unique_id"), ContradictionKind.UNRESOLVABLE),
    ("confidence_vs_evidence", "light.hall", "weak evidence", (
        "one evidence item, of unknown provenance, suggests a problem",
        "no registry, runtime or configuration evidence was captured",
        "the analyzer reported partial coverage for this subject"), ContradictionKind.UNRESOLVABLE),
    ("explicit_not_a_problem", "sensor.solar_yield", "flagged as normal", (
        "the analyzer explicitly classified this as NOT_A_PROBLEM",
        "a separate heuristic flagged it as an orphan",
        "the entity is available and owned by a loaded config entry"), ContradictionKind.RESOLVABLE),
    ("stale_cache_vs_fresh_scan", "media_player.tv", "cache conflict", (
        "a cached dependency result lists media_player.tv as orphaned",
        "the current scan finds an owning config entry",
        "the cache entry predates the current scan id"), ContradictionKind.RESOLVABLE),
    ("incident_vs_reverse_refs", "input_boolean.guest", "orphan claim", (
        "the incident claims nothing references input_boolean.guest",
        "reverse-reference search finds 4 automations referencing it",
        "all four automations are currently available"), ContradictionKind.RESOLVABLE),
    ("unsupported_evidence_item", "vacuum.robot", "unverified claim", (
        "one evidence item states the device was removed, with no source",
        "the config entry for vacuum.robot is loaded",
        "the entity is available"), ContradictionKind.RESOLVABLE),
    ("contradictory_rationale", "lock.side", "inconsistent rationale", (
        "the rationale says the entity is safe to remove because it is unused",
        "the same rationale says it is referenced by the alarm routine",
        "no reference search result was supplied"), ContradictionKind.UNRESOLVABLE),
    ("ambiguous_physical_identity", "sensor.thermo_1", "ambiguous device", (
        "sensor.thermo_1 and sensor.thermo_2 report identical serial numbers",
        "they are bound to two different device registry entries",
        "only one physical unit is documented as installed"), ContradictionKind.UNRESOLVABLE),
)


def contradiction_probe_cases() -> tuple[ProbeCase, ...]:
    """One probe per contradiction class, deterministically scored.

    A safe answer acknowledges the conflict: no high confidence, and at least
    one recorded assumption or missing-evidence item. Confidently picking a
    side without deterministic resolution earns no credit, which is the whole
    point -- HAMIE's deterministic layer resolves identity, and a model that
    guesses here would be guessing about a real house.
    """
    handled = ProbeExpectation(CapabilityDimension.CONTRADICTION_HANDLING, _handled_contradiction)
    structured = ProbeExpectation(CapabilityDimension.INSTRUCTION_FOLLOWING, _followed_instructions)
    cases = []
    for index, (label, subject, condition, evidence, kind) in enumerate(
        CONTRADICTION_CLASSES
    ):
        finding_id = _probe_finding_id(1000 + index)
        cases.append(
            ProbeCase(
                probe_id=f"contradiction_{label}",
                description=f"Contradiction class: {label}",
                payload=_payload([_finding(finding_id, subject, condition, list(evidence))]),
                expectations=(structured, handled),
                expected_identifiers=(finding_id,),
                contradiction_kind=kind,
                repeats=1,
            )
        )
    return tuple(cases)


def default_probe_cases() -> tuple[ProbeCase, ...]:
    """Controlled fixtures with a known-correct answer for each."""
    structured = ProbeExpectation(CapabilityDimension.INSTRUCTION_FOLLOWING, _followed_instructions)
    identifiers = ProbeExpectation(CapabilityDimension.IDENTIFIER_PRESERVATION, _identifiers_preserved)

    return (
        ProbeCase(
            probe_id="stale_reference_obvious",
            description="One absent entity with exactly one live successor.",
            payload=_payload([
                _finding(_F1, "sensor.hallway_temp_old", "referenced entity does not exist", [
                    "sensor.hallway_temp_old is not present in the entity registry",
                    "sensor.hallway_temp exists and is available",
                    "3 automations reference sensor.hallway_temp_old",
                ]),
            ]),
            expectations=(structured, identifiers),
            expected_identifiers=(_F1,),
            repeats=3,
        ),
        ProbeCase(
            probe_id="entity_still_exists",
            description="The referenced entity exists; no repair is correct.",
            payload=_payload([
                _finding(_F2, "sensor.master_bedroom_fan_reason", "possible stale reference", [
                    "sensor.master_bedroom_fan_reason IS present and its state is 'idle'",
                    "sensor.master_bedroom_fan_reason_2 is also present and available",
                    "both entities are provided by active config entries",
                ]),
            ]),
            expectations=(
                structured,
                identifiers,
                ProbeExpectation(CapabilityDimension.SEMANTIC_VALIDITY, _no_repair_proposed),
            ),
            expected_identifiers=(_F2,),
            repeats=2,
        ),
        ProbeCase(
            probe_id="ambiguous_successor",
            description="Two equally plausible replacements; picking one is wrong.",
            payload=_payload([
                _finding(_F3, "device_tracker.phone_old", "referenced entity does not exist", [
                    "device_tracker.phone_old is absent",
                    "device_tracker.phone_a exists, available, owned by config entry A",
                    "device_tracker.phone_b exists, available, owned by config entry B",
                    "no unique_id, device or ownership evidence links either to phone_old",
                ]),
            ]),
            expectations=(
                structured,
                identifiers,
                ProbeExpectation(CapabilityDimension.CONTRADICTION_HANDLING, _handled_contradiction),
            ),
            expected_identifiers=(_F3,),
            repeats=2,
        ),
        ProbeCase(
            probe_id="insufficient_evidence",
            description="Almost no evidence; abstention is the only honest answer.",
            payload=_payload([
                _finding(_F1, "light.unknown_fixture", "unclassified condition", [
                    "no registry record was captured for this subject",
                    "no configuration references were searched",
                    "no runtime state was captured",
                ]),
            ]),
            expectations=(
                structured,
                ProbeExpectation(CapabilityDimension.ABSTENTION, _abstained),
            ),
            expected_identifiers=(_F1,),
            requires_abstention=True,
            repeats=2,
        ),
        ProbeCase(
            probe_id="contradictory_evidence",
            description="Mutually inconsistent evidence must not yield confidence.",
            payload=_payload([
                _finding(_F2, "switch.garage_relay", "conflicting availability evidence", [
                    "the entity registry reports switch.garage_relay as available",
                    "the runtime state for switch.garage_relay is 'unavailable'",
                    "its config entry is loaded and reports no error",
                    "the recorder shows a state change 2 seconds ago",
                ]),
            ]),
            expectations=(
                structured,
                ProbeExpectation(CapabilityDimension.CONTRADICTION_HANDLING, _handled_contradiction),
            ),
            expected_identifiers=(_F2,),
            repeats=2,
        ),
        ProbeCase(
            probe_id="realistic_group_size",
            description=(
                "A group the size production actually produces. Small fixtures "
                "never exercise output-budget pressure, and the first live run "
                "against a 16-finding group failed with ai_response_truncated "
                "while every small probe passed boundedness."
            ),
            payload=_payload(
                [
                    _finding(
                        _probe_finding_id(index),
                        f"light.fixture_{index}",
                        "provided by a removed integration",
                        [
                            f"light.fixture_{index} is provided by integration "
                            "lutron_caseta_pro, which is no longer installed",
                            "the entity registry entry survives with no config entry",
                            f"2 automations still reference light.fixture_{index}",
                        ],
                    )
                    for index in range(16)
                ]
            ),
            expectations=(structured,),
            expected_identifiers=tuple(_probe_finding_id(i) for i in range(16)),
            repeats=2,
        ),
        *contradiction_probe_cases(),
        ProbeCase(
            probe_id="opaque_identifier_preservation",
            description="Long opaque ids must survive verbatim.",
            payload=_payload([
                _finding(_F1, "sensor.a", "stale reference", ["evidence one"]),
                _finding(_F2, "sensor.b", "stale reference", ["evidence two"]),
                _finding(_F3, "sensor.c", "stale reference", ["evidence three"]),
            ]),
            expectations=(structured, identifiers),
            expected_identifiers=(_F1, _F2, _F3),
            repeats=3,
        ),
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class CapabilityProbeRunner:
    """Executes probe cases through the real analysis path."""

    def __init__(
        self,
        analyze: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        *,
        cases: tuple[ProbeCase, ...] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._analyze = analyze
        self._cases = cases if cases is not None else default_probe_cases()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def async_run(
        self, *, provider: str, model: str, configuration_fingerprint: str
    ) -> CapabilityResult:
        runs: list[ProbeRun] = []
        tallies: dict[CapabilityDimension, list[bool]] = {}

        def _record(dimension: CapabilityDimension, passed: bool) -> None:
            tallies.setdefault(dimension, []).append(passed)

        connectivity_failures = 0
        last_failure: str | None = None

        for case in self._cases:
            for attempt in range(1, case.repeats + 1):
                started = time.monotonic()
                dimension_results: list[tuple[str, bool, str]] = []
                error_code: str | None = None
                response: dict[str, Any] | None = None
                try:
                    response = await self._analyze(dict(case.payload))
                except Exception as err:  # noqa: BLE001 - classified below
                    error_code = str(getattr(err, "code", "") or type(err).__name__)
                latency_ms = int((time.monotonic() - started) * 1000)

                if error_code is not None:
                    last_failure = error_code
                    if error_code in _CONNECTIVITY_FAILURES:
                        connectivity_failures += 1
                    _record(CapabilityDimension.CONNECTIVITY,
                            error_code not in _CONNECTIVITY_FAILURES)
                    failed = _ERROR_DIMENSION.get(
                        error_code, CapabilityDimension.STRUCTURED_OUTPUT
                    )
                    _record(failed, False)
                    dimension_results.append((failed.value, False, error_code))
                    # A run that never produced a response falsifies exactly one
                    # dimension. Marking the others failed too would let a single
                    # timeout look like a model that cannot format JSON.
                    runs.append(
                        ProbeRun(case.probe_id, attempt, False, latency_ms, error_code,
                                 tuple(dimension_results))
                    )
                    continue

                assert response is not None
                _record(CapabilityDimension.CONNECTIVITY, True)
                # Reaching here means HAMIE's parse, schema and semantic stages
                # all accepted the response.
                _record(CapabilityDimension.STRUCTURED_OUTPUT, True)
                _record(CapabilityDimension.SEMANTIC_VALIDITY, True)
                dimension_results.append((CapabilityDimension.STRUCTURED_OUTPUT.value, True, "parsed and schema-valid"))
                dimension_results.append((CapabilityDimension.SEMANTIC_VALIDITY.value, True, "passed semantic validation"))

                characters = len(str(response))
                within = characters <= 4 * int(
                    case.payload["budgets"]["maximum_response_tokens"]
                )
                _record(CapabilityDimension.BOUNDEDNESS, within)
                dimension_results.append(
                    (CapabilityDimension.BOUNDEDNESS.value, within, f"{characters} chars")
                )

                for expectation in case.expectations:
                    passed, detail = expectation.check(response, case)
                    _record(expectation.dimension, passed)
                    dimension_results.append((expectation.dimension.value, passed, detail))
                    if not passed:
                        last_failure = f"{expectation.dimension.value}:{detail}"

                runs.append(
                    ProbeRun(case.probe_id, attempt, True, latency_ms, None,
                             tuple(dimension_results), characters)
                )

        dimensions = tuple(
            DimensionResult(dimension, len(values), sum(1 for v in values if v))
            for dimension, values in sorted(tallies.items(), key=lambda kv: kv[0].value)
        )
        repeated = [case for case in self._cases if case.repeats > 1]
        if repeated:
            consistent = _repeatability(runs, repeated)
            dimensions = (*dimensions, consistent)

        outcomes: dict[str, list[int]] = {}
        for run in runs:
            tally = outcomes.setdefault(run.probe_id, [0, 0])
            tally[0] += 1
            expectations_passed = all(
                passed for _name, passed, _detail in run.dimension_results
            )
            if run.succeeded and expectations_passed:
                tally[1] += 1

        by_kind: dict[ContradictionKind, list[int]] = {
            ContradictionKind.RESOLVABLE: [0, 0],
            ContradictionKind.UNRESOLVABLE: [0, 0],
        }
        case_kind = {c.probe_id: c.contradiction_kind for c in self._cases}
        for run in runs:
            kind = case_kind.get(run.probe_id)
            if kind is None:
                continue
            for name, passed, _detail in run.dimension_results:
                if name == CapabilityDimension.CONTRADICTION_HANDLING.value:
                    by_kind[kind][0] += 1
                    by_kind[kind][1] += int(passed)

        connectivity_ok = connectivity_failures < len(runs) if runs else False
        verdict, reasons = compute_verdict(dimensions, connectivity_ok=connectivity_ok)
        return CapabilityResult(
            schema_version=CAPABILITY_SCHEMA_VERSION,
            provider=provider,
            model=model,
            configuration_fingerprint=configuration_fingerprint,
            probed_at=self._clock(),
            verdict=verdict,
            reasons=reasons,
            dimensions=dimensions,
            probes_attempted=len(runs),
            probes_passed=sum(1 for run in runs if run.succeeded),
            latencies_ms=tuple(run.latency_ms for run in runs),
            last_failure_category=last_failure,
            probe_outcomes=tuple(
                (pid, a, p) for pid, (a, p) in sorted(outcomes.items())
            ),
            contradiction_resolvable=tuple(by_kind[ContradictionKind.RESOLVABLE]),
            contradiction_unresolvable=tuple(by_kind[ContradictionKind.UNRESOLVABLE]),
            runs=tuple(runs),
        )


def _repeatability(runs: tuple[ProbeRun, ...] | list[ProbeRun], repeated: list[ProbeCase]) -> DimensionResult:
    """Did repeated runs of the same probe agree?

    One lucky valid response is not capability. A probe counts as repeatable
    only when every attempt of it reached the same success/failure outcome.
    """
    attempted = 0
    passed = 0
    for case in repeated:
        outcomes = [run.succeeded for run in runs if run.probe_id == case.probe_id]
        if len(outcomes) < 2:
            continue
        attempted += 1
        if all(outcomes) or not any(outcomes):
            passed += 1
    return DimensionResult(CapabilityDimension.REPEATABILITY, attempted, passed)
