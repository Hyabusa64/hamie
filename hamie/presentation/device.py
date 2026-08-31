"""Stable HAMIE Home Assistant device identity."""

from __future__ import annotations

from typing import Any

from ..const import DOMAIN

DEVICE_NAME = "HAMIE Engine"
DEVICE_MANUFACTURER = "HAMIE"
DEVICE_MODEL = "Home Assistant Maintenance Intelligence Engine"


async def async_device_info(hass: Any, entry: Any) -> Any:
    """Build canonical device metadata from the integration manifest version."""
    from homeassistant.helpers.entity import DeviceInfo
    from homeassistant.loader import async_get_integration

    integration = await async_get_integration(hass, DOMAIN)
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=DEVICE_NAME,
        manufacturer=DEVICE_MANUFACTURER,
        model=DEVICE_MODEL,
        sw_version=str(integration.version),
    )
