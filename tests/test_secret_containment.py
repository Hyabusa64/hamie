"""Credential containment: sanitizer rules, scanner behaviour, repo invariant.

secret-scan: allow-credential-shaped-literals
  This file must contain a JWT-shaped literal to prove the sanitizer rewrites
  one. The pragma suppresses only the value-shape class and only under tests/.

This repository committed two verbatim ``core.config_entries`` documents --
every integration credential in the house, in cleartext, in git. These tests
exist so that cannot happen quietly again, and so the sanitizer that fixed it
cannot silently start missing a field.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

from sanitize_ha_snapshot import (  # noqa: E402
    CREDENTIAL_SUFFIXES,
    NOT_CREDENTIALS,
    placeholder,
    sanitize_document,
)
from secret_scan import (  # noqa: E402
    SYNTHETIC_MARKER,
    ScanResult,
    load_reviewed,
    scan_file,
)


def _entry(entry_id: str, data: dict, options: dict | None = None) -> dict:
    return {
        "entry_id": entry_id,
        "domain": "demo",
        "title": "Demo",
        "source": "user",
        "unique_id": f"uid-{entry_id}",
        "version": 1,
        "minor_version": 1,
        "disabled_by": None,
        "data": data,
        "options": options or {},
    }


def _doc(*entries: dict) -> dict:
    return {
        "version": 1,
        "minor_version": 1,
        "key": "core.config_entries",
        "data": {"entries": list(entries)},
    }


# ------------------------------------------------------------- sanitizer


def test_credential_named_string_fields_are_replaced() -> None:
    doc = _doc(
        _entry(
            "e1",
            {
                "access_token": "live-value-aaaaaaaaaaaaaaaa",
                "refresh_token": "live-value-bbbbbbbbbbbbbbbb",
                "password": "hunter2hunter2",
                "client_secret": "cs-cccccccccccccccc",
                "api_key": "ak-dddddddddddddddd",
            },
        )
    )
    out, stats = sanitize_document(doc)
    values = out["data"]["entries"][0]["data"]
    assert stats["key_name"] == 5
    for field, value in values.items():
        assert SYNTHETIC_MARKER in value, field
        assert "live-value" not in value and "hunter2" not in value


def test_homekit_long_term_secret_keys_are_replaced() -> None:
    """AccessoryLTSK / iOSDeviceLTSK have no underscore boundary.

    An underscore-anchored pattern misses all four HomeKit key fields, which
    is exactly the sort of gap that leaves real key material in a fixture
    everyone believes is sanitized.
    """
    doc = _doc(
        _entry(
            "hk",
            {
                "AccessoryLTPK": "aaaaaaaaaaaaaaaaaaaaaaaa",
                "AccessoryLTSK": "bbbbbbbbbbbbbbbbbbbbbbbb",
                "iOSDeviceLTPK": "cccccccccccccccccccccccc",
                "iOSDeviceLTSK": "dddddddddddddddddddddddd",
                "AccessoryPairingID": "AA:BB:CC:DD:EE:FF",
            },
        )
    )
    out, _stats = sanitize_document(doc)
    values = out["data"]["entries"][0]["data"]
    for field in ("AccessoryLTPK", "AccessoryLTSK", "iOSDeviceLTPK", "iOSDeviceLTSK"):
        assert SYNTHETIC_MARKER in values[field], field
    # A pairing *identifier* is not key material and must survive.
    assert values["AccessoryPairingID"] == "AA:BB:CC:DD:EE:FF"
    for name in ("AccessoryLTSK", "iOSDeviceLTSK"):
        assert CREDENTIAL_SUFFIXES.search(name)


def test_numeric_settings_whose_names_contain_token_are_preserved() -> None:
    """max_tokens is a setting, not a secret. Destroying it changes behaviour."""
    doc = _doc(
        _entry(
            "ai",
            {
                "max_tokens": 4096,
                "ollama_maximum_output_tokens": 2048,
                "ai_maximum_estimated_tokens": 120000,
                "access_token": "real-token-aaaaaaaaaaaa",
            },
        )
    )
    out, _stats = sanitize_document(doc)
    values = out["data"]["entries"][0]["data"]
    assert values["max_tokens"] == 4096
    assert values["ollama_maximum_output_tokens"] == 2048
    assert values["ai_maximum_estimated_tokens"] == 120000
    assert SYNTHETIC_MARKER in values["access_token"]
    for name in ("max_tokens", "ollama_maximum_output_tokens"):
        assert name in NOT_CREDENTIALS


def test_credential_shaped_values_are_replaced_under_any_key_name() -> None:
    doc = _doc(_entry("jwt", {"harmless_field": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sig"}))
    out, stats = sanitize_document(doc)
    assert stats.get("value_shape") == 1
    assert SYNTHETIC_MARKER in out["data"]["entries"][0]["data"]["harmless_field"]


def test_placeholders_are_location_derived_never_value_derived() -> None:
    """Hashing a secret to make a 'safe' placeholder publishes a crack target."""
    a = _doc(_entry("e1", {"password": "secret-one-aaaaaaaa"}))
    b = _doc(_entry("e1", {"password": "completely-different-bbbb"}))
    out_a, _ = sanitize_document(a)
    out_b, _ = sanitize_document(b)
    # Same location, different secrets -> identical placeholder. The output
    # therefore carries no information about the input.
    assert out_a["data"]["entries"][0]["data"]["password"] == (
        out_b["data"]["entries"][0]["data"]["password"]
    )
    assert out_a["data"]["entries"][0]["data"]["password"] == placeholder("e1", "data.password")


def test_different_entries_get_different_placeholders() -> None:
    doc = _doc(_entry("e1", {"password": "x" * 20}), _entry("e2", {"password": "x" * 20}))
    out, _ = sanitize_document(doc)
    first, second = (e["data"]["password"] for e in out["data"]["entries"])
    assert first != second


def test_sanitizing_twice_changes_nothing_further() -> None:
    doc = _doc(_entry("e1", {"access_token": "live-aaaaaaaaaaaaaaaa"}))
    once, _ = sanitize_document(doc)
    twice, stats = sanitize_document(once)
    assert once == twice
    assert stats.get("key_name", 0) == 0
    assert stats.get("already_synthetic", 0) == 1


def test_structure_is_preserved_exactly() -> None:
    doc = _doc(
        _entry(
            "e1",
            {"host": "10.0.0.5", "port": 8123, "ssl": False, "nested": {"password": "p" * 12}},
            {"scan_interval": 30},
        )
    )
    out, _ = sanitize_document(doc)
    entry = out["data"]["entries"][0]
    assert entry["entry_id"] == "e1" and entry["unique_id"] == "uid-e1"
    assert entry["data"]["host"] == "10.0.0.5"
    assert entry["data"]["port"] == 8123
    assert entry["data"]["ssl"] is False
    assert entry["options"] == {"scan_interval": 30}
    assert SYNTHETIC_MARKER in entry["data"]["nested"]["password"]
    assert out["key"] == "core.config_entries" and out["version"] == 1


# --------------------------------------------------------------- scanner


def _scan(tmp_path, name: str, payload) -> ScanResult:
    path = tmp_path / name
    path.write_text(json.dumps(payload) if not isinstance(payload, str) else payload)
    result = ScanResult()
    scan_file(str(path), result, set(), str(tmp_path))
    return result


def test_scanner_detects_a_raw_config_entry_snapshot(tmp_path) -> None:
    result = _scan(tmp_path, "core.config_entries", _doc(_entry("e1", {"password": "Tr0ub4dor-and-3-horses"})))
    kinds = {f.kind for f in result.findings}
    assert "ha_storage_snapshot" in kinds
    assert "populated_credential_keys" in kinds
    assert not result.ok


def test_scanner_passes_a_sanitized_snapshot(tmp_path) -> None:
    sanitized, _ = sanitize_document(_doc(_entry("e1", {"password": "Tr0ub4dor-and-3-horses"})))
    result = _scan(tmp_path, "core.config_entries", sanitized)
    assert result.synthetic_values_seen == 1
    assert [f.kind for f in result.findings] == ["ha_storage_snapshot"]


def test_scanner_never_emits_a_secret(tmp_path) -> None:
    secret = "super-secret-value-do-not-print-1234"
    result = _scan(tmp_path, "core.config_entries", _doc(_entry("e1", {"password": secret})))
    blob = json.dumps([f.as_dict() for f in result.findings])
    assert secret not in blob
    for fragment in (secret[:8], secret[-8:]):
        assert fragment not in blob


def test_scanner_ignores_ui_labels_that_merely_mention_credentials(tmp_path) -> None:
    result = _scan(
        tmp_path,
        "strings.json",
        {"options": {"step": {"x": {"data": {"credential_required": "Credential is required"}}}}},
    )
    assert [f for f in result.findings if f.kind == "populated_credential_keys"] == []


def test_scanner_ignores_discovery_identifiers(tmp_path) -> None:
    doc = _doc(_entry("e1", {}))
    doc["data"]["entries"][0]["discovery_keys"] = {
        "dhcp": [{"domain": "dhcp", "key": "aabbccddeeff", "version": 1}]
    }
    result = _scan(tmp_path, "core.config_entries", doc)
    assert [f for f in result.findings if f.kind == "populated_credential_keys"] == []


def test_scanner_ignores_the_storage_envelope_key(tmp_path) -> None:
    result = _scan(tmp_path, "core.area_registry",
                   {"version": 1, "key": "core.area_registry", "data": {"areas": []}})
    assert [f for f in result.findings if f.kind == "populated_credential_keys"] == []


def test_scanner_detects_provider_token_shapes(tmp_path) -> None:
    result = _scan(tmp_path, "notes.json", {"note": "ghp_" + "a" * 30})
    assert any(f.kind == "credential_value_shape" for f in result.findings)


def test_shape_pragma_is_scoped_to_tests_only(tmp_path) -> None:
    """A pragma that worked anywhere would be a scanner off-switch."""
    from secret_scan import SHAPE_PRAGMA

    payload = f"# {SHAPE_PRAGMA}\n" + json.dumps({"note": "ghp_" + "b" * 30})
    outside = tmp_path / "hamie"
    outside.mkdir()
    (outside / "sneaky.py").write_text(payload)
    result = ScanResult()
    scan_file(str(outside / "sneaky.py"), result, set(), str(tmp_path))
    assert any(f.kind == "credential_value_shape" for f in result.findings)

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "ok.py").write_text(payload)
    allowed = ScanResult()
    scan_file(str(tests_dir / "ok.py"), allowed, set(), str(tmp_path))
    assert not any(f.kind == "credential_value_shape" for f in allowed.findings)


def test_pragma_cannot_hide_a_raw_storage_snapshot(tmp_path) -> None:
    from secret_scan import SHAPE_PRAGMA

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    doc = {"_comment": SHAPE_PRAGMA, **_doc(_entry("e1", {"password": "Tr0ub4dor-and-3-horses"}))}
    (tests_dir / "snap.json").write_text(json.dumps(doc))
    result = ScanResult()
    scan_file(str(tests_dir / "snap.json"), result, set(), str(tmp_path))
    kinds = {f.kind for f in result.findings}
    assert "ha_storage_snapshot" in kinds
    assert "populated_credential_keys" in kinds


def test_reviewed_manifest_downgrades_a_clean_snapshot(tmp_path) -> None:
    payload = {"version": 1, "key": "core.area_registry", "data": {"areas": []}}
    path = tmp_path / "core.area_registry"
    path.write_text(json.dumps(payload))
    unreviewed = ScanResult()
    scan_file(str(path), unreviewed, set(), str(tmp_path))
    assert not unreviewed.ok, "an unreviewed raw snapshot must fail"
    reviewed = ScanResult()
    scan_file(str(path), reviewed, {"core.area_registry"}, str(tmp_path))
    assert reviewed.ok
    assert reviewed.advisories


# ---------------------------------------------------- repository invariant


def _tracked(pattern: str) -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    return [p for p in out.stdout.split() if pattern in p]


@pytest.fixture(scope="session")
def repository_scan() -> ScanResult:
    """One repo-wide scan shared by every invariant test.

    Scanning 500+ files is not free, and a suite that takes a minute is a
    suite people start skipping -- which would defeat the point of having a
    committed secret guard at all.
    """
    result = ScanResult()
    reviewed = load_reviewed(REPO)
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    for rel in out.stdout.split():
        scan_file(os.path.join(REPO, rel), result, reviewed, REPO)
    return result


@pytest.mark.parametrize("path", _tracked("config_entries"))
def test_no_tracked_config_entry_snapshot_contains_credentials(path: str) -> None:
    """The permanent guard. If this fails, a raw capture was committed."""
    with open(os.path.join(REPO, path), encoding="utf-8") as handle:
        document = json.load(handle)
    _out, stats = sanitize_document(document)
    assert stats.get("key_name", 0) == 0, f"{path} has credential-named values"
    assert stats.get("value_shape", 0) == 0, f"{path} has credential-shaped values"


def test_every_tracked_storage_snapshot_is_reviewed(repository_scan: ScanResult) -> None:
    unreviewed = [f.path for f in repository_scan.errors if f.kind == "ha_storage_snapshot"]
    assert not unreviewed, f"raw .storage snapshots not in the reviewed manifest: {unreviewed}"


def test_repository_scan_is_clean(repository_scan: ScanResult) -> None:
    assert repository_scan.ok, [f.as_dict() for f in repository_scan.errors]


def test_sanitized_config_entry_fixture_kept_its_analysis_surface() -> None:
    """Sanitization must not have cost the fields HAMIE's analysis reads."""
    path = os.path.join(REPO, "benchmark/live_snapshot_20260823_2311/storage/core.config_entries")
    if not os.path.exists(path):
        pytest.skip("benchmark/ live-snapshot fixture not present in this checkout")
    with open(path, encoding="utf-8") as handle:
        entries = json.load(handle)["data"]["entries"]
    assert len(entries) == 166
    assert len({e["entry_id"] for e in entries}) == 166
    for field in ("domain", "title", "source", "unique_id", "version", "disabled_by"):
        assert any(field in e for e in entries), field
    # unique_id is identity evidence for duplicate/migration analysis, so it
    # must survive sanitization intact. Not every config entry has one -- the
    # invariant is that the ones that do were not stripped or replaced.
    with_uid = [e["unique_id"] for e in entries if e.get("unique_id")]
    assert len(with_uid) > 50
    assert not any(SYNTHETIC_MARKER in str(u) for u in with_uid)
    # unique_id is unique per platform, not globally: a MAC address can be the
    # unique_id of several integrations for the same physical device. Uniqueness
    # is asserted per domain, which is the constraint Home Assistant enforces.
    per_domain: dict[str, list[str]] = {}
    for entry in entries:
        if entry.get("unique_id"):
            per_domain.setdefault(entry["domain"], []).append(entry["unique_id"])
    for domain, ids in per_domain.items():
        assert len(set(ids)) == len(ids), f"unique_id collision within {domain}"


