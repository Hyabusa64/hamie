"""tools/build_deploy.py's --deploy pipeline: order, rollback, retention.

Every ssh/rsync/test/scan boundary is monkeypatched. Nothing here shells
out, touches a network, or runs the real test suite recursively.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import build_deploy

# The SAME module object build_deploy.py calls through (it does its own
# sys.path.insert + bare `import deploy_backup`, a different sys.modules
# key than `tools.deploy_backup`) -- patching that other identity here
# would silently miss every call build_deploy.deploy() actually makes.
deploy_backup = build_deploy.deploy_backup


@pytest.fixture(autouse=True)
def _stub_preflight_and_package(monkeypatch):
    monkeypatch.setattr(
        build_deploy, "preflight", lambda *, allow_dirty: ("0.6.0-beta.1", "abc123def456", False)
    )
    monkeypatch.setattr(build_deploy, "package", lambda destination, *, allow_dirty: None)
    monkeypatch.setattr(build_deploy, "run_tests", lambda: None)
    monkeypatch.setattr(build_deploy, "run_secret_scan", lambda: None)


def _stub_backup(monkeypatch, *, create_name="hamie-predeploy-20260830T000000Z.tar.gz"):
    calls: list[str] = []

    def fake_create(target, deploy_path, backup_dir, timestamp):
        calls.append("create")
        return create_name

    def fake_retention(target, backup_dir, *, keep, required_for_rollback=None, **kw):
        calls.append("retention")
        return deploy_backup.RetentionPlan(keep=(create_name,), delete=())

    monkeypatch.setattr(deploy_backup, "create_backup_over_ssh", fake_create)
    monkeypatch.setattr(deploy_backup, "apply_retention_over_ssh", fake_retention)
    return calls


def test_successful_deploy_calls_every_stage_in_order(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    backup_calls = _stub_backup(monkeypatch)

    monkeypatch.setattr(build_deploy, "_rsync", lambda staging, *, target, deploy_path: calls.append("rsync"))
    monkeypatch.setattr(
        build_deploy, "verify_parity", lambda staging, *, target, deploy_path: calls.append("parity")
    )
    monkeypatch.setattr(build_deploy, "_ssh", lambda command, *, target: calls.append("ssh:" + command.split()[0]))
    monkeypatch.setattr(build_deploy, "wait_for_startup", lambda *, target, deploy_path: calls.append("wait"))
    monkeypatch.setattr(
        build_deploy, "verify_runtime",
        lambda version, commit, *, target, deploy_path: calls.append("runtime"),
    )

    result = build_deploy.deploy(
        target="example-host",
        deploy_path="/config/custom_components/hamie",
        backup_dir="/config/hamie_backups",
        restart_command="ha core restart",
    )

    assert calls == ["rsync", "parity", "ssh:ha", "wait", "runtime"]
    assert backup_calls == ["create", "retention"]
    assert result["version"] == "0.6.0-beta.1"
    assert result["commit"] == "abc123def456"
    assert result["backup"] == "hamie-predeploy-20260830T000000Z.tar.gz"


def test_retention_is_told_the_backup_it_must_never_delete(monkeypatch) -> None:
    seen: dict[str, object] = {}
    _stub_backup(monkeypatch)

    def fake_retention(target, backup_dir, *, keep, required_for_rollback=None, **kw):
        seen["required_for_rollback"] = required_for_rollback
        return deploy_backup.RetentionPlan(keep=(), delete=())

    monkeypatch.setattr(deploy_backup, "apply_retention_over_ssh", fake_retention)
    monkeypatch.setattr(build_deploy, "_rsync", lambda *a, **k: None)
    monkeypatch.setattr(build_deploy, "verify_parity", lambda *a, **k: None)
    monkeypatch.setattr(build_deploy, "_ssh", lambda *a, **k: None)
    monkeypatch.setattr(build_deploy, "wait_for_startup", lambda *a, **k: None)
    monkeypatch.setattr(build_deploy, "verify_runtime", lambda *a, **k: None)

    build_deploy.deploy(
        target="example-host", deploy_path="/x", backup_dir="/backups", restart_command="ha core restart",
    )

    assert seen["required_for_rollback"] == "hamie-predeploy-20260830T000000Z.tar.gz"


def test_a_failed_parity_check_triggers_rollback_and_restart(monkeypatch) -> None:
    calls: list[str] = []
    _stub_backup(monkeypatch)

    monkeypatch.setattr(build_deploy, "_rsync", lambda *a, **k: calls.append("rsync"))

    def failing_parity(*a, **k):
        calls.append("parity")
        raise build_deploy.BuildError("parity mismatch")

    monkeypatch.setattr(build_deploy, "verify_parity", failing_parity)
    monkeypatch.setattr(build_deploy, "_ssh", lambda command, *, target: calls.append("ssh"))
    monkeypatch.setattr(build_deploy, "wait_for_startup", lambda *a, **k: calls.append("wait"))
    monkeypatch.setattr(
        deploy_backup, "restore_backup_over_ssh",
        lambda target, deploy_path, backup_dir, name: calls.append(f"restore:{name}"),
    )

    with pytest.raises(build_deploy.BuildError, match="deploy failed, rolled back successfully"):
        build_deploy.deploy(
            target="example-host", deploy_path="/x", backup_dir="/backups",
            restart_command="ha core restart",
        )

    assert calls == [
        "rsync", "parity",
        "restore:hamie-predeploy-20260830T000000Z.tar.gz",
        "ssh", "wait",
    ]


def test_a_failed_rollback_reports_both_failures_and_the_manual_restore_path(monkeypatch) -> None:
    _stub_backup(monkeypatch)
    monkeypatch.setattr(build_deploy, "_rsync", lambda *a, **k: None)
    monkeypatch.setattr(
        build_deploy, "verify_parity",
        lambda *a, **k: (_ for _ in ()).throw(build_deploy.BuildError("parity mismatch")),
    )

    def failing_restore(*a, **k):
        raise deploy_backup.BackupError("ssh unreachable")

    monkeypatch.setattr(deploy_backup, "restore_backup_over_ssh", failing_restore)

    with pytest.raises(build_deploy.BuildError, match="DEPLOY FAILED AND ROLLBACK FAILED"):
        build_deploy.deploy(
            target="example-host", deploy_path="/x", backup_dir="/backups",
            restart_command="ha core restart",
        )


def test_run_test_suite_and_scanner_are_skippable_but_default_on(monkeypatch) -> None:
    order: list[str] = []
    monkeypatch.setattr(build_deploy, "run_tests", lambda: order.append("tests"))
    monkeypatch.setattr(build_deploy, "run_secret_scan", lambda: order.append("scan"))
    _stub_backup(monkeypatch)
    monkeypatch.setattr(build_deploy, "_rsync", lambda *a, **k: None)
    monkeypatch.setattr(build_deploy, "verify_parity", lambda *a, **k: None)
    monkeypatch.setattr(build_deploy, "_ssh", lambda *a, **k: None)
    monkeypatch.setattr(build_deploy, "wait_for_startup", lambda *a, **k: None)
    monkeypatch.setattr(build_deploy, "verify_runtime", lambda *a, **k: None)

    build_deploy.deploy(
        target="example-host", deploy_path="/x", backup_dir="/backups", restart_command="ha core restart",
    )
    assert order == ["tests", "scan"]

    order.clear()
    build_deploy.deploy(
        target="example-host", deploy_path="/x", backup_dir="/backups", restart_command="ha core restart",
        run_test_suite=False, run_scanner=False,
    )
    assert order == []


def test_a_failing_test_suite_aborts_before_any_backup_is_taken(monkeypatch) -> None:
    created: list[str] = []

    def failing_tests():
        raise build_deploy.BuildError("2 tests failed")

    monkeypatch.setattr(build_deploy, "run_tests", failing_tests)
    monkeypatch.setattr(
        deploy_backup, "create_backup_over_ssh",
        lambda *a, **k: created.append("backup") or "unused",
    )

    with pytest.raises(build_deploy.BuildError, match="2 tests failed"):
        build_deploy.deploy(
            target="example-host", deploy_path="/x", backup_dir="/backups",
            restart_command="ha core restart",
        )

    assert created == []


@pytest.mark.parametrize(
    ("resolver", "env_name", "cli_value", "env_value", "default"),
    [
        (build_deploy.resolve_ssh_target, "HAMIE_SSH_TARGET", None, None, build_deploy.DEFAULT_SSH_TARGET),
        (build_deploy.resolve_deploy_path, "HAMIE_DEPLOY_PATH", None, None, build_deploy.DEFAULT_DEPLOY_PATH),
        (build_deploy.resolve_backup_dir, "HAMIE_BACKUP_DIR", None, None, build_deploy.DEFAULT_BACKUP_DIR),
        (
            build_deploy.resolve_restart_command, "HAMIE_RESTART_COMMAND", None, None,
            build_deploy.DEFAULT_RESTART_COMMAND,
        ),
    ],
)
def test_resolvers_fall_back_to_a_generic_default(
    monkeypatch, resolver, env_name, cli_value, env_value, default
) -> None:
    monkeypatch.delenv(env_name, raising=False)
    assert resolver(None) == default


def test_cli_flag_takes_precedence_over_environment_variable(monkeypatch) -> None:
    monkeypatch.setenv("HAMIE_SSH_TARGET", "from-env")
    assert build_deploy.resolve_ssh_target("from-cli") == "from-cli"


def test_environment_variable_takes_precedence_over_default(monkeypatch) -> None:
    monkeypatch.setenv("HAMIE_DEPLOY_PATH", "/custom/path")
    assert build_deploy.resolve_deploy_path(None) == "/custom/path"


def test_no_hardcoded_household_ssh_target_remains() -> None:
    """Regression: the tool must never assume one operator's ssh alias."""
    assert build_deploy.DEFAULT_SSH_TARGET != "ha"
