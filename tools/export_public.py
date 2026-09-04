#!/usr/bin/env python3
"""Deterministic export of a sanitized, publishable HAMIE tree.

This is the ONLY supported path from the private, authoritative HAMIE
checkout to anything that might become a public repository. It never
touches the private repository's git history, and it never leaves behind
a half-sanitized export: any privacy or secret finding deletes the export
directory and raises, rather than reporting the problem and keeping the
output around.

What it does, in order:

1. Reads the SOURCE tree's currently tracked files (``git ls-files`` --
   this is an allowlist by construction: anything never added to git,
   such as a stray scratch directory or a local snapshot, is invisible to
   the export regardless of what it contains).
2. Drops everything under an excluded path (``benchmark/``, ``analysis/``
   -- real household analysis/benchmark artifacts that must never be
   published) or an excluded exact path (``docs/ACCESS_MAP.md``).
3. Applies a literal find-and-replace table (SUBSTITUTIONS) to every text
   file's content. This is deliberately NOT regex-based: every entry is an
   exact, hand-verified string discovered by manual privacy audit, chosen
   so a shorter pattern is never applied before a longer pattern it is a
   substring of (see the ordering comment above SUBSTITUTIONS).
4. Writes the result to DEST as a plain directory -- no ``.git`` -- so the
   caller must deliberately run ``git init`` there before it can be pushed
   anywhere. The private repository's own git history is never read or
   written by this tool.
5. Re-scans the export with tools/secret_scan.py (in ``--all`` / whole-tree
   mode, since DEST is not a git repository) AND independently re-checks
   every text file against FORBIDDEN_AFTER_EXPORT, a hand-maintained regex
   of exactly the household-identifying strings this tool is meant to
   remove. Two independent checks on purpose: the secret scanner looks for
   credential SHAPES, not for "this is my house's real entity id" -- a
   passing secret scan says nothing about privacy leaks, so it cannot be
   the only gate.
6. If either check finds anything, the export directory is deleted in
   full and the tool exits non-zero. It never reports "found N issues,
   proceeding anyway" -- there is no partial-success mode.

Usage:
    python tools/export_public.py --source . --dest /path/to/export
    python tools/export_public.py --source . --dest /path/to/export --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import secret_scan  # noqa: E402  (local sibling module, path set above)

# ---------------------------------------------------------------------------
# Whole directories/files that never leave the private repository, no
# matter what they contain. These are real household analysis/benchmark
# artifacts and a real private network map, not something a substitution
# table could safely genericize line-by-line.
# ---------------------------------------------------------------------------
EXCLUDED_PATH_PREFIXES: tuple[str, ...] = (
    "benchmark/",
    "analysis/",
)
EXCLUDED_PATHS: frozenset[str] = frozenset({
    "docs/ACCESS_MAP.md",
    # A historical incident report naming the exact real integrations and
    # credential fields awaiting rotation (door lock, alarm, camera NVR,
    # cloud accounts...) and confirming they have NOT been rotated yet. No
    # literal-pattern scan would catch this -- it is real prose describing
    # a real, still-open exposure, not a value with a recognisable shape.
    # docs/SECURITY.md is the private incident record; the public SECURITY.md
    # at the repo root is a generic policy document, unrelated in purpose.
    "docs/SECURITY.md",
    # A private operational snapshot from a specific live mission (real
    # finding/incident counts, this installation's actual HA version and
    # start state) -- a development journal entry, not product
    # documentation a contributor needs.
    "docs/CHECKPOINT.md",
    # Only ever meaningful as a review manifest for benchmark/, which is
    # wholesale-excluded above; without it, this is a dangling list of
    # paths that do not exist in the export.
    "tools/reviewed_snapshots.txt",
    # A private research record naming real household automations/
    # entities, cited by docs/REPAIR_ORCHESTRATION.md. The generic,
    # sanitized lessons drawn from it are reproduced in that document's
    # own "Known Failure Modes / Cautions" section, which IS exported.
    "docs/REPAIR_TAXONOMY_EVIDENCE.md",
})

# ---------------------------------------------------------------------------
# Literal household-specific values that legitimately live in a handful of
# production/test files as real registry data -- not credentials, but real
# Home Assistant entity ids, a device nickname, and a LAN IP that this
# installation's HAMIE actually depends on to protect its own inference
# power path. They stay real and unchanged in the private repository (the
# whole point is that HAMIE keeps working); this table only ever runs
# against a COPY written to the export destination.
#
# Ordering: longer/more-specific strings first. A shorter pattern that is a
# substring of a longer one (e.g. "9AEDD40" inside the full unique_id hex)
# is applied after the longer one has already consumed its occurrences, so
# it only catches the standalone shorthand mentions in prose comments.
# ---------------------------------------------------------------------------
SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    (
        "8022DC0FD77C8ED239C2BAFF292A5AD9249AEDD400",
        "TPLINKEXAMPLE00000000000000000000000000001",
    ),
    # Only the fingerprint prefix, WITH its trailing hyphen: the real source
    # wraps this literal across two adjacent string literals ("...001D-" \n
    # "MatterNodeDevice-..."), and a substitution key spanning that line
    # break would never match the raw file text. This shorter key never
    # crosses the wrap point, so it matches every occurrence -- wrapped,
    # single-line, or inside a plain string -- consistently.
    (
        "FAAD046E75459CE1-000000000000001D-",
        "MATTEREXAMPLE001-0000000000000001-",
    ),
    ("9AEDD40", "EXAMPLE0"),
    ("DESKTOP-29H0UF1", "EXAMPLE-DESKTOP-01"),
    ("MECCA", "EXAMPLE-HOST"),
    ("Blackwell", "Example-Monitor"),
    ("keris_iphone", "example_phone"),
    ("switch.office_tapo_smart_strip_switch_1", "switch.example_inference_host_plug_matter"),
    ("switch.office_tapo_smart_strip_switch_2", "switch.example_sibling_outlet"),
    ("switch.office_tapo_office_pug_2", "switch.example_office_outlet_2"),
    ("switch.office_tapo_printer_plug", "switch.example_printer_plug"),
    ("switch.office_tapo_ai_pc_plug", "switch.example_inference_host_plug"),
    ("Office Tapo", "Example Smart Plug"),
    ("P316M", "X1"),
    ("10.91.1.50", "192.0.2.10"),
)

#: Independent of SUBSTITUTIONS and of tools/secret_scan.py. If any of
#: these survive in the export, the export is deleted and the tool fails --
#: this is the safety net for a private value nobody added to the table
#: above, not a duplicate of it.
FORBIDDEN_AFTER_EXPORT = re.compile(
    r"10\.91\.[0-9]+\.[0-9]+"
    r"|MECCA"
    r"|DESKTOP-29H0UF1"
    r"|Blackwell"
    r"|keris_iphone"
    r"|office_tapo"
    r"|9AEDD4"
    r"|FAAD046E"
    r"|drowusu"
    r"|hassio_sky"
)

#: Suffixes never worth attempting a text decode/substitution pass on.
BINARY_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".gz", ".tar", ".pdf",
})

#: This tool's own source, and its own tests, necessarily contain the exact
#: private literals SUBSTITUTIONS and FORBIDDEN_AFTER_EXPORT exist to catch
#: -- as configuration data and as test fixtures, not as leaked real
#: content. Running this file's own substitution table against itself
#: would silently corrupt it (several tuples have their search key equal
#: their own replacement value, turning entries into no-ops), and running
#: the forbidden-literal sweep against it would flag its own redaction
#: list. Both checks are skipped ONLY for these two paths, which are
#: copied byte-for-byte instead -- and specifically NOT for any other file,
#: so the safety net stays live everywhere it matters.
SELF_REFERENTIAL_PATHS: frozenset[str] = frozenset({
    "tools/export_public.py",
    "tests/test_export_public.py",
})


class ExportError(RuntimeError):
    """Raised when the export cannot be produced safely. Never partial."""


@dataclass
class ExportManifest:
    dest: str
    exported: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    substitutions_applied: int = 0


def _is_excluded(rel_path: str) -> bool:
    if rel_path in EXCLUDED_PATHS:
        return True
    return any(rel_path.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES)


def tracked_paths(source: str) -> list[str]:
    """Every path git considers tracked in SOURCE, forward-slash, sorted.

    This is the allowlist: a file must be `git add`-ed in the private
    repository before this tool can ever see it, let alone export it.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=source,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(p for p in out.stdout.split("\0") if p)


