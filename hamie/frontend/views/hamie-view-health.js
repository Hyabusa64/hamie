/**
 * <hamie-view-health> — renders the "Systems" screen (by-system and
 * by-integration real health states -- spec: "Healthy/Degraded/Offline/
 * Needs Review/Unknown, not just raw finding counts"). Originally
 * reconstructed from App.tsx's `HouseHealthPage`; this pass adds a real
 * connector health-state row (`hamie/connectors/status`, already used
 * unchanged by Connectors/Overview) and converts the by-category finding
 * breakdown into by-integration <hamie-system-card> rows carrying one of
 * exactly five real states, computed honestly from each integration's
 * own open-finding severities -- never a bare count alone.
 *
 * State derivation (`_systemState`): no open findings -> healthy; only
 * warning-severity findings -> degraded; any critical-severity finding
 * -> needs_review; no scan has ever completed yet -> unknown. "Offline"
 * is deliberately never derived for an integration this way -- findings
 * alone cannot prove an integration's process is unreachable, only that
 * it has open issues -- and is reserved for `_connectorState`, which
 * maps a connector's own real reachability status
 * (ConnectorManager.public_status()) directly.
 *
 * Real-data reconciliation:
 * - Gauge score: real `availability_health` (same field Overview uses).
 * - "All systems nominal" chip: derived honestly from the real score
 *   using the same 90/70 threshold hamie-gauge's color already uses --
 *   not a new invented rule.
 * - "Scanned X ago / Next in Y min": real `last_scan` only. "Next in Y"
 *   has no backing at all -- HAMIE has no recurring scan schedule
 *   (confirmed: only a one-time startup `initial_scan_delay`, no
 *   periodic interval anywhere in the runtime). Omitted rather than
 *   inventing a countdown.
 * - "System breakdown": Figma's Climate/Lighting/Security/etc. categories
 *   don't exist in HAMIE's domain model (confirmed in the design audit).
 *   Re-purposed for something HAMIE actually has and House Health can
 *   meaningfully add over Overview: open findings grouped by their real
 *   `category` field (a free-form, analyzer-defined string, not a fixed
 *   enum -- one generic icon is used for all categories rather than
 *   assuming a closed set that doesn't exist). No fabricated percentage/
 *   score bar -- Figma's 87-100% figures have no real per-category score
 *   to bind to, so a plain count + severity-derived status chip is shown
 *   instead.
 * - Active findings table: real, identical shape to the Findings screen,
 *   filtered to lifecycle=open -- a genuine, direct reuse of real data,
 *   including the same shared findingStatusToken() helper Findings uses
 *   (this view originally hardcoded the status chip to always show
 *   "warning", reproducing the exact severity-color bug already fixed
 *   on Findings -- factored out once into findings-status.js instead of
 *   fixing it a second time independently).
 *
 * Functionality-pass fixes (this view was silently broken end-to-end):
 * - `hamie/explorer/findings` hard-caps `limit` at 100
 *   (domain/intelligence.py MAX_PAGE_SIZE) -- this view previously sent
 *   `limit: 200`, which always raised ValueError server-side, which
 *   always rendered the unavailable state. Every load of this screen was
 *   failing. Fixed to filter server-side (`filters: {lifecycle: "open"}`)
 *   at `limit: 100`, which is also strictly more correct than fetching a
 *   mixed page and filtering client-side.
 * - `availability_health` is `null` before any scan has ever completed
 *   (domain confirmed: only computed once entities_evaluated > 0). The
 *   90/70 comparisons treated `null` as "critical issues detected", a
 *   fabricated claim about a system that has simply never been scanned.
 *   Now shown as an honest "not scanned yet" state instead.
 * - The Refresh button had no click handler at all. Wired to the real
 *   `hamie.scan` service (services.py SERVICE_SCAN, no fields, awaits
 *   full completion) followed by a reload, mirroring hamie-view-overview.
 */
import { LitElement, css, html } from "lit";

import { relativeTime } from "../format.js";
import { friendlyError } from "../errors.js";
import { findingStatusToken, groupFindingsBy } from "../findings-status.js";
import "../components/hamie-page-header.js";
import "../components/hamie-card.js";
import "../components/hamie-section.js";
import "../components/hamie-status.js";
import "../components/hamie-gauge.js";
import "../components/hamie-metric.js";
import "../components/hamie-table.js";
import "../components/hamie-button.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";
import "../components/hamie-system-card.js";

