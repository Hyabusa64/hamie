"""Consult durable knowledge from a live scan (mission Part 11/52).

Persistence alone does not make HAMIE learn anything -- a knowledge
record only has value once a future scan actually asks it "have you
seen this before?" This module is that question, asked two ways:

- ``consult_entity_successor``: "is this stale entity id a known,
  currently-active successor relationship?"
- ``consult_implementation_group``: "does this exact set of members
  match a known, currently-active implementation group?"

Both functions are conservative in the same direction: they only ever
return a match for a relationship/group whose ``status``/identity is
still current. A ``SUPERSEDED``/``INVALIDATED``/``CONFLICTING``/
``PENDING_REVALIDATION`` record is deliberately never treated as
confirming knowledge (mission Part 52: "live identity evidence takes
precedence over stale cached conclusions") -- a caller who wants to
know about those non-active records can inspect the raw tuples
directly; these two functions answer only "can I currently trust this."

Pure and I/O-free like every other ``domain/`` module: callers own
loading the known-knowledge tuples from the repository and pass them
in.
"""

from __future__ import annotations

from .implementation_groups import ImplementationGroup
from .successors import EntitySuccessorRelationship, SuccessorStatus


def consult_entity_successor(
    stale_entity_id: str,
    known_successors: tuple[EntitySuccessorRelationship, ...],
    *,
    canonical_entity_id: str | None = None,
) -> EntitySuccessorRelationship | None:
    """Return the active known successor relationship for ``stale_entity_id``.

    When ``canonical_entity_id`` is given, a match additionally requires
    the known relationship's canonical id to agree -- a caller who
    already independently identified a candidate successor can confirm
    it matches recorded knowledge exactly, rather than accepting
    whatever HAMIE previously recorded for the same stale id (which
    could, in principle, point elsewhere if evidence conflicted; see
    ``SuccessorStatus.CONFLICTING``).
    """
    for relationship in known_successors:
        if relationship.stale_entity_id != stale_entity_id:
            continue
        if relationship.status is not SuccessorStatus.ACTIVE:
            continue
        if (
            canonical_entity_id is not None
            and relationship.canonical_entity_id != canonical_entity_id
        ):
            continue
        return relationship
    return None


def consult_implementation_group(
    member_entity_ids: tuple[str, ...],
    known_groups: tuple[ImplementationGroup, ...],
) -> ImplementationGroup | None:
    """Return the known implementation group matching this exact member set.

    Exact-set matching only (never a subset/superset/partial overlap
    match) -- a group whose recorded membership no longer matches
    exactly is precisely the "membership changed, reopen for review"
    signal mission Part 23 describes; silently matching a shrunk or
    grown set would hide that signal instead of surfacing it. A caller
    that gets ``None`` back for a set that plausibly overlaps a known
    group should treat the group as needing revalidation, not assume
    no knowledge exists.
    """
    candidate = frozenset(member_entity_ids)
    if len(candidate) < 2:
        return None
    for group in known_groups:
        if frozenset(group.members) == candidate:
            return group
    return None
