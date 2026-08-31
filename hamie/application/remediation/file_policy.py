"""Deterministic path resolution and traversal/symlink policy (Phase 3B).

This is the *only* place a logical editable-resource id
(``domain/remediation_resources.py``) is ever turned into a real
filesystem path, and the only place that path is validated safe to
touch. The model never sees, chooses, or supplies a path -- it only
ever names a ``resource_id`` HAMIE already reviewed and returned to it
as editable (see ``domain/llm_proposal.py``).

Every resolved path is required to stay inside HAMIE's own editable-
resource root (a HAMIE-namespaced subdirectory of the Home Assistant
config directory, never ``/config`` itself) and is re-checked against
an explicit critical-file denylist as defense in depth, even though
today's ``EDITABLE_RESOURCE_CATALOG`` can never reference any of those
paths in the first place.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from ...domain.remediation_resources import (
    EditableResourceDefinition,
    resolve_editable_resource,
)

# A HAMIE-namespaced subdirectory of the Home Assistant config directory --
# deliberately never "/config" itself, never ".storage", and never
# "custom_components" (a dotted or otherwise unusual directory name placed
# directly inside custom_components/ can break Home Assistant's own
# integration loader; see project history). This directory is created by
# HAMIE itself the first time it is needed and contains nothing but
# HAMIE-owned, HAMIE-authored editable resources.
EDITABLE_RESOURCE_ROOT_DIRNAME = "hamie_editable"

# Absolute defense-in-depth denylist. EDITABLE_RESOURCE_CATALOG cannot
# reference any of these today -- every entry's relative_path is reviewed
# at definition time (domain/remediation_resources.py) -- but a resolved
# path is still re-checked against this list before every read or write,
# so a future catalog authoring mistake can never reach a critical file.
_DENIED_FILENAMES = frozenset(
    {
        "configuration.yaml",
        "secrets.yaml",
        "automations.yaml",
        "scripts.yaml",
        "scenes.yaml",
        ".env",
    }
)
_DENIED_PATH_SEGMENTS = frozenset(
    {
        ".storage",
        ".git",
        ".ssh",
        "custom_components",
        "known_devices.yaml",
    }
)


class FilePolicyError(RuntimeError):
    """A stable, non-sensitive path-policy rejection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_editable_resource_path(
    config_root: Path, resource_id: str
) -> tuple[EditableResourceDefinition, Path]:
    """Resolve one logical resource id to a validated, safe absolute path.

    Fails closed (``FilePolicyError``) on any unknown resource, path
    traversal, absolute-path override, null byte, symlink escape, or
    denylisted critical-file/directory match.
    """
    resource = resolve_editable_resource(resource_id)
    if resource is None:
        raise FilePolicyError(
            "unknown_editable_resource", f"{resource_id!r} is not an editable resource"
        )
    root = (Path(config_root) / EDITABLE_RESOURCE_ROOT_DIRNAME).resolve(strict=False)
    candidate = (root / resource.relative_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as err:
        raise FilePolicyError(
            "path_escape", "resolved path escapes the editable-resource root"
        ) from err
    text = str(candidate)
    if "\x00" in text:
        raise FilePolicyError("invalid_path", "path contains a null byte")
    if candidate.name.casefold() in _DENIED_FILENAMES:
        raise FilePolicyError(
            "denied_path", "resolved path targets a denied critical file"
        )
    if _DENIED_PATH_SEGMENTS & {part.casefold() for part in candidate.parts}:
        raise FilePolicyError(
            "denied_path", "resolved path passes through a denied directory"
        )
    if candidate.is_symlink():
        raise FilePolicyError("symlink_escape", "resolved path is a symlink")
    if candidate.exists():
        real = Path(os.path.realpath(candidate))
        real_root = Path(os.path.realpath(root))
        try:
            real.relative_to(real_root)
        except ValueError as err:
            raise FilePolicyError(
                "symlink_escape",
                "resolved path escapes the editable-resource root via a symlink",
            ) from err
    return resource, candidate


def read_current_bytes(path: Path) -> bytes | None:
    """Return the current file content, or ``None`` if it does not exist yet."""
    if not path.exists():
        return None
    if not path.is_file():
        raise FilePolicyError("not_a_file", "resolved path is not a regular file")
    return path.read_bytes()


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Write ``content`` to ``path`` atomically (Phase 10).

    Writes to a temporary file in the same directory, flushes and
    fsyncs it, then atomically renames it onto the target -- never an
    in-place partial write. On any failure the temporary file is
    removed and the original file is left completely untouched.
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(directory), prefix=".hamie_tmp_")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_name)
        raise
