"""Disabled-by-default optional HAMIE connector adapters.

Keep the package import lightweight.  Importing a pure connector helper must
not eagerly import every optional network adapter (and its Home Assistant
dependencies); the composition root imports ``manager`` directly when it
actually needs the full connector set.
"""

from __future__ import annotations

from typing import Any

__all__ = ("ConnectorManager",)


def __getattr__(name: str) -> Any:
    if name != "ConnectorManager":
        raise AttributeError(name)
    from .manager import ConnectorManager

    return ConnectorManager
