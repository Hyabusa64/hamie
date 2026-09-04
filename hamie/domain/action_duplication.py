"""Duplicate-automation-action detection (repair-orchestration Phase 8).

Answers a question no analyzer in this codebase answers today: "do two
automations/scripts produce the same real-world effect?" Deliberately
never compares automation *names* -- the real incident this module
generalizes (three differently-named automations: two exact-duplicate
versions plus an unrelated-looking "Dock Manager 2.4" all firing the
same dock-notification action) would have been invisible to a
name-similarity check and was only found by comparing normalized
*effect*.

Pure and I/O-free like every other ``domain/`` module: it takes already-
parsed automation/script action bodies (e.g. from
``infrastructure/source_definition_index.py``'s ``raw_files`` +
``parse_config_yaml``), not a live ``hass`` object.

Classification is deliberately conservative. Only an ``EXACT_DUPLICATE``
verdict is ever a candidate for automatic consolidation, and even then
only when exactly one of the two definitions can be identified as the
sole authoritative implementation (see ``identify_authoritative``) --
everything else stays ``OPERATOR_DECISION_REQUIRED`` in the repair
orchestration layer. The real precedent this generalizes needed human
judgement to tell "fully redundant" from "same purpose, different
detail" (one duplicate carried an unrelated announcement worth keeping);
this module does not attempt that judgement call, it only proves
byte-identical effect where it genuinely exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .common import canonical_json, require_non_empty, stable_digest

#: Keys inside a service/action call's ``data``/``data_template`` mapping
#: that vary between otherwise-identical calls without changing whether
#: two automations are "doing the same thing" in the sense this module
#: cares about (e.g. a human-readable title that differs only in wording
#: while the notification still targets the same device with the same
#: urgency). Deliberately short and conservative: an unrecognised key is
#: always significant, never silently dropped.
_INSIGNIFICANT_DATA_KEYS = frozenset({"title"})


class ActionDuplicationVerdict(StrEnum):
    """How two automations'/scripts' normalized actions relate.

    Ordered by how safe it is to act on the finding: only
    ``EXACT_DUPLICATE`` is ever eligible for automatic consolidation.
    """

    #: Identical target, operation, and significant parameters.
    EXACT_DUPLICATE = "exact_duplicate"
    #: Same target and operation, but at least one significant parameter
    #: differs (e.g. two volume-cap automations capping to different
    #: values) -- or one side has additional actions the other lacks.
    OVERLAPPING_DUPLICATE = "overlapping_duplicate"
    #: Same target, operations that plausibly fight each other (e.g. one
    #: turns a switch on, the other off) rather than merely duplicating.
    POTENTIALLY_CONFLICTING = "potentially_conflicting"


@dataclass(frozen=True, slots=True)
class NormalizedAction:
    """One service/action call's effect, stripped of insignificant detail."""

    service: str
    target_entities: tuple[str, ...]
    significant_data: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        require_non_empty(self.service, "service")
        object.__setattr__(self, "target_entities", tuple(sorted(self.target_entities)))
        object.__setattr__(self, "significant_data", tuple(sorted(self.significant_data)))

    @property
    def join_key(self) -> tuple[str, ...]:
        """What this action is "aimed at", for deciding whether two actions
        are even worth comparing.

        Falls back to the service name itself when there is no explicit
        entity target -- the common shape for ``notify.*`` calls, where
        each recipient is its own service (``notify.mobile_app_alice``)
        rather than an ``entity_id``/``target`` field. Without this
        fallback, two automations that both notify the same device would
        never be compared at all, because neither has any
        ``target_entities``.
        """
        return self.target_entities or (self.service,)

    @property
    def effect_digest(self) -> str:
        """Identity used to decide whether two actions are byte-for-byte equal."""
        return stable_digest(self.service, self.target_entities, self.significant_data)


@dataclass(frozen=True, slots=True)
class AutomationActionProfile:
    """One automation/script's normalized action set, ready to compare."""

    entity_id: str
    unique_id: str
    actions: tuple[NormalizedAction, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.entity_id, "entity_id")
        require_non_empty(self.unique_id, "unique_id")


@dataclass(frozen=True, slots=True)
class ActionDuplicationFinding:
    """One pair of automations found to share at least one normalized effect."""

    left_entity_id: str
    right_entity_id: str
    verdict: ActionDuplicationVerdict
    shared_effect_keys: tuple[str, ...]
    rationale: str
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_non_empty(self.left_entity_id, "left_entity_id")
        require_non_empty(self.right_entity_id, "right_entity_id")
        if self.left_entity_id == self.right_entity_id:
            raise ValueError("a finding must compare two distinct automations")
        if not self.shared_effect_keys:
            raise ValueError("a duplication finding requires at least one shared effect")
        # Canonical, order-independent pair identity: the same pair must
        # never appear as both (A, B) and (B, A).
        if self.left_entity_id > self.right_entity_id:
            raise ValueError(
                "left_entity_id must sort before right_entity_id; use "
                "compare_profiles(), which enforces this, rather than "
                "constructing ActionDuplicationFinding directly"
            )

    @property
    def pair_id(self) -> str:
        return stable_digest(self.left_entity_id, self.right_entity_id)


