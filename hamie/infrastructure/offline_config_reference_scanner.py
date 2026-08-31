"""Offline, file-content-based entity-reference scanner (mission Part 3b/4).

``infrastructure/dependency_source.py`` is genuinely comprehensive for a
*live* Home Assistant process -- it already covers automation/script
``referenced_entities``, scene/group state-attribute entity lists,
explicit-source helpers, template-tracked entities, the Energy
dashboard, and Lovelace dashboards (``capture_dashboard_references``
reads ``hass.data[LOVELACE_DATA].dashboards``, which *is* how a live
process's storage-mode dashboards -- the same ``.storage/lovelace*``
files this module reads directly -- are exposed once loaded). None of
that is duplicated here: every one of those signals genuinely requires
a live ``hass`` object (HA's own already-computed
``referenced_entities`` cached_property, the live Lovelace dashboard
registry, a live template tracker, ...), and this task has no live HA
Python process to run or test that code against (see the mission's
absolute constraints).

What this module adds is the offline equivalent needed to run Mode B
(``benchmark/run_mode_b_live_validation.py``) against a read-only
snapshot pulled from disk instead of a live process:

- **Lovelace dashboards**: reuses
  ``dependency_source.py``'s own ``_walk_lovelace_entities`` walker
  unchanged (imported directly, not reimplemented) over each pulled
  ``.storage/lovelace*`` file's ``data.config.views`` -- the exact
  subtree shape that walker already expects, confirmed against a real
  pulled dashboard file as part of this task.
- **automation/script/scene YAML + packages**: a conservative,
  bounded, file-content-only entity-reference extractor. This is
  deliberately *not* a reimplementation of HA's trigger/condition/
  action schema evaluation (that would require the same live component
  code ``dependency_source.py`` already delegates to) -- it is a
  best-effort static scan for entity-id-shaped strings in three
  well-known positions: (1) explicit ``entity_id``/``entity``/
  ``target.entity_id`` keys, matching how ``_walk_lovelace_entities``
  already treats the same key names for dashboards; (2) Jinja template
  calls the mission explicitly names --
  ``states('domain.object_id')``/``is_state('domain.object_id', ...)``/
  ``state_attr('domain.object_id', ...)`` -- found by a bounded regex
  over every string scalar; (3) any bare ``domain.object_id``-shaped
  token, restricted to Home Assistant's real domain vocabulary, so an
  unrelated dotted string (a hostname, a version number) is never
  misread as an entity reference.

Every result is a ``domain/dependency_references.py::ReferenceSourceResult``
-- the exact same currency ``dependency_source.py`` already produces --
so ``domain/dependency_references.py::build_reference_index`` (already
existing, unmodified) combines both without any special-casing, and
anything downstream (the orphan/duplicate analyzers) never needs to
know whether a given reference came from a live capture or an offline
snapshot.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..domain.dependency_references import ReferenceSourceResult
from .dependency_source import _walk_lovelace_entities  # reuse, not reimplement
from .source_definition_index import ConfigSourceFile, _as_dict_of_dicts, _parse_yaml

MAX_REFERENCES_PER_SOURCE = 20_000

# Home Assistant's real domain vocabulary is open-ended (any integration
# can add one), so this is deliberately generous rather than an
# exhaustive allowlist -- but it still excludes obviously-non-entity
# dotted tokens (version strings, hostnames, decimal numbers) that a
# fully unrestricted `\w+\.\w+` regex would otherwise misread as a
# reference. Sourced from the actual domains observed in the live
# registry pull plus HA's own long-standing built-in domains -- if a
# real reference uses a domain not listed here, it is safely missed
# (undercounted, never fabricated), which only ever makes a downstream
# "definitely referenced" claim more conservative, never less.
_KNOWN_DOMAIN_PREFIXES = (
    "automation",
    "script",
    "scene",
    "group",
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "input_datetime",
    "input_button",
    "sensor",
    "binary_sensor",
    "switch",
    "light",
    "climate",
    "cover",
    "lock",
    "fan",
    "vacuum",
    "media_player",
    "camera",
    "person",
    "device_tracker",
    "zone",
    "sun",
    "weather",
    "number",
    "select",
    "text",
    "button",
    "timer",
    "counter",
    "schedule",
    "alarm_control_panel",
    "humidifier",
    "valve",
    "update",
    "notify",
    "utility_meter",
)
_ENTITY_ID_RE = re.compile(
    r"\b(?:" + "|".join(_KNOWN_DOMAIN_PREFIXES) + r")\.[a-z0-9_]+\b"
)
_TEMPLATE_CALL_RE = re.compile(
    r"(?:states|is_state|state_attr)\(\s*['\"]([a-z_]+\.[a-z0-9_]+)['\"]"
)


def _extract_template_call_targets(text: str) -> set[str]:
    """Only the ``states()``/``is_state()``/``state_attr()`` call targets.

    Safe to apply to *every* string scalar in the tree -- a template
    expression can legitimately appear anywhere (a condition, a
    ``value_template``, deep inside an action's ``data``), and this
    pattern only ever matches inside one of those three specific call
    forms, never a bare dotted token.
    """
    return {match.group(1) for match in _TEMPLATE_CALL_RE.finditer(text)}


def _extract_entity_like_strings(text: str) -> set[str]:
    """Template-call targets plus bare ``domain.object_id`` tokens.

    Reserved for values already known, from their key, to *be* an
    entity id or list of entity ids (``entity_id``/``entity``/
    ``target.entity_id``) -- deliberately not applied to arbitrary
    string scalars, where a service-call name (``lock.lock``,
    ``light.turn_on``) is syntactically indistinguishable from an
    entity id and would otherwise be misread as a reference.
    """
    found = _extract_template_call_targets(text)
    for match in _ENTITY_ID_RE.finditer(text):
        found.add(match.group(0))
    return found


def _walk_config_tree(node: Any, found: set[str]) -> None:
    """Recursively collect plausible entity-id references from a parsed
    automation/script/scene document.

    Deliberately conservative and read-only over already-parsed YAML --
    never raises on an unexpected shape, matching every other capture
    function's discipline in ``dependency_source.py``. Every string
    scalar is checked for a template-call reference (safe anywhere);
    only strings reached through a recognised entity-bearing key
    additionally get the bare-token check (see
    ``_extract_entity_like_strings``'s docstring for why the two are
    not conflated).
    """
    if isinstance(node, str):
        found.update(_extract_template_call_targets(node))
    elif isinstance(node, dict):
        for key in ("entity_id", "entity"):
            value = node.get(key)
            if isinstance(value, str):
                found.update(_extract_entity_like_strings(value))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        found.update(_extract_entity_like_strings(item))
        for value in node.values():
            _walk_config_tree(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk_config_tree(item, found)


def _referencing_id(entry: dict, *, fallback_prefix: str, index: int) -> str:
    entry_id = entry.get("id")
    if isinstance(entry_id, str | int):
        return str(entry_id)
    alias = entry.get("alias")
    if isinstance(alias, str) and alias:
        return f"{fallback_prefix}:{alias}"
    return f"{fallback_prefix}:{index}"


def scan_automation_script_scene_references(
    files: tuple[ConfigSourceFile, ...],
) -> ReferenceSourceResult:
    """Best-effort offline reference scan over the pulled config tree.

    One combined ``ReferenceSourceResult`` (source id
    ``"offline_config_tree"``) covering everything a live automation/
    script/scene/template scan would otherwise answer -- kept as one
    source rather than four because, unlike the live per-component
    captures in ``dependency_source.py``, this static scan cannot tell
    templates apart from plain automation actions; it is intentionally
    coarser and more conservative, never a claim of parity with the
    live scan.
    """
    pairs: list[tuple[str, str]] = []
    failed_any = False
    for source_file in files:
        is_package = source_file.path.startswith("packages/")
        is_top_automations = source_file.path == "automations.yaml"
        is_top_scripts = source_file.path == "scripts.yaml"
        is_top_scenes = source_file.path == "scenes.yaml"
        if not (is_package or is_top_automations or is_top_scripts or is_top_scenes):
            continue
        try:
            document = _parse_yaml(source_file.content)
        except Exception:
            failed_any = True
            continue

        entries: list[tuple[str, dict]] = []
        if is_top_automations and isinstance(document, list):
            entries.extend(
                (
                    _referencing_id(item, fallback_prefix="automation", index=idx),
                    item,
                )
                for idx, item in enumerate(document)
                if isinstance(item, dict)
            )
        if is_top_scenes and isinstance(document, list):
            entries.extend(
                (_referencing_id(item, fallback_prefix="scene", index=idx), item)
                for idx, item in enumerate(document)
                if isinstance(item, dict)
            )
        if is_top_scripts and isinstance(document, dict):
            for object_id, body in _as_dict_of_dicts(document).items():
                entries.append((f"script.{object_id}", body))
        if is_package and isinstance(document, dict):
            auto_node = document.get("automation")
            if isinstance(auto_node, list):
                entries.extend(
                    (
                        _referencing_id(item, fallback_prefix="automation", index=idx),
                        item,
                    )
                    for idx, item in enumerate(auto_node)
                    if isinstance(item, dict)
                )
            elif isinstance(auto_node, dict):
                entries.append(
                    (_referencing_id(auto_node, fallback_prefix="automation", index=0), auto_node)
                )
            scene_node = document.get("scene")
            if isinstance(scene_node, list):
                entries.extend(
                    (_referencing_id(item, fallback_prefix="scene", index=idx), item)
                    for idx, item in enumerate(scene_node)
                    if isinstance(item, dict)
                )
            script_node = document.get("script")
            if isinstance(script_node, dict):
                for object_id, body in _as_dict_of_dicts(script_node).items():
                    entries.append((f"script.{object_id}", body))

        for referencing_id, body in entries:
            found: set[str] = set()
            _walk_config_tree(body, found)
            for target in sorted(found):
                if len(pairs) >= MAX_REFERENCES_PER_SOURCE:
                    break
                pairs.append((referencing_id, target))

    return ReferenceSourceResult(
        source="offline_config_tree",
        status="failed" if failed_any and not pairs else "succeeded",
        references=tuple(pairs),
    )


def scan_lovelace_dashboard_references(
    dashboard_files: tuple[tuple[str, str], ...],
) -> ReferenceSourceResult:
    """Reuse ``dependency_source._walk_lovelace_entities`` over pulled
    ``.storage/lovelace*`` JSON files (``(dashboard_key, raw_json_text)``
    pairs).
    """
    pairs: list[tuple[str, str]] = []
    any_parsed = False
    for dashboard_key, raw_text in dashboard_files:
        try:
            document = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError):
            continue
        views = document.get("data", {}).get("config", {}).get("views", [])
        if not isinstance(views, list):
            continue
        any_parsed = True
        for view_index, view in enumerate(views):
            referencing_id = f"dashboard:{dashboard_key}:view_{view_index}"
            for target in _walk_lovelace_entities(view):
                if len(pairs) >= MAX_REFERENCES_PER_SOURCE:
                    break
                if target != referencing_id:
                    pairs.append((referencing_id, target))

    return ReferenceSourceResult(
        source="dashboard",
        status="succeeded" if any_parsed or not dashboard_files else "unavailable",
        references=tuple(pairs),
    )
