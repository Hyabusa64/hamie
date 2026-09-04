# Lifecycle fixture (J / K / N live proof)

Written before creation, then corrected by what actually happened. Both are
kept: the prediction that was wrong is more useful than a clean document that
pretends it was right.

## The constraint that shapes everything

`async_derive_plan` produces a REPAIR_CANDIDATE only when all of these hold
(see `rediscover_targets` and `runtime._similar_entities`):

1. the incident names an affected subject that is **absent from
   `hass.states`** -- not merely `unavailable`;
2. `_DUP_SUFFIX` strips a single `_2`..`_9` from the object id and the **base
   entity exists**;
3. active configuration still **references** the absent entity;
4. domains match and no ambiguity remains.

Condition 1 is the hard one, and it pulls against the analyzer: a duplicate
group is built from *capture records*, so the stale sibling has to be visible
to the scan while being absent from the state machine.

## What the original design got wrong

The first version of this document concluded that the entity had to be
registered, then have its **registry entry removed**, costing three restarts
before the first proof. Two of those three assumptions were wrong:

- **Removing the definition is not enough.** Measured live: deleting the
  sensor from YAML and reloading leaves the entity `unavailable`, not absent.
- **Registry removal is not required, and is the wrong tool.** A registry
  entry **disabled** by the user is never set up, so it has no state object at
  all -- `hass.states.get()` returns `None` -- while `ha_source` still captures
  it as a registry-only record (`state="unavailable"`, `available=False`).
  That satisfies condition 1 *and* keeps the finding regenerating on every
  scan, which registry removal would have destroyed.
- **The disable does need one restart.** `template.reload` leaves the stale
  state object behind; only a restart drops it.

Restarts required to build the fixture: **1**, not 3. And the fixture is
fully reversible, because nothing was deleted from the registry to build it.

## Entities and files

| Item | Value |
|---|---|
| Definition package | `/config/packages/hamie_lifecycle_fixture.yaml` |
| Reference holder (repair target) | `/config/packages/hamie_lifecycle_fixture_refs.yaml` |
| Successor (survives, alive) | `sensor.hamie_lifecycle_fixture` |
| Stale subject (registered, DISABLED) | `sensor.hamie_lifecycle_fixture_2` |
| Classification | `BROKEN_REFERENCE_TO_OLD_SIBLING` |
| Category / priority | `duplicate_migration` / `p1` |
| Validity / repairability | `STILL_PRESENT` / `REPAIR_CANDIDATE` |
| Risk | `config_mutation` (explicit approval required) |
| Protected effects | none |

Both are template sensors with constant values. They control nothing, call no
service, notify nothing, reach no network, and target no device or area.

## Forcing a rollback without ever leaving invalid configuration

Gate N needs validation to fail *after* a successful write. Two attempts
failed for instructive reasons:

- **Duplicate YAML attribute keys**: Home Assistant accepted them. No failure.
- **Making the migration target unavailable via an availability template**:
  the lifecycle reloads `automation` and `script`, *not* `template`, so the
  fixture's own template changes never took effect during runtime validation.
  A self-referential availability template is also suppressed by HA.

What worked: a `!include` whose **filename embeds the stale identity**.
Rewriting the identity points the include at a file that does not exist, and
HA's own configuration check rejects it. Deterministic, caused purely by the
repair, and confined to the fixture.

The cost is a window in which configuration on disk is invalid. That window is
bounded by HAMIE's own rollback, and Home Assistant only reads configuration
on restart -- so it is safe as long as no restart happens inside it. Every
scenario here verified `check_config` **before** restarting.

## Cleanup

1. Remove every fixture registry entry, verifying `entity_id` prefix,
   `platform == "template"`, and null `config_entry_id`/`device_id`/`area_id`
   before each removal.
2. Delete both packages, every `.hamie_bak_*` of them, both include targets,
   and the halt marker.
3. Restart, rescan, and retire the fixture incident.

Audit records are retained deliberately: HAMIE's transaction history is
evidence, and deleting it to make a residue count reach zero would destroy the
thing the audit exists for.

**Known residue.** A baseline whose target files have been *deleted*
classifies as `DIVERGED` (the file cannot be read, so it matches neither
hash). `DIVERGED` is deliberately non-terminal -- an operator should still see
it -- so such a baseline is never retired and never pruned. Deleting the
configuration a repair targeted therefore leaves a permanently un-clearable
entry. Recorded rather than fixed: reordering the decision so "the incident is
gone" outranks "the files diverged" would make the number reach zero, but that
ordering change deserves its own justification, not a cleanup's convenience.
