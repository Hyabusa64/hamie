"""Best-effort entity-reference capture from Home Assistant (mission Part 12).

Uses only public, HA-core-relied-upon entity/state APIs, verified
directly against the installed Home Assistant package rather than
guessed:

- **automation** / **script**: each entity's ``referenced_entities``
  (a ``set[str]`` `cached_property` HA's own automation/script
  components compute and rely on for their own UI features -- e.g. the
  entity-in-use warning shown before deleting an entity) via
  ``hass.data[<component data key>].entities``. Pure in-memory object
  access over already-loaded configuration -- no blocking I/O, safe to
  call directly on the event loop.
- **scene** / **group**: the ``entity_id`` list every scene/group
  entity already exposes in its own public state attributes (confirmed
  via ``homeassistant/components/homeassistant/scene.py``'s
  ``extra_state_attributes``) -- read through ``hass.states``, exactly
  like ``infrastructure/ha_source.py`` already reads every other
  entity's state.

Every source is captured defensively: a missing/unloaded component, an
unexpected shape, or any exception is reported as
``unavailable``/``failed`` (see ``domain/dependency_references.py``)
rather than raised or silently treated as "no references" -- this
module never asserts an entity is safe to remove; it only reports what
it could observe.
"""

from __future__ import annotations

from typing import Any

from ..domain.dependency_references import (
    EntityReferenceIndex,
    ReferenceSourceResult,
    build_reference_index,
)

MAX_REFERENCES_PER_SOURCE = 20_000


def _capture_component_referenced_entities(
    hass: Any, source: str, component: Any
) -> ReferenceSourceResult:
    if component is None:
        return ReferenceSourceResult(source=source, status="unavailable")
    try:
        pairs: list[tuple[str, str]] = []
        for entity in component.entities:
            entity_id = getattr(entity, "entity_id", None)
            referenced = getattr(entity, "referenced_entities", None)
            if not isinstance(entity_id, str) or not referenced:
                continue
            for target in referenced:
                if (
                    isinstance(target, str)
                    and target != entity_id
                    and len(pairs) < MAX_REFERENCES_PER_SOURCE
                ):
                    pairs.append((entity_id, target))
        return ReferenceSourceResult(
            source=source, status="succeeded", references=tuple(pairs)
        )
    except Exception:
        return ReferenceSourceResult(source=source, status="failed")


def capture_automation_references(hass: Any) -> ReferenceSourceResult:
    try:
        from homeassistant.components.automation import DATA_COMPONENT
    except ImportError:
        return ReferenceSourceResult(source="automation", status="unavailable")
    return _capture_component_referenced_entities(
        hass, "automation", hass.data.get(DATA_COMPONENT)
    )


def capture_script_references(hass: Any) -> ReferenceSourceResult:
    try:
        from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
    except ImportError:
        return ReferenceSourceResult(source="script", status="unavailable")
    return _capture_component_referenced_entities(
        hass, "script", hass.data.get(SCRIPT_DOMAIN)
    )


def _capture_state_attribute_entities(hass: Any, source: str) -> ReferenceSourceResult:
    try:
        pairs: list[tuple[str, str]] = []
        for state in hass.states.async_all(source):
            targets = state.attributes.get("entity_id")
            if not isinstance(targets, list | tuple):
                continue
            for target in targets:
                if (
                    isinstance(target, str)
                    and target != state.entity_id
                    and len(pairs) < MAX_REFERENCES_PER_SOURCE
                ):
                    pairs.append((state.entity_id, target))
        return ReferenceSourceResult(
            source=source, status="succeeded", references=tuple(pairs)
        )
    except Exception:
        return ReferenceSourceResult(source=source, status="failed")


def capture_scene_references(hass: Any) -> ReferenceSourceResult:
    return _capture_state_attribute_entities(hass, "scene")


def capture_group_references(hass: Any) -> ReferenceSourceResult:
    return _capture_state_attribute_entities(hass, "group")


