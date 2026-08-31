# Architecture

This is an overview of how HAMIE is put together and why. For the AI/model
trust boundary specifically, see [AI_ACCESS_LAYER.md](AI_ACCESS_LAYER.md) —
this document summarizes it but that one is authoritative. For the reasoning
behind the incident model, see
[adr/0001-controlled-ai-access-layer.md](adr/0001-controlled-ai-access-layer.md).

## Layering

```
hamie/domain/          pure logic: no I/O, no Home Assistant imports.
                        Findings, incidents, protected dependencies, the
                        remediation state machine, serialization.

hamie/application/      orchestration: turns domain logic into a running
                        system — scan scheduling, the incident lifecycle,
                        the AI investigation service, remediation lifecycle
                        (approve → validate → commit → deploy → verify →
                        roll back).

hamie/infrastructure/   adapters that read the actual Home Assistant
                        installation: entity/device/area registries, the
                        recorder, offline config-reference scanning,
                        installation topology.

hamie/connectors/       outbound integrations: Ollama, an n8n webhook
                        connector, an MCP-style tool surface, a health/
                        heartbeat model shared by every connector.

hamie/analysis/analyzers/
                        the deterministic scanners themselves: each one
                        reads evidence and emits Finding objects. Adding a
                        new class of problem HAMIE can detect means adding
                        an analyzer here, not touching the incident or
                        remediation machinery.

hamie/presentation/     the HTTP/websocket API surface Home Assistant's
                        frontend (and HAMIE's own panel) talks to.

hamie/frontend/         a Lit-based custom panel (see docs/DEVELOPMENT.md
                        for the build pipeline).
```

The dependency direction is one-way: `domain` knows nothing about Home
Assistant or the network; `application` depends on `domain`;
`infrastructure`/`connectors`/`presentation` depend on both. A pure domain
type should never import from `infrastructure` or `connectors`.

## Evidence → incident pipeline

```
Home Assistant registries, config, recorder (via infrastructure/ adapters)
                    |
                    v
      deterministic analyzers (hamie/analysis/analyzers/)
                    |
                    v
   Finding objects -- atomic, reproducible, the audit-grade unit
                    |
                    v
 deterministic incident grouping by root key, safety-based priority
 (not group size), lifecycle: new / investigating / confirmed / dismissed
 / ignored / resolved / recurring / regressed
                    |
                    v
   incident workbench (frontend) + bounded AI evidence packet + audit log
                    |
                    v
        optional immutable remediation proposal
```

A `Finding` is never mutated in place and never disappears silently — an
incident's finding count is preserved even as the incident's own state
changes, so "we're showing you less" never means "we know less."

## The AI boundary, summarized

Investigation is the default mode and is read-only: entity/automation/
incident/dependency lookup, recent-changes lookup, provenance context, and
planning-only validation of a *proposed* change. There is no shell,
filesystem, registry mutation, service call, approval, execution, reload,
restart, or deployment tool reachable from investigation —
`EXECUTION_TOOLS = frozenset()` in `hamie/domain/investigation.py` is the
literal, checked expression of that.

Execution is a separate, approval-bound state transition with its own
pipeline (see below). Investigation tools cannot create an approval or
invoke an execution; the two are enforced as distinct capability sets, not
as a permission check inside one shared code path.

Model output is advisory everywhere. Deterministic evidence — not the
model — decides what entities exist, whether a reference is stale, whether
a repair succeeded, and whether a protected invariant held.

## Remediation lifecycle

For the incidents that have an automatic fix, the pipeline
(`hamie/application/remediation_lifecycle.py`,
`hamie/application/incident_remediation.py`) is:

1. investigate and establish an evidence-backed incident;
2. propose an exact remediation and its blast radius;
3. bind human approval to that proposal's *immutable fingerprint* — a
   materially changed plan requires a new approval, not a re-confirmation
   of the old one;
4. verify backup, git, and authoritative-source preconditions;
5. modify and validate the authoritative configuration;
6. commit only after validation passes;
7. deploy through a deterministic adapter;
8. verify hashes and Home Assistant's actual runtime behavior;
9. roll back automatically wherever a pre-verified rollback exists, and
   report failure explicitly rather than continuing past it.

## Protected dependencies

`hamie/domain/protected_dependencies.py` is a declarative registry of
dependency chains that must not be severed — the canonical shipped example
is "this installation's own AI inference host depends on a specific smart
plug staying on," proven from a real incident where a house-empty automation
cut power to the machine running the local LLM backend through an alias its
own protection registry didn't know about. New protected dependencies are
added as data (an id, a chain of `DependencyLink`s, evidence, and a rule),
not as new branches in remediation code, and the registry supports declaring
*multiple entity-id aliases for one physical endpoint* — the exact gap that
incident exposed.

## Provenance and build verification

`hamie/build_info.py` and `tools/build_deploy.py` exist because a manual
copy-to-deploy workflow allows the running code to silently drift from the
source it was supposedly built from. `tools/build_deploy.py` refuses to
report a deploy successful until:

```
source HEAD == packaged build_commit == deployed build_commit == runtime build_commit
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for using it.

## Test architecture

`tests/ha_stubs.py` stubs the slice of the Home Assistant Python API HAMIE's
own tests touch, so the full test suite runs without installing the real
`homeassistant` package. Domain-layer tests take plain Python objects, not
Home Assistant fixtures, wherever the code under test doesn't need Home
Assistant at all — that is what the `domain`/`application`/`infrastructure`
split is for.
