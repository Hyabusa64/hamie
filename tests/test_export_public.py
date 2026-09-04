"""tools/export_public.py must never leave a half-sanitized export behind."""

from __future__ import annotations

import os
import subprocess

import pytest

from tools import export_public


def _git(*args: str, cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: str) -> None:
    _git("init", "-q", cwd=root)
    _git("config", "user.email", "test@example.invalid", cwd=root)
    _git("config", "user.name", "Test", cwd=root)


def _write(root: str, rel_path: str, content: str) -> None:
    full = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as handle:
        handle.write(content)


def _commit_all(root: str) -> None:
    _git("add", "-A", cwd=root)
    _git("commit", "-q", "-m", "seed", cwd=root)


def test_clean_tree_exports_everything_tracked(tmp_path) -> None:
    source = str(tmp_path / "source")
    os.makedirs(source)
    _init_repo(source)
    _write(source, "README.md", "hello world\n")
    _write(source, "pkg/mod.py", "def f():\n    return 1\n")
    _commit_all(source)

    dest = str(tmp_path / "dest")
    manifest = export_public.export(source, dest, dry_run=False)

    assert sorted(manifest.exported) == ["README.md", "pkg/mod.py"]
    assert manifest.excluded == []
    assert os.path.isfile(os.path.join(dest, "README.md"))
    assert os.path.isfile(os.path.join(dest, "pkg", "mod.py"))
    assert not os.path.isdir(os.path.join(dest, ".git"))
    assert os.path.isfile(dest.rstrip(os.sep) + ".manifest.txt")


def test_excluded_prefixes_never_reach_the_export(tmp_path) -> None:
    source = str(tmp_path / "source")
    os.makedirs(source)
    _init_repo(source)
    _write(source, "README.md", "hello world\n")
    _write(source, "benchmark/real_household_dump.json", '{"secret": "irrelevant"}\n')
    _write(source, "analysis/findings.json", '{"finding": "irrelevant"}\n')
    _write(source, "docs/ACCESS_MAP.md", "10.91.1.1 -> ha\n")
    _write(source, "docs/SECURITY.md", "real unrotated credential inventory\n")
    _write(source, "docs/CHECKPOINT.md", "real live finding counts\n")
    _write(source, "tools/reviewed_snapshots.txt", "benchmark/live_snapshot/x.json\n")
    _write(source, "docs/REPAIR_TAXONOMY_EVIDENCE.md", "real automation names and incidents\n")
    _commit_all(source)

    dest = str(tmp_path / "dest")
    manifest = export_public.export(source, dest, dry_run=False)

    assert manifest.exported == ["README.md"]
    assert set(manifest.excluded) == {
        "benchmark/real_household_dump.json",
        "analysis/findings.json",
        "docs/ACCESS_MAP.md",
        "docs/SECURITY.md",
        "docs/CHECKPOINT.md",
        "tools/reviewed_snapshots.txt",
        "docs/REPAIR_TAXONOMY_EVIDENCE.md",
    }
    assert not os.path.exists(os.path.join(dest, "benchmark"))
    assert not os.path.exists(os.path.join(dest, "analysis"))
    assert not os.path.exists(os.path.join(dest, "docs", "ACCESS_MAP.md"))


def test_untracked_files_are_invisible_to_export(tmp_path) -> None:
    """git ls-files is the allowlist -- an un-added file cannot leak."""
    source = str(tmp_path / "source")
    os.makedirs(source)
    _init_repo(source)
    _write(source, "README.md", "hello world\n")
    _commit_all(source)
    _write(source, "stray/never_added.json", "10.91.1.1 real household data\n")

    dest = str(tmp_path / "dest")
    manifest = export_public.export(source, dest, dry_run=False)

    assert manifest.exported == ["README.md"]
    assert not os.path.exists(os.path.join(dest, "stray"))


@pytest.mark.parametrize(
    ("needle", "expected_substring"),
    [
        ("switch.office_tapo_ai_pc_plug", "switch.example_inference_host_plug"),
        ("switch.office_tapo_smart_strip_switch_1", "switch.example_inference_host_plug_matter"),
        ("device_tracker.keris_iphone_15", "device_tracker.example_phone_15"),
        ("device_tracker.keris_iphone_15_2", "device_tracker.example_phone_15_2"),
        ("MECCA / DESKTOP-29H0UF1", "EXAMPLE-HOST / EXAMPLE-DESKTOP-01"),
        ("10.91.1.50:11434", "192.0.2.10:11434"),
        (
            "8022DC0FD77C8ED239C2BAFF292A5AD9249AEDD400",
            "TPLINKEXAMPLE00000000000000000000000000001",
        ),
        ("unique_id ...9AEDD400", "unique_id ...EXAMPLE00"),
    ],
)
def test_known_private_literals_are_substituted(tmp_path, needle, expected_substring) -> None:
    source = str(tmp_path / "source")
    os.makedirs(source)
    _init_repo(source)
    _write(source, "hamie/domain/protected_dependencies.py", f"VALUE = {needle!r}\n")
    _commit_all(source)

    dest = str(tmp_path / "dest")
    export_public.export(source, dest, dry_run=False)

    with open(os.path.join(dest, "hamie", "domain", "protected_dependencies.py"), encoding="utf-8") as handle:
        exported_text = handle.read()
    assert expected_substring in exported_text
    assert needle not in exported_text


