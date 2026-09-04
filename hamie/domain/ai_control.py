"""AI operating mode and AI Control acknowledgement (cleanup engine).

Three explicit, user-selected operating modes govern how much autonomy
HAMIE's cleanup engine has:

- ``OBSERVE`` -- analyze, group, explain, recommend, draft proposals.
  Never mutates Home Assistant. The default for every existing and new
  installation (see Part 30 migration discipline: existing users default
  safely to Observe).
- ``ASSISTED_CLEANUP`` -- after the user explicitly enables it, HAMIE may
  automatically execute allowlisted, reversible, low-risk cleanup
  operations once deterministic dependency/eligibility checks pass, with
  no per-object approval required.
- ``AI_CONTROL`` -- broader maintenance control. Reaching this tier's
  actual automatic-execution behavior additionally requires a current,
  durable ``AiControlAcknowledgement`` (see below) -- setting the config
  option alone is not sufficient. This is a deliberate two-key design:
  the option expresses *intent*, the acknowledgement expresses *informed
  consent*, and only both together unlock AI-Control-tier automation.

Pure and I/O-free, matching every other ``domain/`` module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .common import require_non_empty, require_utc
from .findings import RiskLevel

# Bump this whenever the acknowledgement text (mission Part 21) changes
# materially -- a stored acknowledgement whose version does not match is
# treated as absent, forcing re-acknowledgement (AiControlAcknowledgement
# .is_current_for()).
AI_CONTROL_ACKNOWLEDGEMENT_VERSION = 1

AI_CONTROL_ACKNOWLEDGEMENT_TEXT = (
    "I understand that HAMIE may modify my Home Assistant configuration "
    "and registry using supported maintenance actions, and I accept "
    "responsibility for enabling AI Control."
)


class AiOperatingMode(StrEnum):
    """The user-selected AI autonomy tier (mission Part 1)."""

    OBSERVE = "observe"
    ASSISTED_CLEANUP = "assisted_cleanup"
    AI_CONTROL = "ai_control"


@dataclass(frozen=True, slots=True)
class AiControlAcknowledgement:
    """Durable evidence that a human explicitly accepted AI Control.

    Never inferred, never defaulted to true -- only created by the
    dedicated acknowledgement command (mission Part 21), which requires
    the exact checkbox/confirmation text.
    """

    version: int
    acknowledged_at: datetime
    acknowledged_by: str

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("acknowledgement version must be positive")
        require_non_empty(self.acknowledged_by, "acknowledged_by")
        object.__setattr__(
            self,
            "acknowledged_at",
            require_utc(self.acknowledged_at, "acknowledged_at"),
        )

    @property
    def is_current(self) -> bool:
        """Return whether this acknowledgement still matches the current text."""
        return self.version == AI_CONTROL_ACKNOWLEDGEMENT_VERSION


def encode_ai_control_acknowledgement(
    value: AiControlAcknowledgement | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "version": value.version,
        "acknowledged_at": value.acknowledged_at.isoformat().replace("+00:00", "Z"),
        "acknowledged_by": value.acknowledged_by,
    }


def decode_ai_control_acknowledgement(
    raw: object,
) -> AiControlAcknowledgement | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("ai_control_acknowledgement must be an object")
    acknowledged_at = datetime.fromisoformat(str(raw["acknowledged_at"]))
    if acknowledged_at.tzinfo is None:
        acknowledged_at = acknowledged_at.replace(tzinfo=UTC)
    return AiControlAcknowledgement(
        version=int(raw["version"]),
        acknowledged_at=acknowledged_at,
        acknowledged_by=str(raw["acknowledged_by"]),
    )


def effective_ai_mode(
    *,
    configured_mode: AiOperatingMode,
    acknowledgement: AiControlAcknowledgement | None,
) -> AiOperatingMode:
    """Return the mode HAMIE actually behaves as, never the raw config alone.

    ``AI_CONTROL``'s real automatic-execution power is only ever unlocked
    by a *current* acknowledgement record -- an operator setting the
    option without ever completing the acknowledgement flow (or after
    the acknowledgement text changed and the old record went stale)
    fails closed to ``ASSISTED_CLEANUP`` behavior, never silently to
    full AI Control and never to a crash.
    """
    if configured_mode is AiOperatingMode.AI_CONTROL:
        if acknowledgement is not None and acknowledgement.is_current:
            return AiOperatingMode.AI_CONTROL
        return AiOperatingMode.ASSISTED_CLEANUP
    return configured_mode


def is_low_risk_auto_execute_allowed(
    *, mode: AiOperatingMode, auto_execute_low_risk_setting: bool
) -> bool:
    """Return whether a safe_auto_fix-classified action may run without
    per-object approval right now.

    Observe never auto-executes regardless of the stored setting -- the
    mode gate is checked first and is authoritative.
    """
    if mode is AiOperatingMode.OBSERVE:
        return False
    return auto_execute_low_risk_setting


def is_medium_risk_auto_execute_allowed(
    *, mode: AiOperatingMode, auto_execute_medium_risk_setting: bool
) -> bool:
    """Return whether a medium-risk action may run without per-object approval.

    Medium-risk auto-execution is only ever available at the AI Control
    tier (mission Part 2: "Auto-execute medium-risk repairs... Only
    available in AI Control") -- Observe and Assisted Cleanup can never
    reach this regardless of the stored setting.
    """
    if mode is not AiOperatingMode.AI_CONTROL:
        return False
    return auto_execute_medium_risk_setting


def is_risk_class_auto_executable(
    *,
    risk: RiskLevel,
    mode: AiOperatingMode,
    auto_execute_low_risk_setting: bool,
    auto_execute_medium_risk_setting: bool,
) -> bool:
    """Return whether one risk classification may auto-execute under the
    current mode/settings. HIGH and CRITICAL are never auto-executable
    through this path regardless of mode or settings -- mission Part 1's
    "High-risk or destructive operations should remain separately
    classified" is enforced here, not left to caller discipline.
    """
    if risk is RiskLevel.LOW:
        return is_low_risk_auto_execute_allowed(
            mode=mode, auto_execute_low_risk_setting=auto_execute_low_risk_setting
        )
    if risk is RiskLevel.MEDIUM:
        return is_medium_risk_auto_execute_allowed(
            mode=mode,
            auto_execute_medium_risk_setting=auto_execute_medium_risk_setting,
        )
    return False
