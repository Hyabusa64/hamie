/**
 * <hamie-view-review> — the Review screen: human-judgment triage,
 * deliberately separate from Issues (spec section "Review"). Six fixed
 * categories: Confirmed Orphans, Unavailable But Used, Duplicate/
 * Migration, Insufficient Evidence, Protected Dormant, Broken Reference.
 * Every item shows evidence FOR and AGAINST its recommendation
 * separately, plus confidence/risk/external-consumer uncertainty. No
 * destructive action is ever offered here -- only "View in Issues" and
 * "Open in Review Queue" navigation, matching the verified safety gate
 * (approval/execution lives in the existing Remediation engine, reached
 * from Advanced -> Review Queue, which this screen never duplicates).
 *
 * Data provenance (updated this pass -- see the mission brief): all six
 * categories are now backed by a real, live code path. The duplicate/
 * migration analyzer (`hamie/analysis/analyzers/duplicate_migration.py`,
 * wrapping `domain/duplicate_classifier.py`'s
 * `DuplicateGroupClassification`) is registered in
 * `hamie/__init__.py`'s `ScanCoordinator` supervisors and runs every
 * scan, emitting findings with `category: "duplicate_migration"` and
 * one of four `recommendation_kind` values
 * (`investigate`/`review_duplicate`/`repair`/`no_action`) depending on
 * classification. Both remaining categories query
 * `hamie/explorer/findings` like the original four, using the
 * `category`/`recommendation_kind` server-side filters
 * (`domain/intelligence.py::_matches_filters`'s `direct` dict):
 * - Duplicate / Migration <- category "duplicate_migration" AND
 *                          recommendation_kind "investigate" (migration
 *                          leftover, an active old id with a new
 *                          sibling) OR "review_duplicate" (ambiguous --
 *                          no single rule matched confidently).
 * - Broken Reference      <- category "duplicate_migration" AND
 *                          recommendation_kind "repair" (a live
 *                          reference points at a disabled/unavailable
 *                          sibling -- BROKEN_REFERENCE_TO_OLD_SIBLING).
 * A duplicate group classified LIKELY_DISTINCT_ENTITIES
 * (`recommendation_kind: "no_action"`) is deliberately never shown in
 * either tab -- it was actively evaluated and cleared, not a pending
 * decision for a human. It remains visible in Issues/Search for
 * auditability.
 *
 * The first four categories are unchanged from the prior pass, built
 * from fields `hamie/explorer/findings` and
 * `hamie/remediation/queue/list` already return (verified against
 * `domain/intelligence.py`'s `_finding_decision` and
 * `domain/maintenance_work_record.py`, not guessed):
 * - Confirmed Orphans   <- classification "Persistently unavailable" +
 *                          repairability "Potentially safe to disable"
 *                          (dependency scan complete, zero references).
 * - Unavailable But Used <- classification "Referenced entity".
 * - Insufficient Evidence <- repairability "Needs more evidence".
 * - Protected Dormant    <- durable maintenance work items whose
 *                          `lifecycle_state` is "dependency_blocked".
 *
 * All six categories can honestly be empty at any time (e.g. this
 * installation's backend has not been reloaded since these analyzers
 * were wired in -- HAMIE requires a Home Assistant Core restart or
 * config-entry reload to pick up new Python source, see the mission
 * report's activation-path finding) -- an empty tab always renders
 * `<hamie-empty>`, never fake/placeholder rows.
 */
import { LitElement, css, html } from "lit";

import { relativeTime } from "../format.js";
import { friendlyError } from "../errors.js";
import "../components/hamie-page-header.js";
import "../components/hamie-review-item.js";
import "../components/hamie-button.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";

const RISK_TONE_MAP = { low: "low", medium: "medium", high: "high", critical: "high" };

