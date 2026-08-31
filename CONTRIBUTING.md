# Contributing to HAMIE

Thanks for considering it. HAMIE is pre-1.0 and still finding its shape, so
please open an issue to discuss anything larger than a small fix before
putting significant work into a PR.

## Before you start

- Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
  [docs/AI_ACCESS_LAYER.md](docs/AI_ACCESS_LAYER.md). The safety boundary
  they describe — deterministic evidence decides, the model only describes
  — is the one non-negotiable design constraint in this project. A PR that
  widens what an AI provider can do without going through that boundary
  will not be merged regardless of how useful it is.
- Set up your environment per [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Coding style

Match the surrounding file. In particular:

- `hamie/domain/` is pure logic: no imports of `homeassistant.*`, no I/O,
  no network. If your change needs either, it belongs in `application/`,
  `infrastructure/`, or `connectors/`.
- Prefer immutable data (frozen dataclasses) for anything that represents
  evidence, a decision, or an approval. HAMIE's audit trail depends on
  these objects not changing out from under it.
- Docstrings and comments explain *why*, not *what* — the code already says
  what it does. A comment earns its place by recording a non-obvious
  constraint, a workaround for a specific bug, or a fact proven from a real
  incident (several existing modules do this; it's deliberate, not
  decoration).

## Tests

- New behavior needs a new test. A bug fix needs a test that fails without
  the fix.
- Run `python -m pytest` before opening a PR; it should pass with no
  network access and no real Home Assistant instance.
- If your change touches Home Assistant's API surface, extend
  `tests/ha_stubs.py` rather than requiring the real `homeassistant`
  package in tests.
- Run `python tools/secret_scan.py --all` before committing anything
  derived from a real Home Assistant instance (a diagnostics export, a
  `.storage` snapshot). See [SECURITY.md](SECURITY.md).

## Proposing a new analyzer, protected-dependency type, or remediation capability

- **A new analyzer** (`hamie/analysis/analyzers/`): describe the class of
  problem it detects, why existing analyzers don't already cover it, and
  what evidence it needs. It should emit `Finding` objects and nothing
  else — grouping, prioritization, and lifecycle are the incident layer's
  job, not the analyzer's.
- **A new protected-dependency type** (`hamie/domain/protected_dependencies.py`):
  these are declarative data (an id, a dependency chain, evidence, a rule),
  not new branches in remediation code. If you're protecting a chain that
  can be reached through more than one entity id or alias (the way a
  device integrated twice can be), see that module's `ProtectedEndpoint`/
  `AliasEvidence` model — protecting a single id when the real endpoint has
  several is exactly the gap the existing shipped example was built to
  close.
- **A new remediation capability**: it must fit the existing pipeline
  (evidence → proposal → fingerprinted approval → validate → commit →
  deploy → verify → rollback), not bypass a stage of it. If your use case
  genuinely doesn't fit, open an issue to discuss before writing code —
  this is the part of HAMIE most worth getting right before merging.

## What a PR should include

- Tests, as above.
- A clean `python tools/secret_scan.py` run if you touched fixtures or
  example configuration.
- No real Home Assistant data: no real entity ids, hostnames, IPs, device
  identifiers, or `.storage`/diagnostics dumps from an actual installation.
  Use the generic patterns already in `tests/` and `examples/` (e.g.
  `switch.example_*`, `192.0.2.x` documentation-range addresses).
- A short note on backward compatibility if you changed a public API,
  config-flow behavior, or the incident/finding schema.
- A short note on safety-boundary impact if you touched anything in
  `hamie/domain/investigation.py`, `hamie/domain/protection.py`,
  `hamie/domain/protected_dependencies.py`, or the remediation lifecycle.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
