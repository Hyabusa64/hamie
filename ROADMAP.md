# Roadmap

HAMIE is pre-1.0. This is a direction, not a set of promises with dates.
Priorities will shift based on what contributors and early users actually
run into.

## Toward a stable 1.0

- **Pin a minimum Home Assistant version.** `manifest.json` doesn't declare
  one yet; it should, once compatibility has been checked across a real
  version range rather than just the version development happens to run.
- **HACS readiness.** Current gaps: no `hacs.json`, no tagged GitHub
  releases with the expected asset naming, no brand assets submitted to
  [home-assistant/brands](https://github.com/home-assistant/brands). None
  of this is architecturally hard; it just hasn't been done yet.
- **Static analysis in CI.** No linter or type-checker is configured today
  (see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)). Adding one — and fixing
  what it finds — is overdue for a project this size.
- **Multi-release compatibility testing.** CI currently runs against one
  Python version and whatever Home Assistant APIs `tests/ha_stubs.py`
  models; testing against a matrix of supported Home Assistant releases
  would catch drift earlier.

## Investigation surface

Several evidence adapters described in
[docs/AI_ACCESS_LAYER.md](docs/AI_ACCESS_LAYER.md) are designed for but not
yet implemented: device/area/floor/label registry lookup, config-entry and
integration detail, repairs, traces, recorder history, long-term
statistics, relevant log excerpts, and a more complete dependency graph.
Each needs its own bounded, read-only adapter and sensitivity policy before
being exposed as an AI-reachable tool — see
[CONTRIBUTING.md](CONTRIBUTING.md) if you want to propose one.

## Analyzer ecosystem

The current analyzer set (`hamie/analysis/analyzers/`) covers duplicate-
migration residue, orphaned definitions, unavailable entities, functional
self-references, removed-integration orphans, abandoned bugfix forks, and
wrong-domain actions. There is room for more: config validation drift,
entity-naming convention checks, dashboard-reference staleness, and
whatever else contributors' own installations turn out to need. See
[CONTRIBUTING.md](CONTRIBUTING.md#proposing-a-new-analyzer-protected-dependency-type-or-remediation-capability).

## Deployment

`tools/build_deploy.py --deploy` targets an ssh + rsync workflow generic
enough for most manual/Core/Supervised installs. It has not been exercised
against Home Assistant OS's more managed update paths, and there is no
integration with HACS's own update mechanism yet — that only becomes
relevant once HACS readiness above is addressed.

## Documentation and community

- More worked examples under `examples/` as real usage patterns emerge from
  actual installations (with entity ids and network details genericized,
  as everything in this repository already is).
- Expanding [docs/adr/](docs/adr/) as further architectural decisions are
  made, rather than only documenting the AI-access-layer decision.

## Contributing to this roadmap

Open an issue if something here doesn't match reality anymore, or if
there's a direction you think is missing. See [CONTRIBUTING.md](CONTRIBUTING.md).
