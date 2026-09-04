/**
 * <hamie-view-findings> — the maintenance-console redesign's issue-inbox
 * Findings screen.
 *
 * All underlying data/action logic (search, sort, the full 15-field
 * advanced filter panel, group bulk actions, dependency-graph
 * navigation) is unchanged from the prior UI 3.0 implementation -- every
 * `hamie/explorer/findings`/`hamie/group/*` call and field it reads is
 * the same real backend contract, verified field-by-field against
 * domain/intelligence.py's finding_summary()/_matches_filters() before
 * this pass, not guessed. Only the presentation changed:
 *
 * - Quick filters are now the real, evidence-only `classification`/
 *   `repairability` fields finding_summary() already computes per
 *   finding (Referenced entity / Potentially safe to disable / Needs
 *   more evidence / Transient unavailable -- see _finding_decision in
 *   domain/intelligence.py) instead of leading with severity, which the
 *   mission redesign correctly identifies as nearly always "warning" and
 *   therefore not a useful primary axis. `_matches_filters` gained real
 *   server-side `classification`/`repairability` filter keys this pass
 *   (a small, justified backend addition exposing an already-computed
 *   field, not a new heuristic) so this is a genuine server-side filter,
 *   not a client-side approximation.
 * - Severity/lifecycle filtering still exists in full -- moved into the
 *   existing "More filters" advanced panel alongside the other 13 real
 *   filter fields, rather than removed.
 * - Rows are now compact <hamie-issue-row> entries (title/entity id,
 *   status+duration, integration·area, trailing classification chip)
 *   instead of a wide table -- a severity indicator only renders when
 *   the finding is genuinely critical, per the redesign's "small
 *   severity indicator only when severity meaningfully differs" rule.
 * - Row click opens a right-side <hamie-drawer> (mobile: full-screen
 *   sheet) instead of a centered modal -- same six detail sections
 *   (location, state, dependency summary, group actions, evidence, AI
 *   explanations, audit history) as before, now under "Technical
 *   details" disclosure where the content is raw/internal.
 */
import { LitElement, css, html } from "lit";

import { relativeTime } from "../format.js";
import { friendlyError } from "../errors.js";
import { idempotencyToken } from "../idempotency.js";
import { findingStatusToken, realFindingStatus } from "../findings-status.js";
import { primeHaRegistry, resolveAreaName } from "../ha-registry.js";
import "../components/hamie-page-header.js";
import "../components/hamie-issue-row.js";
import "../components/hamie-drawer.js";
import "../components/hamie-disclosure.js";
import "../components/hamie-card.js";
import "../components/hamie-input.js";
import "../components/hamie-select.js";
import "../components/hamie-button.js";
import "../components/hamie-status.js";
import "../components/hamie-dialog.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";

// Real, evidence-only classification/repairability values
// (_finding_decision in domain/intelligence.py) -- the primary quick
// filters. "all" aside, each maps to one real backend filter key+value.
const QUICK_FILTERS = [
  { id: "all", label: "All" },
  { id: "actionable", label: "Actionable", key: "repairability", value: "Potentially safe to disable" },
  { id: "protected", label: "Protected", key: "classification", value: "Referenced entity" },
  { id: "needs_evidence", label: "Needs evidence", key: "repairability", value: "Needs more evidence" },
  { id: "transient", label: "Transient", key: "classification", value: "Transient unavailable" },
];

const PAGE_SIZE = 25;
// Real server hard cap (domain/intelligence.py MAX_PAGE_SIZE) -- used
// only for the focusFindingId client-side match, to search as wide a
// page as the server allows since there's no server-side finding_id
// filter to narrow the query itself.
const PAGE_SIZE_MAX = 100;

const SORT_OPTIONS = [
  ["priority", "Priority"],
  ["severity", "Severity"],
  ["dependency_risk", "Dependency risk"],
  ["affected_objects", "Affected objects"],
  ["confidence", "Confidence"],
  ["age", "Age"],
  ["recurrence", "Recurrence"],
  ["newness", "Newness"],
  ["group_size", "Group size"],
  ["user_priority", "User priority"],
  ["ai_advisory_priority", "AI advisory priority"],
].map(([value, label]) => ({ value, label }));