def normalize_actions(raw_actions: Any) -> tuple[NormalizedAction, ...]:
    """Extract normalized effects from a parsed automation/script's action list.

    ``raw_actions`` is whatever
    ``infrastructure/source_definition_index.py``'s ``parse_config_yaml``
    produced for the ``action:``/``sequence:`` key of one automation or
    script -- untrusted, possibly malformed YAML content, never a typed
    structure. Anything not shaped like a plain service/action call
    (a template-driven action, a `repeat:`/`choose:` block, a `delay:`)
    is skipped rather than guessed at: a normalized action this module
    did not confidently extract is not represented as "no action" (which
    would wrongly suggest two automations do nothing), it is simply
    absent from the comparison, so the caller's evidence never claims
    more than was actually understood.
    """
    if not isinstance(raw_actions, list):
        raw_actions = [raw_actions] if isinstance(raw_actions, dict) else []

    normalized: list[NormalizedAction] = []
    for step in raw_actions:
        if not isinstance(step, dict):
            continue
        service = step.get("service") or step.get("action")
        if not isinstance(service, str) or not service.strip():
            continue
        target_entities = _extract_target_entities(step)
        data = step.get("data") or step.get("data_template") or {}
        if not isinstance(data, dict):
            data = {}
        significant_data = tuple(
            (str(key), canonical_json(value))
            for key, value in sorted(data.items())
            if key not in _INSIGNIFICANT_DATA_KEYS
        )
        normalized.append(
            NormalizedAction(
                service=service.strip(),
                target_entities=target_entities,
                significant_data=significant_data,
            )
        )
    return tuple(normalized)


def _extract_target_entities(step: dict) -> tuple[str, ...]:
    entities: set[str] = set()
    for source in (step.get("target"), step):
        if not isinstance(source, dict):
            continue
        raw = source.get("entity_id")
        if isinstance(raw, str):
            entities.add(raw)
        elif isinstance(raw, list):
            entities.update(item for item in raw if isinstance(item, str))
    return tuple(sorted(entities))


def compare_profiles(
    left: AutomationActionProfile, right: AutomationActionProfile
) -> ActionDuplicationFinding | None:
    """Compare two automations' normalized actions.

    Returns ``None`` when they share no effect at all (the overwhelming
    majority of pairs) -- callers should only ever see a finding for
    pairs actually worth looking at, never a "no relationship" record.
    """
    if left.entity_id == right.entity_id:
        raise ValueError("cannot compare an automation against itself")
    # Canonical order so the same unordered pair never produces two
    # differently-labelled findings.
    if left.entity_id > right.entity_id:
        left, right = right, left

    left_by_join: dict[tuple[str, ...], list[NormalizedAction]] = {}
    for action in left.actions:
        left_by_join.setdefault(action.join_key, []).append(action)
    right_by_join: dict[tuple[str, ...], list[NormalizedAction]] = {}
    for action in right.actions:
        right_by_join.setdefault(action.join_key, []).append(action)

    shared_keys = sorted(set(left_by_join) & set(right_by_join))
    if not shared_keys:
        return None

    exact_keys: list[tuple[str, ...]] = []
    differing_keys: list[tuple[str, ...]] = []
    conflicting_keys: list[tuple[str, ...]] = []
    for key in shared_keys:
        # Multiple actions can share one join key within an automation
        # (rare); comparing every pair on both sides is still bounded --
        # join groups are small by construction (one target/service).
        pair_verdicts: set[str] = set()
        for la in left_by_join[key]:
            for ra in right_by_join[key]:
                if la.service != ra.service:
                    pair_verdicts.add("conflicting")
                elif la.effect_digest == ra.effect_digest:
                    pair_verdicts.add("exact")
                else:
                    pair_verdicts.add("differing")
        if "conflicting" in pair_verdicts:
            conflicting_keys.append(key)
        elif "differing" in pair_verdicts:
            differing_keys.append(key)
        else:
            exact_keys.append(key)

    left_extra = bool(set(left_by_join) - set(shared_keys))
    right_extra = bool(set(right_by_join) - set(shared_keys))

    if conflicting_keys:
        verdict = ActionDuplicationVerdict.POTENTIALLY_CONFLICTING
        rationale = (
            f"{left.entity_id} and {right.entity_id} act on the same "
            "target via different services that were not confirmed "
            "compatible -- review by hand."
        )
    elif exact_keys and not differing_keys and not left_extra and not right_extra:
        verdict = ActionDuplicationVerdict.EXACT_DUPLICATE
        rationale = (
            f"{left.entity_id} and {right.entity_id} call the identical "
            f"service(s) against the identical target(s) with identical "
            "parameters, and neither has any additional action -- the "
            "same shape as the real incident this detector generalizes "
            "(multiple automations independently producing one dock/"
            "volume/notification effect)."
        )
    elif exact_keys or differing_keys:
        verdict = ActionDuplicationVerdict.OVERLAPPING_DUPLICATE
        rationale = (
            f"{left.entity_id} and {right.entity_id} both act on the same "
            f"target(s) via the same service(s), but "
            + (
                "differ in a significant parameter -- verify by hand "
                "whether one is simply stale before consolidating."
                if differing_keys
                else "at least one side has an additional action the "
                "other lacks -- this may be intentional (e.g. one "
                "automation also announces something unrelated), so "
                "consolidation needs a human decision."
            )
        )
    else:
        # Unreachable: every shared key was classified into conflicting,
        # exact, or differing above, and conflicting is handled first --
        # kept as a fail-closed guard rather than trusting that invariant
        # silently.
        raise AssertionError("unclassified shared join key(s); this is a bug")

    return ActionDuplicationFinding(
        left_entity_id=left.entity_id,
        right_entity_id=right.entity_id,
        verdict=verdict,
        shared_effect_keys=tuple("/".join(key) for key in shared_keys),
        rationale=rationale,
        evidence=(
            f"left_unique_id:{left.unique_id}",
            f"right_unique_id:{right.unique_id}",
        ),
    )


