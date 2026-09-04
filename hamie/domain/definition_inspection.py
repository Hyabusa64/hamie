"""Structural inspection of an automation/script's own YAML definition.

Fills a real gap identified while building the repair-orchestration
layer: every existing read-only investigation tool
(``hamie_get_automation``/``hamie_get_script`` in ``hamie/llm.py``)
returns the entity's Home Assistant *state* view, never its
trigger/condition/action *definition* -- so a stale-entity-reference or
duplicate-action repair candidate has never had a way to see exactly
where inside an automation an entity id is used. This module answers
that, from already-read YAML text (no live ``hass`` object), the same
shape ``infrastructure/source_definition_index.py`` and
``domain/action_duplication.py`` already take.

Deliberately narrow: it locates one automation/script's own YAML
mapping by id (automation) or object id (script) inside already-read
package/top-level file content, and reports every entity/device/area
reference it can structurally find inside `trigger`/`condition`/
`action`/`sequence`, tagged with a JSON-pointer-style path so a
mutating tool (``replace_entity_reference_in_scope``) can target an
*exact* location rather than a blind file-wide substitution -- see
``docs/REPAIR_ORCHESTRATION.md``'s caution about a real prior mistake
where a blind substitution inverted a comment's meaning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .common import require_non_empty


@dataclass(frozen=True, slots=True)
class EntityReferenceLocation:
    """Exactly where one entity id appears inside a parsed definition."""

    entity_id: str
    path: str  # e.g. "action[0].target.entity_id" or "condition[1].entity_id"

    def __post_init__(self) -> None:
        require_non_empty(self.entity_id, "entity_id")
        require_non_empty(self.path, "path")


@dataclass(frozen=True, slots=True)
class DefinitionInspection:
    """One automation/script's parsed definition, ready for evidence or repair."""

    entity_id: str
    unique_id: str
    domain: str  # "automation" | "script"
    defining_file: str
    trigger: tuple[dict, ...]
    condition: tuple[dict, ...]
    action: tuple[dict, ...]
    references: tuple[EntityReferenceLocation, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.entity_id, "entity_id")
        require_non_empty(self.unique_id, "unique_id")
        require_non_empty(self.defining_file, "defining_file")
        if self.domain not in ("automation", "script"):
            raise ValueError(f"unsupported domain for definition inspection: {self.domain!r}")

    def references_to(self, target_entity_id: str) -> tuple[EntityReferenceLocation, ...]:
        return tuple(ref for ref in self.references if ref.entity_id == target_entity_id)


def _as_list(node: Any) -> list[dict]:
    if isinstance(node, list):
        return [item for item in node if isinstance(item, dict)]
    if isinstance(node, dict):
        return [node]
    return []


def find_automation_entry(document: Any, unique_id: str) -> dict | None:
    """Locate one automation's own mapping by its ``id:`` field.

    ``document`` is whatever ``parse_config_yaml`` returned for one
    already-read file. Handles both shapes real Home Assistant config
    uses: a package's ``automation:`` key holding a list (or single
    mapping), and a bare top-level ``automations.yaml`` list.
    """
    candidates: list[Any] = []
    if isinstance(document, dict) and "automation" in document:
        candidates.append(document["automation"])
    elif isinstance(document, list):
        candidates.append(document)
    for candidate in candidates:
        for entry in _as_list(candidate):
            if str(entry.get("id", "")) == unique_id:
                return entry
    return None


def find_script_entry(document: Any, object_id: str) -> dict | None:
    """Locate one script's own mapping by its object id (the dict key).

    Handles a package's ``script:`` key holding a mapping, and a bare
    top-level ``scripts.yaml`` mapping -- scripts are keyed by object
    id, not an internal ``id:`` field (unlike automations).
    """
    candidates: list[Any] = []
    if isinstance(document, dict) and "script" in document and isinstance(document["script"], dict):
        candidates.append(document["script"])
    elif isinstance(document, dict) and "automation" not in document and "script" not in document:
        candidates.append(document)
    for candidate in candidates:
        if isinstance(candidate, dict) and object_id in candidate:
            value = candidate[object_id]
            if isinstance(value, dict):
                return value
    return None


def _walk_references(node: Any, path: str, out: list[EntityReferenceLocation]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}"
            if key == "entity_id":
                if isinstance(value, str):
                    out.append(EntityReferenceLocation(entity_id=value, path=child_path))
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        if isinstance(item, str):
                            out.append(
                                EntityReferenceLocation(entity_id=item, path=f"{child_path}[{index}]")
                            )
            else:
                _walk_references(value, child_path, out)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _walk_references(item, f"{path}[{index}]", out)


def inspect_automation(
    document: Any, *, entity_id: str, unique_id: str, defining_file: str
) -> DefinitionInspection | None:
    """Build a ``DefinitionInspection`` for one automation, or ``None`` if not found."""
    entry = find_automation_entry(document, unique_id)
    if entry is None:
        return None
    return _build_inspection(
        entry, entity_id=entity_id, unique_id=unique_id, domain="automation", defining_file=defining_file
    )


def inspect_script(
    document: Any, *, entity_id: str, object_id: str, defining_file: str
) -> DefinitionInspection | None:
    """Build a ``DefinitionInspection`` for one script, or ``None`` if not found."""
    entry = find_script_entry(document, object_id)
    if entry is None:
        return None
    return _build_inspection(
        entry, entity_id=entity_id, unique_id=object_id, domain="script", defining_file=defining_file
    )


def _build_inspection(
    entry: dict, *, entity_id: str, unique_id: str, domain: str, defining_file: str
) -> DefinitionInspection:
    trigger = tuple(_as_list(entry.get("trigger") or entry.get("triggers")))
    condition = tuple(_as_list(entry.get("condition") or entry.get("conditions")))
    action = tuple(_as_list(entry.get("action") or entry.get("sequence")))

    references: list[EntityReferenceLocation] = []
    _walk_references(list(trigger), "trigger", references)
    _walk_references(list(condition), "condition", references)
    _walk_references(list(action), "action", references)

    return DefinitionInspection(
        entity_id=entity_id,
        unique_id=unique_id,
        domain=domain,
        defining_file=defining_file,
        trigger=trigger,
        condition=condition,
        action=action,
        references=tuple(
            sorted(references, key=lambda ref: (ref.path, ref.entity_id))
        ),
    )
