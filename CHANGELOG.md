# Changelog

All notable changes to HAMIE are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). HAMIE is pre-1.0;
minor version bumps may include breaking changes until 1.0.0.

## [0.7.0-beta.1] — repair orchestration

Builds the layer that lets HAMIE perform bounded Home Assistant
maintenance work directly, instead of every investigation ending in a
recommendation someone else has to act on.

### Added

- **Duplicate-automation-action detection**: compares automations'/
  scripts' normalized *effect* (target, service, significant
  parameters) rather than their names, classifying exact duplicates,
  overlapping duplicates, and potentially conflicting actions on the
  same target.
- **Structural automation/script definition inspection**, plus two new
  read-only investigation tools (`hamie_get_automation_definition`,
  `hamie_get_script_definition`) that return an automation's own
  trigger/condition/action body with each entity reference's exact
  structural location — enabling scoped mutation instead of a blind
  file-wide substitution. `EXECUTION_TOOLS` remains `frozenset()`.
- **A versioned Home Assistant compatibility rule registry**
  (mechanism only — ships with zero rules; see `docs/REPAIR_ORCHESTRATION.md`
  for why speculative rules were deliberately not included).
- **A Claude-escalation packet**: a secret-sanitized artifact packaging
  an incident's deterministic evidence and the specific unresolved
  question, for the cases HAMIE genuinely can't resolve on its own.
- **A repair recommendation queue and manual-escalation-rate metrics**,
  turning a large findings/incident set into a small, honestly-tiered
  "what's actually worth fixing right now" list.
- Strengthened the shared secret-looking-text redactor to also catch a
  credential embedded directly in a database connection URI.
- `docs/REPAIR_ORCHESTRATION.md`: the capability matrix, the
  evidence-backed top-priority repair classes, and an honest account of
  what was and wasn't built this pass.

### Notes

A ten-incident pilot against real (non-cherry-picked) findings data
found zero incidents eligible for the new playbooks in that specific
sample — expected, since the flagship stale-entity-reference class this
release targets was already resolved by prior manual repairs before the
sample was captured. See `docs/REPAIR_ORCHESTRATION.md`'s pilot section.

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
