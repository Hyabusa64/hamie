"""Gate H's failure hook must be inert everywhere except when armed.

Gate H needs proof that a group which is selected, attempted, and then
rejected is excluded from achieved coverage. The real provider keeps
succeeding (correctly), and sabotaging Ollama or the AI PC to force a failure
would break the protected invariant HAMIE exists to defend. So the failure is
injected -- and these tests pin the refusals rather than the feature.
"""

from __future__ import annotations

import pytest

from hamie.application.operations_service import (
    ANALYSIS_FAIL_MARKER,
    InjectedAnalysisFailure,
    read_analysis_fail_group,
)


def _arm(tmp_path, value: str) -> str:
    (tmp_path / ANALYSIS_FAIL_MARKER).write_text(value, encoding="utf-8")
    return str(tmp_path)


def test_disabled_when_no_marker_exists(tmp_path):
    assert read_analysis_fail_group(str(tmp_path)) == ""


def test_armed_marker_names_exactly_one_group(tmp_path):
    assert read_analysis_fail_group(_arm(tmp_path, "grp_abc123")) == "grp_abc123"


def test_whitespace_is_stripped_not_matched(tmp_path):
    assert read_analysis_fail_group(_arm(tmp_path, "  grp_abc123 \n")) == "grp_abc123"


def test_empty_marker_arms_nothing(tmp_path):
    # An empty file must not become a wildcard that fails every group.
    assert read_analysis_fail_group(_arm(tmp_path, "   \n")) == ""


def test_unreadable_directory_arms_nothing(tmp_path):
    assert read_analysis_fail_group(str(tmp_path / "does-not-exist")) == ""


def test_injected_failure_classifies_as_a_provider_error():
    # It must travel the same typed-error path a real connector failure does,
    # or the accounting it is meant to prove would not be the real accounting.
    err = InjectedAnalysisFailure("boom")
    assert err.code == "provider_execution_failed"
    assert isinstance(err, RuntimeError)
