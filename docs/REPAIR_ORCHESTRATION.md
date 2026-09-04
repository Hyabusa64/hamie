# Repair orchestration: making HAMIE perform its own maintenance work

This document is the evidence trail and design record for turning HAMIE from
a detection/advisory tool into something that can perform the bounded Home
Assistant maintenance work that previously required a human directing an AI
coding assistant by hand. It exists so a future contributor (or a future
session) can see *why* a given repair class is trusted, not just that it is.

Everything in the AUTO-REPAIRABLE and OPERATOR-DECISION sections below is
backed by a real, cited historical repair from this project's own git
history or forensic reports — not a hypothetical. Where the record does not
support a claim, that is stated explicitly rather than filled in.

## Method

Phase 0 of this work was forensic, not design-first: the full git history
(92 commits at the time of writing), the `analysis/*/REPORT.md` forensic
reports, and dated incident narratives embedded as comments in
`hamie/domain/protected_dependencies.py` and `hamie/application/runtime.py`
were mined for every real repair or incident, not just the ones that were
easy to generalize. See **Appendix: repair taxonomy** for the full
class-by-class citation trail this document is built from.

## Repair-capability matrix

Columns: whether HAMIE can currently **Detect** the defect (an existing
analyzer or scan), **Investigate** it (gather the specific evidence a repair
decision needs), produce **Deterministic evidence** (not model inference),
**Derive** a candidate repair, **Dry-run** it, **Execute** it, **Verify**
the result, and **Roll back** on failure — plus the **Current gap**.