def test_archives_are_surfaced_rather_than_silently_skipped(tmp_path) -> None:
    """A build artifact shipping a raw snapshot is a real risk.

    The scanner does not open archives -- extracting them inside a security
    tool is its own hazard -- but it must not imply it checked them.
    """
    archive = tmp_path / "build.zip"
    archive.write_bytes(b"PK\x03\x04not-a-real-zip")
    result = ScanResult()
    scan_file(str(archive), result, set(), str(tmp_path))
    kinds = {f.kind for f in result.findings}
    assert "archive_not_scanned" in kinds
    assert result.ok, "an unexamined archive is advisory, not a build failure"


# ------------------------------------ credentials embedded in connection URIs
#
# This class was invisible to the scanner and shipped to production. The live
# Home Assistant recorder carried
# `db_url: mysql://<user>:<password>@<host>/<db>` in
# configuration.yaml, and two git-TRACKED snapshot copies of that file carried
# the same password into committed history -- while the scanner reported PASS.
# The key is `db_url`, matching no credential-key pattern, and the value is a
# URL, matching no value signature.

import pytest

from tools.secret_scan import SYNTHETIC_MARKER, VALUE_SIGNATURES

_URI_RE = dict(VALUE_SIGNATURES)["connection_uri_credential"]


@pytest.mark.parametrize(
    "text",
    [
        "db_url: mysql://svc:hunter2hunter2@db.example.invalid/appdb?charset=utf8mb4",
        "db_url: mariadb://user:pw12345@db.local/homeassistant",
        "DATABASE_URL=postgresql://admin:s3cr3tvalue@10.0.0.5:5432/app",
        "mongodb+srv://svc:tokenvalue@cluster0.example.net/db",
        "redis://default:cachepass@10.0.0.9:6379/0",
        "amqp://guest:guestpass@rabbit.local:5672/vhost",
    ],
)
def test_embedded_uri_credentials_are_detected(text: str) -> None:
    assert _URI_RE.search(text), f"connection-URI credential not detected in: {text}"


@pytest.mark.parametrize(
    "text",
    [
        # The remediated shape. Must never be flagged, or the fix would be
        # unusable.
        "db_url: !secret recorder_db_url",
        "db_url: mysql://svc:!secret recorder_db_pw@db.example.invalid/appdb",
        # No credential present at all.
        "db_url: sqlite:////config/home-assistant_v2.db",
        "postgresql://readonly@10.0.0.5:5432/app",
        "url: https://example.com/path?query=1",
        "mysql://user:@host/db",
    ],
)
def test_credential_free_connection_strings_are_not_flagged(text: str) -> None:
    assert not _URI_RE.search(text), f"false positive on: {text}"


def test_synthetic_marker_still_exempts_a_uri() -> None:
    text = f"db_url: mysql://hass:{SYNTHETIC_MARKER}@db/homeassistant"
    match = _URI_RE.search(text)
    # It may match the shape, but the marker is what exempts it downstream.
    assert match is None or SYNTHETIC_MARKER in match.group(0)
