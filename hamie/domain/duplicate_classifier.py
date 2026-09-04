"""Suffix-duplicate / migration-leftover group classifier (mission Part 3c).

Home Assistant appends ``_2``, ``_3``, ... to an entity's object_id
only when a *new* entity would otherwise collide with one already in
the registry -- never as a semantic signal about the two entities'
relationship. A ``foo``/``foo_2`` pair can be: the same physical device
re-added under a new integration/config entry (the common "migration
leftover" case a house accumulates over years of re-pairing hardware),
two genuinely distinct devices whose auto-generated names happened to
collide (e.g. two identical smart plugs both named "Plug"), or a
partially-completed rename where some automations/dashboards still
reference the old id.

This module never uses the suffix itself as evidence -- only as the
*grouping* key (``group_suffix_siblings``). Every classification
decision in ``classify_duplicate_group`` is driven by the actual
identity/lifecycle signals the mission specifies: unique_id, platform,
config_entry_id, device_id, area_id, current state/availability,
reference counts, and (for automation/script/scene) source-definition
ownership from ``infrastructure/source_definition_index.py``.

Pure and I/O-free like every other ``domain/`` module: every input is
already computed by a caller (the entity registry snapshot, the
reference index, the source-definition index); this module only
applies deterministic rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .common import require_non_empty

_SUFFIX_RE = re.compile(r"^(?P<base>.+)_(?P<suffix>\d+)$")


class DuplicateGroupClassification(StrEnum):
    """Every suffix-duplicate group lands in exactly one of these."""

    LIKELY_MIGRATION_LEFTOVER = "likely_migration_leftover"
    LIKELY_DISTINCT_ENTITIES = "likely_distinct_entities"
    ACTIVE_OLD_ID_WITH_NEW_SIBLING = "active_old_id_with_new_sibling"
    BROKEN_REFERENCE_TO_OLD_SIBLING = "broken_reference_to_old_sibling"
    AMBIGUOUS_DUPLICATE_GROUP = "ambiguous_duplicate_group"


@dataclass(frozen=True, slots=True)
class DuplicateGroupMember:
    """Everything the classifier needs about one entity in a suffix group."""

    entity_id: str
    unique_id: str | None
    platform: str | None
    config_entry_id: str | None
    device_id: str | None
    area_id: str | None
    disabled: bool
    available: bool | None  # None = current availability not captured
    referenced_by_count: int
    # ISO 8601 registry creation timestamp when known -- the real
    # ordering signal (not the suffix number, which only ever reflects
    # a collision-avoidance counter, not creation order across
    # deletions/re-registrations).
    created_at: str | None = None
    # Only meaningful for automation/script/scene members -- None for
    # every other domain (this classifier is not limited to those three
    # domains; suffix collisions happen across any domain).
    source_definition_missing: bool | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.entity_id, "entity_id")
        if self.referenced_by_count < 0:
            raise ValueError("referenced_by_count cannot be negative")

    @property
    def is_orphaned_or_dead(self) -> bool:
        """Return whether this member looks like a leftover, not a live entity.

        Deliberately conservative (all must line up): disabled AND
        (known-unavailable OR a confirmed-missing source definition)
        AND unreferenced. A member with any signal pointing the other
        way (still available, still referenced, or its definition
        status is simply unknown) is never treated as dead.
        """
        return (
            self.disabled
            and (self.available is False or self.source_definition_missing is True)
            and self.referenced_by_count == 0
        )

    @property
    def is_clearly_alive(self) -> bool:
        """Return whether this member looks actively in use."""
        return (
            not self.disabled
            and self.available is not False
            and (self.available is True or self.referenced_by_count > 0)
        )


@dataclass(frozen=True, slots=True)
class DuplicateGroupDecision:
    """One classification result for one suffix-duplicate group."""

    group_key: str
    classification: DuplicateGroupClassification
    rationale: str
    member_entity_ids: tuple[str, ...]
    primary_entity_id: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.group_key, "group_key")
        require_non_empty(self.rationale, "rationale")
        if len(self.member_entity_ids) < 2:
            raise ValueError("a duplicate group decision requires 2+ members")
        object.__setattr__(
            self, "member_entity_ids", tuple(sorted(set(self.member_entity_ids)))
        )


def group_suffix_siblings(entity_ids: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """Group ``foo``/``foo_2``/``foo_3``-style entity ids by their shared base.

    Pure grouping only -- returns every base with 2+ members (a bare
    ``foo`` counts as a member of its own group when it coexists with
    at least one numbered sibling). A base with only a single ``_N``
    member and no bare/other sibling is not returned: that is simply
    one entity whose object_id happens to end in a digit, not a
    duplicate group.

    Zero-padded numeric suffixes (``_001``, ``_02``, ...) are never
    treated as Home Assistant's own collision-avoidance convention
    (mission Part 6 / false-positive suppression): HA's real
    ``_2``/``_3``/.../``_10``/``_11`` suffix generator never zero-pads
    -- a zero-padded tail is a channel/zone/index number some other
    integration's own naming scheme chose (observed this session on a
    12-outlet Matter power strip and MQTT LED-strip segments), and
    grouping e.g. ``light.strip_001``..``light.strip_020`` as one
    20-member "duplicate group" would be a dangerous false positive a
    naive digit-suffix regex alone cannot avoid.
    """
    all_ids = set(entity_ids)
    bases: dict[str, list[str]] = {}
    for entity_id in entity_ids:
        domain, _, object_id = entity_id.partition(".")
        match = _SUFFIX_RE.match(object_id)
        if match is None:
            continue
        suffix = match.group("suffix")
        if len(suffix) > 1 and suffix.startswith("0"):
            continue
        base_entity_id = f"{domain}.{match.group('base')}"
        bases.setdefault(base_entity_id, []).append(entity_id)

    groups: dict[str, tuple[str, ...]] = {}
    for base_entity_id, siblings in bases.items():
        members = set(siblings)
        if base_entity_id in all_ids:
            members.add(base_entity_id)
        if len(members) >= 2:
            groups[base_entity_id] = tuple(sorted(members))
    return groups


def classify_duplicate_group(
    group_key: str, members: tuple[DuplicateGroupMember, ...]
) -> DuplicateGroupDecision:
    """Classify one suffix-duplicate group. Never raises for an ordinary reason."""
    require_non_empty(group_key, "group_key")
    if len(members) < 2:
        raise ValueError("a duplicate group requires 2 or more members")
    member_ids = tuple(sorted({item.entity_id for item in members}))

    def _decision(
        classification: DuplicateGroupClassification,
        rationale: str,
        *,
        primary: str | None = None,
    ) -> DuplicateGroupDecision:
        return DuplicateGroupDecision(
            group_key=group_key,
            classification=classification,
            rationale=rationale,
            member_entity_ids=member_ids,
            primary_entity_id=primary,
        )

    alive = [item for item in members if item.is_clearly_alive]
    dead = [item for item in members if item.is_orphaned_or_dead]
    undetermined = [
        item for item in members if item not in alive and item not in dead
    ]

    # Exactly one clearly-alive member and every other member looks
    # dead: the textbook migration-leftover shape -- one current
    # entity, N abandoned prior registrations of "the same thing".
    if len(alive) == 1 and len(dead) == len(members) - 1 and not undetermined:
        return _decision(
            DuplicateGroupClassification.LIKELY_MIGRATION_LEFTOVER,
            f"{len(dead)} of {len(members)} member(s) are disabled, unavailable "
            "or definition-confirmed-missing, and unreferenced; exactly one "
            f"member ({alive[0].entity_id}) is actively in use -- looks like "
            "prior device/integration re-registrations left behind, not "
            "distinct hardware.",
            primary=alive[0].entity_id,
        )

    # Two or more members are independently, clearly alive: distinct
    # config_entry/device/area or independent references each --
    # genuinely different entities that happen to share a base name.
    if len(alive) >= 2:
        distinct_devices = {item.device_id for item in alive if item.device_id}
        distinct_config_entries = {
            item.config_entry_id for item in alive if item.config_entry_id
        }
        distinct_areas = {item.area_id for item in alive if item.area_id}
        if (
            len(distinct_devices) > 1
            or len(distinct_config_entries) > 1
            or len(distinct_areas) > 1
        ):
            return _decision(
                DuplicateGroupClassification.LIKELY_DISTINCT_ENTITIES,
                f"{len(alive)} members are all actively in use and back onto "
                "distinct devices/config entries/areas -- a name collision "
                "between genuinely separate entities, not a duplicate to "
                "clean up.",
            )
        # Multiple alive members with no distinguishing device/area/config
        # signal at all is exactly the case that must not be guessed --
        # fall through to AMBIGUOUS rather than picking a side.

    # The lowest-suffix ("old") member is still clearly alive and a
    # higher-suffix ("new") sibling also exists and is alive: the old
    # id is still doing real work despite a newer sibling's existence.
    ordered_by_creation = sorted(
        members, key=lambda item: (item.created_at is None, item.created_at or "")
    )
    oldest = ordered_by_creation[0]
    newest = ordered_by_creation[-1]
    if (
        oldest.entity_id != newest.entity_id
        and oldest.created_at is not None
        and newest.created_at is not None
        and oldest.is_clearly_alive
        and newest.is_clearly_alive
    ):
        return _decision(
            DuplicateGroupClassification.ACTIVE_OLD_ID_WITH_NEW_SIBLING,
            f"the oldest member ({oldest.entity_id}, created {oldest.created_at}) "
            f"is still actively in use even though a newer sibling "
            f"({newest.entity_id}, created {newest.created_at}) also exists and "
            "is active -- likely still depended on; do not assume the older id "
            "is safe to retire.",
            primary=oldest.entity_id,
        )

    # A disabled/unavailable member still has live references pointing
    # at it while a sibling is the one actually working: a rename/
    # migration left a dangling pointer at the old id. Deliberately
    # checked over *all* non-alive members (dead + undetermined), not
    # only ``dead`` -- ``is_orphaned_or_dead`` requires zero references
    # by definition (a referenced entity is never "dead"), so this is
    # the one place a disabled-but-still-referenced member is
    # recognised on its own terms rather than needing to first qualify
    # as fully "dead".
    dangling = [
        item
        for item in members
        if item not in alive
        and item.referenced_by_count > 0
        and (item.disabled or item.available is False)
    ]
    if dangling and alive:
        return _decision(
            DuplicateGroupClassification.BROKEN_REFERENCE_TO_OLD_SIBLING,
            f"{dangling[0].entity_id} is disabled/unavailable but still has "
            f"{dangling[0].referenced_by_count} live reference(s) pointing at "
            f"it, while {alive[0].entity_id} is the sibling actually in use "
            "-- likely a rename left a dangling reference to the old id.",
            primary=alive[0].entity_id,
        )

    return _decision(
        DuplicateGroupClassification.AMBIGUOUS_DUPLICATE_GROUP,
        f"{len(alive)} alive, {len(dead)} dead, {len(undetermined)} undetermined "
        f"among {len(members)} members -- no single rule above matched "
        "confidently; needs a human look rather than a guess.",
    )


# ---------------------------------------------------------------------------
# Version-bump self-reference regression detector (mission Part 2, Analyzer
# 1) -- the highest-value new check, formalizing the pattern found 3x this
# session by hand (kitchen-cleaning, vacuum-status, water-goal-percentage):
# a package's unique_id is bumped to a new version string in-place, the OLD
# unique_id's entity_id (the base slug) goes dead, a NEW `_2`/`_3` sibling
# takes over the live unique_id -- but the SAME package's own Jinja/YAML
# logic still references the now-dead base slug, breaking real automation
# with zero errors logged (is_state()/numeric_state on an unavailable
# entity fails silently). Distinct from LIKELY_MIGRATION_LEFTOVER: that
# classification only looks at registry lifecycle signals (disabled/
# available/referenced), never at whether the *current* live source text
# still points at the dead member -- this function is the one place that
# textual self-reference is actually checked.
# ---------------------------------------------------------------------------

_VERSION_DIGIT_RE = re.compile(r"\d+")


def _version_tokens(unique_id: str) -> tuple[int, ...] | None:
    """Extract a comparable numeric version signature from a unique_id.

    Returns ``None`` when no digit run exists at all -- nothing to
    compare, never guessed. A unique_id with multiple digit runs (e.g.
    ``example_appliance_2024_02``) compares every run left-to-right, the
    same way a version tuple naturally orders.
    """
    digits = _VERSION_DIGIT_RE.findall(unique_id)
    if not digits:
        return None
    return tuple(int(value) for value in digits)


@dataclass(frozen=True, slots=True)
class SelfReferenceRegressionEvidence:
    """One confirmed version-bump self-reference regression."""

    group_key: str
    base_entity_id: str
    base_unique_id: str
    sibling_entity_id: str
    sibling_unique_id: str
    defining_file: str
    matched_snippet: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.group_key, "group_key"),
            (self.base_entity_id, "base_entity_id"),
            (self.sibling_entity_id, "sibling_entity_id"),
            (self.defining_file, "defining_file"),
        ):
            require_non_empty(value, name)


def detect_self_reference_regression(
    *,
    group_key: str,
    base_entity_id: str,
    base_unique_id: str | None,
    sibling_entity_id: str,
    sibling_unique_id: str | None,
    raw_files: dict[str, str] | None,
) -> SelfReferenceRegressionEvidence | None:
    """Detect the exact confirmed regression shape, or return ``None``.

    Requires **all** of (mission Part 2, Analyzer 1's (a)/(b)/(c)):

    (a) both unique_ids are known and the sibling's version token is
        strictly newer than the base's (``_version_tokens`` compares
        numerically, not lexicographically, so ``..._9`` correctly
        precedes ``..._10``);
    (b) some scanned config file's raw text literally contains the
        sibling's unique_id (it currently defines the sibling) but does
        **not** also contain the base's unique_id (the base's own prior
        definition is genuinely gone from this file, not merely
        duplicated) -- i.e. exactly a version bump *in place*, not two
        independently-still-defined entities;
    (c) that same file's raw text also literally contains the base
        entity_id string (e.g. ``vacuum.example_appliance``) -- the
        self-reference: the file's own logic still points at the now-
        dead base slug.

    Deliberately a plain substring search over already-read raw config
    text (``raw_files``, from
    ``infrastructure/source_definition_index.py``'s ``SourceDefinitionIndex.
    raw_files``) rather than a structured Jinja/YAML parse -- sufficient
    to prove the pattern this session actually found by hand three
    times, and conservative: a file that merely *mentions* both strings
    without evidence they are the version-bumped unique_id/its own dead
    reference (e.g. an unrelated comment) is a rare, tolerable false
    positive next to the alternative of silently missing a repeat of a
    confirmed real production bug.
    """
    if not raw_files or not sibling_unique_id or not base_unique_id:
        return None
    base_tokens = _version_tokens(base_unique_id)
    sibling_tokens = _version_tokens(sibling_unique_id)
    if base_tokens is None or sibling_tokens is None or sibling_tokens <= base_tokens:
        return None
    for path, content in sorted(raw_files.items()):
        if sibling_unique_id not in content or base_unique_id in content:
            continue
        index = content.find(base_entity_id)
        if index < 0:
            continue
        start = max(0, index - 60)
        end = min(len(content), index + len(base_entity_id) + 60)
        snippet = " ".join(content[start:end].split())
        return SelfReferenceRegressionEvidence(
            group_key=group_key,
            base_entity_id=base_entity_id,
            base_unique_id=base_unique_id,
            sibling_entity_id=sibling_entity_id,
            sibling_unique_id=sibling_unique_id,
            defining_file=path,
            matched_snippet=snippet[:240],
        )
    return None


# ---------------------------------------------------------------------------
# Abandoned bugfix fork detector (mission Part 2, Analyzer 5) -- the
# water_bill_estimate_2 / water_cost_today_2 / water_flow_gpm_2 pattern: a
# `_N` sibling whose own unique_id carries a distinguishing one-off marker
# AND has zero live source definition AND zero references. Deliberately
# never triggers on the suffix pattern alone (mission Part 6): both the
# marker match and the zero-source/zero-reference combination are required.
# ---------------------------------------------------------------------------

ABANDONED_FORK_MARKERS = frozenset(
    {
        "fixed",
        "fix",
        "temp",
        "tmp",
        "test",
        "copy",
        "backup",
        "bak",
        "draft",
        "wip",
        "old",
        "v2",
        "v3",
        "v4",
        "new",
        "retry",
        "scratch",
    }
)


@dataclass(frozen=True, slots=True)
class AbandonedForkEvidence:
    """One confirmed abandoned bugfix/experiment fork."""

    group_key: str
    fork_entity_id: str
    fork_unique_id: str
    matched_marker: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.group_key, "group_key"),
            (self.fork_entity_id, "fork_entity_id"),
            (self.fork_unique_id, "fork_unique_id"),
            (self.matched_marker, "matched_marker"),
        ):
            require_non_empty(value, name)


def detect_abandoned_bugfix_fork(
    *,
    group_key: str,
    member: DuplicateGroupMember,
    has_zero_source_definition: bool,
    has_recorder_activity_beyond_restart: bool | None = None,
) -> AbandonedForkEvidence | None:
    """Detect one abandoned one-off fix/experiment fork, or return ``None``.

    ``has_zero_source_definition`` and referenced-by-zero are both
    structurally required -- this is the exact "zero source + zero
    references" combination the mission requires, matching the proven
    safe/real cases exactly (never a plain suffix-pattern guess).
    ``has_recorder_activity_beyond_restart`` is an optional, honestly-
    sourced disqualifier: when a caller can positively confirm real
    (non-restart-heartbeat) recorder activity, that alone disqualifies
    the "abandoned" claim regardless of the marker/zero-reference
    evidence -- passing ``None`` (not evaluated) never blocks the
    finding, since HAMIE never requires evidence it cannot honestly
    obtain to reach a conservative, already-well-supported verdict.
    """
    if has_recorder_activity_beyond_restart:
        return None
    if member.referenced_by_count != 0 or not has_zero_source_definition:
        return None
    if not member.unique_id:
        return None
    tokens = set(re.split(r"[^a-z0-9]+", member.unique_id.casefold()))
    for marker in sorted(ABANDONED_FORK_MARKERS):
        if marker in tokens:
            return AbandonedForkEvidence(
                group_key=group_key,
                fork_entity_id=member.entity_id,
                fork_unique_id=member.unique_id,
                matched_marker=marker,
            )
    return None
