/**
 * <hamie-view-search> — entity/device/integration/area/issue search
 * (spec section "Search"). Findings/groups search is real, existing
 * server-side filtering: `hamie/explorer/findings` and
 * `hamie/explorer/groups` (presentation/api.py's `ws_findings`/
 * `ws_groups`) already accept a `search` string and apply it entirely on
 * the backend (domain/intelligence.py's index), server-paginated at
 * `limit`. No new backend endpoint was needed or added for this screen
 * -- confirmed by reading presentation/api.py before writing this, not
 * assumed -- so the 8,000+ entity universe is never shipped to the
 * browser to search client-side, exactly the constraint the spec calls
 * out.
 *
 * Device/Area/Integration search is genuinely client-side, but
 * deliberately so: those three real Home Assistant registries
 * (ha-registry.js, already primed elsewhere in the app) are small --
 * tens to low hundreds of rows on a real installation -- unlike the
 * entity/finding universe, so filtering the already-cached list in the
 * browser is the correct, minimal choice rather than adding a redundant
 * backend endpoint for data this small.
 */
import { LitElement, css, html } from "lit";

import { friendlyError } from "../errors.js";
import { primeHaRegistry, listDevices, listAreas, listConfigEntries, resolveAreaName } from "../ha-registry.js";
import "../components/hamie-page-header.js";
import "../components/hamie-input.js";
import "../components/hamie-button.js";
import "../components/hamie-card.js";
import "../components/hamie-issue-row.js";
import "../components/hamie-status.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";

const KINDS = [
  { id: "all", label: "All" },
  { id: "entities", label: "Entities & Issues" },
  { id: "groups", label: "Groups" },
  { id: "devices", label: "Devices" },
  { id: "areas", label: "Areas" },
  { id: "integrations", label: "Integrations" },
];

const RESULT_LIMIT = 20;

