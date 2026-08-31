"""Durable subject identity values."""

from __future__ import annotations

from dataclasses import dataclass

from .common import require_non_empty, stable_digest


@dataclass(frozen=True, slots=True)
class SubjectIdentity:
    """Identify a current source object and its durable HAMIE subject."""

    durable_id: str
    kind: str
    source_instance: str
    source_id: str
    display_hint: str | None = None
    aliases: tuple[str, ...] = ()
    tombstoned: bool = False

    def __post_init__(self) -> None:
        require_non_empty(self.durable_id, "durable_id")
        require_non_empty(self.kind, "kind")
        require_non_empty(self.source_instance, "source_instance")
        require_non_empty(self.source_id, "source_id")
        if "." not in self.kind:
            raise ValueError("kind must be namespaced")
        if self.display_hint is not None and not self.display_hint.strip():
            raise ValueError("display_hint cannot be blank")
        aliases = tuple(sorted(set(self.aliases)))
        if any(not alias or alias != alias.strip() for alias in aliases):
            raise ValueError("aliases must be non-empty normalized strings")
        object.__setattr__(self, "aliases", aliases)

    @property
    def identity_key(self) -> str:
        """Return the stable durable subject key."""
        return stable_digest(self.kind, self.source_instance, self.durable_id)
