"""Security modes and narrow AI-access capability catalog."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SecurityMode(StrEnum):
    """HAMIE's two non-overlapping capability modes."""

    INVESTIGATION = "investigation"
    EXECUTION = "execution"


INVESTIGATION_TOOLS = frozenset(
    {
        "hamie_get_entity",
        "hamie_search_entities",
        "hamie_get_automation",
        "hamie_get_script",
        "hamie_get_automation_definition",
        "hamie_get_script_definition",
        "hamie_get_incident",
        "hamie_search_incidents",
        "hamie_get_dependencies",
        "hamie_get_target_writers",
        "hamie_get_recent_changes",
        "hamie_get_source",
        "hamie_get_git_status",
        "hamie_compare_source_deployment",
        "hamie_validate_proposed_change",
    }
)

# Execution is intentionally not an LLM tool catalog.  Existing remediation
# APIs require a durable plan, exact preview digest, and human approval record.
EXECUTION_TOOLS = frozenset()


@dataclass(frozen=True, slots=True)
class InvestigationBudget:
    """Per-call evidence bound; providers never receive an unbounded dump."""

    maximum_items: int = 50
    maximum_characters: int = 16_000

    def __post_init__(self) -> None:
        if not 1 <= self.maximum_items <= 100:
            raise ValueError("maximum_items must be between 1 and 100")
        if not 1_000 <= self.maximum_characters <= 64_000:
            raise ValueError("maximum_characters must be between 1000 and 64000")


def assert_tool_allowed(tool_name: str, mode: SecurityMode) -> None:
    """Reject any capability not explicitly in the selected mode."""
    allowed = INVESTIGATION_TOOLS if mode is SecurityMode.INVESTIGATION else EXECUTION_TOOLS
    if tool_name not in allowed:
        raise PermissionError(f"tool is unavailable in {mode.value} mode")