const CATEGORIES = [
  {
    id: "confirmed_orphans",
    label: "Confirmed Orphans",
    icon: "mdi:file-question-outline",
    description: "Entities with no known references and a complete dependency scan.",
    source: "live_findings",
    filters: { classification: "Persistently unavailable", repairability: "Potentially safe to disable", lifecycle: "open" },
    recommendation: "No local Home Assistant object references this entity and its dependency scan is complete. Consider disabling it.",
  },
  {
    id: "unavailable_but_used",
    label: "Unavailable But Used",
    icon: "mdi:link-variant-off",
    description: "Unavailable, but at least one automation, script, or dashboard still references it.",
    source: "live_findings",
    filters: { classification: "Referenced entity", lifecycle: "open" },
    recommendation: "This entity is currently unavailable but is still referenced elsewhere. Repair the source, do not disable it.",
  },
  {
    id: "duplicate_migration",
    label: "Duplicate / Migration",
    icon: "mdi:content-duplicate",
    description: "Suffix-duplicate entities (e.g. foo / foo_2) from a device re-pair or a partial rename, or a case no single rule could classify confidently.",
    source: "live_findings",
    // Two server-side queries merged: LIKELY_MIGRATION_LEFTOVER /
    // ACTIVE_OLD_ID_WITH_NEW_SIBLING (recommendation_kind
    // "investigate") and AMBIGUOUS_DUPLICATE_GROUP
    // (recommendation_kind "review_duplicate"). Excludes
    // LIKELY_DISTINCT_ENTITIES ("no_action" -- cleared, not a pending
    // decision) and BROKEN_REFERENCE_TO_OLD_SIBLING ("repair" -- its
    // own tab below).
    filtersList: [
      { category: "duplicate_migration", recommendation_kind: "investigate" },
      { category: "duplicate_migration", recommendation_kind: "review_duplicate" },
    ],
    recommendation: "A suffix-duplicate group needs a human look. Confirm which member is genuinely still in use before disabling any sibling.",
  },
  {
    id: "insufficient_evidence",
    label: "Insufficient Evidence",
    icon: "mdi:magnify-scan",
    description: "HAMIE could not fully verify these are safe to touch.",
    source: "live_findings",
    filters: { repairability: "Needs more evidence", lifecycle: "open" },
    recommendation: "The dependency scan for this entity is incomplete. Gather more evidence before deciding.",
  },
  {
    id: "protected_dormant",
    label: "Protected Dormant",
    icon: "mdi:shield-check-outline",
    description: "Inactive, but a real dependency was found -- protected from cleanup.",
    source: "maintenance_work_items",
    lifecycleState: "dependency_blocked",
    recommendation: "A real local dependency was found for this group. Keep it; do not disable or remove.",
  },
  {
    id: "broken_reference",
    label: "Broken Reference",
    icon: "mdi:link-off",
    description: "An automation, script, or dashboard points at an old entity id that no longer resolves.",
    source: "live_findings",
    filters: { category: "duplicate_migration", recommendation_kind: "repair" },
    recommendation: "A disabled or unavailable entity still has a live reference pointing at it. Update the referencing automation, script, or dashboard to point at the active sibling.",
  },
];

function evidenceForAgainst(category, item) {
  const dependency = item.dependency || {};
  const evidenceFor = [];
  const evidenceAgainst = [];

  if (category.id === "confirmed_orphans") {
    evidenceFor.push("Dependency scan complete: no references found");
    evidenceFor.push(`Repairability: ${item.repairability}`);
    if (item.first_seen) evidenceFor.push(`Persistently unavailable since ${relativeTime(item.first_seen)}`);
  } else if (category.id === "unavailable_but_used") {
    evidenceFor.push(`Referenced by ${dependency.count ?? "at least one"} object${dependency.count === 1 ? "" : "s"}`);
    if (dependency.referenced_by?.length) evidenceFor.push(`Referencing objects: ${dependency.referenced_by.join(", ")}`);
  } else if (category.id === "insufficient_evidence") {
    evidenceAgainst.push("Dependency scan is incomplete for this entity");
    if (dependency.unresolved_references?.length) {
      evidenceAgainst.push(`Unresolved references: ${dependency.unresolved_references.join(", ")}`);
    }
  } else if (category.id === "protected_dormant") {
    evidenceFor.push("Currently inactive/unavailable");
    evidenceAgainst.push(item.reason || "A real local dependency was found for this group");
  } else if (category.id === "duplicate_migration") {
    evidenceFor.push(item.recommended_next_action || item.recommendation);
    if (item.recommendation_kind === "review_duplicate") {
      evidenceAgainst.push("No single classification rule matched confidently -- confirm by hand.");
    }
  } else if (category.id === "broken_reference") {
    evidenceAgainst.push(item.recommended_next_action || item.recommendation);
  }

  if (category.id !== "insufficient_evidence") {
    if (dependency.coverage && dependency.coverage !== "complete") {
      evidenceAgainst.push("Dependency scan coverage is incomplete");
    }
    if (item.confidence && item.confidence !== "high") {
      evidenceAgainst.push(`Confidence is ${item.confidence}, not high -- verify manually`);
    }
  }
  return { evidenceFor, evidenceAgainst };
}