# (config-entry domain, option key holding the source entity id(s),
# whether that key holds a list rather than a single entity id) --
# every one of these platforms is a real, config-entry-based helper
# whose config already explicitly names the entity it reads from.
# Verified directly against the installed Home Assistant package
# (homeassistant.components.<domain>.const/__init__), not guessed:
# utility_meter/derivative/integration all key off ``CONF_SOURCE`` ==
# "source"; threshold off ``CONF_ENTITY_ID`` == "entity_id"; min_max
# off its own ``CONF_ENTITY_IDS`` == "entity_ids" (a list).
_HELPER_SOURCE_SPECS: tuple[tuple[str, str, bool], ...] = (
    ("utility_meter", "source", False),
    ("derivative", "source", False),
    ("integration", "source", False),
    ("threshold", "entity_id", False),
    ("min_max", "entity_ids", True),
)


def capture_helper_references(hass: Any) -> ReferenceSourceResult:
    """Capture explicit source-entity references from known helper platforms.

    Only ever records a reference a helper's own configuration
    explicitly names -- a helper merely *existing* is never treated as
    a dependency on anything. A helper's configured source may be an
    entity registry UUID rather than a live entity_id (HA itself always
    resolves through ``async_resolve_entity_id`` for exactly this
    reason), so this does too, rather than emitting a UUID that will
    never match a real entity_id anywhere else in the reference index.
    """
    try:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        pairs: list[tuple[str, str]] = []
        for domain, option_key, is_list in _HELPER_SOURCE_SPECS:
            for entry in hass.config_entries.async_entries(domain):
                raw_targets = entry.options.get(option_key)
                if raw_targets is None:
                    continue
                raw_list = raw_targets if is_list else [raw_targets]
                resolved = [
                    er.async_resolve_entity_id(registry, item)
                    if isinstance(item, str)
                    else None
                    for item in raw_list
                ]
                referencing_entries = er.async_entries_for_config_entry(
                    registry, entry.entry_id
                )
                referencing_id = (
                    referencing_entries[0].entity_id
                    if referencing_entries
                    else f"{domain}.{entry.entry_id}"
                )
                for target in resolved:
                    if (
                        isinstance(target, str)
                        and target != referencing_id
                        and len(pairs) < MAX_REFERENCES_PER_SOURCE
                    ):
                        pairs.append((referencing_id, target))
        return ReferenceSourceResult(
            source="helper", status="succeeded", references=tuple(pairs)
        )
    except Exception:
        return ReferenceSourceResult(source="helper", status="failed")


# Dispatch per Energy source "type" -> the field names holding a
# statistic/entity id. 2026.6+ flattened the "grid" source's
# flow_from/flow_to lists into direct fields (``GridSourceType``);
# 2025.8's nested shape survives as ``LegacyGridSourceType`` and is
# handled by checking for "flow_from"/"flow_to" first, matching
# Home Assistant's own migrate-on-load handling of the same duality.
_ENERGY_DIRECT_FIELDS: dict[str, tuple[str, ...]] = {
    "solar": ("stat_energy_from",),
    "battery": ("stat_energy_from", "stat_energy_to"),
    "gas": ("stat_energy_from", "entity_energy_price"),
    "water": ("stat_energy_from", "entity_energy_price"),
    "grid": (
        "stat_energy_from",
        "stat_energy_to",
        "entity_energy_price",
        "entity_energy_price_export",
    ),
}


def _energy_flow_fields(flow: Any) -> tuple[str, ...]:
    if not isinstance(flow, dict):
        return ()
    return tuple(
        value
        for key in ("stat_energy_from", "stat_energy_to", "entity_energy_price")
        if isinstance(value := flow.get(key), str)
    )


