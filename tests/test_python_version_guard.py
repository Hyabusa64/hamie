"""hamie/__init__.py must fail with a clear message on Python < 3.12.

Without this, importing hamie on an old interpreter surfaces as a bare
"SyntaxError: expected '('" deep inside domain/knowledge_serialization.py
(PEP 695 generic syntax), with no indication it's a version problem.
"""

from __future__ import annotations

import importlib
import sys

import pytest

import hamie


def test_current_interpreter_imports_hamie_cleanly() -> None:
    # If this test file collected at all, this already happened -- but
    # assert it explicitly so a future regression is a clear failure here,
    # not a mysterious later one.
    assert sys.version_info >= (3, 12)
    assert hamie is not None


def test_import_fails_clearly_below_python_3_12(monkeypatch) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 11, 0, "final", 0))
    try:
        with pytest.raises(RuntimeError, match="3.12"):
            importlib.reload(hamie)
    finally:
        # Restore the real version and re-load hamie in its normal,
        # working state so later tests in the same process aren't left
        # with a half-initialized module.
        monkeypatch.undo()
        importlib.reload(hamie)