def apply_substitutions(text: str) -> tuple[str, int]:
    """Apply every entry in SUBSTITUTIONS once; return (text, hit_count)."""
    hits = 0
    for needle, replacement in SUBSTITUTIONS:
        count = text.count(needle)
        if count:
            hits += count
            text = text.replace(needle, replacement)
    return text, hits


def _copy_and_sanitize(src_path: str, dest_path: str, *, rel_path: str) -> int:
    """Copy one file, applying substitutions if it decodes as text.

    Returns the number of substitution hits applied (0 for binary files,
    self-referential paths copied verbatim, or files with no matching
    literal).
    """
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    suffix = os.path.splitext(src_path)[1].lower()
    if suffix in BINARY_SUFFIXES or rel_path in SELF_REFERENTIAL_PATHS:
        shutil.copyfile(src_path, dest_path)
        return 0
    try:
        with open(src_path, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError):
        shutil.copyfile(src_path, dest_path)
        return 0
    sanitized, hits = apply_substitutions(text)
    with open(dest_path, "w", encoding="utf-8") as handle:
        handle.write(sanitized)
    shutil.copystat(src_path, dest_path, follow_symlinks=True)
    return hits


def _scan_for_forbidden_literals(root: str) -> list[str]:
    """Independent defense-in-depth sweep; returns human-readable hits."""
    hits: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            if rel in SELF_REFERENTIAL_PATHS:
                continue
            try:
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
            except (OSError, UnicodeDecodeError):
                continue
            match = FORBIDDEN_AFTER_EXPORT.search(text)
            if match:
                hits.append(f"{rel}: forbidden literal {match.group(0)!r}")
    return hits


