"""Pure YAML action-block scanner: `<domain>.<verb>` service calls plus
their target entity_id(s) (mission Part 2, Analyzer 3).

Answers "does this automation/script action call a service whose own
domain prefix matches the domain of the entity_id it targets, and if
so, does that target entity still exist and work" -- the wrong-domain
migrated action target pattern (found 1x this session, a real security
bug: a porch light's automation kept calling ``light.turn_on`` against
an entity_id that, after an integration migration, moved to
``switch.*`` -- the light entity is a class-2 removed-integration
orphan, but a naive "just fix the entity_id" repair would still be
broken because the service call's own verb domain also needs to change).

Deliberately a bounded regex/structural-YAML scan, not a full Home
Assistant service-schema validator (explicitly permitted by the
mission): ``scan_action_service_calls`` below only ever recognizes the
two conventional action shapes Home Assistant documents --
``service``/``action: <domain>.<verb>`` plus a sibling ``entity_id``
(the pre-2024.8 flat style) or ``target: {entity_id: ...}`` (the
current style) -- and never attempts to resolve templated entity_ids,
device_id/area_id targets, or blueprint-input indirection. Missing a
templated or indirect target is an honest false negative (this scanner
simply finds nothing there), never a false claim.

Pure and I/O-free: every input is already-parsed YAML (from
``infrastructure/source_definition_index.py::parse_config_yaml``, called
by a caller, never here).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .common import require_non_empty

_SERVICE_KEYS = ("action", "service")
_ENTITY_ID_KEY = "entity_id"
_TARGET_KEY = "target"
_SERVICE_PATTERN = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
MAX_CALLS_PER_DOCUMENT = 5_000


@dataclass(frozen=True, slots=True)
class ActionServiceCall:
    """One `<domain>.<verb>` service call plus one target entity_id,
    found in one action dict of one config file."""

    verb_domain: str
    verb_action: str
    target_entity_id: str
    defining_file: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.verb_domain, "verb_domain"),
            (self.verb_action, "verb_action"),
            (self.target_entity_id, "target_entity_id"),
            (self.defining_file, "defining_file"),
        ):
            require_non_empty(value, name)


def _entity_ids_from(value: object) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _walk(node: object, *, defining_file: str, out: list[ActionServiceCall]) -> None:
    if len(out) >= MAX_CALLS_PER_DOCUMENT:
        return
    if isinstance(node, dict):
        service_value: str | None = None
        for key in _SERVICE_KEYS:
            value = node.get(key)
            if isinstance(value, str) and _SERVICE_PATTERN.match(value):
                service_value = value
                break
        if service_value is not None:
            verb_domain, _, verb_action = service_value.partition(".")
            targets: list[str] = list(_entity_ids_from(node.get(_ENTITY_ID_KEY)))
            target_block = node.get(_TARGET_KEY)
            if isinstance(target_block, dict):
                targets.extend(_entity_ids_from(target_block.get(_ENTITY_ID_KEY)))
            for target in targets:
                if len(out) >= MAX_CALLS_PER_DOCUMENT:
                    return
                out.append(
                    ActionServiceCall(
                        verb_domain=verb_domain,
                        verb_action=verb_action,
                        target_entity_id=target,
                        defining_file=defining_file,
                    )
                )
        for value in node.values():
            _walk(value, defining_file=defining_file, out=out)
    elif isinstance(node, list):
        for item in node:
            _walk(item, defining_file=defining_file, out=out)


def scan_action_service_calls(
    documents: dict[str, object],
) -> tuple[ActionServiceCall, ...]:
    """Scan every already-parsed document for `<domain>.<verb>` action calls.

    ``documents`` is ``path -> parsed YAML`` (``None`` for a file that
    failed to parse -- silently skipped, never a reason to abort the
    other files, matching this codebase's established per-file
    degradation pattern).
    """
    out: list[ActionServiceCall] = []
    for path, document in sorted(documents.items()):
        if document is None:
            continue
        _walk(document, defining_file=path, out=out)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class WrongDomainActionEvidence:
    """One confirmed wrong-domain migrated action target."""

    defining_file: str
    verb_domain: str
    verb_action: str
    target_entity_id: str
    replacement_entity_id: str
    replacement_domain: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.defining_file, "defining_file"),
            (self.verb_domain, "verb_domain"),
            (self.target_entity_id, "target_entity_id"),
            (self.replacement_entity_id, "replacement_entity_id"),
        ):
            require_non_empty(value, name)


def detect_wrong_domain_action_target(
    call: ActionServiceCall,
    *,
    target_is_orphaned: bool,
    replacement_entity_id: str | None,
) -> WrongDomainActionEvidence | None:
    """Confirm one call is the wrong-domain migrated-action-target bug.

    Requires the call to be internally *self-consistent as written*
    (``call.target_entity_id``'s own domain matches ``call.verb_domain``
    -- the buggy automation was never edited, so both still agree with
    each other) **and** an independently-confirmed orphan
    (``target_is_orphaned``, from the caller's own removed-integration/
    availability check -- this function never re-derives that) **and** a
    live, alive replacement entity in a genuinely *different* domain
    with the same object_id (``replacement_entity_id``, also supplied
    by the caller). Never guesses a replacement itself -- a caller that
    could not confidently find exactly one live same-object_id sibling
    in another domain should pass ``None``, which this function treats
    as insufficient evidence rather than a partial match.
    """
    if call.target_entity_id.partition(".")[0] != call.verb_domain:
        return None
    if not target_is_orphaned or not replacement_entity_id:
        return None
    replacement_domain = replacement_entity_id.partition(".")[0]
    if replacement_domain == call.verb_domain:
        return None
    return WrongDomainActionEvidence(
        defining_file=call.defining_file,
        verb_domain=call.verb_domain,
        verb_action=call.verb_action,
        target_entity_id=call.target_entity_id,
        replacement_entity_id=replacement_entity_id,
        replacement_domain=replacement_domain,
    )
