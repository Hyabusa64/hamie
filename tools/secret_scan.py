#!/usr/bin/env python3
"""Deterministic local secret scanner for the HAMIE repository.

Exists because this repository committed verbatim Home Assistant
``.storage`` dumps -- ``core.config_entries`` carries every integration's
live credentials in cleartext. No cloud service is required to catch that;
the shape is highly recognisable and the check must be cheap enough to run
on every commit and in CI.

Design rules, in order of importance:

1. **Never emit a secret.** Not the value, not a prefix, not a hash. A hash
   of a short or low-entropy credential is a cracking target, and a
   "redacted" value with four characters showing is still four characters.
   Findings report path, key name, and counts. That is enough to act on.
2. **Recognise deliberate synthetics.** Sanitized fixtures must be able to
   keep a structurally-required credential field without tripping the
   scanner forever after. A value carrying the SYNTHETIC_MARKER is exempt,
   and the marker is chosen so it can never be mistaken for -- or accepted
   as -- real authentication material.
3. **Deterministic, offline, no dependencies.** Same input, same output,
   no network.

Usage:
    python tools/secret_scan.py            # tracked files (what CI checks)
    python tools/secret_scan.py --all      # entire worktree
    python tools/secret_scan.py --json     # machine-readable summary
Exit code 1 when anything is found.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field

#: Any value containing this marker is a declared test synthetic. Chosen to
#: be self-describing and syntactically useless as a credential.
SYNTHETIC_MARKER = "SYNTHETIC-NOT-A-REAL-CREDENTIAL"

#: Key names whose populated values are treated as credential material.
#: Matched case-insensitively as whole-ish words against the key.
CREDENTIAL_KEY_PATTERNS = (
    r"access[_-]?token",
    r"refresh[_-]?token",
    r"auth[_-]?token",
    r"id[_-]?token",
    r"adp[_-]?token",
    r"device[_-]?token",
    r"session[_-]?token",
    r"bearer",
    r"api[_-]?key",
    r"apikey",
    r"app[_-]?key",
    r"secret",
    r"client[_-]?secret",
    r"private[_-]?key",
    r"encryption[_-]?key",
    r"password",
    r"passwd",
    r"pwd",
    r"credential",
    r"cookie",
    r"2fa",
    r"otp",
    r"totp",
    r"ltpk",
    r"ltsk",
    r"pairing[_-]?(data|key|code)",
    r"access[_-]?code",
    r"pin[_-]?code",
    r"webhook[_-]?id",
    r"cloudhook",
    r"^psk$",
    r"^key$",
    r"^token$",
    r"^auth$",
    r"^secret$",
)
_CRED_RE = re.compile("|".join(f"(?:{p})" for p in CREDENTIAL_KEY_PATTERNS), re.I)

#: Keys that match the patterns above but are structurally not credentials
#: in this codebase. Kept explicit and small; every entry is a deliberate
#: decision, not a convenience.
KEY_ALLOWLIST = frozenset(
    {
        "api_key_name",          # label, not the key
        "requires_api_key",      # boolean capability flag
        "password_protected",    # boolean
        "secret_scan",           # this tool's own config keys
        "keys",                  # generic container
        "keyword",
        "keywords",
        "key_name",
        "public_key",            # public by definition
        "accessorypairingid",    # HomeKit accessory *identifier*, not key material
        "accessoryip",
        "accessoryport",
        "mcp_credential",        # UI field label in strings.json / translations
        "hkg_credential",
    }
)

#: Dotted JSON paths that legitimately hold a token-shaped value which is not
#: authentication material. HAMIE's idempotency records carry a request-dedup
#: nonce; it grants nothing and replaying it is precisely what it prevents.
PATH_ALLOWLIST = frozenset({"data.payload.idempotency.token"})

#: A file may declare that it deliberately contains credential-SHAPED
#: literals -- a test that proves the sanitizer rewrites a JWT has to contain
#: something JWT-shaped. Deliberately narrow: the pragma suppresses only the
#: value-shape class, never populated credential keys and never a raw
#: .storage document, and only under tests/. A pragma that could silence the
#: whole scanner would be worse than no scanner.
SHAPE_PRAGMA = "secret-scan: allow-credential-shaped-literals"


#: Path *segments* under which a credential-named key is structurally not a
#: credential. Home Assistant's config-entry ``discovery_keys`` carry the
#: identifier a device was discovered by -- a DHCP MAC, an SSDP UUID, a
#: Bluetooth address, a hassio slug. Those are LAN identifiers, not
#: authentication material, and flagging 24 of them per snapshot would bury
#: the findings that matter.
PATH_SEGMENT_ALLOWLIST = ("discovery_keys",)

#: Value shapes that are credentials regardless of the key they sit under.
VALUE_SIGNATURES = (
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    # A credential embedded in a connection URI. This class was invisible to
    # the scanner: the live Home Assistant recorder shipped
    # `db_url: mysql://<user>:SYNTHETIC-NOT-A-REAL-CREDENTIAL@<host>/<db>` in
    # configuration.yaml, and two git-TRACKED snapshot copies of that file
    # carried the same password into committed history -- while this scanner
    # reported PASS. The key is `db_url`, which matches no credential-key
    # pattern, and the value is a URL, which matched no value signature.
    #
    # Matches scheme://user:secret@host for the drivers a Home Assistant
    # install realistically uses. The password must be non-empty and must not
    # be a placeholder, so `postgresql://user:@host` and
    # `mysql://user:!secret@host` do not trip it.
    (
        "connection_uri_credential",
        re.compile(
            r"\b(?:mysql|mariadb|postgres(?:ql)?|mongodb(?:\+srv)?|redis|amqp|"
            r"mssql|oracle|sqlite\+\w+|mysql\+\w+|postgresql\+\w+)"
            r"://[^:/@\s]+:(?!\s*!secret\b)[^@/\s]+@[^\s/]+",
            re.I,
        ),
    ),
)

#: A Home Assistant .storage document. Committing one of these is the
#: original defect; it is reported as its own class so it can never be
#: reduced to "a few key hits".
HA_STORAGE_KEY_RE = re.compile(r'"key"\s*:\s*"(core\.[a-z_]+|[a-z_]+\.[a-z_]+)"')

SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"})
BINARY_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
     ".tar", ".whl", ".so", ".dylib", ".woff", ".woff2", ".ttf", ".mp4"}
)
MAX_BYTES = 40 * 1024 * 1024


#: Snapshot paths a human has reviewed and accepted as fixture evidence.
#: A raw .storage document that is NOT on this list is an error even when it
#: contains no credentials, because the next capture of the same store might.
#: Reviewing a path is a deliberate act; the list is data, not code.
REVIEWED_SNAPSHOTS_FILE = "tools/reviewed_snapshots.txt"


def load_reviewed(root: str) -> set[str]:
    path = os.path.join(root, REVIEWED_SNAPSHOTS_FILE)
    if not os.path.isfile(path):
        return set()
    reviewed = set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.split("#", 1)[0].strip()
            if line:
                reviewed.add(line)
    return reviewed


@dataclass
class Finding:
    path: str
    kind: str
    detail: str
    count: int = 1
    #: Only errors fail the build. A reviewed, credential-free snapshot is
    #: worth listing without blocking every commit forever after.
    severity: str = "error"

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "kind": self.kind,
            "detail": self.detail,
            "count": self.count,
            "severity": self.severity,
        }


@dataclass
class ScanResult:
    files_scanned: int = 0
    findings: list[Finding] = field(default_factory=list)
    synthetic_values_seen: int = 0

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def advisories(self) -> list[Finding]:
        return [f for f in self.findings if f.severity != "error"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    total = len(value)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def _is_placeholder(value: str) -> bool:
    """Is this value unmistakably not a credential?"""
    if SYNTHETIC_MARKER in value:
        return True
    stripped = value.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    if lowered in {
        "null", "none", "true", "false", "redacted", "removed", "changeme",
        "placeholder", "example", "test", "dummy", "fake", "xxx", "n/a",
    }:
        return True
    # Uniform filler such as "****", "xxxxxxxx", "000000".
    return len(set(stripped)) <= 2


#: A store name or entity id, e.g. "core.config_entries" / "sensor.foo_2".
#: These appear under a bare ``key`` field in every .storage envelope and are
#: identifiers, not secrets.
_IDENTIFIER_SHAPE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")


def _suspicious_value(key: str, value: object, *, depth: int = 1) -> str | None:
    """Return a reason when this key/value pair looks like live credential material.

    Tuned against this repository's real false positives rather than in the
    abstract. A scanner that cries wolf on every translation string teaches
    people to ignore it, which is worse than not having one.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return None
    if not isinstance(value, str):
        return None
    if _is_placeholder(value):
        return None
    bare = key.split(".")[-1].lower()
    if bare in KEY_ALLOWLIST:
        return None
    if not _CRED_RE.search(bare):
        return None
    # Credentials do not contain whitespace. A "credential_required" key
    # holding an English sentence is a UI label -- hamie/strings.json and
    # translations/en.json are full of them, and flagging those forever
    # would train the operator to ignore this tool.
    if any(ch.isspace() for ch in value):
        return None
    # "key": "core.config_entries" is the .storage envelope's own store name.
    if _IDENTIFIER_SHAPE.match(value):
        return None
    # A credential-named field holding a short, low-entropy, human word is
    # far more likely to be a label than a secret. Require some substance.
    if len(value) < 8 and _entropy(value) < 2.5:
        return None
    return bare


