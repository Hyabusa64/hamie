"""Installation topology: which integration platforms are actually live
right now, and which custom-integration source directories exist
(mission Part 2, Analyzer 2).

Formalizes the "removed custom integration" pattern proven by hand this
session (``lutron_caseta_pro``, found 16x): an entity is orphaned by a
*removed integration*, not merely a broken/renamed entity, when **all**
of these independently-observable facts line up:

- its registry ``config_entry_id`` is ``None`` and its ``device_id`` is
  ``None`` (or points at a device whose own config entry is also gone --
  callers cross-check this against ``EntityRecord.device_id`` plus the
  same ``live_config_entry_domains`` set, since HAMIE does not capture a
  separate device registry snapshot);
- its ``platform`` has **zero** live ``config_entries`` rows anywhere in
  the current installation;
- no ``custom_components/<platform>`` directory exists (the integration
  was not just misconfigured -- its code is gone).

Neither of the last two facts was previously captured by any HAMIE
infrastructure module before this one (checked
``infrastructure/ha_source.py``, ``infrastructure/dependency_source.py``):
this is genuinely new infrastructure, not a reuse of an existing read --
a real gap the mission anticipated might exist ("if it doesn't currently
capture the custom_components directory listing, note that as a real
gap ... and implement it via the same live-file-read pattern
source_definition_index.py already uses"). Both reads below follow that
exact pattern: public, documented Home Assistant APIs
(``hass.config_entries.async_entries()``, ``hass.config.path()``),
offloaded to the executor for the filesystem read, captured defensively
so a failure degrades honestly (``None``) rather than aborting a scan.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

MAX_CUSTOM_COMPONENT_DIRS = 2_000

# Core Home Assistant platforms that are legitimately pure-YAML (or
# UI-helper) configured and, by design, never register a config entry
# for their bare platform name -- mission Part 5, false-positive test
# 11 ("template platform entities legitimately have no config_entry").
# A bare "zero live config_entries + no custom_components dir" reading
# cannot, on its own, distinguish "this integration was removed" from
# "this integration has simply always worked this way" -- disambiguated
# here via an explicit allowlist rather than a manifest read (this
# codebase has no live-process access to enumerate HA core's real
# integration manifests from -- see this module's own docstring on
# infrastructure gaps addressed honestly rather than guessed). This
# allowlist is deliberately not claimed exhaustive; it covers the
# common core YAML-only platforms and the platforms demonstrated by the
# 2026-08-25 live read-only review.  In particular, automation/script/
# scene rows and Home Assistant's own helper/energy rows routinely have
# neither a config entry nor a custom_components directory.  Treating
# those ordinary ownership models as proof of a removed integration
# produced hundreds of false positives, including safety-sensitive
# entities.  The allowlist is therefore a hard safety boundary: this
# analyzer may miss an unusual stale core row, but it must not recommend
# registry removal from absence evidence that is normal for the platform.
CORE_YAML_ONLY_PLATFORMS = frozenset(
    {
        "automation",
        "script",
        "scene",
        "energy",
        "homeassistant",
        "template",
        "group",
        "min_max",
        "statistics",
        "filter",
        "derivative",
        "integration",
        "threshold",
        "generic_hygrostat",
        "generic_thermostat",
        "generic_camera",
        "trend",
        "history_stats",
        "tod",
        "workday",
        "time_date",
        "command_line",
        "rest",
        "scrape",
        "utility_meter",
        "input_boolean",
        "input_number",
        "input_text",
        "input_select",
        "input_datetime",
        "input_button",
        "timer",
        "counter",
        "schedule",
        "person",
        "zone",
    }
)


@dataclass(frozen=True, slots=True)
class InstallationTopology:
    """Bounded, pure snapshot of "what platforms/integrations exist right now"."""

    live_config_entry_domains: frozenset[str]
    custom_component_dirs: frozenset[str]

    def platform_has_removed_integration(self, platform: str | None) -> bool:
        """Return whether ``platform`` looks like a fully-removed custom
        integration: zero live config entries anywhere for it, no
        ``custom_components/<platform>`` directory backing it, and it is
        not a known core YAML-only platform (see
        ``CORE_YAML_ONLY_PLATFORMS`` above).

        Conservative on missing information: a blank/unknown platform
        never claims removal (nothing to check), matching this
        codebase's "never guess" discipline.
        """
        if not platform or platform in CORE_YAML_ONLY_PLATFORMS:
            return False
        return (
            platform not in self.live_config_entry_domains
            and platform not in self.custom_component_dirs
        )


def build_installation_topology(
    config_entry_domains: frozenset[str], custom_component_dirs: frozenset[str]
) -> InstallationTopology:
    """Pure constructor -- kept separate from the async live readers below
    so tests can build an ``InstallationTopology`` directly without any
    ``hass`` object at all."""
    return InstallationTopology(
        live_config_entry_domains=config_entry_domains,
        custom_component_dirs=custom_component_dirs,
    )


async def async_read_live_config_entry_domains(hass: Any) -> frozenset[str] | None:
    """Return every domain with at least one live config entry.

    ``hass.config_entries.async_entries()`` (no domain filter) is the
    same public API ``infrastructure/dependency_source.py``'s
    ``capture_helper_references`` already calls per-domain -- this is
    the unfiltered form, synchronous and non-blocking (an in-memory
    registry read, not I/O), matching that module's own defensive
    capture pattern. Returns ``None`` (never an empty frozenset used to
    mean "no integrations at all", which would be an implausible,
    misleading answer for a real installation) on any failure.
    """
    try:
        entries = hass.config_entries.async_entries()
        return frozenset(
            entry.domain for entry in entries if getattr(entry, "domain", None)
        )
    except Exception:  # noqa: BLE001 -- defensive, see module docstring
        _LOGGER.exception(
            "HAMIE could not read live config_entries for installation "
            "topology this scan; removed-integration-orphan detection "
            "degrades to 'not evaluated' for every entity"
        )
        return None


async def async_read_custom_component_dirs(hass: Any) -> frozenset[str] | None:
    """Return every subdirectory name under ``<config>/custom_components``.

    Read via ``hass.async_add_executor_job`` (blocking filesystem I/O,
    exactly ``infrastructure/source_definition_index.py``'s
    ``async_read_config_source_files`` pattern) rather than
    ``hass.config.path()`` called directly on the event loop. Returns
    ``None`` on any read failure or a missing directory is reported as
    an *empty* frozenset (a real, meaningful answer: no custom
    integrations installed at all) -- the two cases are deliberately
    distinguished, matching ``async_read_live_config_entry_domains``'s
    own None-vs-empty discipline.
    """

    def _read_all() -> frozenset[str]:
        config_dir = hass.config.path()
        custom_dir = os.path.join(config_dir, "custom_components")
        if not os.path.isdir(custom_dir):
            return frozenset()
        names = []
        for entry in sorted(os.listdir(custom_dir))[:MAX_CUSTOM_COMPONENT_DIRS]:
            full_path = os.path.join(custom_dir, entry)
            if os.path.isdir(full_path) and not entry.startswith("__"):
                names.append(entry)
        return frozenset(names)

    try:
        return await hass.async_add_executor_job(_read_all)
    except Exception:  # noqa: BLE001 -- defensive, see module docstring
        _LOGGER.exception(
            "HAMIE could not read custom_components/ for installation "
            "topology this scan; removed-integration-orphan detection "
            "degrades to 'not evaluated' for every entity"
        )
        return None


async def async_build_installation_topology(hass: Any) -> InstallationTopology | None:
    """Build the full topology once per capture; ``None`` if either read failed."""
    domains = await async_read_live_config_entry_domains(hass)
    dirs = await async_read_custom_component_dirs(hass)
    if domains is None or dirs is None:
        return None
    return build_installation_topology(domains, dirs)
