"""Centrally governed production analyzers with lazy package exports."""

from __future__ import annotations

from typing import Any

__all__ = ["UnavailableEntityAnalyzer"]


def __getattr__(name: str) -> Any:
    if name != "UnavailableEntityAnalyzer":
        raise AttributeError(name)
    from .unavailable_entities import UnavailableEntityAnalyzer

    return UnavailableEntityAnalyzer