| Defect class | Detect | Investigate | Det. evidence | Derive repair | Dry run | Execute | Verify | Rollback | Current gap |
|---|---|---|---|---|---|---|---|---|---|
| Stale entity reference after version-bump migration (real: 19 sites, 4+ commits) | Partial — `functional_self_reference` and `duplicate_migration` analyzers detect the shape; no analyzer yet flags "reference is dead AND a version-bumped sibling exists" as one finding | Partial — `hamie/domain/successors.py` + the schema-v8 knowledge layer track successor candidates; no tool yet reads the *specific automation/template body* around the reference | Yes — registry unavailability + recorder-sample proof of sibling equivalence is exactly how the 19 real sites were verified by hand | No — this is manual today | No | No | No | Backup/hash-verify exists generically (`RemediationExecutor`) but untested for this class | **New playbook + 2 new tools** (see Phase 9 below) |
| Duplicate entity identity / `_2`.._9` successor confusion | Yes, partially — `duplicate_classifier.py` exists | Partial | Yes — `hamie/domain/successors.py`'s existence-only matching (never fuzzy) is a proven, tested principle (see B4 in the appendix) | No | No | No | No | N/A | Reuse `successors.py`, do not rebuild |
| Orphaned automation/script (removed-integration false shape) | Yes — `removed_integration_orphan` analyzer | Yes — read-only registry/YAML/dashboard cross-reference already exists (`offline_config_reference_scanner.py`, `dependency_source.py`) | Yes | Manual only, and historically the analyzer itself had a false-positive defect (45.8% of 1,135 findings were wrong) fixed by extending an allowlist | No | No | No | N/A — deletion is destructive by design | **Detect-and-decide only.** Deletion stays BLOCKED; a supported-API *disable* (not delete) is a plausible AUTO-REPAIRABLE-WITH-APPROVAL candidate, not yet built |
| Self-referencing automation | Yes — `FunctionalSelfReferenceAnalyzer`, built explicitly after catching 3 real bugs by hand | Partial | Yes | No | No | No | No | N/A | Same gap as stale-reference: detection exists, repair tooling doesn't |
| Duplicate automations producing the same effect (e.g. duplicate volume caps, duplicate notifications) | **No dedicated analyzer.** The real case (roborock dock, `c6e63ea`) was found from recorder `automation_triggered` event correlation, done by hand | No | Partial — recorder event correlation is a sound method but not implemented as a tool | No | No | No | No | N/A | **New detector + new playbook** (Phase 8) |
| Cross-integration protected-endpoint aliasing (AI-PC incident class) | N/A going forward — `ProtectedDependencyRegistry`/`ProtectedEndpoint` now *prevents* this by design | N/A | Registry-proven vs. declared vs. refused-observed alias evidence is a real, tested model | N/A — this is a protection mechanism, not a repair target | N/A | N/A | N/A | N/A | **Solved as prevention.** A *new* instance (new device family) still needs a human `DECLARED` alias — correctly OPERATOR-DECISION forever, not a gap |
| Deprecated HA syntax (`service:` → `action:`, renamed selectors, etc.) | No | No | No real historical incident found in this project's own config to cite | No | No | No | No | N/A | **Design-only, not evidence-backed yet.** See Phase 4 — build the registry mechanism now, populate rules only as real instances are found, do not pre-fill with unverified trivia |
| Blueprint schema incompatibility | No | No | **No corroborating incident found** in git history or analysis reports for this project. The mission brief references a prior blueprint mistake; it could not be located in the available record. | No | No | No | No | N/A | UNSUPPORTED. Do not build a blueprint-specific migration rule from an unverified anecdote — see Phase 11 note below |
| Committed/leaked credentials (connection-URI shape, raw `.storage` capture) | Yes — `tools/secret_scan.py`, already comprehensive and tested | Yes | Yes | Yes for detection; rotation itself is explicitly BLOCKED (security-critical, human-executed) | N/A | N/A | N/A | N/A | Already solved for detection; **not a repair-orchestration target** — rotation must stay a human action |
| Registry entries surviving a deleted integration (Watchman-style) | Yes — same `removed_integration_orphan` analyzer, plus a manual sweep methodology (`analysis/cleanup_20260825T151600Z`) proved 16+2 real orphans this way | Yes | Yes — 20/20 unavailable samples, no live config entry, no custom_components dir, no indirect targeting possible | Yes, but every real instance historically stopped here: **no authenticated API/token was available** to even disable, let alone delete | No | No | No | N/A | UNSUPPORTED pending a supported disable-entity tool + an authenticated path to the HA API (this project now has SSH host access but no HA API/Supervisor token as of this writing) |

Rows the mission's own checklist named but for which **no real historical
instance exists** in this repository's evidence (renamed trigger/behavior
semantics, invalid HA syntax after a version upgrade, missing dependencies,
config-package dependency errors, integration/config-entry health problems)
are intentionally omitted from the table above rather than padded with
speculative rows. They remain open questions for Phase 4's compatibility
registry to grow into *if and when* a real instance is found — see
**Known Failure Modes / Cautions** for why this matters.

## Classification

### AUTO-REPAIRABLE WITH APPROVAL

- **`STALE_ENTITY_REFERENCE_REPAIR`** — a reference to an absent entity,
  where exactly one existence-verified successor exists (never fuzzy-matched
  — see the B4 caution below), domain-compatible, not protected, in a
  parsed (not string-substituted) config structure. Real precedent: 19
  sites across 4 real repairs.
- **`EXACT_DUPLICATE_ACTION_CONSOLIDATION`** — two automations/scripts
  proven (via recorder trigger-event correlation, not name similarity) to
  produce the identical effect, where exactly one is unambiguously the
  authoritative/newer implementation. Real precedent: the roborock
  dock-notification consolidation. Narrower than the mission brief's
  aspiration — the real case required distinguishing "fully redundant" from
  "same purpose, different detail," which is not always mechanical; only
  the *provably byte-identical-effect* subset is AUTO-REPAIRABLE, everything
  else is OPERATOR-DECISION (see below).

### OPERATOR-DECISION REQUIRED

- Duplicate entity identities where more than one plausible successor exists,
  or where the "authoritative" implementation among duplicates is not
  provably singular.
- New protected-dependency aliases (a device newly integrated through a
  second platform) — cross-integration equivalence is *never* inferable by
  design (see A2/the AI-PC incident); it always needs a human `DECLARED`
  rationale.
- Orphaned-registry disposition beyond disable (i.e. deletion).
- Any repair whose evidence includes a `REVIEW_REQUIRED` or
  `hamie_false_positive` disposition in prior analysis — of the 2,672 real
  findings reviewed on 2026-08-25, 1,399 (52%) were `REVIEW_REQUIRED` and a
  further 534 were confirmed false positives from the tool itself. That
  ratio is the single strongest argument in this whole document for keeping
  the OPERATOR-DECISION bucket wide rather than narrow.

### UNSUPPORTED

- Blueprint option repair (no real incident to build from yet).
- Deprecated-syntax/version-migration rewrites (registry mechanism built,
  no populated rules yet — see Phase 4).
- Registry entity deletion via supported API (disable is a plausible next
  step; delete stays out of scope).
- Trace-based automation-execution analysis beyond what recorder-event
  correlation already proved feasible by hand.

### BLOCKED

- Credential rotation.
- Any `.storage` hand-edit (this is not a style preference — it is how the
  2026-08-25 credential-leak incident happened, and how a hand-added HA
  config entry would repeat the same category of mistake).
- Physical/security-critical mutation of any kind.
- Registry entity deletion (as opposed to disable).

## Top repair classes selected for implementation now

Scored on frequency × real evidence quality × deterministic repairability ×
reversibility, per the mission's own instruction to prefer "high-frequency
boring repairs" over flashy ones:

1. **`STALE_ENTITY_REFERENCE_REPAIR`** — highest real frequency (19 sites),
   fully deterministic once a tested successor-discovery tool exists,
   trivially reversible (file backup), explicitly named by the mission as
   what should become HAMIE's strongest repair path. **Implemented this
   pass.**
2. **`EXACT_DUPLICATE_ACTION_CONSOLIDATION`** (detection only this pass;
   consolidation stays OPERATOR-DECISION until a second real precedent
   proves the "provably singular authoritative implementation" case is
   common enough to automate) — real precedent exists, high operational
   value (triple Alexa announcements, silent duplicate device commands are
   exactly the kind of thing worth catching automatically). **Detector
   implemented this pass; consolidation playbook deferred, honestly, as
   OPERATOR-DECISION for now.**
3. Everything else in the matrix above stays at its current gap. Building a
   deprecated-syntax rewrite engine, a blueprint repair tool, or a
   trace-analysis subsystem *before* a second real instance of each exists
   would be exactly the "design from hypotheticals" the mission explicitly
   warned against. They are documented as the next candidates, not built
   speculatively.

## Repair playbook: `STALE_ENTITY_REFERENCE_REPAIR`

| Field | Value |
|---|---|
| Eligibility | An entity reference inside a parsed automation/script/template config object resolves to no live entity, AND exactly one existence-verified, domain-compatible successor is found by `hamie/domain/successors.py`'s exact-suffix matching (never fuzzy string similarity — see caution below), AND the successor is not itself stale. |
| Evidence requirements | Registry row for the referenced entity: absent or unavailable across the full available sample window. Registry row for the candidate successor: present, available, domain-matched. The reference's exact location in the authoritative source file (see Phase 12 — package-aware, not registry-representation). |
| Required tools | `inspect_automation_definition` / `inspect_script_definition` (read), `resolve_entity` (read, existing), `replace_entity_reference_in_scope` (mutate, new — see Tool Gap Analysis) |
| Ambiguity conditions | More than one existence-verified candidate → OPERATOR_DECISION_REQUIRED. Candidate's domain differs from the referenced entity's domain → OPERATOR_DECISION_REQUIRED. Reference appears in a place whose meaning inversion by blind substitution can't be ruled out (e.g. inside a comment describing the *old* entity's deletion, as caught by hand in commit `961a445`) → refuse, do not substitute. |
| Protected effects | Refuse if either the stale reference's automation or the successor participates in a `ProtectedDependency` chain, until that chain is separately re-verified. |
| Risk class | `CONFIG_MUTATION` |
| Approval requirement | Explicit, fingerprinted, per HAMIE's existing remediation lifecycle — no auto-execute. |
| Mutation | Exact scoped text replacement inside the parsed structure's specific field, in the authoritative YAML source file — never a blind global string replace across the file. |
| Validation | HA `check_config` equivalent before commit; config hash recorded pre/post. |
| Rollback | Existing backup/restore mechanism; triggered automatically on validation failure. |
| Completion criteria | Config validates, the affected automation/script reloads without a new error attributable to this change, and the incident's `CurrentValidity` re-evaluates to resolved on rescan. |

## Duplicate-action detector: design (Phase 8)

Detection, not consolidation, is what's implemented this pass. The method
mirrors the one real precedent exactly, generalized:

1. For every automation/script pair, compare **normalized measured effect**
   — target entity/domain, operation (service/action called), and the
   parameters that matter to that operation (e.g. a volume-set value, a
   notification's rendered text) — never automation *names*, which is how
   name-based comparison would have missed the real case (three
   differently-named automations, one effect).
2. Cross-reference recorder `automation_triggered`/`script_started` events
   (where available) for actual temporal overlap, the same method used by
   hand in the roborock case, not YAML trigger-schema comparison alone
   (two automations can share a trigger condition on paper and never
   actually fire together, or vice versa via an automation calling another).
3. Classify: `EXACT_DUPLICATE` (identical effect, provably one authoritative
   implementation — eligible for the consolidation playbook once that's
   built), `OVERLAPPING_DUPLICATE` (same effect, different detail — e.g. one
   also does something else) or `POTENTIALLY_CONFLICTING` (same target,
   different/contradictory effect). Only the first tier is ever a repair
   candidate; the other two are always OPERATOR_DECISION_REQUIRED.

## Tool gap analysis

See the appendix in this document's companion research
(`hamie/application/remediation_tools.py` et al.) for the exact existing
tool registration mechanism this extends. New tools added this pass:

**Read-only:**
- `inspect_automation_definition(entity_id)` — returns the parsed automation
  config (triggers/conditions/actions) from its authoritative source file,
  with every entity/device/area reference it contains and that reference's
  exact structural location (for scoped, not blind, mutation).
- `inspect_script_definition(entity_id)` — same, for scripts.

**Mutating:**
- `replace_entity_reference_in_scope(source_path, structural_location,
  old_entity_id, new_entity_id)` — replaces exactly one reference at an
  exact, previously-identified structural location. Never a string
  substitution across a whole file. Requires a matching prior
  `inspect_automation_definition`/`inspect_script_definition` result as
  provenance for `structural_location`, and goes through the existing
  `ProtectedDependencyRegistry.evaluate(...)` check before any dry-run is
  even offered.

No `call_service`, no filesystem write tool, no YAML editor tool, no
registry deletion tool were added. This preserves exactly the tool
philosophy already in place.

## Known Failure Modes / Cautions

These are drawn directly from the appendix taxonomy, kept here (not just in
the appendix) because they are the specific mistakes future repair-playbook
code must not repeat:

- **Never fuzzy-match a successor entity.** A prior defect stripped *any*
  trailing `_<digits>` from an entity id, silently losing the real
  successor for a real incident. The fix — strip only a single HA-convention
  digit suffix, and only when that exact base entity exists — is now the
  permanent rule. Do not "improve" this with similarity scoring.
- **A blind string substitution can invert meaning.** One real substitution
  was caught and reverted in diff review because a comment documenting the
  *deletion* of the old entity would have had its own meaning inverted by
  applying the same substitution literally. This is why the new mutating
  tool requires a structural location from a prior inspection, not a raw
  find-and-replace.
- **Absence of evidence is not evidence of absence.** The single
  most-repeated architectural lesson in this project's history: an unbound
  reader, an untriggered analyzer, or an unresolved API call must never be
  treated as a quiet "nothing to report." Every new tool in this layer
  raises rather than returning a falsy default on missing infrastructure.
- **Cross-integration device identity is never inferable, only declarable.**
  Home Assistant models two integrations' views of one physical device as
  unrelated devices. Synchronized on/off timing is evidence worth recording
  but is explicitly insufficient alone (`AliasAuthority.OBSERVED` can never
  singly justify a protected alias). Do not build a "these always move
  together, so they must be the same thing" heuristic into any new tool.
- **A blueprint's custom option schema is not Home Assistant's schema.**
  Noted in the mission brief as a prior mistake; not independently
  corroborated in this project's own history (see the matrix note above).
  Documented here as a standing caution regardless, since the failure mode
  is architecturally obvious even without a citable instance: a version-
  migration rule written against native HA selector/service semantics must
  never be applied to a blueprint-defined enum without first confirming the
  blueprint's own schema permits it.
- **Do not hand-edit `.storage`.** Not a style preference — this is
  literally how the 2026-08-25 credential-leak incident happened, and it
  remains the reason registry entity *deletion* stays out of scope even
  though *disable* is a plausible next capability.

## What's built vs. what's designed

Everything in this section is real, tested code, not a proposal:

- **Duplicate-automation-action detection**
  (`hamie/domain/action_duplication.py`) — compares normalized effect
  (target + service + significant parameters), classifies
  `EXACT_DUPLICATE`/`OVERLAPPING_DUPLICATE`/`POTENTIALLY_CONFLICTING`,
  and separately proves (or honestly refuses to prove) which side is the
  sole authoritative implementation. 35 tests.
- **Structural definition inspection**
  (`hamie/domain/definition_inspection.py`) plus two new investigation
  tools, `hamie_get_automation_definition`/`hamie_get_script_definition`
  (added to `INVESTIGATION_TOOLS` in `hamie/domain/investigation.py`,
  wired into `hamie/llm.py`) — returns an automation/script's own
  trigger/condition/action body with each entity reference's *exact*
  structural path (e.g. `action[0].target.entity_id`), so a mutation can
  target one location instead of a blind file-wide substitution.
- **HA compatibility rule registry**
  (`hamie/domain/ha_compatibility.py`) — the mechanism for version-bounded,
  detect-then-optional-rewrite migration rules. Ships with zero rules by
  design (see the module's own docstring): no real deprecated-syntax
  incident exists in this project's history to build one from.
- **Claude-escalation packet** (`hamie/domain/escalation.py`) — packages
  an incident's deterministic facts, evidence, and the specific
  unresolved question into one secret-sanitized artifact. Finding and
  closing a real gap here (a database-connection-URI-embedded credential
  wasn't caught by the existing freeform-text redactor) also strengthened
  `hamie/domain/common.py`'s shared `redact_secret_looking_text`.
- **Repair recommendation queue** (`hamie/domain/repair_queue.py`) —
  tiers incidents into `READY_TO_APPROVE` / `NEEDS_A_DECISION` /
  `NOT_YET_ACTIONABLE` / `NOT_HAMIES_TO_FIX` and surfaces only the
  actionable ones, capped at a small N.
- **Repair metrics** (`hamie/domain/repair_metrics.py`) — the
  `manual_escalation_rate` metric (fraction of *investigated* incidents
  that still needed a Claude escalation), returning `None` rather than a
  fabricated `0.0` when nothing has been investigated yet.

**Not built this pass, and why**, rather than left silently implied:

- **A multi-turn, tool-calling investigation loop** (the mission's
  "bounded investigation graph," Phase 5). `hamie/application/investigator.py`'s
  `Investigator.async_investigate` is single-shot: one evidence package
  in, one classification out, no iterative tool-calling. The existing,
  *proven* pattern (`IncidentRemediationPipeline.async_triage`) instead
  does deterministic rediscovery first, then a single bounded model call
  for classification — which is what the flagship stale-entity-reference
  class actually runs on in production today. Building a genuine
  multi-turn loop on top of the 13 `INVESTIGATION_TOOLS` is a
  substantial, separate piece of work, not a small extension.
- **Live HA error/trace ingestion** (Phases 6-7). Both need a live
  config entry and, for traces, Home Assistant's trace API — neither
  was available in this session (see the pilot below). The normalization
  *shape* these would produce is compatible with `escalation.py`'s
  `deterministic_facts`/`config_excerpts` fields, so wiring them in later
  does not require redesigning what already exists.
- **Registry disable-via-supported-API tool** (Phase 13's middle
  ground between read-only and destructive delete). Real evidence (the
  pilot below) shows this is the single most common blocker among real
  orphan-class findings — a clear, evidence-backed next priority, not
  built yet.
- **Blueprint repair, deprecated-syntax rewrites** — no real incident to
  build from; see the capability matrix.

## Ten-incident pilot

HAMIE currently has no active config entry on the production instance
this mission was developed against — the integration is deployed but
was not reconfigured during this session (outside this session's
access: reconfiguring it is a Home Assistant UI/API action). Per this
mission's own instruction not to manufacture live candidates when none
exist, the pilot instead classified 10 real findings, drawn by
non-cherry-picked random sample stratified across analyzer/disposition
pairs, from a real 2,672-finding dataset, against the current
capability matrix above. (Full per-entity detail is in the private
`docs/REPAIR_TAXONOMY_EVIDENCE.md` — this section reports the
generic result.)

**Result: 0 of 10 were dry-run-eligible.** 3 were registry-orphan/
no-source-definition findings blocked on the not-yet-built disable-API
tool; 3 needed live re-investigation that this offline dataset can't
provide (evidence explicitly marked insufficient to decide); 2 were
correctly safety-gated to `OPERATOR_DECISION_REQUIRED`; 1 was already
resolved (confirmed active, no repair needed); 1 was a confirmed false
positive from this project's own analyzer history that turned out to
already be fixed in the current code (a `source_definition_missing`
structural check now hard-excludes it, superseding the
allowlist-extension fix an earlier review had merely recommended).

This is expected, not a shortfall: the real stale-entity-reference sites
this mission's flagship playbook targets were already repaired by prior
manual work before this dataset was captured, so a random sample of
findings still open on that date naturally excludes that class. The
duplicate-action detector similarly needs live automation action bodies
that no analyzer in this dataset ever captured. The pilot's honest value
is confirming the matrix's UNSUPPORTED/OPERATOR_DECISION_REQUIRED calls
hold up against real, unfiltered data — and sharpening the priority
order for what to build next (the disable-API tool is the clearest
single next win, given it's what most of these real findings are
actually blocked on).

## Appendix: repair taxonomy

The full class-by-class citation trail (commit hashes, real evidence,
real fixes, judgment calls, validation, and a frequency ranking across
92 commits and the `analysis/`/`benchmark/` forensic reports) that this
document's matrix and playbook selection are built from is in
`docs/REPAIR_TAXONOMY_EVIDENCE.md` — **private-only**, not exported
publicly, because it names real household entities and automations.
Summary counts cited above (19 sites, 1,399 REVIEW_REQUIRED of 2,672,
etc.) are drawn from it directly; the generic lessons are reproduced in
this document's "Known Failure Modes / Cautions" section, which is the
public-safe form of the same evidence.
