"""Admin-authorized bounded WebSocket API for AI Control status/acknowledgement.

Thin presentation-layer adapter only, matching
``presentation/remediation_api.py``'s own discipline: every command
here validates a bounded request shape, calls one function in
``application/ai_control_service.py``, and translates the result.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api

from ..application import ai_control_service as service
from ..connectors.base import now_utc
from ..const import DOMAIN
from ..domain.ai_control import AI_CONTROL_ACKNOWLEDGEMENT_TEXT
from .api import _config_entry

AI_CONTROL_API_REGISTERED = "hamie.ai_control_websocket_api_registered"
_LOGGER = logging.getLogger(__name__)


def _runtime(hass: Any) -> Any:
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise RuntimeError("HAMIE is not loaded")
    return next(iter(entries.values()))


def _actor(connection: Any) -> str:
    return f"home_assistant_user:{connection.user.id}"


def _ai_control_error(connection: Any, msg: dict[str, Any], err: Exception) -> None:
    if isinstance(err, service.AiControlServiceError):
        connection.send_error(msg["id"], err.code, err.message)
        return
    _LOGGER.error(
        "HAMIE AI Control operation failed: error_type=%s", type(err).__name__
    )
    connection.send_error(
        msg["id"],
        "ai_control_internal_error",
        "An unexpected error occurred while processing the AI Control request.",
    )


def _status_dict(status: service.AiControlStatus) -> dict[str, Any]:
    acknowledgement = status.acknowledgement
    return {
        "configured_mode": status.configured_mode.value,
        "effective_mode": status.effective_mode.value,
        "acknowledgement_required": status.acknowledgement_required,
        "acknowledgement_text": AI_CONTROL_ACKNOWLEDGEMENT_TEXT,
        "current_acknowledgement_version": status.current_acknowledgement_version,
        "acknowledgement": (
            None
            if acknowledgement is None
            else {
                "version": acknowledgement.version,
                "is_current": acknowledgement.is_current,
                "acknowledged_at": acknowledgement.acknowledged_at.isoformat().replace(
                    "+00:00", "Z"
                ),
                "acknowledged_by": acknowledgement.acknowledged_by,
            }
        ),
    }


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "hamie/ai_control/status"})
@websocket_api.async_response
async def ws_ai_control_status(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Return the current AI Control mode/acknowledgement status. Read-only."""
    try:
        runtime = _runtime(hass)
        state = await runtime.repository.async_load()
        options = dict(_config_entry(hass).options)
        status = service.get_status(
            state, configured_mode_raw=options.get("ai_operating_mode", "observe")
        )
        connection.send_result(msg["id"], _status_dict(status))
    except Exception as err:
        _ai_control_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "hamie/ai_control/acknowledge",
        vol.Required("acknowledgement_text"): vol.Equal(
            AI_CONTROL_ACKNOWLEDGEMENT_TEXT
        ),
        vol.Required("confirmed"): vol.Equal(True),
    }
)
@websocket_api.async_response
async def ws_ai_control_acknowledge(
    hass: Any, connection: Any, msg: dict[str, Any]
) -> None:
    """Record one explicit AI Control acknowledgement.

    Requires the caller to echo back the exact, current acknowledgement
    text (mission Part 21) plus the literal ``confirmed: true`` flag,
    mirroring the remediation engine's own ``execute``/``rollback``
    confirmation pattern -- a stale or partially-read client can never
    accidentally grant this.
    """
    try:
        acknowledgement = await service.async_acknowledge_ai_control(
            _runtime(hass).repository, actor=_actor(connection), now=now_utc()
        )
        connection.send_result(
            msg["id"],
            {
                "version": acknowledgement.version,
                "acknowledged_at": acknowledgement.acknowledged_at.isoformat().replace(
                    "+00:00", "Z"
                ),
                "acknowledged_by": acknowledgement.acknowledged_by,
            },
        )
    except Exception as err:
        _ai_control_error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "hamie/ai_control/revoke_acknowledgement"}
)
@websocket_api.async_response
async def ws_ai_control_revoke(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Clear a previously granted AI Control acknowledgement. Idempotent."""
    try:
        await service.async_revoke_ai_control_acknowledgement(_runtime(hass).repository)
        connection.send_result(msg["id"], {"revoked": True})
    except Exception as err:
        _ai_control_error(connection, msg, err)


COMMANDS = (
    ws_ai_control_status,
    ws_ai_control_acknowledge,
    ws_ai_control_revoke,
)


def async_register_commands(hass: Any) -> None:
    """Register the AI Control command schemas once per HA instance."""
    if hass.data.get(AI_CONTROL_API_REGISTERED):
        return
    for command in COMMANDS:
        websocket_api.async_register_command(hass, command)
    hass.data[AI_CONTROL_API_REGISTERED] = True