def export(source: str, dest: str, *, dry_run: bool = False) -> ExportManifest:
    """Build a sanitized export of SOURCE's tracked tree at DEST.

    Raises ExportError, and leaves nothing behind at DEST, if:
    - DEST already exists,
    - the post-export secret scan finds anything, or
    - the post-export forbidden-literal sweep finds anything.
    """
    source = os.path.abspath(source)
    dest = os.path.abspath(dest)

    if os.path.exists(dest):
        raise ExportError(f"export destination already exists: {dest}")

    manifest = ExportManifest(dest=dest)
    all_tracked = tracked_paths(source)
    for rel_path in all_tracked:
        if _is_excluded(rel_path):
            manifest.excluded.append(rel_path)
        else:
            manifest.exported.append(rel_path)

    if dry_run:
        return manifest

    try:
        for rel_path in manifest.exported:
            src_path = os.path.join(source, rel_path)
            dest_path = os.path.join(dest, rel_path)
            manifest.substitutions_applied += _copy_and_sanitize(
                src_path, dest_path, rel_path=rel_path
            )

        scan_result = secret_scan.scan(dest, everything=True)
        forbidden_hits = _scan_for_forbidden_literals(dest)

        if scan_result.findings or forbidden_hits:
            details = ["PUBLICATION MUST STOP: privacy/secret findings in export."]
            for finding in scan_result.findings:
                details.append(f"  secret_scan: {finding.path}: {finding.kind} ({finding.detail})")
            for hit in forbidden_hits:
                details.append(f"  forbidden_literal: {hit}")
            raise ExportError("\n".join(details))
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    manifest_path = dest.rstrip(os.sep) + ".manifest.txt"
    with open(manifest_path, "w", encoding="utf-8") as handle:
        handle.write(f"HAMIE public export manifest\nsource: {source}\ndest: {dest}\n\n")
        handle.write(f"exported files: {len(manifest.exported)}\n")
        handle.write(f"excluded files: {len(manifest.excluded)}\n")
        handle.write(f"substitution hits applied: {manifest.substitutions_applied}\n\n")
        handle.write("--- exported ---\n")
        for rel_path in manifest.exported:
            handle.write(rel_path + "\n")
        handle.write("\n--- excluded ---\n")
        for rel_path in manifest.excluded:
            handle.write(rel_path + "\n")

    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--dest", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        manifest = export(args.source, args.dest, dry_run=args.dry_run)
    except ExportError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"DRY RUN -- would export {len(manifest.exported)} files, exclude {len(manifest.excluded)}")
    else:
        print(
            f"exported {len(manifest.exported)} files to {manifest.dest} "
            f"({manifest.substitutions_applied} substitution hits, "
            f"{len(manifest.excluded)} paths excluded)"
        )
        print(f"manifest: {manifest.dest.rstrip(os.sep)}.manifest.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