const CONNECTOR_ICON = {
  ollama: "mdi:brain",
  n8n: "mdi:sitemap-outline",
  mcp: "mdi:server-network-outline",
  hkg: "mdi:graph-outline",
};

// Maps ConnectorManager.public_status()'s real 5-value status
// (healthy/degraded/error/disabled/unknown) onto the Systems screen's
// fixed 5-state vocabulary. "error" (unreachable within the configured
// timeout) is the one real connector meaning of "offline"; "disabled" is
// honestly "unknown" here, not "offline" -- a disabled connector's
// underlying reachability was never checked at all, so claiming it is
// offline would be a fabricated claim, not a derived one.
const CONNECTOR_STATE = { healthy: "healthy", degraded: "degraded", error: "offline", disabled: "unknown", unknown: "unknown" };

export class HamieViewHealth extends LitElement {
  static properties = {
    hass: { attribute: false },
    _overview: { state: true },
    _findings: { state: true },
    _findingsTotal: { state: true },
    _connectors: { state: true },
    _error: { state: true },
    _refreshError: { state: true }, // scan-refresh-only failure; keeps existing data visible
    _scanning: { state: true },
  };

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .refresh-error {
      margin-bottom: var(--hamie-space-4);
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
    .health-summary {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-4);
    }
    @media (max-width: 870px) {
      .health-summary {
        grid-template-columns: repeat(2, 1fr);
      }
    }
    .content-grid {
      display: grid;
      grid-template-columns: 1fr 2fr;
      gap: var(--hamie-space-4);
      margin-bottom: var(--hamie-space-5);
    }
    .system-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-5);
    }
    @media (max-width: 870px) {
      .content-grid {
        grid-template-columns: 1fr;
      }
    }
    .gauge-card {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: var(--hamie-space-3);
      text-align: center;
    }
    .scanned {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .breakdown-row {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-2) 0;
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .breakdown-row:last-child {
      border-bottom: none;
    }
    .breakdown-name {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      width: 140px;
      flex-shrink: 0;
      text-transform: capitalize;
    }
    .breakdown-count {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      flex: 1;
    }
    ha-icon {
      --mdc-icon-size: 14px;
      color: var(--hamie-text-secondary);
      flex-shrink: 0;
    }
  `;

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  async _load() {
    if (!this.hass) return;
    try {
      const [overview, findings, connectors] = await Promise.all([
        this.hass.callWS({ type: "hamie/explorer/overview" }),
        this.hass.callWS({
          type: "hamie/explorer/findings",
          search: "",
          filters: { lifecycle: "open" },
          sort: "priority",
          offset: 0,
          // Server hard-caps this at 100 (domain/intelligence.py
          // MAX_PAGE_SIZE) -- sending more always raises ValueError.
          limit: 100,
        }),
        this.hass.callWS({ type: "hamie/connectors/status" }).catch(() => []),
      ]);
      this._overview = overview;
      this._findings = findings.items;
      this._findingsTotal = findings.total;
      this._connectors = connectors;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Systems data is temporarily unavailable.");
    }
  }

  // No open findings -> healthy; only warnings -> degraded; any critical
  // -> needs_review; no scan completed yet -> unknown. See the module
  // docstring for why this never derives "offline".
  _systemState(groupItems) {
    if (!this._overview?.last_scan) return "unknown";
    if (groupItems.some((item) => item.severity === "critical")) return "needs_review";
    if (groupItems.some((item) => item.severity === "warning")) return "degraded";
    return "healthy";
  }

  async _onRefresh() {
    if (!this.hass) return;
    this._scanning = true;
    this._refreshError = null;
    try {
      // Real hamie.scan service (services.py SERVICE_SCAN) -- takes no
      // fields, awaits full scan completion before resolving.
      await this.hass.callService("hamie", "scan", {});
      await this._load();
    } catch (err) {
      const message = friendlyError(err, "The scan could not be completed.");
      if (this._overview && this._findings) {
        // Data was already showing (this scan's own retry, or an
        // earlier successful load) -- a failed refresh never blanks
        // out real, still-valid results. Only the banner below reports
        // the failure; House Health itself keeps showing what it last
        // successfully loaded.
        this._refreshError = message;
      } else {
        this._error = message;
      }
    } finally {
      this._scanning = false;
    }
  }

  render() {
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="House Health data is unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._overview || !this._findings) {
      return html`<hamie-loading .lines=${4}></hamie-loading>`;
    }

    const health = this._overview.availability_health;
    // `availability_health` is null until the first scan with evaluated
    // entities completes -- treated as its own honest state, never
    // coerced into a fabricated "critical" reading.
    const hasHealth = health !== null && health !== undefined;
    // Tone/wording follow Operational Health, not the whole-house
    // Maintenance figure (same distinction Overview makes -- see
    // hamie-view-overview.js): operational_health already excludes
    // diagnostic/optional entity clutter, so hundreds of stale diagnostic
    // sensors never read as "critical issues detected" on a house whose
    // primary entities/devices/automations are actually fine.
    const operational = this._overview.operational_health;
    const hasOperational = operational !== null && operational !== undefined;
    const tone = !hasOperational ? "unknown" : operational >= 90 ? "healthy" : operational >= 70 ? "warning" : "critical";
    const toneLabel = !hasOperational
      ? "Not scanned yet"
      : operational >= 90
        ? "All systems nominal"
        : operational >= 70
          ? "Needs attention"
          : "Critical issues detected";
    const breakdown = groupFindingsBy(this._findings, "category");
    const truncated = this._findingsTotal > this._findings.length;

    // By-integration real health states (see `_systemState`'s docstring)
    // -- the "by-system" view the Systems spec calls for, distinct from
    // the by-category breakdown below (which HAMIE also has real data
    // for and keeps, rather than replacing one real breakdown with
    // another).
    const integrationGroups = new Map();
    for (const item of this._findings) {
      const key = item.integration || "Unknown";
      if (!integrationGroups.has(key)) integrationGroups.set(key, []);
      integrationGroups.get(key).push(item);
    }
    const systemCards = [...integrationGroups.entries()]
      .map(([name, items]) => ({
        name,
        state: this._systemState(items),
        detail: `${items.length} open finding${items.length === 1 ? "" : "s"}`,
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
    const repairable = this._findings.filter((item) => item.repairability === "Potentially safe to disable").length;
    const advisoryOnly = this._findings.filter((item) => item.repairability !== "Potentially safe to disable").length;

    const rows = this._findings.map((item) => {
      const status = findingStatusToken(item);
      return {
        id: item.finding_id,
        cells: [
          html`<hamie-status variant="severity" status=${item.severity}></hamie-status>`,
          html`<span style="font-family: var(--hamie-font-code); font-size: var(--hamie-text-micro); color: var(--hamie-text-secondary)">${item.entity_id}</span>`,
          html`${item.recommendation}`,
          html`${item.category}`,
          html`<span style="font-family: var(--hamie-font-code); font-size: var(--hamie-text-micro); color: var(--hamie-text-secondary)">${relativeTime(item.first_seen)}</span>`,
          html`<hamie-status status=${status.status} label=${status.label}></hamie-status>`,
        ],
      };
    });

    return html`
      <hamie-page-header heading="Systems" subtitle="Real health states by integration and by connector -- continuous monitoring across all home systems">
        <div slot="actions">
          <hamie-button variant="secondary" size="sm" ?disabled=${this._scanning} @click=${this._onRefresh}>
            <ha-icon icon="mdi:refresh"></ha-icon> ${this._scanning ? "Scanning…" : "Refresh"}
          </hamie-button>
        </div>
      </hamie-page-header>

      ${this._refreshError
        ? html`
            <div class="refresh-error" role="alert">
              <span>Latest scan failed: ${this._refreshError} Showing results from ${this._overview.last_scan ? relativeTime(this._overview.last_scan) : "the last successful scan"}.</span>
              <hamie-button variant="ghost" size="xs" aria-label="Dismiss" @click=${() => (this._refreshError = null)}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          `
        : null}

      <div class="health-summary">
        <hamie-metric
          label="Current risks"
          value=${(this._overview.critical_findings || 0) + (this._overview.warning_findings || 0)}
          sub="Critical and warning findings"
          icon="mdi:alert-outline"
        ></hamie-metric>
        <hamie-metric
          label="Root causes"
          value=${this._overview.root_cause_groups ?? 0}
          sub="Evidence-derived groups"
          icon="mdi:family-tree"
        ></hamie-metric>
        <hamie-metric
          label="Changed since scan"
          value=${(this._overview.new_findings || 0) + (this._overview.resolved_findings || 0)}
          sub="${this._overview.new_findings || 0} new · ${this._overview.resolved_findings || 0} resolved"
          icon="mdi:swap-vertical"
        ></hamie-metric>
        <hamie-metric
          label="Repairability"
          value=${repairable}
          sub="${advisoryOnly} advisory or needs evidence"
          icon="mdi:wrench-outline"
        ></hamie-metric>
      </div>

      <div class="content-grid">
        <hamie-card padding="md">
          <div class="gauge-card">
            <hamie-gauge .score=${hasOperational ? operational : health}></hamie-gauge>
            <hamie-status status=${tone} label=${toneLabel}></hamie-status>
            <p class="scanned">
              ${this._overview.last_scan ? `Scanned ${relativeTime(this._overview.last_scan)}` : "No scan yet"}
            </p>
          </div>
        </hamie-card>

        <hamie-card padding="md">
          <hamie-section heading="Findings by category" description="Open findings grouped by analyzer category"></hamie-section>
          ${breakdown.length === 0
            ? html`<hamie-empty tone="positive" heading="No open findings"></hamie-empty>`
            : breakdown.map(
                (group) => html`
                  <div class="breakdown-row">
                    <ha-icon icon="mdi:shape-outline"></ha-icon>
                    <span class="breakdown-name">${group.key}</span>
                    <span class="breakdown-count">${group.count} open finding${group.count === 1 ? "" : "s"}</span>
                    <hamie-status status=${group.status}></hamie-status>
                  </div>
                `,
              )}
        </hamie-card>
      </div>

      <hamie-section heading="By integration" description="Real health state derived from each integration's own open findings"></hamie-section>
      ${systemCards.length === 0
        ? html`<hamie-empty tone="positive" heading="No open findings in any integration"></hamie-empty>`
        : html`
            <div class="system-grid">
              ${systemCards.map((card) => html`<hamie-system-card name=${card.name} icon="mdi:puzzle-outline" state=${card.state} detail=${card.detail}></hamie-system-card>`)}
            </div>
          `}

      ${this._connectors?.length
        ? html`
            <hamie-section heading="By connector" description="HAMIE's own outbound connectors -- reachability, not finding counts"></hamie-section>
            <div class="system-grid">
              ${this._connectors.map((connector) => {
                const state = connector.enabled ? CONNECTOR_STATE[connector.status] || "unknown" : "unknown";
                const detail = connector.enabled
                  ? `${connector.status}${connector.latency_ms != null ? ` · ${connector.latency_ms} ms` : ""}`
                  : "Disabled";
                return html`
                  <hamie-system-card
                    name=${connector.connector_id}
                    icon=${CONNECTOR_ICON[connector.connector_id] || "mdi:swap-horizontal"}
                    state=${state}
                    detail=${detail}
                  ></hamie-system-card>
                `;
              })}
            </div>
          `
        : null}

      <hamie-card padding="none">
        <div style="padding: var(--hamie-space-3) var(--hamie-space-4); border-bottom: 1px solid var(--hamie-border-hairline); font-size: var(--hamie-text-small); font-weight: var(--hamie-weight-medium); color: var(--hamie-text-primary)">
          Active findings
        </div>
        <hamie-table .columns=${["Severity", "Entity", "Issue", "Category", "Detected", "Status"]} .rows=${rows}>
          <div slot="empty" style="padding: var(--hamie-space-8) 0">
            <hamie-empty tone="positive" heading="No active findings"></hamie-empty>
          </div>
        </hamie-table>
        ${truncated
          ? html`<div style="padding: var(--hamie-space-2) var(--hamie-space-4); font-size: var(--hamie-text-micro); color: var(--hamie-text-secondary); border-top: 1px solid var(--hamie-border-hairline)">
              Showing ${this._findings.length} of ${this._findingsTotal} open findings — see the Findings screen for the full list.
            </div>`
          : null}
      </hamie-card>
    `;
  }
}

if (!customElements.get("hamie-view-health")) {
  customElements.define("hamie-view-health", HamieViewHealth);
}