const GROUP_BY_OPTIONS = [
  ["integration", "Integration"],
  ["config_entry", "Config entry"],
  ["device", "Device"],
  ["category", "Category"],
  ["duration", "Duration"],
  ["repairability", "Repairability"],
  ["dependency_status", "Dependency status"],
  ["proposed_action", "Proposed action"],
].map(([value, label]) => ({ value, label }));

const SEVERITY_OPTIONS = ["info", "warning", "critical"];
const LIFECYCLE_OPTIONS = ["open", "resolved"];
const REVIEW_STATE_OPTIONS = ["new", "acknowledged", "snoozed", "retained", "dismissed"];
const DEPENDENCY_RISK_OPTIONS = ["low", "medium", "high", "critical"];
const AI_STATE_OPTIONS = ["none", "new", "acknowledged", "rejected", "retained", "expired", "stale"];

const GROUP_ACTIONS = [
  { id: "acknowledge", label: "Acknowledge", icon: "mdi:check-circle-outline" },
  { id: "snooze", label: "Snooze", icon: "mdi:clock-outline" },
  { id: "retain", label: "Retain", icon: "mdi:shield-check-outline" },
  { id: "dismiss", label: "Dismiss", icon: "mdi:close-circle-outline" },
  { id: "suppress", label: "Suppress", icon: "mdi:eye-off-outline" },
];

function withBlank(values) {
  return [{ value: "", label: "Any" }, ...values.map((value) => ({ value, label: value }))];
}

