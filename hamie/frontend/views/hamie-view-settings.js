/**
 * <hamie-view-settings> — no Figma source (Settings is a real HAMIE-only
 * capability the design audit identified with no corresponding screen
 * in the extracted project). A legitimate, documented extension of the
 * reconstructed design system.
 *
 * Scope decision, made explicitly rather than guessed: `hamie/configuration
 * /get` (requires `schema_version`, verified against presentation/api.py)
 * returns a fully self-describing schema for every section --
 * configuration.py's FieldSpec.public() already includes each field's
 * real label/kind/choices/description, and `sanitized_section()` already
 * redacts secret values server-side (never sending them at all, just an
 * empty string). This view is therefore a genuinely generic, real,
 * schema-driven READ-ONLY renderer -- it needs zero per-section
 * hardcoded field lists (the exact fragility behind every bug found and
 * fixed elsewhere this pass), and never fabricates a value or a
 * `_configured` flag name for secrets it can't see.
 *
 * Real editing is deliberately NOT reimplemented here. HAMIE's native
 * Home Assistant Options Flow (config_flow.py) already implements full
 * per-section validation, credential actions, and secret handling
 * correctly and is exhaustively tested; rebuilding that entire system a
 * second time in Lit would not be "wiring real data" so much as building
 * a whole new subsystem with its own risk of exactly the kind of
 * frontend/backend contract mismatch already found and fixed multiple
 * times this pass (House Health, Findings, Dependencies, Intelligence).
 * Instead, "Edit in Home Assistant" navigates to the real native options
 * page via `hamie/configuration/context`'s `fallback_path` -- the same
 * real field and navigation pattern already used by the Connectors
 * screen's "Configure" button.
 *
 * Only sections with real field specs (configuration.py SECTION_FIELDS:
 * general, provenance, findings, grouping, ollama, n8n, mcp, hkg,
 * safety, audit) are
 * rendered here. `suppression`, `connector_status`, and
 * `test_connections` are real PANEL_SECTIONS entries but have no field
 * specs at all (confirmed: not keys in SECTION_FIELDS) -- they are pure
 * UI groupings in the legacy panel, not simple field-driven sections.
 * `connector_status` is already its own real screen (Connectors);
 * suppression-rule browsing/management and a dedicated test-connections
 * panel are real gaps, honestly left for future work rather than
 * fabricated here.
 *
 * The one exception to "real editing is not reimplemented here" is the
 * Ollama/AI provider section (capability-matrix #34): the audit found
 * native Options Flow has zero equivalent for it (no connection-method
 * selector, no live AI Task entity picker, no Ollama model discovery or
 * search) -- deferring there for this one section specifically would be
 * a real regression, not parity. Its "Edit" button expands
 * <hamie-ai-provider-editor> inline in place of the read-only field
 * list, using the same real backend APIs (see that component's own
 * docstring for the full architectural reasoning); the other 11
 * sections are untouched and still defer to native Options Flow.
 */
import { LitElement, css, html } from "lit";

import { friendlyError } from "../errors.js";
import { relativeTime } from "../format.js";
import "../components/hamie-page-header.js";
import "../components/hamie-card.js";
import "../components/hamie-section.js";
import "../components/hamie-button.js";
import "../components/hamie-status.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";
import "./hamie-ai-provider-editor.js";

const SECTION_LABELS = {
  general: "General",
  provenance: "Source & Deployment",
  findings: "Findings",
  grouping: "Grouping",
  ollama: "Ollama",
  n8n: "n8n",
  mcp: "MCP",
  hkg: "HKG",
  safety: "Safety",
  audit: "Audit",
  ai_control: "AI Control",
};

