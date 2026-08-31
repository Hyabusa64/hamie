"""Editable logical resource registry (HAMIE Phase 3B).

Deterministic, allowlist-based policy for the *only* file-shaped
mutation surface HAMIE exposes to the remediation engine. This module
is pure and I/O-free -- like every other ``domain/`` module -- and
never resolves a real filesystem path; path resolution, traversal
protection, and symlink checks are an application-layer concern
(``application/remediation/file_policy.py``) that consults this
catalog for the *logical* resource identity only.

Design intent (see mission Phase 5/14): "non-critical" is never
whatever the model claims -- it is exactly this closed, reviewed,
narrow registry. HAMIE ships with exactly one editable resource in
this release: a HAMIE-owned maintenance-notes YAML document that HAMIE
itself creates, owns, and fully controls the format of. No real Home
Assistant configuration file (``configuration.yaml``, ``secrets.yaml``,
``automations.yaml``, ``.storage/*``, etc.) is, or can become,
reachable through this registry without a new, separately reviewed
``EditableResourceDefinition`` and a matching adapter -- see
``application/remediation/file_adapters.py`` module docstring for the
full extension checklist.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .common import require_non_empty

MAX_RESOURCE_ID_LENGTH = 128
MAX_RELATIVE_PATH_LENGTH = 256
MAX_ALLOWED_KEY_LENGTH = 128


class EditableResourceFormat(StrEnum):
    """The narrow, HAMIE-owned format one editable resource is stored in."""

    HAMIE_OWNED_YAML_MAP = "hamie_owned_yaml_map"


@dataclass(frozen=True, slots=True)
class EditableResourceDefinition:
    """One reviewed, allowlisted logical resource an action may target.

    ``relative_path`` is relative to HAMIE's own editable-resource root
    (never Home Assistant's ``/config`` root directly, and never an
    absolute or caller-supplied path -- see
    ``application/remediation/file_policy.py``). ``allowed_action_types``
    is the closed set of ``LlmProposedAction.action_type``/catalog
    ``action_type`` values this resource accepts. ``allowed_keys``, when
    non-empty, further restricts which operation keys may be written --
    an empty tuple means "any bounded key", used only for resources
    whose schema is intentionally open-ended key/value annotations.
    """

    resource_id: str
    description: str
    relative_path: str
    resource_format: EditableResourceFormat
    allowed_action_types: tuple[str, ...]
    max_bytes: int
    allowed_keys: tuple[str, ...] = ()
    creatable: bool = True

    def __post_init__(self) -> None:
        require_non_empty(self.resource_id, "resource_id")
        if len(self.resource_id) > MAX_RESOURCE_ID_LENGTH:
            raise ValueError("resource_id is too long")
        require_non_empty(self.description, "description")
        require_non_empty(self.relative_path, "relative_path")
        if len(self.relative_path) > MAX_RELATIVE_PATH_LENGTH:
            raise ValueError("relative_path is too long")
        if self.relative_path.startswith("/") or self.relative_path.startswith("\\"):
            raise ValueError("relative_path must not be absolute")
        if ".." in self.relative_path.replace("\\", "/").split("/"):
            raise ValueError("relative_path must not contain '..'")
        if "\x00" in self.relative_path:
            raise ValueError("relative_path must not contain a null byte")
        if not self.allowed_action_types:
            raise ValueError("allowed_action_types must not be empty")
        object.__setattr__(
            self,
            "allowed_action_types",
            tuple(dict.fromkeys(self.allowed_action_types)),
        )
        if self.max_bytes < 1 or self.max_bytes > 65_536:
            raise ValueError("max_bytes must be between 1 and 65536")
        deduped_keys = tuple(dict.fromkeys(self.allowed_keys))
        for key in deduped_keys:
            if not key or len(key) > MAX_ALLOWED_KEY_LENGTH:
                raise ValueError("allowed_keys items must be bounded non-empty strings")
        object.__setattr__(self, "allowed_keys", deduped_keys)

    def supports_action_type(self, action_type: str) -> bool:
        return action_type in self.allowed_action_types

    def allows_key(self, key: str) -> bool:
        if not self.allowed_keys:
            return True
        return key in self.allowed_keys


# The complete, reviewed registry. Adding an entry here is a reviewed,
# deliberate change -- see application/remediation/file_adapters.py's
# module docstring for the full checklist a new resource requires
# before it is genuinely reachable from any real plan.
EDITABLE_RESOURCE_CATALOG: dict[str, EditableResourceDefinition] = {
    "hamie.maintenance_notes": EditableResourceDefinition(
        resource_id="hamie.maintenance_notes",
        description=(
            "HAMIE-owned maintenance annotation notes -- a small, "
            "HAMIE-authored YAML document HAMIE itself creates and fully "
            "controls the format of. Never a Home Assistant configuration "
            "file; never hand-edited or expected to contain comments, "
            "anchors, or custom YAML tags a generic writer could corrupt."
        ),
        relative_path="hamie_maintenance_notes.yaml",
        resource_format=EditableResourceFormat.HAMIE_OWNED_YAML_MAP,
        allowed_action_types=("yaml_set",),
        max_bytes=8_192,
        allowed_keys=(),
        creatable=True,
    ),
}


def resolve_editable_resource(resource_id: str) -> EditableResourceDefinition | None:
    """Return the reviewed definition for ``resource_id``, or ``None``.

    The single deterministic authority for "is this a real, editable
    resource" -- callers must never infer editability any other way.
    """
    return EDITABLE_RESOURCE_CATALOG.get(resource_id)


def list_editable_resources() -> tuple[EditableResourceDefinition, ...]:
    """Return every reviewed editable resource, sorted by id."""
    return tuple(
        sorted(EDITABLE_RESOURCE_CATALOG.values(), key=lambda item: item.resource_id)
    )
