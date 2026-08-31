"""Predeploy backup retention must never delete the wrong thing.

Only tests tools/deploy_backup.py's pure retention policy -- nothing here
opens a socket or shells out. The ssh-driving wrappers are a thin,
deliberately dumb layer over this policy and are exercised by mocking
subprocess.run, not by touching a real host.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tools import deploy_backup


def _names(*timestamps: str) -> tuple[str, ...]:
    return tuple(deploy_backup.backup_name(ts) for ts in timestamps)


def test_backup_name_round_trips_through_parse() -> None:
    name = deploy_backup.backup_name("20260830T041500Z")
    assert name == "hamie-predeploy-20260830T041500Z.tar.gz"
    assert deploy_backup.parse_backup_name(name) == "20260830T041500Z"


def test_backup_name_rejects_a_malformed_timestamp() -> None:
    with pytest.raises(deploy_backup.BackupError):
        deploy_backup.backup_name("not-a-timestamp")


@pytest.mark.parametrize(
    "name",
    ["README.md", "hamie-predeploy-broken.tar.gz", "hamie-predeploy-20260830T041500Z.zip", ""],
)
def test_parse_backup_name_returns_none_for_anything_not_ours(name: str) -> None:
    assert deploy_backup.parse_backup_name(name) is None


def test_keeps_only_the_newest_n_by_default() -> None:
    existing = _names(
        "20260101T000000Z", "20260102T000000Z", "20260103T000000Z",
        "20260104T000000Z", "20260105T000000Z", "20260106T000000Z", "20260107T000000Z",
    )
    plan = deploy_backup.plan_retention(existing, keep=5)

    assert set(plan.keep) == set(_names(
        "20260103T000000Z", "20260104T000000Z", "20260105T000000Z",
        "20260106T000000Z", "20260107T000000Z",
    ))
    assert set(plan.delete) == set(_names("20260101T000000Z", "20260102T000000Z"))
    assert set(plan.keep) & set(plan.delete) == set()


def test_default_keep_is_five() -> None:
    assert deploy_backup.DEFAULT_KEEP == 5
    existing = _names(*(f"2026010{i}T000000Z" for i in range(1, 8)))
    plan = deploy_backup.plan_retention(existing)
    assert len(plan.keep) == 5


def test_ranking_is_by_embedded_timestamp_not_input_order() -> None:
    existing = _names("20260105T000000Z", "20260101T000000Z", "20260103T000000Z")
    plan = deploy_backup.plan_retention(existing, keep=1)
    assert plan.keep == _names("20260105T000000Z")


def test_pinned_backups_survive_even_outside_the_keep_window() -> None:
    old = deploy_backup.backup_name("20200101T000000Z")
    existing = (old, *_names(*(f"2026010{i}T000000Z" for i in range(1, 8))))
    plan = deploy_backup.plan_retention(existing, keep=2, pinned=frozenset({old}))

    assert old in plan.keep
    assert old not in plan.delete


def test_pinning_a_name_not_present_is_a_silent_no_op() -> None:
    existing = _names("20260101T000000Z")
    plan = deploy_backup.plan_retention(
        existing, keep=5, pinned=frozenset({"hamie-predeploy-20991231T000000Z.tar.gz"})
    )
    assert plan.keep == existing
    assert plan.delete == ()


def test_required_for_rollback_survives_even_outside_the_keep_window() -> None:
    old = deploy_backup.backup_name("20200101T000000Z")
    existing = (old, *_names(*(f"2026010{i}T000000Z" for i in range(1, 8))))
    plan = deploy_backup.plan_retention(existing, keep=2, required_for_rollback=old)

    assert old in plan.keep
    assert old not in plan.delete


def test_unrecognised_filenames_are_never_delete_candidates() -> None:
    existing = (
        "README.md",
        ".DS_Store",
        *_names(*(f"2026010{i}T000000Z" for i in range(1, 8))),
    )
    plan = deploy_backup.plan_retention(existing, keep=1)

    assert "README.md" not in plan.delete
    assert ".DS_Store" not in plan.delete
    assert "README.md" not in plan.keep  # not touched at all, not "kept" either
    assert ".DS_Store" not in plan.keep


def test_keep_must_be_at_least_one() -> None:
    with pytest.raises(deploy_backup.BackupError):
        deploy_backup.plan_retention(_names("20260101T000000Z"), keep=0)


def test_fewer_backups_than_keep_deletes_nothing() -> None:
    existing = _names("20260101T000000Z", "20260102T000000Z")
    plan = deploy_backup.plan_retention(existing, keep=5)
    assert set(plan.keep) == set(existing)
    assert plan.delete == ()


def test_apply_retention_over_ssh_dry_run_issues_no_delete(monkeypatch) -> None:
    calls: list[str] = []

    def fake_ssh(target: str, command: str) -> str:
        calls.append(command)
        if command.startswith("mkdir -p"):
            return "\n".join(_names(*(f"2026010{i}T000000Z" for i in range(1, 8)))) + "\n"
        raise AssertionError(f"dry-run must never issue a mutating command: {command}")

    monkeypatch.setattr(deploy_backup, "_ssh", fake_ssh)
    plan = deploy_backup.apply_retention_over_ssh(
        "example-host", "/config/hamie_backups", keep=5, dry_run=True
    )

    assert len(plan.delete) == 2
    assert not any("rm " in c for c in calls)


def test_apply_retention_over_ssh_deletes_exactly_the_planned_set(monkeypatch) -> None:
    listed = "\n".join(_names(*(f"2026010{i}T000000Z" for i in range(1, 8))))
    rm_commands: list[str] = []

    def fake_ssh(target: str, command: str) -> str:
        if command.startswith("mkdir -p"):
            return listed
        if "rm -f" in command:
            rm_commands.append(command)
            return ""
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(deploy_backup, "_ssh", fake_ssh)
    plan = deploy_backup.apply_retention_over_ssh(
        "example-host", "/config/hamie_backups", keep=5, dry_run=False
    )

    assert len(rm_commands) == 1
    for name in plan.delete:
        assert name in rm_commands[0]
    for name in plan.keep:
        assert name not in rm_commands[0]


def test_ssh_wrapper_raises_backup_error_on_nonzero_exit() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "connection refused"
        with pytest.raises(deploy_backup.BackupError, match="connection refused"):
            deploy_backup._ssh("example-host", "echo hi")