def detect_duplicate_actions(
    profiles: tuple[AutomationActionProfile, ...],
) -> tuple[ActionDuplicationFinding, ...]:
    """Pairwise-compare every profile that shares at least one target entity.

    Bounded to pairs sharing a target rather than a full O(n^2) scan over
    every automation in the house: two automations with no common target
    entity cannot be duplicating an effect on anything, by construction,
    so they are never compared at all -- this keeps the method usable on
    a real installation's automation count without an artificial cap
    that could silently hide a real duplicate.
    """
    by_target: dict[tuple[str, ...], list[AutomationActionProfile]] = {}
    for profile in profiles:
        join_keys = {action.join_key for action in profile.actions}
        for key in join_keys:
            by_target.setdefault(key, []).append(profile)

    seen_pairs: set[tuple[str, str]] = set()
    findings: list[ActionDuplicationFinding] = []
    for candidates in by_target.values():
        for i, left in enumerate(candidates):
            for right in candidates[i + 1 :]:
                pair = tuple(sorted((left.entity_id, right.entity_id)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                finding = compare_profiles(left, right)
                if finding is not None:
                    findings.append(finding)
    return tuple(sorted(findings, key=lambda f: (f.left_entity_id, f.right_entity_id)))


def identify_authoritative(
    finding: ActionDuplicationFinding,
    *,
    left_reference_count: int,
    right_reference_count: int,
    left_source_definition_missing: bool | None,
    right_source_definition_missing: bool | None,
) -> str | None:
    """Which side (if either) is provably the sole authoritative implementation.

    Returns the entity_id to KEEP, or ``None`` if the choice is not
    provable from the given evidence -- callers must treat ``None`` as
    OPERATOR_DECISION_REQUIRED, never as "keep the first one arbitrarily."

    Only defined for ``EXACT_DUPLICATE``: a consolidation candidate for
    any other verdict is exactly the ambiguity this module refuses to
    resolve on its own.
    """
    if finding.verdict is not ActionDuplicationVerdict.EXACT_DUPLICATE:
        return None
    # A side whose YAML/package definition is confirmed gone cannot be
    # the one to keep, regardless of anything else.
    left_gone = left_source_definition_missing is True
    right_gone = right_source_definition_missing is True
    if left_gone and not right_gone:
        return finding.right_entity_id
    if right_gone and not left_gone:
        return finding.left_entity_id
    if left_gone and right_gone:
        return None  # both gone is not this module's problem to resolve
    # Neither definition is confirmed missing: reference count alone is
    # never sufficient authority to choose (zero references does not
    # mean unused -- see domain/temporal_evidence.py's documented
    # 7-day-retention limitation), so an equal or ambiguous count stays
    # undecided.
    if left_reference_count > 0 and right_reference_count == 0:
        return finding.left_entity_id
    if right_reference_count > 0 and left_reference_count == 0:
        return finding.right_entity_id
    return None
