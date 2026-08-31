"""Immutable evidence values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .common import require_non_empty, require_utc, stable_digest
from .identity import SubjectIdentity


class EvidenceKind(StrEnum):
    """Authority class of an evidence item."""

    OBSERVED = "observed"
    DERIVED = "derived"
    ASSERTED = "asserted"


class Sensitivity(StrEnum):
    """Diagnostics handling for an evidence item."""

    PUBLIC = "public"
    REDACT = "redact"
    NEVER_EXPORT = "never_export"


EvidenceValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """Minimal source observation embedded in a finding."""

    subject: SubjectIdentity
    predicate: str
    value: EvidenceValue
    observed_at: datetime
    source_id: str
    source_revision: str
    kind: EvidenceKind = EvidenceKind.OBSERVED
    sensitivity: Sensitivity = Sensitivity.REDACT

    def __post_init__(self) -> None:
        require_non_empty(self.predicate, "predicate")
        require_non_empty(self.source_id, "source_id")
        require_non_empty(self.source_revision, "source_revision")
        if "@" not in self.predicate:
            raise ValueError("predicate must include a schema version")
        # EvidenceValue is declared scalar-only, but nothing previously enforced
        # it at construction.  A collection-valued `value` therefore serialised
        # happily and only failed later in decode_evidence(), after the corrupt
        # document had already replaced known-good persisted state.  Failing
        # fast here makes it impossible for any analyzer to emit evidence that
        # cannot be read back.  See domain/serialization.py::decode_evidence.
        if self.value is not None and not isinstance(self.value, str | int | float | bool):
            raise TypeError(
                "evidence.value must be a JSON scalar "
                f"(str|int|float|bool|None); got {type(self.value).__name__} "
                f"for predicate {self.predicate!r}"
            )
        object.__setattr__(
            self, "observed_at", require_utc(self.observed_at, "observed_at")
        )

    @property
    def evidence_id(self) -> str:
        """Return a stable identifier for this semantic observation."""
        return stable_digest(
            self.subject.identity_key,
            self.predicate,
            self.value,
            self.source_id,
            self.source_revision,
            self.kind.value,
        )
