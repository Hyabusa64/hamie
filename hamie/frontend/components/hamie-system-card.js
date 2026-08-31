/**
 * <hamie-system-card> — one system/integration's real health state, for
 * the Systems screen (spec: "real health states (Healthy/Degraded/
 * Offline/Needs Review/Unknown), not just raw finding counts").
 *
 * `state` is always one of exactly those five (see hamie-view-health.js's
 * `_systemState`/`_connectorState` mappings, the only two real callers):
 * a connector's own real ConnectorManager.public_status() status
 * (healthy/degraded/error/disabled/unknown), or an integration's derived
 * state from its real open-finding severities (no criticals -> healthy;
 * only warnings -> degraded; any critical -> needs_review; no scan data
 * yet -> unknown). "Offline" only ever applies to a connector that is
 * unreachable, never derived for an integration (findings alone cannot
 * prove an integration is offline vs. merely has issues).
 */
import { LitElement, css, html } from "lit";

const STATE_TOKEN = {
  healthy: "healthy",
  degraded: "warning",
  offline: "critical",
  needs_review: "critical",
  unknown: "unknown",
};
const STATE_LABEL = {
  healthy: "Healthy",
  degraded: "Degraded",
  offline: "Offline",
  needs_review: "Needs review",
  unknown: "Unknown",
};

export class HamieSystemCard extends LitElement {
  static properties = {
    name: { type: String },
    icon: { type: String },
    state: { type: String }, // "healthy" | "degraded" | "offline" | "needs_review" | "unknown"
    detail: { type: String }, // one short line, e.g. "2 critical · 5 warning"
    interactive: { type: Boolean, reflect: true },
  };

  static styles = css`
    :host {
      display: block;
    }
    .card {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-3);
      width: 100%;
      box-sizing: border-box;
      padding: var(--hamie-space-3) var(--hamie-space-4);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg);
      background: var(--hamie-surface-card);
      text-align: left;
      font: inherit;
      color: inherit;
    }
    :host([interactive]) .card {
      cursor: pointer;
    }
    :host([interactive]) .card:hover {
      border-color: var(--hamie-border-normal);
      background: var(--hamie-surface-hover);
    }
    .card:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: -2px;
    }
    .icon-badge {
      flex-shrink: 0;
      width: 36px;
      height: 36px;
      border-radius: var(--hamie-radius-md);
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .icon-badge ha-icon {
      --mdc-icon-size: 18px;
    }
    .body {
      flex: 1;
      min-width: 0;
    }
    .name {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .detail {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .state-chip {
      flex-shrink: 0;
      display: inline-flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      padding: var(--hamie-space-half) var(--hamie-space-2);
      border-radius: var(--hamie-radius-pill);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
    }
    .dot {
      width: 6px;
      height: 6px;
      border-radius: var(--hamie-radius-circle);
      flex-shrink: 0;
    }
  `;

  _onClick() {
    if (!this.interactive) return;
    this.dispatchEvent(new CustomEvent("hamie-system-click", { bubbles: true, composed: true }));
  }

  render() {
    const state = this.state || "unknown";
    const token = STATE_TOKEN[state] || "unknown";
    const inner = html`
      <span class="icon-badge" style="background: var(--hamie-status-${token}-fill)">
        <ha-icon icon=${this.icon || "mdi:cube-outline"} style="color: var(--hamie-status-${token})"></ha-icon>
      </span>
      <span class="body">
        <p class="name">${this.name}</p>
        ${this.detail ? html`<p class="detail">${this.detail}</p>` : null}
      </span>
      <span class="state-chip" style="background: var(--hamie-status-${token}-fill); color: var(--hamie-status-${token})">
        <span class="dot" style="background: var(--hamie-status-${token})"></span>
        ${STATE_LABEL[state] || state}
      </span>
    `;
    return this.interactive
      ? html`<button type="button" class="card" @click=${this._onClick}>${inner}</button>`
      : html`<div class="card">${inner}</div>`;
  }
}

if (!customElements.get("hamie-system-card")) {
  customElements.define("hamie-system-card", HamieSystemCard);
}