def _walk_json(
    node: object, path: str, out: Counter, synthetic: list[int], depth: int = 0
) -> None:
    if isinstance(node, dict):
        envelope = depth == 0 and {"version", "key", "data"} <= set(node)
        for key, value in node.items():
            if isinstance(value, str) and SYNTHETIC_MARKER in value:
                synthetic[0] += 1
            # The .storage envelope's own "key" names the store, not a secret.
            child = f"{path}.{key}" if path else str(key)
            exempt = (
                (envelope and key == "key")
                or child in PATH_ALLOWLIST
                or any(seg in child.split(".") for seg in PATH_SEGMENT_ALLOWLIST)
            )
            if not exempt:
                reason = _suspicious_value(str(key), value, depth=depth)
                if reason:
                    out[reason] += 1
            _walk_json(value, child, out, synthetic, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _walk_json(item, path, out, synthetic, depth + 1)


#: Archives are not opened. Extracting attacker-influenced archives inside a
#: security scanner is its own hazard (zip bombs, path traversal on extract),
#: and the honest alternative is to say plainly that the contents were not
#: examined rather than to imply a clean bill of health. A build artifact
#: that ships a raw snapshot is a real risk, so its presence is surfaced.
ARCHIVE_SUFFIXES = frozenset({".zip", ".gz", ".tgz", ".tar", ".bz2", ".xz", ".7z"})


def scan_file(
    path: str,
    result: ScanResult,
    reviewed: set[str] | None = None,
    root: str | None = None,
) -> None:
    suffix = os.path.splitext(path)[1].lower()
    if suffix in ARCHIVE_SUFFIXES:
        rel = os.path.relpath(path, root) if root else os.path.relpath(path)
        result.findings.append(
            Finding(
                rel,
                "archive_not_scanned",
                "contents were not examined; verify it carries no raw snapshot",
                severity="advisory",
            )
        )
        return
    if suffix in BINARY_SUFFIXES:
        return
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    if size > MAX_BYTES:
        return
    try:
        with open(path, encoding="utf-8", errors="strict") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError):
        return
    result.files_scanned += 1
    # Relative to the SCAN ROOT, never to the process cwd: the pre-commit hook
    # scans an exported copy of the staged tree from an arbitrary directory,
    # and a cwd-relative path would never match the reviewed-snapshot manifest.
    rel = os.path.relpath(path, root) if root else os.path.relpath(path)

    # 1. Raw Home Assistant .storage document.
    if text.lstrip().startswith("{") and '"key"' in text[:2000] and '"data"' in text[:4000]:
        match = HA_STORAGE_KEY_RE.search(text[:2000])
        if match and '"version"' in text[:2000]:
            store = match.group(1)
            accepted = rel in (reviewed or set())
            result.findings.append(
                Finding(
                    rel,
                    "ha_storage_snapshot",
                    f'storage key "{store}"'
                    + ("" if accepted else "  [NOT REVIEWED]"),
                    severity="advisory" if accepted else "error",
                )
            )

    # 2. Credential-shaped values, key-independent.
    shapes_declared = SHAPE_PRAGMA in text[:2000] and rel.startswith("tests/")
    for name, pattern in VALUE_SIGNATURES:
        if shapes_declared:
            break
        hits = [m for m in pattern.findall(text) if SYNTHETIC_MARKER not in str(m)]
        if hits:
            result.findings.append(Finding(rel, "credential_value_shape", name, len(hits)))

    # 3. Credential-named keys holding populated values (structured formats).
    #
    # Gated on CONTENT, not on the filename. Home Assistant writes its stores
    # as `core.config_entries` with no .json suffix at all; an extension-based
    # gate skipped the credential walk on exactly the file this scanner exists
    # to catch, and only found the repository's copies because they happened
    # to live under benchmark/.
    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            document = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            document = None
        if document is not None:
            counts: Counter = Counter()
            synthetic = [0]
            _walk_json(document, "", counts, synthetic)
            result.synthetic_values_seen += synthetic[0]
            if counts:
                result.findings.append(
                    Finding(
                        rel,
                        "populated_credential_keys",
                        ", ".join(sorted(counts)),
                        sum(counts.values()),
                    )
                )