export class HamieViewSearch extends LitElement {
  static properties = {
    hass: { attribute: false },
    _query: { state: true },
    _kind: { state: true },
    _results: { state: true }, // { entities: [], groups: [], devices: [], areas: [], integrations: [] } | null
    _searching: { state: true },
    _error: { state: true },
    _registryReady: { state: true },
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
      flex-direction: column;
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-4);
    }
    .search-input {
      max-width: 480px;
    }
    .kinds {
      display: flex;
      flex-wrap: wrap;
      gap: 2px;
      padding: var(--hamie-space-1);
      background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-md);
      width: fit-content;
    }
    .kinds button {
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
    .kinds button[aria-pressed="true"] {
      background: var(--hamie-accent-fill-loud);
      color: var(--hamie-accent-on);
    }
    .group {
      margin-bottom: var(--hamie-space-5);
    }
    .group h2 {
      margin: 0 0 var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-text-secondary);
    }
    .list {
      display: flex;
      flex-direction: column;
    }
    .list > * + * {
      border-top: 1px solid var(--hamie-border-hairline);
    }
    .entity-id {
      font-family: var(--hamie-font-code);
      font-size: var(--hamie-text-caption);
      color: var(--hamie-text-secondary);
    }
  `;

  constructor() {
    super();
    this._query = "";
    this._kind = "all";
    this._results = null;
  }

  connectedCallback() {
    super.connectedCallback();
    primeHaRegistry(this.hass).then(() => (this._registryReady = true));
  }

  _onInput(event) {
    this._query = event.detail.value;
  }

  async _onSearch() {
    if (!this.hass) return;
    const query = this._query.trim();
    if (!query) {
      this._results = null;
      return;
    }
    this._searching = true;
    this._error = null;
    try {
      const wantEntities = this._kind === "all" || this._kind === "entities";
      const wantGroups = this._kind === "all" || this._kind === "groups";
      const [findings, groups] = await Promise.all([
        wantEntities
          ? this.hass.callWS({ type: "hamie/explorer/findings", search: query, filters: {}, sort: "priority", offset: 0, limit: RESULT_LIMIT })
          : Promise.resolve({ items: [] }),
        wantGroups
          ? this.hass.callWS({ type: "hamie/explorer/groups", search: query, offset: 0, limit: RESULT_LIMIT })
          : Promise.resolve({ items: [] }),
      ]);
      const lowered = query.toLowerCase();
      const wantDevices = this._kind === "all" || this._kind === "devices";
      const wantAreas = this._kind === "all" || this._kind === "areas";
      const wantIntegrations = this._kind === "all" || this._kind === "integrations";
      this._results = {
        entities: findings.items,
        groups: groups.items,
        devices: wantDevices
          ? listDevices()
              .filter((item) => (item.name_by_user || item.name || "").toLowerCase().includes(lowered))
              .slice(0, RESULT_LIMIT)
          : [],
        areas: wantAreas
          ? listAreas()
              .filter((item) => (item.name || "").toLowerCase().includes(lowered))
              .slice(0, RESULT_LIMIT)
          : [],
        integrations: wantIntegrations
          ? listConfigEntries()
              .filter((item) => (item.title || item.domain || "").toLowerCase().includes(lowered))
              .slice(0, RESULT_LIMIT)
          : [],
      };
    } catch (err) {
      this._error = friendlyError(err, "Search is temporarily unavailable.");
    } finally {
      this._searching = false;
    }
  }

  _onViewFinding(findingId) {
    this.dispatchEvent(new CustomEvent("hamie-navigate-finding", { detail: { findingId }, bubbles: true, composed: true }));
  }

  _onViewGroup(groupId, groupTitle) {
    this.dispatchEvent(
      new CustomEvent("hamie-navigate-findings-group", { detail: { groupId, groupTitle }, bubbles: true, composed: true }),
    );
  }

  _hasAnyResults() {
    const r = this._results;
    return r && (r.entities.length || r.groups.length || r.devices.length || r.areas.length || r.integrations.length);
  }

  render() {
    return html`
      <hamie-page-header heading="Search" subtitle="Find entities, issues, groups, devices, areas, and integrations."></hamie-page-header>

      <div class="toolbar">
        <hamie-input
          class="search-input"
          icon="mdi:magnify"
          placeholder="Search HAMIE and Home Assistant…"
          .value=${this._query}
          @hamie-input=${this._onInput}
          @keydown=${(event) => event.key === "Enter" && this._onSearch()}
        ></hamie-input>
        <div class="kinds" role="tablist">
          ${KINDS.map(
            (kind) => html`
              <button
                type="button"
                role="tab"
                aria-pressed=${kind.id === this._kind ? "true" : "false"}
                @click=${() => {
                  this._kind = kind.id;
                  if (this._query.trim()) this._onSearch();
                }}
              >
                ${kind.label}
              </button>
            `,
          )}
          <hamie-button variant="primary" size="sm" ?disabled=${this._searching} @click=${this._onSearch}>
            ${this._searching ? "Searching…" : "Search"}
          </hamie-button>
        </div>
      </div>

      ${this._error ? html`<hamie-empty tone="unavailable" heading="Search is unavailable" description=${this._error}></hamie-empty>` : null}

      ${!this._error && this._results === null
        ? html`<hamie-empty tone="neutral" heading="Search for anything in your home" description="Entities, findings, groups, devices, areas, or integrations."></hamie-empty>`
        : null}

      ${this._searching ? html`<hamie-loading .lines=${4}></hamie-loading>` : null}

      ${!this._error && !this._searching && this._results !== null
        ? this._hasAnyResults()
          ? html`
              ${this._results.entities.length
                ? html`
                    <div class="group">
                      <h2>Entities &amp; Issues (${this._results.entities.length})</h2>
                      <hamie-card padding="none">
                        <div class="list">
                          ${this._results.entities.map(
                            (item) => html`
                              <hamie-issue-row interactive title=${item.friendly_name || item.entity_id} @hamie-row-click=${() => this._onViewFinding(item.finding_id)}>
                                <span slot="extra" class="entity-id">${item.entity_id}</span>
                                <hamie-status slot="trailing" status=${item.severity} variant="severity"></hamie-status>
                                <ha-icon slot="trailing" icon="mdi:chevron-right"></ha-icon>
                              </hamie-issue-row>
                            `,
                          )}
                        </div>
                      </hamie-card>
                    </div>
                  `
                : null}
              ${this._results.groups.length
                ? html`
                    <div class="group">
                      <h2>Groups (${this._results.groups.length})</h2>
                      <hamie-card padding="none">
                        <div class="list">
                          ${this._results.groups.map(
                            (item) => html`
                              <hamie-issue-row
                                interactive
                                title=${item.title}
                                meta="${item.member_count} member${item.member_count === 1 ? "" : "s"}"
                                @hamie-row-click=${() => this._onViewGroup(item.group_id, item.title)}
                              >
                                <hamie-status slot="trailing" status=${item.critical_count > 0 ? "critical" : item.warning_count > 0 ? "warning" : "info"} label="Priority ${item.priority}"></hamie-status>
                                <ha-icon slot="trailing" icon="mdi:chevron-right"></ha-icon>
                              </hamie-issue-row>
                            `,
                          )}
                        </div>
                      </hamie-card>
                    </div>
                  `
                : null}
              ${this._results.devices.length
                ? html`
                    <div class="group">
                      <h2>Devices (${this._results.devices.length})</h2>
                      <hamie-card padding="none">
                        <div class="list">
                          ${this._results.devices.map(
                            (item) => html`
                              <hamie-issue-row title=${item.name_by_user || item.name || item.id} meta=${resolveAreaName(item.area_id) || "No area"}>
                                <ha-icon slot="leading" icon="mdi:chip"></ha-icon>
                              </hamie-issue-row>
                            `,
                          )}
                        </div>
                      </hamie-card>
                    </div>
                  `
                : null}
              ${this._results.areas.length
                ? html`
                    <div class="group">
                      <h2>Areas (${this._results.areas.length})</h2>
                      <hamie-card padding="none">
                        <div class="list">
                          ${this._results.areas.map(
                            (item) => html`
                              <hamie-issue-row title=${item.name}>
                                <ha-icon slot="leading" icon="mdi:floor-plan"></ha-icon>
                              </hamie-issue-row>
                            `,
                          )}
                        </div>
                      </hamie-card>
                    </div>
                  `
                : null}
              ${this._results.integrations.length
                ? html`
                    <div class="group">
                      <h2>Integrations (${this._results.integrations.length})</h2>
                      <hamie-card padding="none">
                        <div class="list">
                          ${this._results.integrations.map(
                            (item) => html`
                              <hamie-issue-row title=${item.title || item.domain} meta=${item.domain}>
                                <ha-icon slot="leading" icon="mdi:puzzle-outline"></ha-icon>
                              </hamie-issue-row>
                            `,
                          )}
                        </div>
                      </hamie-card>
                    </div>
                  `
                : null}
            `
          : html`<hamie-empty tone="neutral" heading="No results for &ldquo;${this._query}&rdquo;"></hamie-empty>`
        : null}
    `;
  }
}

if (!customElements.get("hamie-view-search")) {
  customElements.define("hamie-view-search", HamieViewSearch);
}
