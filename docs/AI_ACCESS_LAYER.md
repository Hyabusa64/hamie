# HAMIE AI access layer

## Purpose

HAMIE is the controlled engineering boundary between Home Assistant evidence and
an AI provider. The deterministic HAMIE engine gathers and validates evidence;
the provider may interpret that evidence, but it does not receive shell access,
Home Assistant credentials, secrets, or an unrestricted service-call surface.

This document describes the implemented boundary. It deliberately distinguishes
current capabilities from future evidence and deployment adapters.

## Security modes

### Investigation mode

Investigation is the default and is read-only. The Home Assistant LLM API
registered by HAMIE exposes only bounded tools:

- entity lookup and search;
- automation and script lookup;
- incident lookup and search;
- dependency and target-writer lookup;
- recent HAMIE changes;
- configured source/deployment provenance context;
- planning-only validation of a proposed change.

Search returns identities and names, not an unbounded state dump. Entity lookup
uses a small attribute allowlist and redacts states for security- or
presence-sensitive entity domains. Tool calls have invocation and result-size
budgets. Every invocation must be written to HAMIE's audit log; if the audit
write fails, the tool fails closed.

There is no shell, filesystem, registry mutation, service call, approval,
execution, reload, restart, or deployment tool in this capability set.

Home Assistant exposes registered LLM APIs through its MCP endpoint. That gives
supported AI clients the same narrow HAMIE investigation surface without giving
them general Home Assistant administration or SSH access. Home Assistant still
enforces its own authentication and administrator requirement at the MCP
boundary.

### Execution mode

Execution is a separate, approval-bound state transition. The existing HAMIE
remediation domain retains immutable plans, exact-fingerprint approval records,
execution records, rollback information, and audit events. Investigation tools
cannot create an approval or invoke an execution.

The intended pipeline is:

1. investigate and establish an evidence-backed incident;
2. propose an exact remediation and blast radius;
3. bind user approval to that immutable proposal fingerprint;
4. verify backup, Git, and authoritative-source preconditions;
5. modify and validate the authoritative source;
6. commit only after validation;
7. deploy through a deterministic adapter;
8. verify hashes and Home Assistant behavior;
9. roll back only where a pre-verified rollback is demonstrably safe.

The current provenance configuration accepts only `disabled` and
`preview_only` deployment-adapter modes. No production deployment executor is
exposed by this implementation. That is intentional: the authorization model is
in place before a write adapter is added.

## Evidence and incident pipeline

```text
Home Assistant capture and configured evidence adapters
                    |
                    v
      deterministic analyzers and safety gates
                    |
                    v
   candidate findings + suppression/normal evidence
                    |
                    v
 deterministic incident grouping and reconciliation
                    |
                    v
 incident workbench / bounded AI evidence packet / audit
                    |
                    v
        optional immutable remediation proposal
```

`Finding` remains the atomic analyzer result. `Incident` is the durable
engineering unit presented to people and AI. It groups related findings by a
deterministic root key, records hypotheses and evidence status, and has its own
lifecycle: new, investigating, confirmed, dismissed, ignored, resolved,
recurring, or regressed.

Incident priority is based on condition and safety impact, not member count. A
large group of low-value diagnostic entities cannot become urgent merely by
being large. Each incident records how many raw findings it represents so HAMIE
can report context reduction without hiding underlying evidence.

The 2026-08-25 live review also established a false-positive safety rule for the
removed-integration analyzer: known core/YAML/helper platforms are excluded, and
a source definition positively known to be present is a hard disqualifier.
Missing ownership metadata cannot outweigh direct definition evidence.

## AI provider integration

Provider execution and provider access are separate concerns:

- Home Assistant AI Task is the primary structured-advisory path when an AI
  Task entity is configured. HAMIE supplies a native structured-output selector
  and then applies its own strict schema and semantic safety validation.
- A configured local Ollama endpoint remains a privacy-first fallback for
  bounded advisory work.
- The provider-independent LLM/MCP tool API exposes deterministic investigation
  records to Claude, OpenAI/Codex-compatible clients, local clients, and future
  providers supported by Home Assistant.

Provider output is advisory. It cannot increase a deterministic safety gate,
invent an executable change, approve a proposal, or bypass the provenance
boundary. Evidence passed to a provider is curated by sensitivity: never-export
items are omitted and redacted items are represented without their values.

The audit record uses the provider platform made available by Home Assistant.
Home Assistant does not expose a reliable model identifier to this LLM tool
layer, so the model is recorded as `not_exposed_by_home_assistant` rather than
guessed.

## Source and deployment provenance

Each configured HAMIE instance can declare:

- `authoritative_source_repository`;
- `deployment_target`;
- `optional_remote_development_hosts`;
- `deployment_adapter_mode`.

Provenance roles are `SOURCE`, `WORKTREE`, `STAGING`, `DEPLOYMENT`, `BACKUP`,
and `UNKNOWN`. Source selection requires an explicitly configured repository and
uses repository role, Git lineage/HEAD, working-tree state, and content hashes.
Filesystem modification time is never a source-of-truth signal.

The current investigation tools report the configured boundary. Git and
source/deployment comparison tools return `not_captured` until a bounded,
read-only provenance adapter has supplied actual repository and deployment
evidence. They do not fall back to arbitrary filesystem exploration.

## Web workflow

The default HAMIE view is now the incident workbench. It shows root cause,
evidence status, confidence, affected objects, recommended next step, and the
underlying finding count. The user can investigate, confirm, ignore, dismiss, or
view raw evidence. Raw findings remain available under Advanced for engineering
inspection.

No generic "let AI change my house" action exists. A future UI approval action
must display and bind to an exact remediation proposal, including files,
production targets, blast radius, validation plan, rollback plan, reload/restart
requirements, destructive flag, and proposal fingerprint.

## Current adapter limits

The incident and access-layer foundation is implemented, but these investigation
surfaces still require bounded adapters before they can be advertised as live
tools: device/area/floor/label registries, config entries/integration detail,
repairs, traces, recorder history, long-term statistics, relevant log excerpts,
Watchman, and complete dependency graphs. Arbitrary passthrough access is not an
acceptable substitute.

A production deployment adapter is also not implemented. It must be
deterministic, testable, hash-verifying, rollback-aware, and separately
authorized before `preview_only` can become an execution-capable mode.
