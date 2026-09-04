# HAMIE

**Status: 0.6.0-beta.1 — pre-1.0 beta. Expect rough edges, breaking changes
between minor versions, and gaps documented in [ROADMAP.md](ROADMAP.md).**

HAMIE is a custom [Home Assistant](https://www.home-assistant.io/) integration
that finds real problems in a Home Assistant configuration — duplicate
entities left behind by a migration, automations that reference something
that no longer exists, orphaned helpers, unavailable entities that quietly
broke — and turns them into durable, evidence-backed **incidents** instead of
a flat, ever-growing list of findings. An AI provider (local or cloud) can be
attached to help interpret evidence and explain incidents in plain language,
but it never gets a shell, credentials, or an unrestricted service-call
surface, and it cannot execute anything on its own. HAMIE decides what is
true; the model may only describe it.

## What HAMIE is

- A deterministic scanning engine: a set of analyzers that read Home
  Assistant's registries, configuration, and (optionally) recorder history,
  and emit atomic, reproducible **findings**.
- An incident layer on top of findings: related findings are grouped under a
  durable root cause with its own lifecycle (new → investigating → confirmed
  → resolved, or dismissed/ignored), so the same underlying problem doesn't
  re-appear as a fresh item on every scan.
- An optional, tightly bounded AI investigation layer. When configured with an
  AI Task entity or a local Ollama endpoint, HAMIE exposes a narrow, read-only
  tool surface (entity/automation/incident lookup, dependency and
  target-writer lookup, planning-only validation) through Home Assistant's own
  LLM API. There is no shell, filesystem, service-call, approval, execution,
  reload, restart, or deployment tool in that surface. See
  [docs/AI_ACCESS_LAYER.md](docs/AI_ACCESS_LAYER.md) for the full boundary.
- An approval-bound remediation model for the incidents that have an
  automatic fix: an exact, evidence-backed plan is proposed, a human approves
  the specific fingerprint of that plan (not just "yes, fix it"), and only
  then does HAMIE modify the authoritative configuration, validate it, and
  roll back automatically if validation fails.

## What HAMIE is not

- Not a general-purpose "AI controls my house" product. There is no
  free-form action tool reachable by any AI provider; see
  `EXECUTION_TOOLS = frozenset()` in `hamie/domain/investigation.py`.
- Not 1.0. APIs, the incident schema, and the frontend are still moving.
- Not HACS-listed yet. See [ROADMAP.md](ROADMAP.md) for what that needs.
- Not a replacement for Home Assistant's own repairs/issues system — HAMIE
  complements it with durable, cross-scan incident tracking and optional
  automatic remediation, where Home Assistant's own repairs are transient,
  per-check notices.

## Requirements

- Home Assistant, a reasonably current release. HAMIE is developed and
  tested against a recent 2026.x release; no minimum version is pinned in
  `manifest.json` yet (see [ROADMAP.md](ROADMAP.md)) and older releases are
  untested, not guaranteed broken.
- Python 3.12+ on the machine running Home Assistant (HAMIE's serialization
  module uses PEP 695 generic syntax available since 3.12).
- Optional: an AI Task-capable entity, or a local [Ollama](https://ollama.com)
  endpoint, if you want AI-assisted investigation. HAMIE works fully without
  either — you get deterministic scanning, incidents, and (where applicable)
  approval-bound remediation regardless.

## Installation

HAMIE is not yet published on HACS (see [ROADMAP.md](ROADMAP.md)). For now,
install manually:

1. Copy the `hamie/` directory from this repository into your Home
   Assistant configuration's `custom_components/` directory, so you end up
   with `<config>/custom_components/hamie/`.
2. Restart Home Assistant.
3. Add the integration from Settings → Devices & Services → Add Integration
   → HAMIE, and follow the config flow.

If you are packaging a build yourself rather than copying the source tree
directly, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the build and
provenance-verification tooling.

## Documentation

- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — clone, environment, tests,
  frontend build, deployment tooling.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how evidence becomes an
  incident, where the AI boundary is enforced, how remediation is approved
  and rolled back.
- [docs/AI_ACCESS_LAYER.md](docs/AI_ACCESS_LAYER.md) — the AI/model trust
  boundary in detail.
- [docs/adr/](docs/adr/) — architecture decision records.
- [SECURITY.md](SECURITY.md) — security model and how to report a
  vulnerability.
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to propose an analyzer, a
  protected-dependency type, or a remediation capability, and what a PR is
  expected to include.
- [ROADMAP.md](ROADMAP.md) / [CHANGELOG.md](CHANGELOG.md).

## License

[Apache License 2.0](LICENSE).

## A note on privacy

This repository is a sanitized export of a private development tree. Every
Home Assistant entity id, hostname, IP address, and device identifier you
see in examples, fixtures, or tests is synthetic or genericized — none of it
describes any real installation. See
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#privacy-and-the-private-tree) for
how that export is produced and verified.