def test_substitution_survives_a_literal_wrapped_across_two_string_pieces(tmp_path) -> None:
    """Regression: a source file that spells one private literal as two
    adjacent string literals ("...001D-" \n "MatterNodeDevice-...") must
    not let the real fingerprint survive just because it isn't contiguous
    text on a single line of the file.
    """
    source = str(tmp_path / "source")
    os.makedirs(source)
    _init_repo(source)
    _write(
        source,
        "hamie/domain/protected_dependencies.py",
        'unique_id=(\n'
        '    "FAAD046E75459CE1-000000000000001D-"\n'
        '    "MatterNodeDevice-1-MatterPlug-6-0"\n'
        '),\n',
    )
    _commit_all(source)

    dest = str(tmp_path / "dest")
    export_public.export(source, dest, dry_run=False)

    with open(os.path.join(dest, "hamie", "domain", "protected_dependencies.py"), encoding="utf-8") as handle:
        exported_text = handle.read()
    assert "FAAD046E75459CE1" not in exported_text
    assert "MATTEREXAMPLE001-0000000000000001-" in exported_text


def test_export_refuses_to_overwrite_an_existing_destination(tmp_path) -> None:
    source = str(tmp_path / "source")
    os.makedirs(source)
    _init_repo(source)
    _write(source, "README.md", "hello\n")
    _commit_all(source)

    dest = str(tmp_path / "dest")
    os.makedirs(dest)
    _write(dest, "already_here.txt", "pre-existing\n")

    with pytest.raises(export_public.ExportError):
        export_public.export(source, dest, dry_run=False)

    # untouched -- the pre-existing content must survive a refused export.
    assert os.path.isfile(os.path.join(dest, "already_here.txt"))


def test_a_private_literal_missing_from_the_substitution_table_aborts_and_cleans_up(tmp_path) -> None:
    """The FORBIDDEN_AFTER_EXPORT sweep is a safety net independent of the
    substitution table: something the table doesn't know about must still
    block publication rather than silently pass through.
    """
    source = str(tmp_path / "source")
    os.makedirs(source)
    _init_repo(source)
    _write(source, "README.md", "hello\n")
    # A literal from FORBIDDEN_AFTER_EXPORT that SUBSTITUTIONS does not cover.
    _write(source, "notes.md", "reachable at 10.91.7.200 on the LAN\n")
    _commit_all(source)

    dest = str(tmp_path / "dest")
    with pytest.raises(export_public.ExportError, match="PUBLICATION MUST STOP"):
        export_public.export(source, dest, dry_run=False)

    assert not os.path.exists(dest)
    assert not os.path.exists(dest.rstrip(os.sep) + ".manifest.txt")


def test_a_credential_shaped_secret_aborts_and_cleans_up(tmp_path) -> None:
    """Independent layer #2: tools/secret_scan.py itself, not just the
    household-literal sweep.
    """
    source = str(tmp_path / "source")
    os.makedirs(source)
    _init_repo(source)
    _write(source, "README.md", "hello\n")
    _write(
        source,
        "leaked.json",
        '{"api_key": "sk-live-abcdefghijklmnopqrstuvwxyz0123456789ABCD"}\n',
    )
    _commit_all(source)

    dest = str(tmp_path / "dest")
    with pytest.raises(export_public.ExportError, match="PUBLICATION MUST STOP"):
        export_public.export(source, dest, dry_run=False)

    assert not os.path.exists(dest)


def test_dry_run_reports_without_writing_anything(tmp_path) -> None:
    source = str(tmp_path / "source")
    os.makedirs(source)
    _init_repo(source)
    _write(source, "README.md", "hello\n")
    _write(source, "benchmark/x.json", "{}\n")
    _commit_all(source)

    dest = str(tmp_path / "dest")
    manifest = export_public.export(source, dest, dry_run=True)

    assert manifest.exported == ["README.md"]
    assert manifest.excluded == ["benchmark/x.json"]
    assert not os.path.exists(dest)


def test_self_referential_paths_are_copied_verbatim_not_substituted(tmp_path) -> None:
    """Regression: this tool's own source (and its own tests) legitimately
    contain the exact literals SUBSTITUTIONS/FORBIDDEN_AFTER_EXPORT exist to
    catch, as configuration data and test fixtures -- not as leaked real
    content. Running the substitution table against export_public.py's own
    source would corrupt it (several tuples have identical key/value once
    the key matches itself); this must not happen, and must not trip the
    forbidden-literal sweep either.
    """
    source = str(tmp_path / "source")
    os.makedirs(source)
    _init_repo(source)
    literal_text = "SUBSTITUTIONS = (('MECCA', 'EXAMPLE-HOST'), ('10.91.1.50', 'x'))\n"
    _write(source, "tools/export_public.py", literal_text)
    _write(source, "tests/test_export_public.py", "NEEDLE = 'MECCA'\n")
    _commit_all(source)

    dest = str(tmp_path / "dest")
    manifest = export_public.export(source, dest, dry_run=False)

    with open(os.path.join(dest, "tools", "export_public.py"), encoding="utf-8") as handle:
        assert handle.read() == literal_text
    with open(os.path.join(dest, "tests", "test_export_public.py"), encoding="utf-8") as handle:
        assert handle.read() == "NEEDLE = 'MECCA'\n"
    assert manifest.exported  # export succeeded rather than aborting


def test_binary_files_are_copied_without_a_text_decode_attempt(tmp_path) -> None:
    source = str(tmp_path / "source")
    os.makedirs(source)
    _init_repo(source)
    payload = bytes(range(256))
    with open(os.path.join(source, "asset.png"), "wb") as handle:
        handle.write(payload)
    _commit_all(source)

    dest = str(tmp_path / "dest")
    export_public.export(source, dest, dry_run=False)

    with open(os.path.join(dest, "asset.png"), "rb") as handle:
        assert handle.read() == payload
