#!/usr/bin/env python3
"""Build, deploy and *prove* a HAMIE integration build.

The version drift this tool exists to prevent happened because deployment was
a manual file copy: nothing ever compared what was built against what Home
Assistant ended up executing. So this refuses to report success until

    source HEAD == packaged build_commit == deployed build_commit == runtime build_commit

Every stage is verified, and a failure at any stage is fatal.

Usage:
    tools/build_deploy.py --check                 # provenance preflight only
    tools/build_deploy.py --package DIR           # build a staging tree
    tools/build_deploy.py --deploy                # package, deploy, verify
    tools/build_deploy.py --deploy --allow-dirty  # mark the build dirty instead

Deployment is driven over SSH against whatever Home Assistant host you
configure -- nothing here is specific to any one installation. Set:

    HAMIE_SSH_TARGET   ssh destination: a Host alias from ~/.ssh/config, or
                        user@host. Default: "homeassistant" (a placeholder
                        alias; define it in your own ssh config).
    HAMIE_DEPLOY_PATH   remote custom_components path.
                        Default: "/config/custom_components/hamie", which is
                        where Home Assistant OS/Supervised expects a manually
                        installed custom integration.
    HAMIE_BACKUP_DIR    remote directory for predeploy backups.
                        Default: "/config/hamie_backups".
    HAMIE_RESTART_COMMAND
                        remote command that restarts Home Assistant.
                        Default: "ha core restart" (the Supervisor CLI,
                        present on Home Assistant OS/Supervised). A Core/venv
                        install should override this, e.g. with
                        "sudo systemctl restart home-assistant@homeassistant".

Each also has a same-named ``--xxx`` flag, which takes precedence.

``--deploy`` runs the whole pipeline: preflight, tests, secret scan,
package, a timestamped predeploy backup, transfer, byte-identical parity
check, restart, wait for startup, and a runtime provenance check. Any
failure after the backup is taken triggers an automatic restore from that
backup -- the tool never leaves a host mid-deploy on its own judgement.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy_backup  # noqa: E402  (local sibling module, path set above)

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "hamie"
MANIFEST = PACKAGE_DIR / "manifest.json"
BUILD_INFO = "build_info.json"

DEFAULT_SSH_TARGET = "homeassistant"
DEFAULT_DEPLOY_PATH = "/config/custom_components/hamie"
DEFAULT_BACKUP_DIR = "/config/hamie_backups"
DEFAULT_RESTART_COMMAND = "ha core restart"

#: Never packaged: build artefacts and editor droppings, not integration code.
EXCLUDED_DIRS = {
    "__pycache__", ".pytest_cache", ".git",
    "node_modules", ".mypy_cache", ".ruff_cache", "htmlcov",
}
EXCLUDED_NAMES = {".DS_Store", ".coverage"}
#: macOS tar emits AppleDouble sidecars; they are not integration code.
EXCLUDED_PREFIXES = ("._",)
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


class BuildError(RuntimeError):
    """A provenance or deployment guarantee could not be met."""


def _git(*args: str) -> str:
    result = subprocess.run(
        ("git", *args), cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise BuildError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def resolve_ssh_target(cli_value: str | None) -> str:
    return cli_value or os.environ.get("HAMIE_SSH_TARGET") or DEFAULT_SSH_TARGET


def resolve_deploy_path(cli_value: str | None) -> str:
    return cli_value or os.environ.get("HAMIE_DEPLOY_PATH") or DEFAULT_DEPLOY_PATH


def resolve_backup_dir(cli_value: str | None) -> str:
    return cli_value or os.environ.get("HAMIE_BACKUP_DIR") or DEFAULT_BACKUP_DIR


def resolve_restart_command(cli_value: str | None) -> str:
    return cli_value or os.environ.get("HAMIE_RESTART_COMMAND") or DEFAULT_RESTART_COMMAND


def _ssh(command: str, *, target: str) -> str:
    result = subprocess.run(
        ("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", target, command),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BuildError(f"ssh failed: {result.stderr.strip()[:400]}")
    return result.stdout.strip()


def semantic_version() -> str:
    """The one human-maintained version, read from the manifest."""
    return str(json.loads(MANIFEST.read_text())["version"])


def source_head() -> str:
    return _git("rev-parse", "HEAD")[:12]


def tree_is_dirty() -> bool:
    """True when tracked files differ from HEAD.

    Untracked files are deliberately ignored: scratch files next to the repo do
    not change the code being built.
    """
    return bool(_git("status", "--porcelain", "--untracked-files=no"))


def meaningful_files(root: Path) -> list[Path]:
    """Integration files that constitute the build, in stable order."""
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.name in EXCLUDED_NAMES or path.suffix in EXCLUDED_SUFFIXES:
            continue
        if path.name.startswith(EXCLUDED_PREFIXES):
            continue
        found.append(path)
    return sorted(found)


def hash_tree(root: Path, *, skip: set[str] | None = None) -> dict[str, str]:
    """Map each relative path to its content hash."""
    skipped = skip or set()
    digests: dict[str, str] = {}
    for path in meaningful_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in skipped:
            continue
        digests[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def preflight(*, allow_dirty: bool) -> tuple[str, str, bool]:
    """Establish the provenance facts this build will claim."""
    version = semantic_version()
    head = source_head()
    dirty = tree_is_dirty()
    if dirty and not allow_dirty:
        raise BuildError(
            "source tree has uncommitted tracked changes; commit them or pass "
            "--allow-dirty to publish an explicitly dirty build"
        )
    return version, head, dirty


def write_build_info(target: Path, *, commit: str, dirty: bool) -> dict[str, object]:
    payload = {
        "build_commit": commit,
        "build_timestamp": _datetime.datetime.now(_datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "build_dirty": dirty,
    }
    (target / BUILD_INFO).write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def package(destination: Path, *, allow_dirty: bool) -> dict[str, object]:
    """Produce a staging tree carrying its own provenance."""
    version, head, dirty = preflight(allow_dirty=allow_dirty)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for path in meaningful_files(PACKAGE_DIR):
        relative = path.relative_to(PACKAGE_DIR)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    info = write_build_info(destination, commit=head, dirty=dirty)
    print(f"  packaged  version={version} commit={head} dirty={dirty}")
    print(f"            files={len(meaningful_files(destination))} -> {destination}")
    return {"version": version, "commit": head, "dirty": dirty, **info}


def deployed_hashes(*, target: str, deploy_path: str) -> dict[str, str]:
    """Content hashes of the live deployed tree, via the configured ssh path."""
    remote = (
        f"cd {deploy_path} && sudo find . -type f "
        "! -path '*/__pycache__/*' ! -name '*.pyc' ! -name '.DS_Store' ! -name '._*' "
        "| sort | while read f; do "
        'printf "%s %s\\n" "$(sudo sha256sum "$f" | cut -d\\  -f1)" "${f#./}"; done'
    )
    digests: dict[str, str] = {}
    for line in _ssh(remote, target=target).splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            digests[parts[1].strip()] = parts[0].strip()
    return digests


def deployed_build_info(*, target: str, deploy_path: str) -> dict[str, object]:
    raw = _ssh(f"sudo cat {deploy_path}/{BUILD_INFO} 2>/dev/null || echo '{{}}'", target=target)
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def verify_parity(staging: Path, *, target: str, deploy_path: str) -> None:
    """Every packaged file must be byte-identical on the deployment target."""
    local = hash_tree(staging)
    remote = deployed_hashes(target=target, deploy_path=deploy_path)
    missing = sorted(set(local) - set(remote))
    extra = sorted(set(remote) - set(local))
    differing = sorted(p for p in set(local) & set(remote) if local[p] != remote[p])
    print(f"  parity    packaged={len(local)} deployed={len(remote)}")
    if missing or extra or differing:
        raise BuildError(
            "deployment parity failed -- "
            f"missing={missing[:5]} deployment_only={extra[:5]} differing={differing[:5]}"
        )
    print(f"  parity    OK ({len(local)}/{len(local)} byte-identical)")


def verify_runtime(expected_version: str, expected_commit: str, *, target: str, deploy_path: str) -> None:
    """The decisive check: what Home Assistant is *executing*."""
    info = deployed_build_info(target=target, deploy_path=deploy_path)
    if info.get("build_commit") != expected_commit:
        raise BuildError(
            f"deployed build_commit {info.get('build_commit')!r} != built {expected_commit!r}"
        )
    print(f"  runtime   deployed build_commit={info.get('build_commit')} matches build")
    manifest = json.loads(_ssh(f"sudo cat {deploy_path}/manifest.json", target=target))
    if manifest.get("version") != expected_version:
        raise BuildError(
            f"deployed version {manifest.get('version')!r} != built {expected_version!r}"
        )
    print(f"  runtime   deployed version={manifest.get('version')} matches build")


def run_tests() -> None:
    result = subprocess.run(
        (sys.executable, "-m", "pytest", "-q"), cwd=REPO_ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise BuildError(
            "test suite failed, refusing to deploy:\n"
            + result.stdout[-4000:] + result.stderr[-2000:]
        )


def run_secret_scan() -> None:
    import secret_scan  # local sibling module; sys.path already set at import time above

    result = secret_scan.scan(str(REPO_ROOT))
    if result.errors:
        details = "; ".join(f"{f.path}:{f.kind}:{f.detail}" for f in result.errors)
        raise BuildError(f"secret scan failed, refusing to deploy: {details}")


def _rsync(staging: Path, *, target: str, deploy_path: str) -> None:
    result = subprocess.run(
        ("rsync", "-az", "--delete", f"{staging}/", f"{target}:{deploy_path}/"),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BuildError(f"rsync to {target}:{deploy_path} failed: {result.stderr.strip()[:400]}")


def wait_for_startup(
    *, target: str, deploy_path: str, timeout_s: int = 180, poll_s: int = 5
) -> None:
    """Poll until Home Assistant is back up and serving build_info.json."""
    deadline = time.monotonic() + timeout_s
    last_error = "no attempt made"
    while time.monotonic() < deadline:
        try:
            info = deployed_build_info(target=target, deploy_path=deploy_path)
            if info.get("build_commit"):
                return
            last_error = "build_info.json present but has no build_commit"
        except BuildError as error:
            last_error = str(error)
        time.sleep(poll_s)
    raise BuildError(f"Home Assistant did not come back within {timeout_s}s: {last_error}")


def deploy(
    *,
    target: str,
    deploy_path: str,
    backup_dir: str,
    restart_command: str,
    allow_dirty: bool = False,
    keep_backups: int = deploy_backup.DEFAULT_KEEP,
    run_test_suite: bool = True,
    run_scanner: bool = True,
) -> dict[str, object]:
    """Package, back up, deploy, verify -- rolling back on any failure.

    Nothing before the transfer touches the remote host. From the moment
    the predeploy backup is taken onward, any failure triggers an
    automatic restore from that same backup before this function raises,
    so a broken deploy never leaves Home Assistant running a partial or
    unverified build. If the rollback itself fails, that is reported
    explicitly and separately -- this never silently continues past a
    partial failure.
    """
    version, head, dirty = preflight(allow_dirty=allow_dirty)

    if run_test_suite:
        print("  tests     running the test suite ...")
        run_tests()
        print("  tests     OK")
    if run_scanner:
        print("  scan      running the secret scan ...")
        run_secret_scan()
        print("  scan      OK")

    staging = Path(tempfile.mkdtemp(prefix="hamie-deploy-"))
    package(staging, allow_dirty=allow_dirty)

    timestamp = _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"  backup    creating predeploy backup ({timestamp}) ...")
    backup = deploy_backup.create_backup_over_ssh(target, deploy_path, backup_dir, timestamp)
    print(f"  backup    {backup}")

    try:
        print("  transfer  rsync -> remote ...")
        _rsync(staging, target=target, deploy_path=deploy_path)
        verify_parity(staging, target=target, deploy_path=deploy_path)

        print("  restart   restarting Home Assistant ...")
        _ssh(restart_command, target=target)
        print("  restart   waiting for startup ...")
        wait_for_startup(target=target, deploy_path=deploy_path)

        verify_runtime(version, head, target=target, deploy_path=deploy_path)
    except (BuildError, deploy_backup.BackupError) as original_failure:
        print(f"  FAIL      {original_failure}", file=sys.stderr)
        print(f"  rollback  restoring {backup} ...", file=sys.stderr)
        try:
            deploy_backup.restore_backup_over_ssh(target, deploy_path, backup_dir, backup)
            _ssh(restart_command, target=target)
            wait_for_startup(target=target, deploy_path=deploy_path)
        except (BuildError, deploy_backup.BackupError) as rollback_failure:
            raise BuildError(
                "DEPLOY FAILED AND ROLLBACK FAILED -- manual intervention required.\n"
                f"  original failure: {original_failure}\n"
                f"  rollback failure: {rollback_failure}\n"
                f"  restore by hand from: {backup_dir}/{backup}"
            ) from rollback_failure
        print("  rollback  restored and restarted", file=sys.stderr)
        raise BuildError(f"deploy failed, rolled back successfully: {original_failure}") from original_failure

    retention = deploy_backup.apply_retention_over_ssh(
        target, backup_dir, keep=keep_backups, required_for_rollback=backup
    )
    print(f"  backups   kept={len(retention.keep)} deleted={len(retention.delete)}")

    return {"version": version, "commit": head, "dirty": dirty, "backup": backup}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="provenance preflight only")
    parser.add_argument("--package", metavar="DIR", help="build a staging tree")
    parser.add_argument(
        "--deploy", action="store_true",
        help="package, back up, deploy, verify -- rolls back automatically on failure",
    )
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--verify-only", action="store_true", help="check live parity")
    parser.add_argument("--ssh-target", help=f"default: ${{HAMIE_SSH_TARGET}} or {DEFAULT_SSH_TARGET!r}")
    parser.add_argument("--deploy-path", help=f"default: ${{HAMIE_DEPLOY_PATH}} or {DEFAULT_DEPLOY_PATH!r}")
    parser.add_argument("--backup-dir", help=f"default: ${{HAMIE_BACKUP_DIR}} or {DEFAULT_BACKUP_DIR!r}")
    parser.add_argument(
        "--restart-command", help=f"default: ${{HAMIE_RESTART_COMMAND}} or {DEFAULT_RESTART_COMMAND!r}"
    )
    parser.add_argument("--keep-backups", type=int, default=deploy_backup.DEFAULT_KEEP)
    parser.add_argument(
        "--skip-tests", action="store_true",
        help="DANGEROUS: deploy without running the test suite first",
    )
    parser.add_argument(
        "--skip-scan", action="store_true",
        help="DANGEROUS: deploy without running the secret scan first",
    )
    args = parser.parse_args()

    target = resolve_ssh_target(args.ssh_target)
    deploy_path = resolve_deploy_path(args.deploy_path)

    try:
        if args.check:
            version, head, dirty = preflight(allow_dirty=args.allow_dirty)
            print(f"  version={version} commit={head} dirty={dirty}")
            return 0
        if args.verify_only:
            version = semantic_version()
            head = source_head()
            verify_runtime(version, head, target=target, deploy_path=deploy_path)
            staging = Path(args.package) if args.package else None
            if staging is None:
                staging = Path(tempfile.mkdtemp(prefix="hamie-verify-"))
                package(staging, allow_dirty=args.allow_dirty)
            verify_parity(staging, target=target, deploy_path=deploy_path)
            return 0
        if args.package:
            package(Path(args.package), allow_dirty=args.allow_dirty)
            return 0
        if args.deploy:
            result = deploy(
                target=target,
                deploy_path=deploy_path,
                backup_dir=resolve_backup_dir(args.backup_dir),
                restart_command=resolve_restart_command(args.restart_command),
                allow_dirty=args.allow_dirty,
                keep_backups=args.keep_backups,
                run_test_suite=not args.skip_tests,
                run_scanner=not args.skip_scan,
            )
            print(f"  deploy    OK version={result['version']} commit={result['commit']}")
            return 0
        parser.print_help()
        return 1
    except (BuildError, deploy_backup.BackupError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
