# ADR 0001: Controlled AI access through deterministic incidents

- Status: accepted
- Date: 2026-08-25

## Context

HAMIE already captured broad Home Assistant evidence, emitted durable findings,
accepted bounded AI advice, and maintained strong remediation approval and audit
objects. Its primary presentation unit, however, was a finding group organized
by device, config entry, or integration. Group size influenced priority. This
made presentation buckets look like root causes and sent too many low-value
entity records to the user and model.

The project also needs to support remote and local AI providers without turning
provider configuration into unrestricted production or filesystem access. The
live `/config` tree may differ from the authoritative development repository, so
write safety also depends on explicit provenance.

## Decision

1. Keep deterministic analyzers and atomic findings as the evidence foundation.
2. Add a durable incident layer with deterministic root keys, explicit evidence
   status, hypotheses, lifecycle, and priority independent of group size.
3. Make incidents the default human and AI context. Keep raw findings for audit
   and advanced inspection.
4. Register a read-only Home Assistant LLM API with narrow, bounded tools. Do not
   expose shell, arbitrary filesystem, general service calls, credentials, or
   execution tools.
5. Fail investigation tools closed when their audit record cannot be persisted.
6. Keep provider reasoning advisory and validate structured output against both
   a schema and deterministic HAMIE safety rules.
7. Keep execution separate and bind approval to an immutable remediation
   fingerprint. A materially changed plan requires a new approval.
8. Require explicit authoritative-source and deployment-target configuration.
   Never select a repository by timestamp.
9. Ship provenance deployment modes as disabled/preview-only until a tested,
   rollback-aware adapter exists.

## Consequences

The user sees fewer, more actionable units while the evidence ledger remains
complete. AI providers receive smaller, curated packets and cannot turn
investigation access into production writes. Home Assistant's registered LLM API
also supplies an MCP-compatible boundary for supported external clients.

Incident grouping is intentionally conservative. It may initially leave several
incidents that a richer dependency graph could later merge; that is safer than
inventing a shared root cause. Adding new evidence tools requires an explicit
bounded adapter and a sensitivity policy.

The system cannot yet perform source-backed deployment. This is a conscious
capability gap, not an implicit invitation to generate ad-hoc SSH, SCP, or rsync
commands.

## Alternatives rejected

- **Send every entity finding to the model.** This is expensive, noisy, creates
  privacy risk, and makes results depend on provider context limits.
- **Let the model group findings and choose priority.** That makes identity and
  urgency nondeterministic and difficult to audit or reconcile over time.
- **Expose Home Assistant administration or SSH as AI tools.** Investigation
  would silently become arbitrary execution and leak credentials and secrets.
- **Treat `/config` or the newest filesystem copy as source of truth.** That can
  edit an older deployment or backup instead of the authoritative repository.
- **Build deployment before the approval/provenance boundary.** A working copy
  mechanism without immutable authorization would create the highest-risk part
  of the system first.
