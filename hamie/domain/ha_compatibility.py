"""Version-aware Home Assistant compatibility rule registry.

Repair-orchestration Phase 4. This is the *mechanism* only. Per this
project's own evidentiary discipline (see
``docs/REPAIR_TAXONOMY_EVIDENCE.md``: "don't fabricate evidence you
don't have," the precedent the 2026-08-25 disposition review
established), ``DEFAULT_HA_COMPATIBILITY_RULES`` ships **empty**. No
deprecated-syntax, renamed-selector, or removed-attribute incident was
found anywhere in this project's real git history or forensic reports
to build a rule from -- inventing one from general Home Assistant
release-note knowledge, rather than a proven real instance, is exactly
the "design from hypotheticals" the repair-orchestration mission
explicitly warned against. A rule belongs here only once a real
instance justifies it (see ``docs/REPAIR_ORCHESTRATION.md``'s matrix row
for this class, and the Phase 21 "learn from a real repair" workflow).

A rule is always **detection first**: ``rewrite`` is optional, and a
rule with no rewrite is still useful as an evidence source for
OPERATOR_DECISION_REQUIRED even when no safe automatic fix exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .common import require_non_empty

#: A dotted Home Assistant release string, e.g. "2026.8.3" or "2026.8".
HaVersion = tuple[int, ...]


def parse_ha_version(version: str) -> HaVersion:
    """Parse a Home Assistant release string into a comparable tuple.

    Only the numeric dot-separated prefix is used
    (``"2026.8.3"`` -> ``(2026, 8, 3)``); anything after a non-numeric
    component (a beta/dev suffix) is ignored rather than rejected, since
    version *ordering* is all this registry ever needs.
    """
    require_non_empty(version, "version")
    parts: list[int] = []
    for segment in version.split("."):
        digits = ""
        for char in segment:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    if not parts:
        raise ValueError(f"could not parse a Home Assistant version from {version!r}")
    return tuple(parts)


@dataclass(frozen=True, slots=True)
class HACompatibilityFinding:
    """One rule's verdict against one parsed config structure."""

    rule_id: str
    description: str
    documentation_reference: str
    rewrite_available: bool


@dataclass(frozen=True, slots=True)
class HACompatibilityRule:
    """One deterministic, version-bounded compatibility check.

    ``detect`` and ``rewrite`` operate on an already-parsed config
    structure (the same shape ``domain/definition_inspection.py`` and
    ``domain/action_duplication.py`` take) -- never raw text, and never
    a live ``hass`` object. A rule with no evidence to prove its
    ``rewrite`` produces the exact supported replacement must leave
    ``rewrite`` as ``None``; a wrong guess published as a "safe rewrite"
    is worse than no rewrite at all.
    """

    rule_id: str
    description: str
    min_ha_version: HaVersion | None
    max_ha_version: HaVersion | None
    detect: Callable[[dict[str, Any]], bool]
    rewrite: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    documentation_reference: str = ""

    def __post_init__(self) -> None:
        require_non_empty(self.rule_id, "rule_id")
        require_non_empty(self.description, "description")

    def applies_to_version(self, ha_version: HaVersion) -> bool:
        if self.min_ha_version is not None and ha_version < self.min_ha_version:
            return False
        if self.max_ha_version is not None and ha_version > self.max_ha_version:
            return False
        return True

    def evaluate(self, structure: dict[str, Any]) -> HACompatibilityFinding | None:
        if not self.detect(structure):
            return None
        return HACompatibilityFinding(
            rule_id=self.rule_id,
            description=self.description,
            documentation_reference=self.documentation_reference,
            rewrite_available=self.rewrite is not None,
        )

    def apply_rewrite(self, structure: dict[str, Any]) -> dict[str, Any]:
        if self.rewrite is None:
            raise ValueError(f"rule {self.rule_id!r} has no deterministic rewrite")
        if not self.detect(structure):
            raise ValueError(
                f"refusing to apply rule {self.rule_id!r}'s rewrite to a structure "
                "its own detect() does not match"
            )
        return self.rewrite(structure)


class HACompatibilityRegistry:
    """A versioned collection of rules, queried by target HA release."""

    def __init__(self, rules: tuple[HACompatibilityRule, ...] = ()) -> None:
        ids = [rule.rule_id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule_id in compatibility registry")
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[HACompatibilityRule, ...]:
        return self._rules

    def register(self, rule: HACompatibilityRule) -> "HACompatibilityRegistry":
        """Return a new registry with one more rule (immutable style)."""
        return HACompatibilityRegistry((*self._rules, rule))

    def applicable_rules(self, ha_version: HaVersion) -> tuple[HACompatibilityRule, ...]:
        return tuple(rule for rule in self._rules if rule.applies_to_version(ha_version))

    def evaluate(
        self, structure: dict[str, Any], *, ha_version: HaVersion
    ) -> tuple[HACompatibilityFinding, ...]:
        """Run every version-applicable rule against one parsed structure."""
        findings = []
        for rule in self.applicable_rules(ha_version):
            finding = rule.evaluate(structure)
            if finding is not None:
                findings.append(finding)
        return tuple(findings)


#: Empty by design -- see module docstring. Populate only from a real,
#: cited repair instance (docs/REPAIR_ORCHESTRATION.md's matrix +
#: docs/REPAIR_TAXONOMY_EVIDENCE.md), never from general Home Assistant
#: release-note knowledge alone.
DEFAULT_HA_COMPATIBILITY_RULES: tuple[HACompatibilityRule, ...] = ()


def default_registry() -> HACompatibilityRegistry:
    return HACompatibilityRegistry(DEFAULT_HA_COMPATIBILITY_RULES)
