# Changelog

All notable changes to HAMIE are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). HAMIE is pre-1.0;
minor version bumps may include breaking changes until 1.0.0.

## [0.6.0-beta.1] — first public beta

Initial public release. Everything below describes the capability set at
this snapshot, not a diff against a prior public release (there wasn't
one).

### Added

- **Deterministic finding engine**: a set of analyzers
  (`hamie/analysis/analyzers/`) that detect duplicate-migration residue,
  orphaned definitions, unavailable entities, functional self-references,
  removed-integration orphans, abandoned bugfix forks, and wrong-domain
  actions, each emitting atomic, reproducible `Finding` objects.
- **Incident layer**: findings are grouped under durable incidents with a
  deterministic root key, explicit evidence status, and a lifecycle (new,
  investigating, confirmed, dismissed, ignored, resolved, recurring,
  regressed). Priority is based on condition and safety impact, not group
  size.
- **Bounded AI investigation layer**: a read-only Home Assistant LLM API
  registration exposing narrow tools (entity/automation/incident/dependency
  lookup, recent changes, provenance context, planning-only validation).
  No shell, filesystem, service-call, approval, execution, reload, restart,
  or deployment tool is reachable from it. See
  [docs/AI_ACCESS_LAYER.md](docs/AI_ACCESS_LAYER.md).
- **Approval-bound remediation lifecycle**: propose → fingerprinted
  approval → precondition verification → modify and validate the
  authoritative configuration → commit → deploy → verify → automatic
  rollback on failure.
- **Protected-dependency registry**
  (`hamie/domain/protected_dependencies.py`): a declarative model for
  dependency chains that must not be severed by an automated action,
  including multi-alias physical endpoints (one outlet reachable through
  more than one integration's entity id).
- **Build provenance verification** (`tools/build_deploy.py`): refuses to
  report a deploy successful until source HEAD, the packaged build,
  the deployed tree, and the running instance's own reported commit all
  agree.
- **Predeploy backup retention** (`tools/deploy_backup.py`): a pure, tested
  keep-latest-N policy with pinning and in-flight-rollback protection,
  decoupled from the ssh transport that actually performs it.
- **Deterministic secret/privacy scanner** (`tools/secret_scan.py`) and a
  companion sanitizer for Home Assistant `.storage` captures
  (`tools/sanitize_ha_snapshot.py`), plus a pre-commit guard and CI
  workflow that run it automatically.
- **Sanitized public export tooling** (`tools/export_public.py`): the
  mechanism this repository itself is produced by — see
  [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#privacy-and-the-private-tree).
- A Lit-based custom panel frontend (`hamie/frontend/`) presenting the
  incident workbench, remediation review, and audit views.

### Known limitations

See [ROADMAP.md](ROADMAP.md) — notably: no HACS listing yet, no pinned
minimum Home Assistant version, several investigation-tool adapters
(device/area/floor/label registries, config-entry detail, repairs, traces,
recorder history, long-term statistics, log excerpts) are not yet wired up,
and no static-analysis/linting is configured in CI yet.
