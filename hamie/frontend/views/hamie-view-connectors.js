/**
 * <hamie-view-connectors> — no Figma source (Connectors is a real
 * HAMIE-only capability the design audit identified with no
 * corresponding screen in the extracted project). A legitimate,
 * documented extension of the reconstructed design system, composed
 * entirely from <hamie-provider-card> (already built in the component
 * library, grounded in ConnectorHealth.public_dict(), but never wired
 * into a screen until now).
 *
 * Data: `hamie/connectors/status` -> ConnectorManager.public_status()
 * (connectors/manager.py), which always returns all 4 real connector
 * ids (ollama/n8n/mcp/hkg -- confirmed as a closed set via the
 * `hamie/connectors/test` schema's `vol.In`), each with its real
 * `enabled` flag -- never a fabricated fixed list, the backend always
 * reports on the true full set regardless of what's currently enabled.
 * Display names/icons below are just cosmetic labels for these 4 fixed,
 * real, closed-set ids, not invented data.
 *
 * Actions:
 * - "Test": the real `hamie/connectors/test` command (requires
 *   `connector_id` in the same closed set). Testing a disabled
 *   connector raises a plain ValueError ("connector is disabled") at
 *   the manager level -- caught and shown as an honest message rather
 *   than a raw exception name.
 * - "Configure": production-usability fix -- this previously navigated
 *   away to HAMIE's native Home Assistant integration options page and
 *   never brought the user back, effectively a decorative control (the
 *   defect explicitly named "Configure buttons do not complete a useful
 *   workflow"). It now opens a real inline editor in a dialog: Ollama
 *   gets the same <hamie-ai-provider-editor> Settings already uses
 *   (live model discovery, connection-method switch); n8n/MCP/HKG get
 *   the generic schema-driven <hamie-connector-editor>. Saving or
 *   cancelling closes the dialog and refreshes this screen's real
 *   connector status -- the user never leaves Connectors.
 * - "Copy inbound endpoint" (n8n only, capability-matrix #25): the real,
 *   fixed inbound webhook path (configuration.py's INBOUND_ENDPOINT,
 *   "/api/hamie/n8n") copied to the clipboard -- matches the legacy
 *   panel's identical n8n-only action.
 */
import { LitElement, css, html } from "lit";

import { relativeTime } from "../format.js";
import { friendlyError } from "../errors.js";
import "../components/hamie-page-header.js";
import "../components/hamie-card.js";
import "../components/hamie-provider-card.js";
import "../components/hamie-button.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";
import "../components/hamie-dialog.js";
import "./hamie-ai-provider-editor.js";
import "./hamie-connector-editor.js";

const CONNECTOR_META = {
  ollama: { displayName: "Ollama", icon: "mdi:server-outline" },
  n8n: { displayName: "n8n", icon: "mdi:sitemap-outline" },
  mcp: { displayName: "MCP", icon: "mdi:api" },
  hkg: { displayName: "HKG", icon: "mdi:graph-outline" },
};

