"""Supported Home Assistant custom-panel lifecycle."""

from __future__ import annotations

import logging
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..const import DOMAIN
from .ai_control_api import (
    async_register_commands as async_register_ai_control_commands,
)
from .api import async_register_commands
from .cleanup_api import (
    async_register_commands as async_register_cleanup_commands,
)
from .remediation_api import (
    async_register_commands as async_register_remediation_commands,
)

PANEL_URL_PATH = "hamie"
PANEL_STATIC_URL = "/hamie_static/hamie-app.js"
PANEL_COMPONENT = "hamie-app"
STATIC_REGISTERED = "hamie.static_path_registered"

_LOGGER = logging.getLogger(__name__)


class PanelAssetError(RuntimeError):
    """The packaged frontend asset could not be read for cache-busting."""


def _compute_digest(module_path: Path) -> str:
    """Blocking file read and hash; must only ever run in the executor."""
    return sha256(module_path.read_bytes()).hexdigest()[:12]


async def _async_module_url(hass: Any, module_path: Path) -> str:
    """Append a content-hash query so browsers cannot serve a stale bundle.

    The static path carries long-lived cache headers (required so the panel
    loads fast within one version), so the URL itself must change whenever
    the served bundle changes. A stable, version-bump-independent content
    hash guarantees every code change invalidates any previously cached
    bundle.

    The read+hash is blocking file I/O, so it must never run directly on
    Home Assistant's event loop; it is dispatched to the executor.
    """
    try:
        digest = await hass.async_add_executor_job(_compute_digest, module_path)
    except OSError as err:
        raise PanelAssetError(f"{module_path.name} is missing or unreadable") from err
    return f"{PANEL_STATIC_URL}?v={digest}"


async def async_register_panel(hass: Any) -> None:
    """Register one admin-only panel and its authenticated bounded API.

    Idempotent: a config-entry reload (any options save, from either the
    inline HAMIE editors or native Options Flow) calls async_setup_entry
    again without a prior async_unload_entry removing the panel first
    (see async_unload_entry's docstring for why) -- so this must be safe
    to call on every reload rather than raising
    `ValueError("Overwriting panel hamie")`, which
    `panel_custom.async_register_panel` does unconditionally.

    Checks `hass.data[frontend.DATA_PANELS]` directly rather than the
    newer `frontend.async_panel_exists` helper, which does not exist on
    the minimum supported Home Assistant version (2025.8) -- confirmed
    by running against all 3 supported HA version lanes. `DATA_PANELS`
    itself is present on every supported lane.
    """
    from homeassistant.components import frontend, panel_custom
    from homeassistant.components.http import StaticPathConfig
    from homeassistant.exceptions import ConfigEntryNotReady

    async_register_commands(hass)
    async_register_remediation_commands(hass)
    async_register_ai_control_commands(hass)
    async_register_cleanup_commands(hass)
    if PANEL_URL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        return
    module_path = Path(__file__).parents[1] / "frontend" / "dist" / "hamie-app.js"
    try:
        module_url = await _async_module_url(hass, module_path)
    except PanelAssetError as err:
        _LOGGER.error(
            "HAMIE cannot register its panel: %s is missing from the packaged "
            "integration (run `npm run build:frontend` before packaging)",
            module_path.name,
        )
        raise ConfigEntryNotReady("HAMIE frontend asset is unavailable") from err
    if not hass.data.get(STATIC_REGISTERED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_URL, str(module_path), True)]
        )
        hass.data[STATIC_REGISTERED] = True
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title="HAMIE",
        sidebar_icon="mdi:radar",
        module_url=module_url,
        require_admin=True,
        config={"domain": DOMAIN, "api_version": 1},
        config_panel_domain=DOMAIN,
    )


async def async_remove_panel(hass: Any) -> None:
    """Remove the sidebar panel while preserving one-time API registration."""
    from homeassistant.components import frontend

    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
