"""HAMIE-owned maintenance notes file format (Phase 3B).

Deterministic, hand-rolled, closed-schema serializer/parser for exactly
one editable resource (``domain/remediation_resources.py``'s
``hamie.maintenance_notes``). Deliberately not a general YAML
implementation, and takes no third-party dependency: HAMIE ships with
zero runtime dependencies beyond Home Assistant itself (see
``pyproject.toml``'s ``dependencies = []``).

Round-trip safety (mission Phase 11) is achieved by construction rather
than by a general-purpose parser: HAMIE is the only writer and the only
reader of this file, so there is no "preserve unknown syntax" problem
to solve. Any on-disk content that does not match this exact, narrow
grammar is treated as foreign/unrecognized and rejected outright --
never guessed at, never partially repaired -- which is exactly the
"restrict editable YAML resources to a HAMIE-owned, explicitly
supported format" option the mission calls out as acceptable when a
proven round-trip-preserving generic parser is not used.
"""

from __future__ import annotations

import re

SCHEMA_VERSION = 1
MAX_NOTE_KEY_LENGTH = 128
MAX_NOTE_VALUE_LENGTH = 500
MAX_NOTES = 64

_HEADER = f"schema_version: {SCHEMA_VERSION}\n"
_NOTES_EMPTY = "notes: {}\n"
_NOTES_HEADER = "notes:\n"
_ENTRY_PATTERN = re.compile(r'^  ([A-Za-z0-9_.\-]{1,128}): "((?:[^"\\]|\\.)*)"\n?$')
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")


class MaintenanceNotesFormatError(ValueError):
    """The file's on-disk content does not match HAMIE's owned format."""


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _unescape(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            next_char = value[index + 1]
            result.append("\n" if next_char == "n" else next_char)
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def render_notes(notes: dict[str, str]) -> str:
    """Return the exact deterministic file content for ``notes``."""
    if len(notes) > MAX_NOTES:
        raise ValueError(f"cannot render more than {MAX_NOTES} notes")
    if not notes:
        return _HEADER + _NOTES_EMPTY
    lines = [_HEADER, _NOTES_HEADER]
    for key in sorted(notes):
        if not _KEY_PATTERN.match(key):
            raise ValueError(f"invalid maintenance note key: {key!r}")
        value = notes[key]
        if len(value) > MAX_NOTE_VALUE_LENGTH:
            raise ValueError(f"maintenance note value for {key!r} is too long")
        lines.append(f'  {key}: "{_escape(value)}"\n')
    return "".join(lines)


def parse_notes(content: str) -> dict[str, str]:
    """Parse HAMIE's own maintenance-notes format strictly.

    Raises ``MaintenanceNotesFormatError`` for anything that does not
    match exactly what ``render_notes`` would have produced.
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0] != _HEADER:
        raise MaintenanceNotesFormatError(
            "missing or unsupported maintenance-notes schema_version header"
        )
    if len(lines) == 2 and lines[1] == _NOTES_EMPTY:
        return {}
    if len(lines) == 1 and content == _HEADER:
        raise MaintenanceNotesFormatError("missing notes header")
    if len(lines) < 2 or lines[1] != _NOTES_HEADER:
        raise MaintenanceNotesFormatError("missing notes header")
    notes: dict[str, str] = {}
    for line in lines[2:]:
        match = _ENTRY_PATTERN.match(line)
        if not match:
            raise MaintenanceNotesFormatError(f"unrecognized notes line: {line!r}")
        key, raw_value = match.group(1), match.group(2)
        if key in notes:
            raise MaintenanceNotesFormatError(f"duplicate note key: {key!r}")
        notes[key] = _unescape(raw_value)
    if len(notes) > MAX_NOTES:
        raise MaintenanceNotesFormatError(f"more than {MAX_NOTES} notes present")
    return notes


def empty_notes_content() -> str:
    return _HEADER + _NOTES_EMPTY