function formatValue(field, value) {
  if (field.secret) return null; // rendered separately as a redacted badge
  if (value === null || value === undefined || value === "") return "—";
  if (field.kind === "boolean") return value ? "Enabled" : "Disabled";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export class HamieViewSettings extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _scheduler: { state: true },
    _error: { state: true },
    _editingOllama: { state: true },
  };

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .sections {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
    }
    .field-row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-4);
      padding: var(--hamie-space-2) 0;
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .field-row:last-child {
      border-bottom: none;
    }
    .field-label {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      flex-shrink: 0;
      width: 40%;
    }
    .field-description {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      font-weight: var(--hamie-weight-normal);
    }
    .field-value {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      font-family: var(--hamie-font-code);
      text-align: right;
      word-break: break-word;
    }
  `;

  connectedCallback() {
    super.connectedCallback();
    this._load();
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
      const [config, context, scheduler] = await Promise.all([
        this.hass.callWS({ type: "hamie/configuration/get", schema_version: 2 }),
        this.hass.callWS({ type: "hamie/configuration/context" }),
        this.hass.callWS({ type: "hamie/scheduler/status" }).catch(() => null),
      ]);
      this._config = config;
      this._fallbackPath = context.fallback_path;
      this._scheduler = scheduler;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Settings are temporarily unavailable.");
    }
  }

  _renderScheduler() {
    const scheduler = this._scheduler;
    if (!scheduler) return null;
    const nextScanText =
      scheduler.next_scan_seconds == null
        ? "—"
        : scheduler.next_scan_seconds <= 0
          ? "Due now"
          : `${Math.max(1, Math.round(scheduler.next_scan_seconds / 60))} minutes`;
    return html`
      <hamie-card padding="md">
        <hamie-section heading="Scanning &amp; connector health"></hamie-section>
        <div class="field-row">
          <div class="field-label">Automatic scanning</div>
          <hamie-status
            status=${scheduler.auto_scan_enabled ? "healthy" : "offline"}
            label=${scheduler.auto_scan_enabled ? "On" : "Off"}
          ></hamie-status>
        </div>
        <div class="field-row">
          <div class="field-label">Interval</div>
          <span class="field-value">Every ${scheduler.auto_scan_interval_minutes} minutes</span>
        </div>
        <div class="field-row">
          <div class="field-label">Last automatic scan</div>
          <span class="field-value">${scheduler.last_scan ? relativeTime(scheduler.last_scan) : "Never"}</span>
        </div>
        ${scheduler.auto_scan_enabled
          ? html`
              <div class="field-row">
                <div class="field-label">Next scan</div>
                <span class="field-value">${nextScanText}</span>
              </div>
            `
          : null}
        ${scheduler.last_scan_error_summary
          ? html`
              <div class="field-row">
                <div class="field-label">Last scan failure</div>
                <span class="field-value">${scheduler.last_scan_error_summary}</span>
              </div>
            `
          : null}
        <div class="field-row">
          <div class="field-label">Connector heartbeat interval</div>
          <span class="field-value">Every ${scheduler.connector_heartbeat_interval_seconds} seconds</span>
        </div>
      </hamie-card>
    `;
  }

  _onEdit() {
    if (!this._fallbackPath) return;
    history.pushState(null, "", this._fallbackPath);
    window.dispatchEvent(new CustomEvent("location-changed"));
  }

  async _onOllamaSaved() {
    this._editingOllama = false;
    await this._load();
  }

  render() {
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="Settings are unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._config) {
      return html`<hamie-loading .lines=${6}></hamie-loading>`;
    }

    const sections = Object.entries(this._config.sections || {}).filter(
      ([, section]) => section.fields && section.fields.length > 0,
    );

    return html`
      <hamie-page-header heading="Settings" subtitle="Current configuration (revision ${this._config.revision})">
        <div slot="actions">
          <hamie-button variant="primary" size="sm" @click=${this._onEdit}>
            <ha-icon icon="mdi:open-in-new"></ha-icon> Edit in Home Assistant
          </hamie-button>
        </div>
      </hamie-page-header>

      <div class="sections">
        ${this._renderScheduler()}
        ${sections.map(([sectionId, section]) =>
          sectionId === "ollama"
            ? html`
                <hamie-card padding="md">
                  <hamie-section heading="${SECTION_LABELS.ollama}">
                    ${this._editingOllama
                      ? null
                      : html`<hamie-button slot="action" variant="secondary" size="sm" @click=${() => (this._editingOllama = true)}>Edit</hamie-button>`}
                  </hamie-section>
                  ${this._editingOllama
                    ? html`
                        <hamie-ai-provider-editor
                          .hass=${this.hass}
                          @hamie-ai-provider-saved=${this._onOllamaSaved}
                          @hamie-ai-provider-cancelled=${() => (this._editingOllama = false)}
                        ></hamie-ai-provider-editor>
                      `
                    : section.fields.map((field) => {
                        const value = section.values?.[field.key];
                        return html`
                          <div class="field-row">
                            <div class="field-label">
                              ${field.label}
                              ${field.description ? html`<p class="field-description">${field.description}</p>` : null}
                            </div>
                            ${field.secret
                              ? html`<hamie-status status="unknown" label="Hidden for security"></hamie-status>`
                              : html`<span class="field-value">${formatValue(field, value)}</span>`}
                          </div>
                        `;
                      })}
                </hamie-card>
              `
            : html`
                <hamie-card padding="md">
                  <hamie-section heading="${SECTION_LABELS[sectionId] || sectionId}"></hamie-section>
                  ${section.fields.map((field) => {
                    const value = section.values?.[field.key];
                    return html`
                      <div class="field-row">
                        <div class="field-label">
                          ${field.label}
                          ${field.description ? html`<p class="field-description">${field.description}</p>` : null}
                        </div>
                        ${field.secret
                          ? html`<hamie-status status="unknown" label="Hidden for security"></hamie-status>`
                          : html`<span class="field-value">${formatValue(field, value)}</span>`}
                      </div>
                    `;
                  })}
                </hamie-card>
              `,
        )}
      </div>
    `;
  }
}

if (!customElements.get("hamie-view-settings")) {
  customElements.define("hamie-view-settings", HamieViewSettings);
}
