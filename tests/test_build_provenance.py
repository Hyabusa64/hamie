"""Build provenance must be truthful, optional, and impossible to fake."""

import json
import re
from pathlib import Path

import pytest

from hamie.build_info import (
    BUILD_INFO_FILENAME,
    DIRTY_SUFFIX,
    UNKNOWN_BUILD,
    BuildInfo,
    read_build_info,
)
from hamie.const import VERSION

MANIFEST = Path(__file__).parent.parent / "hamie" / "manifest.json"
SEMVER_BETA = re.compile(r"^\d+\.\d+\.\d+-beta\.\d+$")

COMMIT = "d174df7195616413f80ff96d2f4ddf990fb6d033"[:12]


def _write(directory: Path, payload: object) -> Path:
    path = directory / BUILD_INFO_FILENAME
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return path


def test_manifest_version_is_a_beta_semantic_version() -> None:
    version = json.loads(MANIFEST.read_text())["version"]
    assert SEMVER_BETA.fullmatch(version), version


def test_const_version_comes_from_the_manifest() -> None:
    assert VERSION == json.loads(MANIFEST.read_text())["version"]


def test_build_info_is_read_when_shipped(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "build_commit": COMMIT,
            "build_timestamp": "2026-08-30T04:00:00Z",
            "build_dirty": False,
        },
    )
    info = read_build_info(tmp_path)

    assert info.available
    assert info.build_commit == COMMIT
    assert info.build_timestamp == "2026-08-30T04:00:00Z"
    assert info.dirty is False
    assert info.display_commit == COMMIT


def test_missing_build_info_degrades_to_unknown(tmp_path: Path) -> None:
    """Running from a source checkout must not break the integration."""
    info = read_build_info(tmp_path)

    assert info == UNKNOWN_BUILD
    assert not info.available
    assert info.display_commit is None


@pytest.mark.parametrize(
    "payload",
    (
        "{ not json",
        json.dumps([1, 2, 3]),
        json.dumps({"build_commit": ""}),
        json.dumps({"build_commit": "zzzz-not-hex"}),
        json.dumps({"build_commit": "abc"}),
        json.dumps({"build_commit": 12345}),
        json.dumps({"build_timestamp": "2026-08-30T04:00:00Z"}),
    ),
)
def test_malformed_build_info_is_treated_as_unknown(tmp_path: Path, payload: str) -> None:
    """A corrupt marker must never be reported as real provenance."""
    _write(tmp_path, payload)

    assert read_build_info(tmp_path) == UNKNOWN_BUILD


def test_dirty_builds_are_marked_and_cannot_masquerade_as_clean() -> None:
    dirty = BuildInfo(build_commit=COMMIT, build_timestamp=None, dirty=True)

    assert dirty.display_commit == f"{COMMIT}{DIRTY_SUFFIX}"
    assert dirty.display_commit != COMMIT
    assert dirty.as_dict()["build_dirty"] is True


def test_as_dict_exposes_exactly_the_provenance_fields() -> None:
    info = BuildInfo(build_commit=COMMIT, build_timestamp="2026-08-30T04:00:00Z", dirty=False)

    assert info.as_dict() == {
        "build_commit": COMMIT,
        "build_timestamp": "2026-08-30T04:00:00Z",
        "build_dirty": False,
    }


def test_unknown_build_still_serialises_for_diagnostics() -> None:
    """Diagnostics must render even with no provenance shipped."""
    assert UNKNOWN_BUILD.as_dict() == {
        "build_commit": None,
        "build_timestamp": None,
        "build_dirty": False,
    }


def test_packaging_excludes_build_artefacts_and_macos_sidecars(tmp_path: Path) -> None:
    """A package must contain integration code and nothing else.

    macOS ``tar`` emits AppleDouble ``._*`` sidecars; deploying them once put
    225 junk files into the live integration, so exclusion is asserted here.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_deploy", Path(__file__).parent.parent / "tools" / "build_deploy.py"
    )
    assert spec and spec.loader
    build_deploy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_deploy)

    (tmp_path / "keep.py").write_text("x = 1\n")
    (tmp_path / "._keep.py").write_text("apple double\n")
    (tmp_path / ".DS_Store").write_text("junk\n")
    (tmp_path / ".coverage").write_text("junk\n")
    (tmp_path / "stale.pyc").write_text("junk\n")
    (tmp_path / "stale.pyo").write_text("junk\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "keep.cpython-313.pyc").write_text("junk\n")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "v").write_text("junk\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("junk\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("junk\n")
    (tmp_path / ".mypy_cache").mkdir()
    (tmp_path / ".mypy_cache" / "cache.json").write_text("junk\n")
    (tmp_path / ".ruff_cache").mkdir()
    (tmp_path / ".ruff_cache" / "cache").write_text("junk\n")
    (tmp_path / "htmlcov").mkdir()
    (tmp_path / "htmlcov" / "index.html").write_text("junk\n")

    names = {p.name for p in build_deploy.meaningful_files(tmp_path)}

    assert names == {"keep.py"}
