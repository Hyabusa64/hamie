#!/usr/bin/env python3
"""Sanitize a Home Assistant .storage snapshot for use as a repository fixture.

Capturing a raw ``core.config_entries`` is the fastest way to get realistic
benchmark data and the fastest way to commit every integration credential in
the house. This turns one into the other safely.

What is preserved -- everything HAMIE's deterministic analysis actually reads:
entry_id, domain, title, source, unique_id, version/minor_version,
disabled_by, created_at/modified_at, pref_* flags, discovery_keys,
subentries, and the full *shape* of ``data``/``options`` including every
non-credential setting. Numeric configuration such as ``max_tokens`` or
``ollama_maximum_output_tokens`` survives untouched: those are settings whose
names merely contain "token", and destroying them would quietly change
fixture behaviour.

What is replaced -- string values under credential-named keys, and string
values matching a known credential shape (JWT, PEM block, provider token
formats) wherever they appear.

The replacement is derived from the ENTRY ID AND KEY PATH, never from the
secret. Hashing a credential to produce a "safe" placeholder just publishes a
cracking target, especially for short or low-entropy values. Deriving from
location instead keeps the output deterministic -- the same field in the same
entry always yields the same placeholder, so equality relationships a fixture
depends on are stable across regenerations -- while carrying no information
about what was there.

    python tools/sanitize_ha_snapshot.py IN [--output OUT] [--check]

``--check`` reports what would change and exits non-zero if anything would,
which is what CI runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Any

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from secret_scan import SYNTHETIC_MARKER, VALUE_SIGNATURES  # noqa: E402

#: Key names whose STRING values are credential material. Deliberately
#: narrower than the scanner's detection set: this one rewrites data, so a
#: false positive silently corrupts a fixture. Numeric settings are excluded
#: structurally (only strings are rewritten), not by name.
CREDENTIAL_KEYS = re.compile(
    r"(?:^|_)(?:"
    r"password|passwd|pwd"
    r"|secret|client_secret"
    r"|api_?key|app_?key|access_?code|pin_?code"
    r"|access_?token|refresh_?token|auth_?token|id_?token|login_?token"
    r"|service_?token|session_?token|device_?token|adp_?token"
    r"|credentials?|credentials_hash|stored_credentials"
    r"|cookie|2fa_cookie"
    r"|private_?key|encryption_?key|psk"
    r"|webhook_?id|cloudhook_?url"
    r"|token|tokens|token_info"
    r"|auth|key"
    r")$",
    re.I,
)

#: Suffix-matched credential names that do NOT use an underscore boundary.
#: HomeKit writes AccessoryLTPK / AccessoryLTSK / iOSDeviceLTPK / iOSDeviceLTSK
#: -- LTSK is the controller's long-term SECRET key. An underscore-anchored
#: pattern misses all four, which is exactly the kind of quiet gap that leaves
#: real key material in a "sanitized" fixture.
CREDENTIAL_SUFFIXES = re.compile(r"(?:ltpk|ltsk|_psk|privatekey|secretkey)$", re.I)

#: Names that end in a credential word but are not credentials here.
NOT_CREDENTIALS = frozenset(
    {
        "max_tokens",
        "ai_maximum_estimated_tokens",
        "ollama_maximum_output_tokens",
        "maximum_output_tokens",
        "num_tokens",
        "public_key",
        "api_key_name",
        "accessorypairingid",
    }
)


def placeholder(entry_id: str, key_path: str) -> str:
    """A value that is unmistakably synthetic and derived only from location."""
    tag = hashlib.sha256(f"{entry_id}|{key_path}".encode()).hexdigest()[:12]
    return f"{SYNTHETIC_MARKER}-{tag}"


def _is_credential_key(key: str) -> bool:
    bare = str(key)
    if bare.lower() in NOT_CREDENTIALS:
        return False
    return bool(CREDENTIAL_KEYS.search(bare) or CREDENTIAL_SUFFIXES.search(bare))


def _has_credential_shape(value: str) -> bool:
    return any(pattern.search(value) for _name, pattern in VALUE_SIGNATURES)


def sanitize_value(value: Any, entry_id: str, key_path: str, stats: dict) -> Any:
    if isinstance(value, dict):
        return {
            k: sanitize_value(v, entry_id, f"{key_path}.{k}", stats)
            if not (_is_credential_key(k) and isinstance(v, str))
            else _replace(v, entry_id, f"{key_path}.{k}", stats, "key_name")
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            sanitize_value(v, entry_id, f"{key_path}[{i}]", stats)
            for i, v in enumerate(value)
        ]
    if isinstance(value, str) and _has_credential_shape(value):
        return _replace(value, entry_id, key_path, stats, "value_shape")
    return value


def _replace(value: str, entry_id: str, key_path: str, stats: dict, why: str) -> str:
    if SYNTHETIC_MARKER in value:
        stats["already_synthetic"] = stats.get("already_synthetic", 0) + 1
        return value
    stats[why] = stats.get(why, 0) + 1
    stats.setdefault("fields", set()).add(key_path.rsplit(".", 1)[-1])
    return placeholder(entry_id, key_path)


def sanitize_document(document: Any) -> tuple[Any, dict]:
    """Sanitize a whole .storage document, preserving its envelope."""
    stats: dict = {}
    data = document.get("data") if isinstance(document, dict) else None
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        entries = []
        for entry in data["entries"]:
            entry_id = str(entry.get("entry_id", ""))
            entries.append(
                {
                    k: (
                        sanitize_value(v, entry_id, k, stats)
                        if k in ("data", "options", "subentries")
                        else v
                    )
                    for k, v in entry.items()
                }
            )
        document = {**document, "data": {**data, "entries": entries}}
    else:  # any other .storage shape: sanitize wholesale, keep the envelope
        document = {
            **document,
            "data": sanitize_value(data, "", "data", stats),
        }
    return document, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--output")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    with open(args.path, encoding="utf-8") as handle:
        original = json.load(handle)
    sanitized, stats = sanitize_document(original)
    replaced = stats.get("key_name", 0) + stats.get("value_shape", 0)
    fields = sorted(stats.get("fields", set()))

    print(f"{args.path}")
    print(f"  replaced by key name : {stats.get('key_name', 0)}")
    print(f"  replaced by value shape: {stats.get('value_shape', 0)}")
    print(f"  already synthetic    : {stats.get('already_synthetic', 0)}")
    print(f"  field names affected : {', '.join(fields) if fields else 'none'}")

    if args.check:
        return 1 if replaced else 0
    target = args.output or args.path
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(sanitized, handle, indent=2, sort_keys=False)
        handle.write("\n")
    print(f"  written              : {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
