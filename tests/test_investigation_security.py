"""Investigation and execution capabilities cannot be conflated."""

import pytest

from hamie.domain.investigation import (
    EXECUTION_TOOLS,
    INVESTIGATION_TOOLS,
    InvestigationBudget,
    SecurityMode,
    assert_tool_allowed,
)


def test_investigation_catalog_has_no_execution_tools() -> None:
    assert EXECUTION_TOOLS == frozenset()
    assert "hamie_get_entity" in INVESTIGATION_TOOLS
    assert not any(
        name.startswith(("hamie_execute", "hamie_deploy", "hamie_apply"))
        for name in INVESTIGATION_TOOLS
    )


def test_investigation_tool_rejected_in_execution_mode() -> None:
    with pytest.raises(PermissionError):
        assert_tool_allowed("hamie_get_entity", SecurityMode.EXECUTION)


def test_investigation_budget_is_bounded() -> None:
    with pytest.raises(ValueError):
        InvestigationBudget(maximum_items=10_000)