function externalConsumerNote(item) {
  const dependency = item.dependency || {};
  if (dependency.coverage && dependency.coverage !== "complete") {
    return "Dependency scan incomplete -- external consumers (dashboards, scripts, or connectors HAMIE could not reach) cannot be fully ruled out.";
  }
  if ((dependency.count ?? 0) > 0) {
    return `Referenced by ${dependency.count} known object(s) inside this Home Assistant installation. HAMIE cannot see dashboards or automations outside this installation (e.g. a separate remote instance).`;
  }
  return null;
}

export class HamieViewReview extends LitElement {
  static properties = {
    hass: { attribute: false },
    _activeId: { state: true },
    _data: { state: true }, // { [categoryId]: items[] | null }
    _error: { state: true },
  };

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: var(--hamie-space-2);
      margin-bottom: var(--hamie-space-4);
    }
    .tab {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      padding: var(--hamie-space-1-5) var(--hamie-space-3);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-pill);
      background: var(--hamie-surface-raised);
      color: var(--hamie-text-secondary);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      cursor: pointer;
      font-family: inherit;
    }
    .tab[aria-pressed="true"] {
      background: var(--hamie-accent-fill-loud);
      color: var(--hamie-accent-on);
      border-color: transparent;
    }
    .tab .count {
      opacity: 0.85;
    }
    ha-icon {
      --mdc-icon-size: 14px;
    }
    .category-description {
      margin: 0 0 var(--hamie-space-4);
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .list {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
    }
    .pending-banner {
      display: flex;
      align-items: flex-start;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-4);
      border-radius: var(--hamie-radius-lg);
      border: 1px dashed var(--hamie-border-normal);
      background: var(--hamie-surface-raised);
      color: var(--hamie-text-secondary);
      font-size: var(--hamie-text-small);
      line-height: 1.6;
    }
    .pending-banner ha-icon {
      --mdc-icon-size: 20px;
      color: var(--hamie-status-evidence);
      flex-shrink: 0;
    }
  `;

  constructor() {
    super();
    this._activeId = CATEGORIES[0].id;
    this._data = {};
  }

  connectedCallback() {
    super.connectedCallback();
    this._loadAll();
    this._onLiveUpdate = () => this._loadAll();
    window.addEventListener("hamie-live-update", this._onLiveUpdate);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("hamie-live-update", this._onLiveUpdate);
  }

  async _loadAll() {
    if (!this.hass) return;
    try {
      const liveCategories = CATEGORIES.filter((cat) => cat.source === "live_findings");
      // A category may need more than one server-side filter combined
      // (`filtersList`) because `hamie/explorer/findings` only supports
      // equality per field, not "one of several values" -- e.g.
      // Duplicate / Migration spans two distinct recommendation_kind
      // values. A plain single-filter category (`filters`) is queried
      // once, same as before.
      const queries = liveCategories.map((cat) => cat.filtersList || [cat.filters]);
      const flatQueries = queries.flat();
      const [findingsResults, queue] = await Promise.all([
        Promise.all(
          flatQueries.map((filters) =>
            this.hass.callWS({
              type: "hamie/explorer/findings",
              search: "",
              filters,
              sort: "priority",
              offset: 0,
              limit: 25,
            }),
          ),
        ),
        this.hass.callWS({ type: "hamie/remediation/queue/list", offset: 0, limit: 1 }),
      ]);
      const data = {};
      let index = 0;
      for (const cat of CATEGORIES) {
        if (cat.source === "live_findings") {
          const count = (cat.filtersList || [cat.filters]).length;
          const merged = findingsResults.slice(index, index + count).flatMap((r) => r.items);
          index += count;
          // De-duplicate by finding_id in case two filter sets in the
          // same filtersList could ever overlap (they do not today --
          // recommendation_kind values are mutually exclusive per
          // finding -- but de-duplicating is a cheap, honest guard
          // against a future classification change silently double-
          // counting a row).
          const seen = new Set();
          data[cat.id] = merged.filter((item) => {
            if (seen.has(item.finding_id)) return false;
            seen.add(item.finding_id);
            return true;
          });
        } else if (cat.source === "maintenance_work_items") {
          data[cat.id] = (queue.maintenance_work_items || []).filter(
            (item) => item.lifecycle_state === cat.lifecycleState,
          );
        } else {
          data[cat.id] = [];
        }
      }
      this._data = data;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Review data is temporarily unavailable.");
    }
  }

  _onViewFinding(findingId) {
    this.dispatchEvent(new CustomEvent("hamie-navigate-finding", { detail: { findingId }, bubbles: true, composed: true }));
  }

  _onOpenReviewQueue() {
    this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "remediation" }, bubbles: true, composed: true }));
  }

  _renderFindingItem(category, item) {
    const { evidenceFor, evidenceAgainst } = evidenceForAgainst(category, item);
    return html`
      <hamie-review-item
        name=${item.friendly_name || item.entity_id}
        entity-id=${item.entity_id}
        integration=${item.integration || ""}
        recommendation=${category.recommendation}
        confidence-level=${item.confidence || ""}
        risk=${RISK_TONE_MAP[item.dependency_risk] || "unknown"}
        .evidenceFor=${evidenceFor}
        .evidenceAgainst=${evidenceAgainst}
        external-consumer-note=${externalConsumerNote(item) || ""}
      >
        <hamie-button slot="actions" variant="secondary" size="xs" @click=${() => this._onViewFinding(item.finding_id)}>
          View in Issues
        </hamie-button>
      </hamie-review-item>
    `;
  }

  _renderWorkItem(category, item) {
    const evidenceFor = ["Currently inactive/unavailable"];
    const evidenceAgainst = [item.reason];
    if (item.missing_evidence?.length) evidenceAgainst.push(`Missing evidence: ${item.missing_evidence.join(", ")}`);
    return html`
      <hamie-review-item
        name=${item.title}
        entity-id=${(item.affected_entity_ids || [])[0] || ""}
        integration=""
        recommendation=${category.recommendation}
        confidence-level=${item.confidence || ""}
        risk=${RISK_TONE_MAP[item.risk] || "unknown"}
        .evidenceFor=${evidenceFor}
        .evidenceAgainst=${evidenceAgainst}
        external-consumer-note=${item.entity_count > 1 ? `Affects ${item.entity_count} entities.` : ""}
      >
        <hamie-button slot="actions" variant="secondary" size="xs" @click=${() => this._onOpenReviewQueue()}>
          Open in Review Queue
        </hamie-button>
      </hamie-review-item>
    `;
  }

  render() {
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="Review is unavailable" description=${this._error}></hamie-empty>`;
    }
    const loaded = Object.keys(this._data).length === CATEGORIES.length;
    if (!loaded) {
      return html`<hamie-loading .lines=${5}></hamie-loading>`;
    }

    const active = CATEGORIES.find((cat) => cat.id === this._activeId);
    const items = this._data[active.id] || [];

    return html`
      <hamie-page-header heading="Review" subtitle="Human-judgment triage, separate from Issues -- recommendations only, no destructive actions."></hamie-page-header>

      <div class="tabs" role="tablist">
        ${CATEGORIES.map(
          (cat) => html`
            <button
              type="button"
              class="tab"
              role="tab"
              aria-pressed=${cat.id === this._activeId ? "true" : "false"}
              @click=${() => (this._activeId = cat.id)}
            >
              <ha-icon icon=${cat.icon}></ha-icon>
              ${cat.label}
              <span class="count">${cat.source === "pending" ? "—" : (this._data[cat.id] || []).length}</span>
            </button>
          `,
        )}
      </div>

      <p class="category-description">${active.description}</p>

      ${active.source === "pending"
        ? html`
            <div class="pending-banner">
              <ha-icon icon="mdi:progress-clock"></ha-icon>
              <span>
                <strong>Pending activation.</strong> ${active.pendingReason}
                This category is deliberately shown as empty rather than approximated, so it is never mistaken for "HAMIE checked and found none."
              </span>
            </div>
          `
        : items.length === 0
          ? html`<hamie-empty tone="positive" heading="Nothing in this category right now"></hamie-empty>`
          : html`
              <div class="list">
                ${items.map((item) =>
                  active.source === "maintenance_work_items" ? this._renderWorkItem(active, item) : this._renderFindingItem(active, item),
                )}
              </div>
            `}
    `;
  }
}

if (!customElements.get("hamie-view-review")) {
  customElements.define("hamie-view-review", HamieViewReview);
}
