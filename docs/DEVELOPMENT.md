# Development

## Clone and environment

```bash
git clone https://github.com/<owner>/hamie.git
cd hamie
python3 -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements-dev.txt
```

Python 3.12+ is required (`hamie/domain/serialization.py` uses PEP 695
generic function syntax). `requirements-dev.txt` was verified against a
genuinely fresh virtualenv running the complete backend test suite with
zero additional packages — the real `homeassistant` package is **not**
required for tests; `tests/ha_stubs.py` stubs the slice of the Home
Assistant API HAMIE's own tests touch.

## Running the tests

```bash
python -m pytest
```

All backend tests should pass with no network access and no Home Assistant
instance running. If a test seems to need one, that's a bug in the test —
please open an issue.

## Running the secret/privacy scanner

```bash
python tools/secret_scan.py          # tracked files only (what CI checks)
python tools/secret_scan.py --all    # your entire working tree
python tools/secret_scan.py --json   # machine-readable output
```

This is a deterministic, offline, dependency-free scanner for credential-
shaped values and raw Home Assistant `.storage` captures. Run it before
committing anything derived from a real Home Assistant instance — a
diagnostics export, a `.storage` snapshot, a config-entries dump. See
[SECURITY.md](../SECURITY.md) for what to do if it finds something.

Optionally install the pre-commit guard, which scans the *staged* tree
(not your working tree) so a secret can't ride in on a file you forgot you
had staged:

```bash
ln -sf ../../tools/hooks/pre-commit .git/hooks/pre-commit
```

## Frontend

The custom panel (`hamie/frontend/`) is built with esbuild from
`hamie/frontend/hamie-app.js` into the single bundle
`hamie/frontend/dist/hamie-app.js` that Home Assistant actually serves.

```bash
npm install
npm run build:frontend
```

`package-lock.json` is committed; use `npm ci` in CI-like contexts for a
reproducible install.

## Static analysis

Not yet configured (see [ROADMAP.md](../ROADMAP.md)). Match the existing
code's style in the file you're editing until a linter/formatter is added.

## Building a deployment package

```bash
python tools/build_deploy.py --check              # provenance preflight only
python tools/build_deploy.py --package /path/to/staging-dir
```

`--package` produces a staging tree containing exactly the integration
files Home Assistant needs (build caches, VCS metadata, and platform
sidecar files like macOS's `._*` are excluded — see
`tools/build_deploy.py`'s `EXCLUDED_*` constants and
`tests/test_build_provenance.py` for what's pinned) plus a generated
`build_info.json` recording the exact source commit and whether the tree
was clean.

### Deploying to a real Home Assistant instance

`tools/build_deploy.py --deploy` runs the full pipeline: test suite, secret
scan, package, a timestamped predeploy backup, transfer over `rsync`/`ssh`,
a byte-identical parity check, a restart, and a runtime provenance check
that confirms Home Assistant is actually executing the commit you just
built. Any failure after the backup is taken triggers an automatic restore
from that backup.

Nothing about your Home Assistant host is hardcoded. Configure it with
environment variables (or the equivalent `--flag`):

| Variable | Default | Meaning |
|---|---|---|
| `HAMIE_SSH_TARGET` | `homeassistant` | an ssh `Host` alias from your `~/.ssh/config`, or `user@host` |
| `HAMIE_DEPLOY_PATH` | `/config/custom_components/hamie` | remote path (this default matches Home Assistant OS/Supervised) |
| `HAMIE_BACKUP_DIR` | `/config/hamie_backups` | where predeploy backups are stored on the remote host |
| `HAMIE_RESTART_COMMAND` | `ha core restart` | the Supervisor CLI restart; a Core/venv install should override this, e.g. `sudo systemctl restart home-assistant@homeassistant` |

Predeploy backups are retained with `tools/deploy_backup.py` (default: keep
the latest 5, plus anything pinned or currently needed for rollback — see
that file's docstring and `tests/test_deploy_backup.py` for the exact
policy). To inspect or prune backups directly:

```bash
python tools/deploy_backup.py --list --target ha --backup-dir /config/hamie_backups
python tools/deploy_backup.py --apply-retention --target ha \
    --backup-dir /config/hamie_backups --keep 5 --dry-run
```

### Verifying provenance without deploying

```bash
python tools/build_deploy.py --verify-only
```

Confirms `source HEAD == packaged build_commit == deployed build_commit ==
runtime build_commit` against whatever is currently live, without
transferring anything.

## Privacy and the private tree

This public repository is produced from a private development tree by
`tools/export_public.py`, which:

1. reads only the private tree's **tracked** files (an allowlist — a file
   that was never `git add`-ed cannot leak, regardless of content);
2. drops a small number of directories/files that are real household
   analysis data or history by construction, not something a line-by-line
   substitution could safely genericize;
3. applies a literal find-and-replace table to genericize the handful of
   real values (entity ids, a device nickname, a LAN IP) that legitimately
   exist in a few files as real registry data the private installation
   depends on;
4. re-scans the result with `tools/secret_scan.py` **and** an independent,
   hand-maintained forbidden-literal sweep, and deletes the entire export
   rather than publishing anything if either finds something.

See `tools/export_public.py`'s module docstring and
`tests/test_export_public.py` for the exact mechanics. If you find real
household-identifying data anywhere in this repository despite that
process, please treat it as a security report — see [SECURITY.md](../SECURITY.md).