async def capture_energy_references(hass: Any) -> ReferenceSourceResult:
    """Capture Energy dashboard source/device-consumption references.

    ``EnergyManager`` is a lazily-created singleton
    (``@singleton.singleton("energy_manager")``) -- Energy's own
    ``async_setup`` never creates it, so a real installation that has
    simply never opened the Energy dashboard would otherwise always
    read ``hass.data.get("energy_manager")`` as absent, permanently
    reporting "unavailable" regardless of whether Energy is actually
    configured. ``async_get_manager`` is awaited instead: safe, bounded
    Store I/O identical in kind to every other Store read HAMIE already
    performs (offloaded to the executor, no network access), and it
    reliably distinguishes "genuinely never configured" (empty
    ``energy_sources``) from "not yet queried this process lifetime" --
    the two cases a synchronous-only read cannot tell apart.
    ``stat_*`` fields are statistic ids, not guaranteed entity ids (an
    external integration's statistic looks like ``domain:object_id``)
    -- only values Home Assistant's own ``valid_entity_id`` accepts are
    ever recorded as an entity reference;
    ``entity_energy_price``/``entity_energy_price_export`` are always
    real entity ids.
    """
    try:
        from homeassistant.components.energy.data import async_get_manager
        from homeassistant.core import valid_entity_id

        manager = await async_get_manager(hass)
        prefs = manager.data
        if not prefs:
            return ReferenceSourceResult(
                source="energy", status="succeeded", references=()
            )
        pairs: list[tuple[str, str]] = []
        for index, source in enumerate(prefs.get("energy_sources", [])):
            if not isinstance(source, dict):
                continue
            referencing_id = f"energy_source_{index}"
            values: list[str] = []
            if source.get("type") == "grid" and (
                "flow_from" in source or "flow_to" in source
            ):
                for flow in source.get("flow_from", []) or []:
                    values.extend(_energy_flow_fields(flow))
                for flow in source.get("flow_to", []) or []:
                    values.extend(_energy_flow_fields(flow))
            else:
                for field in _ENERGY_DIRECT_FIELDS.get(source.get("type", ""), ()):
                    value = source.get(field)
                    if isinstance(value, str):
                        values.append(value)
            for value in values:
                if valid_entity_id(value) and len(pairs) < MAX_REFERENCES_PER_SOURCE:
                    pairs.append((referencing_id, value))
        for index, device in enumerate(prefs.get("device_consumption", [])):
            if not isinstance(device, dict):
                continue
            value = device.get("stat_consumption")
            if (
                isinstance(value, str)
                and valid_entity_id(value)
                and len(pairs) < MAX_REFERENCES_PER_SOURCE
            ):
                pairs.append((f"energy_device_{index}", value))
        return ReferenceSourceResult(
            source="energy", status="succeeded", references=tuple(pairs)
        )
    except Exception:
        return ReferenceSourceResult(source="energy", status="failed")


def _template_entity_referenced_entities(hass: Any) -> list[tuple[str, str]]:
    """Best-effort: read each template entity's already-computed tracked
    entities from its live template-result tracker (``_template_result_info``,
    private but the only in-memory record of what a template statically
    depends on -- there is no public static extractor; the only public
    alternative, ``async_render_to_info``, actually re-renders the
    template). A missing/absent tracker for one entity is simply
    skipped, never treated as a hard failure for the whole source.
    """
    from homeassistant.helpers.entity_component import DATA_INSTANCES

    pairs: list[tuple[str, str]] = []
    for component in hass.data.get(DATA_INSTANCES, {}).values():
        for entity in getattr(component, "entities", ()):
            platform = getattr(entity, "platform", None)
            if getattr(platform, "platform_name", None) != "template":
                continue
            entity_id = getattr(entity, "entity_id", None)
            info = getattr(entity, "_template_result_info", None)
            if not isinstance(entity_id, str) or info is None:
                continue
            try:
                listeners = info.listeners
            except Exception:
                continue
            for target in listeners.get("entities", ()):
                if (
                    isinstance(target, str)
                    and target != entity_id
                    and len(pairs) < MAX_REFERENCES_PER_SOURCE
                ):
                    pairs.append((entity_id, target))
    return pairs


def capture_template_references(hass: Any) -> ReferenceSourceResult:
    try:
        pairs = _template_entity_referenced_entities(hass)
        return ReferenceSourceResult(
            source="template", status="succeeded", references=tuple(pairs)
        )
    except Exception:
        return ReferenceSourceResult(source="template", status="failed")


