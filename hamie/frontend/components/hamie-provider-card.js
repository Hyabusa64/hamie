/**
 * <hamie-provider-card> — no Figma source (real HAMIE connectors/Ollama,
 * n8n, MCP, HKG/have no Figma screen at all — see the design audit's
 * compatibility-concerns section). A legitimate, documented extension of
 * the reconstructed system for HAMIE-specific functionality, built from
 * the same tokens/hamie-card/hamie-status/hamie-button primitives as
 * everything else so it reads as part of one design language.
 *
 * Props are the real wire shape from ConnectorHealth.public_dict()
 * (connectors/base.py): connector_id, enabled, status (disabled/unknown/
 * healthy/degraded/error), capability_mode, last_tested, latency_ms,
 * error_code. Nothing here is invented.
 *
 * Production defect fixed here: error_code (a real but bare backend
 * value -- e.g. "TimeoutError", "unreachable", "model_discovery_failed",
 * see connectors/manager.py's ConnectorManager._run()) used to be shown
 * verbatim on the card. Translated via the same humanizeCode() map
 * errors.js uses for every other real failure code in the app, with a
 * "Retry" action (re-runs the real Test) and a "View Details" disclosure
 * that reveals the raw code only when the user asks for it -- not on the
 * card face by default.
 */
import { LitElement, css, html } from "lit";

import { humanizeCode } from "../errors.js";
import { iconBadgeStyles } from "./shared-styles.js";
import "./hamie-card.js";
import "./hamie-status.js";
import "./hamie-button.js";

// ConnectorStatus (backend) -> hamie-status token
const STATUS_MAP = {
  healthy: "healthy",
  degraded: "warning",
  error: "critical",
  disabled: "offline",
  unknown: "unknown",
};

export class HamieProviderCard extends LitElement {
  static properties = {
    connectorId: { type: String },
    displayName: { type: String },
    icon: { type: String },
    enabled: { type: Boolean },
    status: { type: String }, // ConnectorStatus value
    errorCode: { type: String },
    capabilityMode: { type: String },
    lastTested: { type: String },
    latencyMs: { type: Number },
    consecutiveFailures: { type: Number },
    _detailsOpen: { state: true },
  };

  static styles = [
    iconBadgeStyles,
    css`
    :host {
      display: block;
    }
    .row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .identity {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2-5);
      min-width: 0;
    }
    .icon-badge {
      flex-shrink: 0;
    }
    .name {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .mode {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .meta {
      margin-top: var(--hamie-space-3);
      display: flex;
      flex-wrap: wrap;
      gap: var(--hamie-space-1) var(--hamie-space-4);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .meta strong {
      color: var(--hamie-text-primary);
      font-weight: var(--hamie-weight-medium);
      font-family: var(--hamie-font-code);
    }
    .error {
      margin-top: var(--hamie-space-2);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-status-critical);
    }
    .error-details {
      margin-top: var(--hamie-space-1);
      font-size: var(--hamie-text-micro);
      font-family: var(--hamie-font-code);
      color: var(--hamie-text-secondary);
    }
    .actions {
      display: flex;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-3);
    }
  `,
  ];

  _onTest() {
    this.dispatchEvent(
      new CustomEvent("hamie-provider-test", {
        detail: { connectorId: this.connectorId },
        bubbles: true,
        composed: true,
      }),
    );
  }

  _onConfigure() {
    this.dispatchEvent(
      new CustomEvent("hamie-provider-configure", {
        detail: { connectorId: this.connectorId },
        bubbles: true,
        composed: true,
      }),
    );
  }

  render() {
    const status = this.enabled ? this.status || "unknown" : "disabled";
    return html`
      <hamie-card padding="md">
        <div class="row">
          <div class="identity">
            <div class="icon-badge">
              <ha-icon icon=${this.icon || "mdi:puzzle-outline"}></ha-icon>
            </div>
            <div>
              <p class="name">${this.displayName || this.connectorId}</p>
              ${this.capabilityMode ? html`<p class="mode">${this.capabilityMode}</p>` : null}
            </div>
          </div>
          <hamie-status status=${STATUS_MAP[status] || "unknown"} label=${this._label(status)}></hamie-status>
        </div>

        <div class="meta">
          <span>Last checked: <strong>${this.lastTested || (this.enabled ? "Checking…" : "—")}</strong></span>
          ${this.latencyMs != null ? html`<span>Latency: <strong>${this.latencyMs} ms</strong></span>` : null}
          ${this.consecutiveFailures > 0
            ? html`<span>${this.consecutiveFailures} consecutive failure${this.consecutiveFailures === 1 ? "" : "s"}</span>`
            : null}
        </div>

        ${this.errorCode
          ? html`
              <div class="error">
                <span>${humanizeCode(this.errorCode, "That connector could not complete its last operation.")}</span>
                <hamie-button variant="ghost" size="xs" @click=${() => (this._detailsOpen = !this._detailsOpen)}>
                  ${this._detailsOpen ? "Hide details" : "View Details"}
                </hamie-button>
              </div>
              ${this._detailsOpen ? html`<p class="error-details">Technical: ${this.errorCode}</p>` : null}
            `
          : null}

        <div class="actions">
          <hamie-button variant="secondary" size="xs" ?disabled=${!this.enabled} @click=${this._onTest}>
            <ha-icon icon="mdi:lan-connect"></ha-icon> ${this.errorCode ? "Retry" : "Test"}
          </hamie-button>
          <hamie-button variant="ghost" size="xs" @click=${this._onConfigure}>
            <ha-icon icon="mdi:cog-outline"></ha-icon> Configure
          </hamie-button>
        </div>
      </hamie-card>
    `;
  }

  _label(status) {
    if (status === "disabled") return "Disabled";
    if (status === "unknown") return "Checking…";
    if (status === "degraded") return "Degraded";
    if (status === "error") return "Offline";
    return undefined; // let <hamie-status> use its own default label
  }
}

if (!customElements.get("hamie-provider-card")) {
  customElements.define("hamie-provider-card", HamieProviderCard);
}
