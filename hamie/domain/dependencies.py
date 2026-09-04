"""Dependency assessment values required by recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .common import require_non_empty
from .identity import SubjectIdentity


class DependencyCoverage(StrEnum):
    """Coverage of dependencies relevant to a recommendation."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class DependencyAssessment:
    """Bounded dependency context for one subject recommendation."""

    subject: SubjectIdentity
    required_capabilities: tuple[str, ...]
    used_capabilities: tuple[str, ...]
    coverage: DependencyCoverage
    rationale: str
    supporting_subject_ids: tuple[str, ...] = ()
    referenced_by: tuple[str, ...] = ()
    safe_to_remove: bool = False

    def __post_init__(self) -> None:
        require_non_empty(self.rationale, "rationale")
        object.__setattr__(
            self,
            "required_capabilities",
            tuple(sorted(set(self.required_capabilities))),
        )
        object.__setattr__(
            self, "used_capabilities", tuple(sorted(set(self.used_capabilities)))
        )
        object.__setattr__(
            self,
            "supporting_subject_ids",
            tuple(sorted(set(self.supporting_subject_ids))),
        )
        object.__setattr__(
            self,
            "referenced_by",
            tuple(sorted(set(self.referenced_by))),
        )
        if not set(self.used_capabilities) <= set(self.required_capabilities):
            raise ValueError("used capabilities must be required capabilities")
        if self.safe_to_remove and self.referenced_by:
            raise ValueError("a referenced subject cannot be safe to remove")
        if self.safe_to_remove and self.coverage is not DependencyCoverage.COMPLETE:
            raise ValueError("safe removal requires complete dependency coverage")