// "54 min"/"3h"/"2d" -- the same convention relativeTime() uses, applied
// to a raw duration in seconds (finding.duration_seconds) rather than a
// timestamp.
function formatDuration(seconds) {
  if (seconds == null) return null;
  if (seconds < 60) return "under a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

export class HamieViewFindings extends LitElement {
  static properties = {
    hass: { attribute: false },
    focusFindingId: { type: String },
    focusGroupId: { type: String },
    focusGroupTitle: { type: String },
    _items: { state: true },
    _total: { state: true },
    _error: { state: true },
    _quickFilter: { state: true },
    _search: { state: true },
    _sort: { state: true },
    _advancedOpen: { state: true },
    _advanced: { state: true },
    _offset: { state: true },
    _openCount: { state: true },
    _snoozedCount: { state: true },
    _resolvedCount: { state: true },
    _detailItem: { state: true },
    _pending: { state: true },
    _reason: { state: true },
    _actionError: { state: true },
    _busy: { state: true },
    _scanStatus: { state: true },
    _coverage: { state: true },
    _classificationCounts: { state: true },
    _groupingCounts: { state: true },
    _groupBy: { state: true },
    _registryReady: { state: true },
    _grouped: { state: true },
  };

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .toolbar {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-3);
      flex-wrap: wrap;
    }
    .search {
      width: 240px;
    }
    .filters {
      display: flex;
      align-items: center;
      gap: 2px;
      padding: var(--hamie-space-1);
      background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-md);
    }
    .filters button {
      padding: var(--hamie-space-1) var(--hamie-space-2-5);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      border-radius: var(--hamie-radius-sm);
      border: none;
      background: transparent;
      color: var(--hamie-text-secondary);
      cursor: pointer;
      font-family: inherit;
    }
    .filters button[aria-pressed="true"] {
      background: var(--hamie-accent-fill-loud);
      color: var(--hamie-accent-on);
    }
    .advanced-panel {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-hairline);
    }
    @media (max-width: 870px) {
      .advanced-panel {
        grid-template-columns: 1fr;
      }
    }
    .field label {
      display: block;
      font-size: var(--hamie-text-caption);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-text-secondary);
      margin-bottom: var(--hamie-space-1);
    }
    .advanced-actions {
      grid-column: 1 / -1;
      display: flex;
      gap: var(--hamie-space-2);
    }
    .entity {
      font-family: var(--hamie-font-code);
      font-size: var(--hamie-text-caption);
      color: var(--hamie-text-secondary);
    }
    .row-status {
      display: flex;
      align-items: baseline;
      gap: var(--hamie-space-1-5);
    }
    .pager {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--hamie-space-2-5) var(--hamie-space-1);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .list {
      display: flex;
      flex-direction: column;
    }
    .list > * + * {
      border-top: 1px solid var(--hamie-border-hairline);
    }
    .group-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-2) var(--hamie-space-4);
      background: var(--hamie-surface-raised);
      border-top: 1px solid var(--hamie-border-hairline);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-secondary);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
    }
    .group-header:first-child {
      border-top: none;
    }
    .group-header-count {
      text-transform: none;
      letter-spacing: normal;
      font-weight: var(--hamie-weight-medium);
    }
    .summary-line {
      margin: 0 0 var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .group-strip {
      display: flex;
      flex-wrap: wrap;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-2);
    }
    .summary-chip {
      padding: var(--hamie-space-1) var(--hamie-space-2);
      border-radius: var(--hamie-radius-sm);
      background: var(--hamie-surface-raised);
      color: var(--hamie-text-secondary);
      font-size: var(--hamie-text-micro);
    }
    .action-error {
      margin-bottom: var(--hamie-space-3);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
      font-size: var(--hamie-text-small);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .drawer-eyebrow {
      margin: 0 0 var(--hamie-space-1);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .drawer-section {
      margin-bottom: var(--hamie-space-4);
    }
    .drawer-section h3 {
      margin: 0 0 var(--hamie-space-1-5);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-text-secondary);
    }
    .drawer-section p {
      margin: 0 0 var(--hamie-space-1);
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
      line-height: 1.5;
    }
    .drawer-actions {
      display: flex;
      gap: var(--hamie-space-2);
      flex-wrap: wrap;
      margin-top: var(--hamie-space-3);
    }
    .detail-meta {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.8;
    }
    .detail-list {
      margin: 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
  `;

  constructor() {
    super();
    this._quickFilter = "all";
    this._search = "";
    this._sort = "priority";
    this._advanced = {};
    this._offset = 0;
    this._groupBy = "integration";
    // Issues spec: "grouped findings (by system/domain, not one flat
    // pile of 500+ cards)" -- default view groups the current
    // (already server-paginated, <=25-item) page by real `integration`,
    // not a client-side fetch of the whole finding universe. A flat
    // list remains one click away for anyone who prefers scanning by
    // priority order instead.
    this._grouped = true;
  }

  connectedCallback() {
    super.connectedCallback();
    this._load();
    primeHaRegistry(this.hass).then(() => {
      this._registryReady = true;
    });
  }

  _buildFilters() {
    if (this.focusFindingId) return {};
    if (this.focusGroupId) return { group_id: this.focusGroupId };
    const filters = { ...this._advanced };
    const quick = QUICK_FILTERS.find((item) => item.id === this._quickFilter);
    if (quick?.key) filters[quick.key] = quick.value;
    return filters;
  }

  async _load() {
    if (!this.hass) return;
    try {
      if (this.focusFindingId) {
        const result = await this.hass.callWS({
          type: "hamie/explorer/findings",
          search: "",
          filters: {},
          sort: "priority",
          offset: 0,
          limit: PAGE_SIZE_MAX,
        });
        this._items = result.items.filter((item) => item.finding_id === this.focusFindingId);
        this._total = this._items.length;
        this._error = null;
        return;
      }
      const filters = this._buildFilters();
      const [result, openTotal, snoozedTotal, resolvedTotal, overview] = await Promise.all([
        this.hass.callWS({
          type: "hamie/explorer/findings",
          search: this._search,
          filters,
          sort: this._sort,
          offset: this._offset,
          limit: PAGE_SIZE,
        }),
        this.hass.callWS({ type: "hamie/explorer/findings", search: "", filters: { lifecycle: "open" }, sort: "priority", offset: 0, limit: 1 }),
        this.hass.callWS({ type: "hamie/explorer/findings", search: "", filters: { lifecycle: "open", review_state: "snoozed" }, sort: "priority", offset: 0, limit: 1 }),
        this.hass.callWS({ type: "hamie/explorer/findings", search: "", filters: { lifecycle: "resolved" }, sort: "priority", offset: 0, limit: 1 }),
        this.hass.callWS({ type: "hamie/explorer/overview" }),
      ]);
      this._items = result.items;
      this._classificationCounts = result.classification_counts || {};
      this._groupingCounts = result.grouping_counts || {};
      this._total = result.total;
      this._snoozedCount = snoozedTotal.total;
      this._openCount = openTotal.total - snoozedTotal.total;
      this._resolvedCount = resolvedTotal.total;
      this._scanStatus = overview.scan_status;
      this._coverage = overview.coverage;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Findings are temporarily unavailable.");
    }
  }

  _setQuickFilter(id) {
    this._quickFilter = id;
    this._offset = 0;
    this._load();
  }

  _onSearchInput(event) {
    this._search = event.detail.value;
  }

  _onSearchApply() {
    this._offset = 0;
    this._load();
  }

  _updateAdvanced(key, value) {
    this._advanced = { ...this._advanced, [key]: value };
  }

  _applyAdvanced() {
    this._offset = 0;
    this._load();
  }

  _clearAdvanced() {
    this._advanced = {};
    this._sort = "priority";
    this._offset = 0;
    this._load();
  }

  _nextPage() {
    this._offset += PAGE_SIZE;
    this._load();
  }

  _previousPage() {
    this._offset = Math.max(0, this._offset - PAGE_SIZE);
    this._load();
  }

  _clearFocus() {
    this.focusFindingId = null;
    this.focusGroupId = null;
    this.focusGroupTitle = null;
    this._offset = 0;
    this._load();
  }

  _onViewDependencyGraph(findingId, entityId) {
    this._detailItem = null;
    this.dispatchEvent(
      new CustomEvent("hamie-navigate-dependencies", { detail: { findingId, entityId }, bubbles: true, composed: true }),
    );
  }

  async _onGroupAction(group_id, action) {
    if (!this.hass) return;
    this._actionError = null;
    this._busy = true;
    try {
      const preview = await this.hass.callWS({ type: "hamie/group/preview", group_id, action });
      if (preview.count === 0) {
        this._actionError = `No eligible findings for "${GROUP_ACTIONS.find((item) => item.id === action)?.label}" in this group.`;
        return;
      }
      this._reason = "";
      this._pending = { group_id, action, preview };
      this._detailItem = null;
    } catch (err) {
      this._actionError = friendlyError(err, "That action could not be started.");
    } finally {
      this._busy = false;
    }
  }

  _cancelPending() {
    this._pending = null;
    this._reason = "";
  }

  async _confirmPending() {
    if (!this.hass || !this._pending) return;
    const { action, preview } = this._pending;
    this._busy = true;
    try {
      if (action === "suppress") {
        await this.hass.callWS({
          type: "hamie/group/suppress",
          preview,
          idempotency_token: idempotencyToken(),
          reason: this._reason.trim(),
        });
      } else {
        await this.hass.callWS({ type: "hamie/group/apply", preview, idempotency_token: idempotencyToken() });
      }
      this._pending = null;
      this._reason = "";
      await this._load();
    } catch (err) {
      this._actionError = friendlyError(err, "That action could not be applied.");
    } finally {
      this._busy = false;
    }
  }

  render() {
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="Findings are unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._items) {
      return html`<hamie-loading .lines=${5}></hamie-loading>`;
    }

    const neverScanned = !this.focusFindingId && !this.focusGroupId && this._scanStatus === "never_run";
    const failedWithNothingRetained =
      !this.focusFindingId && !this.focusGroupId && this._scanStatus === "failed" && this._coverage === "unknown";

    if (neverScanned || failedWithNothingRetained) {
      return html`
        <hamie-empty
          tone=${neverScanned ? "neutral" : "unavailable"}
          heading=${neverScanned ? "No scan has completed yet" : "The latest scan failed"}
          description=${neverScanned
            ? "Run a scan to see findings here."
            : "No previous results are available yet. Run a scan to try again."}
        ></hamie-empty>
      `;
    }

    return html`
      <hamie-page-header heading="Findings" subtitle="${this._openCount ?? "—"} open · ${this._snoozedCount ?? "—"} snoozed · ${this._resolvedCount ?? "—"} resolved"></hamie-page-header>

      ${this._actionError
        ? html`
            <div class="action-error">
              <span>${this._actionError}</span>
              <hamie-button variant="ghost" size="xs" @click=${() => (this._actionError = null)}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          `
        : null}

      ${this.focusFindingId || this.focusGroupId
        ? html`
            <div style="display: flex; align-items: center; justify-content: space-between; gap: var(--hamie-space-3); margin-bottom: var(--hamie-space-3); padding: var(--hamie-space-2-5) var(--hamie-space-3); border-radius: var(--hamie-radius-md); background: var(--hamie-surface-raised)">
              <span style="font-size: var(--hamie-text-micro); color: var(--hamie-text-secondary)">
                ${this.focusGroupId
                  ? `Showing findings in group: ${this.focusGroupTitle || this.focusGroupId}.`
                  : "Showing one finding from Recommendations."}
              </span>
              <hamie-button variant="ghost" size="xs" @click=${this._clearFocus}>Show all findings</hamie-button>
            </div>
          `
        : html`
            <div class="toolbar">
              <hamie-input
                class="search"
                placeholder="Search entities or issues…"
                icon="mdi:magnify"
                .value=${this._search}
                @hamie-input=${this._onSearchInput}
                @keydown=${(event) => event.key === "Enter" && this._onSearchApply()}
              ></hamie-input>
              <div class="filters">
                ${QUICK_FILTERS.map(
                  (filter) => html`
                    <button aria-pressed=${filter.id === this._quickFilter ? "true" : "false"} @click=${() => this._setQuickFilter(filter.id)}>
                      ${filter.label}
                    </button>
                  `,
                )}
              </div>
              <hamie-button variant="ghost" size="sm" @click=${() => (this._advancedOpen = !this._advancedOpen)}>
                <ha-icon icon="mdi:tune-variant"></ha-icon> ${this._advancedOpen ? "Hide filters" : "More filters"}
              </hamie-button>
              <hamie-button variant="ghost" size="sm" @click=${() => (this._grouped = !this._grouped)}>
                <ha-icon icon=${this._grouped ? "mdi:view-agenda-outline" : "mdi:folder-multiple-outline"}></ha-icon>
                ${this._grouped ? "Flat list" : "Group by system"}
              </hamie-button>
            </div>

            <hamie-disclosure label="Breakdown">
              <p class="summary-line">
                ${Object.entries(this._classificationCounts || {})
                  .map(([label, count]) => `${count} ${label}`)
                  .join(" · ") || "No breakdown available"}
              </p>
              <div style="display:flex; align-items:center; gap: var(--hamie-space-2); margin-bottom: var(--hamie-space-1)">
                <span class="summary-line" style="margin:0">Group by</span>
                <hamie-select
                  .options=${GROUP_BY_OPTIONS}
                  .value=${this._groupBy}
                  @hamie-change=${(event) => (this._groupBy = event.detail.value)}
                ></hamie-select>
              </div>
              <div class="group-strip" aria-label="Selected grouping summary">
                ${(this._groupingCounts?.[this._groupBy] || []).map(
                  (group) => html`<span class="summary-chip"><strong>${group.count}</strong> ${group.label}</span>`,
                )}
              </div>
            </hamie-disclosure>

            ${this._advancedOpen
              ? html`
                  <div class="advanced-panel">
                    <div class="field">
                      <label>Sort</label>
                      <hamie-select .options=${SORT_OPTIONS} .value=${this._sort} @hamie-change=${(e) => (this._sort = e.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>Severity</label>
                      <hamie-select .options=${withBlank(SEVERITY_OPTIONS)} .value=${this._advanced.severity || ""} @hamie-change=${(e) => this._updateAdvanced("severity", e.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>Lifecycle</label>
                      <hamie-select .options=${withBlank(LIFECYCLE_OPTIONS)} .value=${this._advanced.lifecycle || ""} @hamie-change=${(e) => this._updateAdvanced("lifecycle", e.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>Category</label>
                      <hamie-input .value=${this._advanced.category || ""} @hamie-input=${(e) => this._updateAdvanced("category", e.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Analyzer ID</label>
                      <hamie-input .value=${this._advanced.analyzer || ""} @hamie-input=${(e) => this._updateAdvanced("analyzer", e.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Integration domain</label>
                      <hamie-input .value=${this._advanced.integration || ""} @hamie-input=${(e) => this._updateAdvanced("integration", e.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Device ID</label>
                      <hamie-input .value=${this._advanced.device || ""} @hamie-input=${(e) => this._updateAdvanced("device", e.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Area ID</label>
                      <hamie-input .value=${this._advanced.area || ""} @hamie-input=${(e) => this._updateAdvanced("area", e.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Review state</label>
                      <hamie-select .options=${withBlank(REVIEW_STATE_OPTIONS)} .value=${this._advanced.review_state || ""} @hamie-change=${(e) => this._updateAdvanced("review_state", e.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>Dependency risk</label>
                      <hamie-select .options=${withBlank(DEPENDENCY_RISK_OPTIONS)} .value=${this._advanced.dependency_risk || ""} @hamie-change=${(e) => this._updateAdvanced("dependency_risk", e.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>Safe to remove</label>
                      <hamie-select .options=${[{ value: "", label: "Any" }, { value: "true", label: "Safe" }, { value: "false", label: "Not safe" }]} .value=${this._advanced.safe_to_remove || ""} @hamie-change=${(e) => this._updateAdvanced("safe_to_remove", e.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>AI recommendation state</label>
                      <hamie-select .options=${withBlank(AI_STATE_OPTIONS)} .value=${this._advanced.ai_recommendation_state || ""} @hamie-change=${(e) => this._updateAdvanced("ai_recommendation_state", e.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>First seen from (aware ISO)</label>
                      <hamie-input .value=${this._advanced.first_seen_from || ""} @hamie-input=${(e) => this._updateAdvanced("first_seen_from", e.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>First seen to (aware ISO)</label>
                      <hamie-input .value=${this._advanced.first_seen_to || ""} @hamie-input=${(e) => this._updateAdvanced("first_seen_to", e.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Last seen from (aware ISO)</label>
                      <hamie-input .value=${this._advanced.last_seen_from || ""} @hamie-input=${(e) => this._updateAdvanced("last_seen_from", e.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Last seen to (aware ISO)</label>
                      <hamie-input .value=${this._advanced.last_seen_to || ""} @hamie-input=${(e) => this._updateAdvanced("last_seen_to", e.detail.value)}></hamie-input>
                    </div>
                    <div class="advanced-actions">
                      <hamie-button variant="primary" size="sm" @click=${this._applyAdvanced}>Apply</hamie-button>
                      <hamie-button variant="ghost" size="sm" @click=${this._clearAdvanced}>Clear</hamie-button>
                    </div>
                  </div>
                `
              : null}
          `}

      <hamie-card padding="none">
        ${this._items.length === 0
          ? html`
              <hamie-empty
                tone=${this.focusFindingId ? "unavailable" : "positive"}
                heading=${this.focusFindingId
                  ? "That finding isn't in the current page of results"
                  : this.focusGroupId
                    ? "No findings currently belong to this group"
                    : "No findings match this filter"}
                description=${this.focusFindingId ? "It may have been resolved, or it's outside the highest-priority page currently loaded." : ""}
              ></hamie-empty>
            `
          : this._grouped && !this.focusFindingId && !this.focusGroupId
            ? this._renderGroupedList(this._items)
            : html`
                <div class="list">
                  ${this._items.map((item) => this._renderRow(item))}
                </div>
              `}
      </hamie-card>
      ${!this.focusFindingId && this._items.length
        ? html`
            <div class="pager">
              <hamie-button variant="ghost" size="xs" ?disabled=${this._offset === 0} @click=${this._previousPage}>Previous</hamie-button>
              <span>${this._total === 0 ? 0 : this._offset + 1}–${Math.min(this._offset + PAGE_SIZE, this._total)} of ${this._total}</span>
              <hamie-button variant="ghost" size="xs" ?disabled=${this._offset + PAGE_SIZE >= this._total} @click=${this._nextPage}>Next</hamie-button>
            </div>
          `
        : null}

      ${this._detailItem ? this._renderDetailDrawer(this._detailItem) : null}
      ${this._pending ? this._renderConfirmDialog() : null}
    `;
  }

  // Groups the current findings page by real `integration` (falling
  // back to the finding's `category` when `integration` is unset, then
  // "Other"). Every group's own findings are still real
  // `hamie/explorer/findings` rows -- this only changes visual
  // clustering of the already-fetched page, never a second fetch.
  _renderGroupedList(items) {
    const groups = new Map();
    for (const item of items) {
      const key = item.integration || item.category || "Other";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    const sorted = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
    return html`
      ${sorted.map(
        ([name, groupItems]) => html`
          <div class="group-header">
            <span>${name}</span>
            <span class="group-header-count">${groupItems.length} finding${groupItems.length === 1 ? "" : "s"}</span>
          </div>
          <div class="list">${groupItems.map((item) => this._renderRow(item))}</div>
        `,
      )}
    `;
  }

  _renderRow(item) {
    const status = findingStatusToken(item);
    const duration = formatDuration(item.duration_seconds);
    const areaName = resolveAreaName(item.area) || item.area;
    const locationLine = [item.integration, areaName].filter(Boolean).join(" · ");
    return html`
      <hamie-issue-row
        interactive
        title=${item.friendly_name || item.entity_id}
        @hamie-row-click=${() => (this._detailItem = item)}
      >
        ${item.severity === "critical"
          ? html`<hamie-status slot="leading" variant="severity" status="critical"></hamie-status>`
          : null}
        <span slot="extra" class="entity">${item.entity_id}</span>
        <span slot="extra" class="row-status">
          <hamie-status status=${status.status} label=${realFindingStatus(item) === "open" ? (duration ? `Unavailable ${duration}` : "Open") : status.label}></hamie-status>
          ${locationLine ? html`<span style="color: var(--hamie-text-secondary); font-size: var(--hamie-text-micro)">${locationLine}</span>` : null}
        </span>
        <span slot="trailing" style="font-size: var(--hamie-text-micro); color: var(--hamie-text-secondary)">${item.repairability}</span>
        <ha-icon slot="trailing" icon="mdi:chevron-right"></ha-icon>
      </hamie-issue-row>
    `;
  }

  // Detail drawer taxonomy per the Issues spec: Summary / Impact /
  // Evidence / Dependencies / History / Recommendation / Technical
  // Details (collapsed by default). Every field rendered below is the
  // same real `hamie/explorer/findings` per-finding data the drawer
  // already fetched before this pass -- only the section grouping
  // changed; Evidence/History/AI explanations move OUT of the old
  // single "Technical details" catch-all into their own named sections
  // (the spec names them explicitly), and Technical Details keeps only
  // genuinely raw/internal identifiers.
  _renderDetailDrawer(item) {
    const dependency = item.dependency || {};
    return html`
      <hamie-drawer open heading=${item.friendly_name || item.entity_id} description=${item.entity_id} @hamie-drawer-closed=${() => (this._detailItem = null)}>
        <div class="drawer-section">
          <h3>Summary</h3>
          <p>${item.recommendation}</p>
          <p class="detail-meta">
            Device: ${item.device || "Unknown"} · Integration: ${item.integration || "Unknown"}<br />
            Classification: ${item.classification} · Repairability: ${item.repairability}
          </p>
        </div>

        <div class="drawer-section">
          <h3>Impact</h3>
          <p>${dependency.rationale || item.recommendation}</p>
          <p class="detail-meta">
            Severity: ${item.severity} · Duration: ${formatDuration(item.duration_seconds) || "Unknown"}<br />
            Occurrences: ${item.occurrence_count ?? "Unknown"} · Dependency risk: ${item.dependency_risk || "Unknown"}
          </p>
        </div>

        <div class="drawer-section">
          <h3>Evidence</h3>
          ${item.evidence?.length
            ? html`
                <ul class="detail-list">
                  ${item.evidence.map((e) => html`<li>${e.kind} · ${e.predicate} = ${e.value} · ${e.source} @ ${e.source_revision}</li>`)}
                </ul>
              `
            : html`<p class="detail-meta">No attributed evidence recorded for this finding.</p>`}
        </div>

        <div class="drawer-section">
          <h3>Dependencies</h3>
          <p>
            ${dependency.coverage === "complete" ? "Checked" : "Check incomplete"} ·
            Referenced by ${dependency.count ?? 0} object${dependency.count === 1 ? "" : "s"}
          </p>
          ${dependency.referenced_by?.length
            ? html`<p style="font-size: var(--hamie-text-micro); color: var(--hamie-text-secondary)">${dependency.referenced_by.join(", ")}</p>`
            : null}
          <div class="drawer-actions">
            <hamie-button variant="secondary" size="sm" @click=${() => this._onViewDependencyGraph(item.finding_id, item.entity_id)}>
              View dependency graph
            </hamie-button>
          </div>
        </div>

        <div class="drawer-section">
          <h3>History</h3>
          ${item.audit_history?.length
            ? html`
                <ul class="detail-list">
                  ${item.audit_history.map((e) => html`<li>${relativeTime(e.at)} · ${e.event} · ${e.actor}</li>`)}
                </ul>
              `
            : html`<p class="detail-meta">No HAMIE audit history recorded for this finding yet.</p>`}
        </div>

        <div class="drawer-section">
          <h3>Recommendation</h3>
          <p>${item.recommendation}</p>
          ${item.ai_explanations?.length
            ? html`
                <p class="detail-meta"><strong>AI advisory explanations</strong></p>
                <ul class="detail-list">
                  ${item.ai_explanations.map((e) => html`<li>${e.summary} · ${e.stale ? `stale: ${(e.stale_reasons || []).join(", ")}` : e.review_state}</li>`)}
                </ul>
              `
            : null}
          ${item.group_id
            ? html`
                <div class="drawer-actions">
                  ${GROUP_ACTIONS.map(
                    (action) => html`
                      <hamie-button variant="ghost" size="xs" ?disabled=${this._busy} @click=${() => this._onGroupAction(item.group_id, action.id)}>
                        <ha-icon icon=${action.icon}></ha-icon> ${action.label} group
                      </hamie-button>
                    `,
                  )}
                </div>
              `
            : null}
        </div>

        <hamie-disclosure label="Technical details">
          <p class="detail-meta">
            Finding ID: ${item.finding_id}<br />
            Config entry: ${item.config_entry || "unknown"}<br />
            Area: ${item.area || "unknown"}<br />
            Lifecycle: ${item.lifecycle} · Review: ${item.review_state} · Suppression: ${item.suppression_state} · Confidence: ${item.confidence}<br />
            Current state: ${item.current_state}<br />
            First seen: ${relativeTime(item.first_seen)} · Last seen: ${relativeTime(item.last_seen)} · Occurrences: ${item.occurrence_count}<br />
            Dependency safe to remove: ${String(dependency.safe_to_remove)}
          </p>
        </hamie-disclosure>
      </hamie-drawer>
    `;
  }

  _renderConfirmDialog() {
    const action = GROUP_ACTIONS.find((item) => item.id === this._pending.action);
    return html`
      <hamie-dialog
        open
        heading="${action?.label} group findings?"
        cancel-label="Cancel"
        .confirmLabel=${action?.label || "Confirm"}
        .destructive=${["dismiss", "suppress"].includes(this._pending.action)}
        .busy=${!!this._busy}
        .errorMessage=${this._actionError || ""}
        .confirmDisabled=${this._pending.action === "suppress" && !this._reason?.trim()}
        .onConfirm=${() => this._confirmPending()}
        .onCancel=${() => this._cancelPending()}
      >
        <p>
          ${action?.label} exactly ${this._pending.preview.count} finding${this._pending.preview.count === 1 ? "" : "s"}
          in this finding's group.
          ${this._pending.action === "snooze" ? "They will be snoozed for exactly 24 hours." : ""}
          ${this._pending.action === "suppress" ? "They will be hidden from default views, not deleted." : ""}
          Home Assistant objects will not be changed.
        </p>
        ${this._pending.action === "suppress"
          ? html`
              <div class="field">
                <label>Reason (required)</label>
                <hamie-input placeholder="Why is this being suppressed?" .value=${this._reason} @hamie-input=${(e) => (this._reason = e.detail.value)}></hamie-input>
              </div>
            `
          : null}
      </hamie-dialog>
    `;
  }
}

if (!customElements.get("hamie-view-findings")) {
  customElements.define("hamie-view-findings", HamieViewFindings);
}