def _walk_lovelace_entities(node: Any) -> list[str]:
    """Recursively pull entity ids out of a Lovelace card/view/section
    subtree. Deliberately conservative: only string values under known
    entity-bearing keys are ever treated as a reference, and an
    unrecognised custom-card shape simply yields nothing for that
    subtree rather than raising -- never a reason to abandon the whole
    dashboard walk.
    """
    found: list[str] = []
    if isinstance(node, dict):
        for key in ("entity", "camera_image", "entity_id"):
            value = node.get(key)
            if isinstance(value, str):
                found.append(value)
        entities = node.get("entities")
        if isinstance(entities, list):
            for item in entities:
                if isinstance(item, str):
                    found.append(item)
                elif isinstance(item, dict):
                    found.extend(_walk_lovelace_entities(item))
        for key in ("cards", "elements", "conditions", "badges", "sections"):
            child = node.get(key)
            if isinstance(child, list):
                for item in child:
                    found.extend(_walk_lovelace_entities(item))
        card = node.get("card")
        if isinstance(card, dict):
            found.extend(_walk_lovelace_entities(card))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_lovelace_entities(item))
    return found


async def capture_dashboard_references(hass: Any) -> ReferenceSourceResult:
    """Capture entity references from every Lovelace dashboard's cards.

    Storage-mode dashboard config is loaded lazily by HA (``None``
    until a frontend client first requests it), so a genuinely
    synchronous read would silently miss any dashboard nobody has
    opened since Home Assistant started -- ``async_load`` is awaited
    instead, which is loop-safe (``Store.async_load`` offloads the
    actual file read to the executor) and never triggers a network
    call. A dashboard that fails to load (never configured, corrupt,
    auto-generated-and-empty) contributes nothing and does not fail the
    whole scan -- see the per-dashboard try/except below.
    """
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA
    except ImportError:
        return ReferenceSourceResult(source="dashboard", status="unavailable")
    data = hass.data.get(LOVELACE_DATA)
    dashboards = getattr(data, "dashboards", None)
    if not isinstance(dashboards, dict):
        return ReferenceSourceResult(source="dashboard", status="unavailable")
    try:
        pairs: list[tuple[str, str]] = []
        for url_path, dashboard in dashboards.items():
            referencing_prefix = url_path or "default"
            try:
                config = await dashboard.async_load(False)
            except Exception:
                continue
            views = config.get("views", []) if isinstance(config, dict) else []
            for view_index, view in enumerate(views):
                referencing_id = f"dashboard:{referencing_prefix}:view_{view_index}"
                for target in _walk_lovelace_entities(view):
                    if (
                        target != referencing_id
                        and len(pairs) < MAX_REFERENCES_PER_SOURCE
                    ):
                        pairs.append((referencing_id, target))
        return ReferenceSourceResult(
            source="dashboard", status="succeeded", references=tuple(pairs)
        )
    except Exception:
        return ReferenceSourceResult(source="dashboard", status="failed")


async def capture_all_reference_sources(hass: Any) -> tuple[ReferenceSourceResult, ...]:
    """Capture every reference source HAMIE currently knows how to scan."""
    return (
        capture_automation_references(hass),
        capture_script_references(hass),
        capture_scene_references(hass),
        capture_group_references(hass),
        capture_helper_references(hass),
        capture_template_references(hass),
        await capture_energy_references(hass),
        await capture_dashboard_references(hass),
    )


class HomeAssistantReferenceIndexSource:
    """Thin adapter satisfying ``application.ports.ReferenceIndexPort``
    (mission Part 1.4).

    Every call this makes was already real, tested code
    (``capture_all_reference_sources``/``build_reference_index``, both
    defined above/in ``domain/dependency_references.py``) -- this class
    adds nothing new except the constructor-injection shape
    ``application/scan_coordinator.py`` needs to call it uniformly each
    scan, matching ``infrastructure/ha_source.py``'s
    ``HomeAssistantOperationalSource`` and
    ``infrastructure/recorder_source.py``'s ``RecorderStatisticsSource``
    -- the two existing precedents for "wrap a live ``hass`` object
    behind a small, injectable, single-purpose adapter class".

    Before this class existed, ``capture_all_reference_sources``/
    ``build_reference_index`` were only ever called from
    ``application/cleanup_coordinator.py``'s separate, on-demand
    "run cleanup now" flow -- never from the automatic scan pipeline.
    This adapter is what lets ``ScanCoordinator`` reach the exact same
    real reference evidence every routine scan, not only an explicitly
    user-triggered one.
    """

    def __init__(self, hass: Any) -> None:
        self._hass = hass

    async def async_capture_reference_index(self) -> EntityReferenceIndex:
        return build_reference_index(await capture_all_reference_sources(self._hass))
