#!/usr/bin/env python3
"""Predeploy backup retention for tools/build_deploy.py --deploy.

The retention POLICY (``plan_retention``) is pure and has no idea a network
exists: given a list of backup filenames and a keep-count, it decides which
survive. That is deliberate -- a retention tool that can delete files is
worth testing exhaustively without ever touching a real host, and a policy
entangled with ssh/tar calls cannot be tested that way.

The thin ssh-driving functions at the bottom (``create_backup_over_ssh``,
``apply_retention_over_ssh``) are what tools/build_deploy.py --deploy
actually calls; they do nothing this module doesn't already test the logic
of, they just perform it remotely.

Usage:
    python tools/deploy_backup.py --list --target ha --backup-dir /config/hamie_backups
    python tools/deploy_backup.py --apply-retention --target ha \\
        --backup-dir /config/hamie_backups --keep 5 --dry-run
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass

BACKUP_NAME_RE = re.compile(r"^hamie-predeploy-(\d{8}T\d{6}Z)\.tar\.gz$")
DEFAULT_KEEP = 5


class BackupError(RuntimeError):
    """A backup or retention operation could not be completed safely."""


def backup_name(timestamp: str) -> str:
    """``timestamp`` is a compact UTC ISO-8601 stamp, e.g. '20260830T041500Z'."""
    if not re.fullmatch(r"\d{8}T\d{6}Z", timestamp):
        raise BackupError(f"timestamp must look like 20260830T041500Z, got {timestamp!r}")
    return f"hamie-predeploy-{timestamp}.tar.gz"


def parse_backup_name(name: str) -> str | None:
    """The embedded timestamp, or None if this isn't one of our backups.

    Deliberately returns None instead of raising: a retention tool must be
    safe to point at a directory containing files it doesn't recognise --
    those files are simply never candidates for deletion.
    """
    match = BACKUP_NAME_RE.match(name)
    return match.group(1) if match else None


@dataclass(frozen=True)
class RetentionPlan:
    keep: tuple[str, ...]
    delete: tuple[str, ...]


def plan_retention(
    existing: tuple[str, ...],
    *,
    keep: int = DEFAULT_KEEP,
    pinned: frozenset[str] = frozenset(),
    required_for_rollback: str | None = None,
) -> RetentionPlan:
    """Decide which backup files survive. Never touches a filesystem.

    Rules, in order of precedence:
    1. A filename that doesn't match our own naming scheme is never a
       delete candidate. This tool only ever removes backups it created.
    2. ``required_for_rollback`` (the backup an in-flight deploy would
       restore from on failure) always survives, however old it is.
    3. Every name in ``pinned`` always survives.
    4. The most recent ``keep`` backups by embedded timestamp survive --
       NOT by filesystem mtime, which an rsync or restore can change.
    5. Everything else is scheduled for deletion.
    """
    if keep < 1:
        raise BackupError(f"keep must be at least 1, got {keep}")

    recognised = [
        (ts, n) for ts, n in ((parse_backup_name(n), n) for n in existing) if ts is not None
    ]
    recognised.sort(key=lambda pair: pair[0], reverse=True)  # newest timestamp first

    survivors: set[str] = {n for _, n in recognised[:keep]}
    survivors |= {n for n in pinned if n in existing}
    if required_for_rollback is not None and required_for_rollback in existing:
        survivors.add(required_for_rollback)

    keep_names = tuple(n for _, n in recognised if n in survivors)
    delete_names = tuple(n for _, n in recognised if n not in survivors)
    return RetentionPlan(keep=keep_names, delete=delete_names)


# ---------------------------------------------------------------------------
# Thin ssh-driving layer. Every safety decision above is already made by
# plan_retention(); nothing below does anything except list, create, and
# remove files at the caller's explicit direction.
# ---------------------------------------------------------------------------


def _ssh(target: str, command: str) -> str:
    result = subprocess.run(
        ("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", target, command),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BackupError(f"ssh failed: {result.stderr.strip()[:400]}")
    return result.stdout


def list_backups_over_ssh(target: str, backup_dir: str) -> tuple[str, ...]:
    out = _ssh(target, f"mkdir -p {backup_dir} && ls -1 {backup_dir}")
    return tuple(sorted(line.strip() for line in out.splitlines() if line.strip()))


def create_backup_over_ssh(target: str, deploy_path: str, backup_dir: str, timestamp: str) -> str:
    """Tar the current deployed tree before it is overwritten. Returns the backup name."""
    name = backup_name(timestamp)
    _ssh(
        target,
        f"mkdir -p {backup_dir} && "
        f"sudo tar czf {backup_dir}/{name} -C {deploy_path} . && "
        f"sudo chmod 0644 {backup_dir}/{name}",
    )
    return name


def restore_backup_over_ssh(target: str, deploy_path: str, backup_dir: str, name: str) -> None:
    """Roll back to a prior backup. Used when a deploy's post-checks fail."""
    _ssh(
        target,
        f"sudo rm -rf {deploy_path}/* && "
        f"sudo tar xzf {backup_dir}/{name} -C {deploy_path}",
    )


def apply_retention_over_ssh(
    target: str,
    backup_dir: str,
    *,
    keep: int = DEFAULT_KEEP,
    pinned: frozenset[str] = frozenset(),
    required_for_rollback: str | None = None,
    dry_run: bool = False,
) -> RetentionPlan:
    existing = list_backups_over_ssh(target, backup_dir)
    plan = plan_retention(
        existing, keep=keep, pinned=pinned, required_for_rollback=required_for_rollback
    )
    if not dry_run and plan.delete:
        targets = " ".join(f"{backup_dir}/{n}" for n in plan.delete)
        _ssh(target, f"sudo rm -f {targets}")
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", required=True, help="ssh destination, e.g. a Host alias")
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--apply-retention", action="store_true")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    parser.add_argument("--pin", action="append", default=[], help="backup filename to never delete; repeatable")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        if args.list:
            for name in list_backups_over_ssh(args.target, args.backup_dir):
                print(name)
            return 0
        if args.apply_retention:
            plan = apply_retention_over_ssh(
                args.target,
                args.backup_dir,
                keep=args.keep,
                pinned=frozenset(args.pin),
                dry_run=args.dry_run,
            )
            verb = "would delete" if args.dry_run else "deleted"
            print(f"keeping {len(plan.keep)}, {verb} {len(plan.delete)}")
            for name in plan.delete:
                print(f"  {verb}: {name}")
            return 0
        parser.print_help()
        return 1
    except BackupError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