export class HamieViewConnectors extends LitElement {
  static properties = {
    hass: { attribute: false },
    _connectors: { state: true },
    _error: { state: true },
    _actionError: { state: true },
    _testingId: { state: true },
    _copiedEndpoint: { state: true },
    _configuringId: { state: true },
  };

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
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
    .grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: var(--hamie-space-3);
    }
    .grid hamie-button {
      margin-top: var(--hamie-space-2);
    }
    @media (max-width: 870px) {
      .grid {
        grid-template-columns: 1fr;
      }
    }
    /* A disabled connector is not a problem needing attention -- it must
     * never compete visually with an active, possibly-degraded one. */
    .connector-tile[data-disabled] {
      opacity: 0.55;
    }
    hamie-dialog {
      --mdc-dialog-min-width: min(560px, 90vw);
    }
  `;

  connectedCallback() {
    super.connectedCallback();
    this._load();
    // Live-update channel (see hamie-app.js's _subscribeLiveUpdates) --
    // connector heartbeat updates this page without a manual refresh or
    // pressing Test.
    this._onLiveUpdate = () => this._load();
    window.addEventListener("hamie-live-update", this._onLiveUpdate);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("hamie-live-update", this._onLiveUpdate);
  }

  async _load() {
    if (!this.hass) return;
    try {
      this._connectors = await this.hass.callWS({ type: "hamie/connectors/status" });
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Connector data is temporarily unavailable.");
    }
  }

  async _onTest(event) {
    if (!this.hass) return;
    const connectorId = event.detail.connectorId;
    this._actionError = null;
    this._testingId = connectorId;
    try {
      const result = await this.hass.callWS({ type: "hamie/connectors/test", connector_id: connectorId });
      this._connectors = this._connectors.map((item) => (item.connector_id === connectorId ? result : item));
    } catch (err) {
      this._actionError = friendlyError(err, `Testing ${connectorId} failed.`);
    } finally {
      this._testingId = null;
    }
  }

  _onConfigure(event) {
    this._configuringId = event.detail.connectorId;
  }

  async _onConfigureDone() {
    this._configuringId = null;
    await this._load();
  }

  async _onCopyN8nEndpoint() {
    this._actionError = null;
    try {
      // Real, fixed routing constant (configuration.py INBOUND_ENDPOINT)
      // -- the legacy panel copies this same literal directly too, it
      // isn't fetched from any API since it never changes.
      await navigator.clipboard.writeText("/api/hamie/n8n");
      this._copiedEndpoint = true;
      setTimeout(() => {
        this._copiedEndpoint = false;
      }, 2000);
    } catch {
      this._actionError = "Copy is unavailable. The inbound endpoint is /api/hamie/n8n.";
    }
  }

  render() {
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="Connectors are unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._connectors) {
      return html`<hamie-loading .lines=${4}></hamie-loading>`;
    }

    const enabledCount = this._connectors.filter((item) => item.enabled).length;

    return html`
      <hamie-page-header heading="Connectors" subtitle="${enabledCount} of ${this._connectors.length} connectors enabled"></hamie-page-header>

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

      <div class="grid">
        ${this._connectors.map((item) => {
          const meta = CONNECTOR_META[item.connector_id] || { displayName: item.connector_id, icon: "mdi:puzzle-outline" };
          return html`
            <div class="connector-tile" ?data-disabled=${!item.enabled}>
              <hamie-provider-card
                .connectorId=${item.connector_id}
                .displayName=${meta.displayName}
                .icon=${meta.icon}
                .enabled=${item.enabled}
                .status=${this._testingId === item.connector_id ? "unknown" : item.status}
                .capabilityMode=${item.capability_mode}
                .lastTested=${item.last_tested ? relativeTime(item.last_tested) : null}
                .latencyMs=${item.latency_ms}
                .consecutiveFailures=${item.consecutive_failures}
                .errorCode=${item.error_code}
                @hamie-provider-test=${this._onTest}
                @hamie-provider-configure=${this._onConfigure}
              ></hamie-provider-card>
              ${item.connector_id === "n8n"
                ? html`
                    <hamie-button variant="ghost" size="xs" @click=${this._onCopyN8nEndpoint}>
                      <ha-icon icon="mdi:content-copy"></ha-icon>
                      ${this._copiedEndpoint ? "Copied!" : "Copy inbound endpoint"}
                    </hamie-button>
                  `
                : null}
            </div>
          `;
        })}
      </div>

      ${this._configuringId
        ? html`
            <hamie-dialog
              open
              heading="Configure ${CONNECTOR_META[this._configuringId]?.displayName || this._configuringId}"
              @hamie-dialog-closed=${this._onConfigureDone}
            >
              ${this._configuringId === "ollama"
                ? html`<hamie-ai-provider-editor .hass=${this.hass} @hamie-ai-provider-saved=${this._onConfigureDone} @hamie-ai-provider-cancelled=${this._onConfigureDone}></hamie-ai-provider-editor>`
                : html`<hamie-connector-editor .hass=${this.hass} connector-id=${this._configuringId} @hamie-connector-saved=${this._onConfigureDone} @hamie-connector-cancelled=${this._onConfigureDone}></hamie-connector-editor>`}
            </hamie-dialog>
          `
        : null}
    `;
  }
}

if (!customElements.get("hamie-view-connectors")) {
  customElements.define("hamie-view-connectors", HamieViewConnectors);
}
