"""Constants for HAMIE."""

import json
from pathlib import Path

DOMAIN = "hamie"
NAME = "HAMIE"
DATA_RUNTIME = "runtime"


def _manifest_version() -> str:
    """Read the one authoritative version from manifest.json.

    Dependency-free (stdlib only) so this stays importable before Home
    Assistant is available, and so manifest.json remains the single place
    a release version is ever written.
    """
    manifest_path = Path(__file__).with_name("manifest.json")
    return str(json.loads(manifest_path.read_text())["version"])


VERSION = _manifest_version()
