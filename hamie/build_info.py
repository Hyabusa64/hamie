"""Immutable build provenance for a deployed HAMIE integration.

The semantic version lives in ``manifest.json`` and is the only value a human
edits. Everything else here answers a different question: *which build is this?*

``build_info.json`` is written by the packaging step (``tools/build_deploy.py``)
and shipped alongside the code. Production Home Assistant never needs ``.git``:
if the file is missing -- a developer running straight from a source checkout,
say -- provenance simply reports as unknown rather than failing the integration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUILD_INFO_FILENAME = "build_info.json"

#: Reported when a build was produced from a source tree with uncommitted
#: changes. Kept as an explicit marker so a dirty build is never mistaken for a
#: reproducible one.
DIRTY_SUFFIX = "-dirty"


@dataclass(frozen=True)
class BuildInfo:
    """What the packaging step recorded about this build."""

    build_commit: str | None
    build_timestamp: str | None
    dirty: bool

    @property
    def available(self) -> bool:
        """Whether packaging provenance was shipped with this build."""
        return self.build_commit is not None

    @property
    def display_commit(self) -> str | None:
        """Commit for display, marked when the source tree was dirty."""
        if self.build_commit is None:
            return None
        return f"{self.build_commit}{DIRTY_SUFFIX}" if self.dirty else self.build_commit

    def as_dict(self) -> dict[str, Any]:
        """Serialise for diagnostics and API responses."""
        return {
            "build_commit": self.build_commit,
            "build_timestamp": self.build_timestamp,
            "build_dirty": self.dirty,
        }


UNKNOWN_BUILD = BuildInfo(build_commit=None, build_timestamp=None, dirty=False)


def _coerce_commit(raw: Any) -> str | None:
    """Accept only a plausible git object name, never arbitrary text."""
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    if len(candidate) < 7 or len(candidate) > 40:
        return None
    if not all(character in "0123456789abcdef" for character in candidate.lower()):
        return None
    return candidate.lower()


def _coerce_timestamp(raw: Any) -> str | None:
    """Timestamps are recorded as text; reject anything that is not."""
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    return candidate or None


def read_build_info(directory: Path | None = None) -> BuildInfo:
    """Read shipped build provenance, degrading to unknown when absent.

    A malformed or partially written file is treated exactly like a missing one:
    provenance is a diagnostic, and it must never be able to break startup.
    """
    base = directory if directory is not None else Path(__file__).parent
    path = base / BUILD_INFO_FILENAME
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return UNKNOWN_BUILD
    if not isinstance(payload, dict):
        return UNKNOWN_BUILD
    commit = _coerce_commit(payload.get("build_commit"))
    if commit is None:
        return UNKNOWN_BUILD
    return BuildInfo(
        build_commit=commit,
        build_timestamp=_coerce_timestamp(payload.get("build_timestamp")),
        dirty=bool(payload.get("build_dirty", False)),
    )


BUILD_INFO = read_build_info()