def tracked_files(root: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True
    )
    return [os.path.join(root, p) for p in out.stdout.split("\0") if p]


def all_files(root: str) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            found.append(os.path.join(dirpath, name))
    return found


def scan(root: str, *, everything: bool = False) -> ScanResult:
    result = ScanResult()
    reviewed = load_reviewed(root)
    for path in sorted(all_files(root) if everything else tracked_files(root)):
        scan_file(path, result, reviewed, root)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--all", action="store_true", help="scan the worktree, not just tracked files")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = scan(args.root, everything=args.all)
    if args.json:
        print(json.dumps(
            {
                "files_scanned": result.files_scanned,
                "synthetic_values_seen": result.synthetic_values_seen,
                "findings": [f.as_dict() for f in result.findings],
            },
            indent=2, sort_keys=True,
        ))
    else:
        scope = "worktree" if args.all else "tracked files"
        print(f"secret scan: {result.files_scanned} {scope} scanned")
        print(f"declared synthetics recognised: {result.synthetic_values_seen}")
        advisories = result.advisories
        if advisories:
            print(
                f"advisory: {len(advisories)} reviewed .storage snapshot(s) tracked "
                "(credential-free; listed in tools/reviewed_snapshots.txt)"
            )
        if result.ok:
            print("RESULT: PASS -- no credential material detected")
        else:
            by_kind: Counter = Counter(f.kind for f in result.errors)
            print(f"RESULT: FAIL -- {len(result.errors)} error(s) {dict(by_kind)}\n")
            for finding in result.errors:
                print(f"  [{finding.kind}] {finding.path}")
                print(f"      {finding.count}x  keys/shapes: {finding.detail}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
