/**
 * <hamie-connector-editor> — real inline editable form for n8n/MCP/HKG,
 * the generic counterpart to <hamie-ai-provider-editor> (which is
 * Ollama-specific because Ollama alone needs live model discovery/search
 * and a connection-method switch). Built for the production-usability
 * pass: Connectors' "Configure" button previously navigated away to
 * native Home Assistant Options Flow for every connector, leaving UI 3.0
 * and never returning the user anywhere -- effectively a decorative
 * control, not a completed workflow. This component lets Configure open
 * a real editor in place (a dialog on the Connectors screen) that saves
 * and returns the user to exactly where they started.
 *
 * Deliberately generic/config-driven off `hamie/configuration/get`'s
 * real field specs (configuration.py SECTION_FIELDS) rather than a
 * second bespoke UI per connector -- n8n/MCP/HKG have no live-discovery
 * or connection-method-switch requirements the way Ollama does, so a
 * schema-driven Basic/Advanced split (using the same real
 * hamie/configuration/test + hamie/configuration/save calls
 * hamie-ai-provider-editor.js already uses) is a complete, honest
 * implementation, not a placeholder.
 *
 * Security header (Enabled -> local-network-host approval) production
 * defect fix: every connector already had its own real
 * `{section}_approve_host` field (configuration.py), but this component
 * previously only ever rendered it once a `host_not_allowed` error from
 * a failed Test Connection/Save was already present -- so a user
 * enabling a connector at a private-network address (the overwhelmingly
 * common real case) had no way to see or set the control that made the
 * connection work until *after* deliberately failing a test first. It
 * is now always rendered directly below Enabled -- see
 * connector-security.js for the shared auto-enable-on-first-transition
 * rule this editor and hamie-ai-provider-editor.js both use, so this
 * one deterministic behavior is defined exactly once.
 */
import { LitElement, css, html } from "lit";

import { friendlyError, humanizeCode } from "../errors.js";
import { applyEnabledTransition } from "../connector-security.js";
import { idempotencyToken } from "../idempotency.js";
import "../components/hamie-input.js";
import "../components/hamie-select.js";
import "../components/hamie-switch.js";
import "../components/hamie-button.js";

const CONNECTOR_LABELS = { n8n: "n8n", mcp: "MCP", hkg: "HKG" };

// Everything else the user needs to decide up front, per connector,
// *after* the universal Enabled/local-host-approval header this
// component now always renders first. Credential-removal confirmations,
// timeouts, TLS verification, retry/backoff, payload limits, n8n's
// inbound-command wiring, and remote-host approval move under Advanced.
const BASIC_FIELD_KEYS = {
  n8n: ["n8n_base_url", "n8n_outbound_webhook_url", "n8n_authentication_type", "n8n_username", "n8n_outbound_credential"],
  mcp: ["mcp_endpoint", "mcp_authentication_type", "mcp_credential"],
  hkg: ["hkg_endpoint", "hkg_authentication_type", "hkg_credential"],
};

// n8n's Basic fields are further grouped under two real, distinct
// concepts a user reported confusing: the base service connection HAMIE
// uses to reach n8n at all, versus the *optional* webhook HAMIE sends
// commands/events to. Neither is "n8n" as a whole being reachable or
// not -- see N8nConnector.async_test's own health/webhook-readiness
// split this mirrors.
const N8N_CONNECTION_KEYS = ["n8n_base_url"];
const N8N_OUTBOUND_KEYS = ["n8n_outbound_webhook_url", "n8n_authentication_type", "n8n_username", "n8n_outbound_credential"];

function isBasicFieldVisible(connectorId, key, draft) {
  if (key === "n8n_username") return draft.n8n_authentication_type === "username_and_password";
  if (key === "n8n_outbound_credential") return draft.n8n_authentication_type !== "none";
  if (key === "mcp_credential") return draft.mcp_authentication_type !== "none";
  if (key === "hkg_credential") return draft.hkg_authentication_type !== "none";
  return true;
}

export class HamieConnectorEditor extends LitElement {
  static properties = {
    hass: { attribute: false },
    connectorId: { type: String, attribute: "connector-id" },
    _config: { state: true },
    _draft: { state: true },
    _errors: { state: true },
    _dirty: { state: true },
    _advancedOpen: { state: true },
    _result: { state: true },
    _saving: { state: true },
    _testing: { state: true },
    _error: { state: true },
  };

  static styles = css`
    :host {
      display: block;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      padding-bottom: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-3);
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .dirty-flag {
      margin-left: auto;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .credential-note {
      margin: 0 0 var(--hamie-space-3);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .fields {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-1);
    }
    .field.boolean {
      flex-direction: row;
      align-items: center;
      justify-content: space-between;
    }
    label {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .description {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .field-error {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-status-critical);
    }
    .disclosure {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1);
      background: none;
      border: none;
      cursor: pointer;
      color: var(--hamie-accent);
      font-size: var(--hamie-text-small);
      padding: var(--hamie-space-2) 0;
      margin: var(--hamie-space-3) 0 0;
    }
    .advanced {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
      padding-top: var(--hamie-space-2);
      border-top: 1px solid var(--hamie-border-hairline);
    }
    .result {
      margin: 0 0 var(--hamie-space-3);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      font-size: var(--hamie-text-small);
    }
    .result.ok {
      background: var(--hamie-status-positive-fill);
      color: var(--hamie-status-positive);
    }
    .result.fail {
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
    }
    .group-heading {
      margin: var(--hamie-space-2) 0 0;
      font-size: var(--hamie-text-caption);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-text-secondary);
    }
    .group-help {
      margin: 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .inbound-endpoint {
      font-family: var(--hamie-font-code);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      word-break: break-all;
    }
  `;

  constructor() {
    super();
    this._advancedOpen = false;
    this._errors = {};
    // Reset per editing session (see _resetDraft) -- tracks whether the
    // user has explicitly touched the local-host approval toggle
    // themselves, so a later Enabled off->on transition never silently
    // overrides a choice they already made this session.
    this._approveHostManuallyChanged = false;
  }

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  async _load() {
    if (!this.hass || !this.connectorId) return;
    try {
      this._config = await this.hass.callWS({ type: "hamie/configuration/get", schema_version: 2 });
      this._resetDraft();
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, `${CONNECTOR_LABELS[this.connectorId]} settings are temporarily unavailable.`);
    }
  }

  _section() {
    return this._config?.sections?.[this.connectorId];
  }

  _resetDraft() {
    const section = this._section();
    const values = structuredClone(section?.values || {});
    for (const field of section?.fields || []) {
      if (field.secret) values[field.key] = "";
    }
    this._draft = values;
    this._errors = {};
    this._dirty = false;
    this._result = undefined;
    this._approveHostManuallyChanged = false;
  }

  _fieldsByKey() {
    return Object.fromEntries((this._section()?.fields || []).map((field) => [field.key, field]));
  }

  _onFieldChange(key, value) {
    const enabledKey = `${this.connectorId}_enabled`;
    const approveHostKey = `${this.connectorId}_approve_host`;
    if (key === approveHostKey) {
      this._approveHostManuallyChanged = true;
    }
    this._draft =
      key === enabledKey
        ? applyEnabledTransition({
            draft: this._draft,
            enabledKey,
            approveHostKey,
            nextEnabled: value,
            approveHostManuallyChanged: this._approveHostManuallyChanged,
          })
        : { ...this._draft, [key]: value };
    this._dirty = true;
    if (this._errors[key]) {
      const errors = { ...this._errors };
      delete errors[key];
      this._errors = errors;
    }
    this._result = undefined;
  }

  _buildSaveValues() {
    const section = this._section();
    const values = {};
    for (const field of section.fields || []) {
      const hasDraft = Object.prototype.hasOwnProperty.call(this._draft, field.key);
      values[field.key] = field.locked
        ? section.values[field.key] ?? field.default
        : structuredClone(hasDraft ? this._draft[field.key] : field.default);
    }
    // Auto-manage credential actions the moment a real value is entered --
    // the average user should never have to separately tell HAMIE to
    // "replace" a credential they just typed.
    for (const [credentialKey, actionKey] of [
      ["n8n_outbound_credential", "n8n_outbound_credential_action"],
      ["n8n_inbound_credential", "n8n_inbound_credential_action"],
      ["mcp_credential", "mcp_credential_action"],
      ["hkg_credential", "hkg_credential_action"],
    ]) {
      if (values[credentialKey] && values[actionKey] === "keep") values[actionKey] = "replace";
    }
    return values;
  }

  async _onSave() {
    this._saving = true;
    try {
      const result = await this.hass.callWS({
        type: "hamie/configuration/save",
        schema_version: 2,
        section: this.connectorId,
        values: this._buildSaveValues(),
        expected_revision: this._config.revision,
        idempotency_token: idempotencyToken(),
      });
      if (result.ok === false) {
        this._applyFailure(result);
        return;
      }
      this._config = { ...this._config, revision: result.revision };
      if (result.section_state) {
        this._config = {
          ...this._config,
          sections: { ...this._config.sections, [this.connectorId]: result.section_state },
        };
      }
      this._resetDraft();
      this._result = { ok: true, message: result.saved ? "Settings saved." : "No settings changed." };
      this.dispatchEvent(new CustomEvent("hamie-connector-saved", { bubbles: true, composed: true }));
    } catch (err) {
      this._applyFailure({ error_code: err?.code });
    } finally {
      this._saving = false;
    }
  }

  _onCancel() {
    this.dispatchEvent(new CustomEvent("hamie-connector-cancelled", { bubbles: true, composed: true }));
  }

  async _onTest() {
    this._testing = true;
    try {
      const result = await this.hass.callWS({
        type: "hamie/configuration/test",
        schema_version: 2,
        connector_id: this.connectorId,
        values: this._buildSaveValues(),
      });
      if (result.ok === false || result.connected === false) {
        this._applyFailure(result, result.error_code || "unreachable");
        return;
      }
      this._result = { ok: true, message: this._testSuccessMessage(result) };
    } catch (err) {
      this._applyFailure({ error_code: err?.code }, err?.code || "unreachable");
    } finally {
      this._testing = false;
    }
  }

  _applyFailure(result, fallbackCode = "configuration_failed") {
    this._errors = structuredClone(result?.field_errors || {});
    if (Object.keys(this._errors).length) this._advancedOpen = true;
    this._result = { ok: false, message: result?.message || humanizeCode(result?.error_code || fallbackCode, "That could not be completed.") };
  }

  /**
   * n8n's Test Connection never fails just because the outbound webhook
   * is blank or not yet confirmed -- base service health and webhook
   * readiness are reported as two independent facts (connectors/n8n.py
   * N8nConnector.async_test), so a bare "Connection test succeeded"
   * would hide real, actionable information behind a falsely-complete
   * success message. Reported as concise, structured status sentences
   * ("Service reachable. Outbound webhook not configured.") rather than
   * the previous repetitive "n8n is reachable. n8n is reachable, but
   * ..." phrasing.
   */
  _testSuccessMessage(result) {
    if (this.connectorId !== "n8n") return "Connection test succeeded without saving.";
    const details = result?.result?.details;
    const readiness = details?.webhook_readiness;
    if (!readiness || readiness === "readiness_confirmed") {
      return "Service reachable. Outbound webhook ready.";
    }
    if (readiness === "not_configured") {
      return "Service reachable. Outbound webhook not configured.";
    }
    return `Service reachable. ${humanizeCode(details.webhook_error_code, "Outbound webhook readiness could not be confirmed.")}`;
  }

  _renderField(key) {
    const field = this._fieldsByKey()[key];
    if (!field) return null;
    const value = this._draft[key] ?? field.default ?? "";
    const error = this._errors[key] ? humanizeCode(this._errors[key], this._errors[key]) : "";
    let control;
    if (field.kind === "boolean") {
      control = html`<hamie-switch ?checked=${Boolean(value)} ?disabled=${field.locked} @hamie-change=${(e) => this._onFieldChange(key, e.detail.checked)}></hamie-switch>`;
    } else if (field.kind === "select") {
      const options = (field.choices || []).map((choice) => ({ value: choice, label: String(choice).replaceAll("_", " ") }));
      control = html`<hamie-select .value=${value} .options=${options} ?disabled=${field.locked} @hamie-change=${(e) => this._onFieldChange(key, e.detail.value)}></hamie-select>`;
    } else if (field.kind === "multiselect" || field.kind === "json" || field.kind === "csv") {
      // Rare, advanced-only, non-Basic fields (n8n's selected-events list,
      // user-defined grouping rules elsewhere) -- shown as read/edit text
      // rather than a bespoke picker, since they never appear in Basic.
      const text = Array.isArray(value) ? value.join(", ") : String(value ?? "");
      control = html`<hamie-input .value=${text} ?disabled=${field.locked} @hamie-input=${(e) => this._onFieldChange(key, field.kind === "multiselect" ? e.detail.value.split(",").map((v) => v.trim()).filter(Boolean) : e.detail.value)}></hamie-input>`;
    } else {
      control = html`<hamie-input
        .value=${String(value)}
        type=${field.secret ? "password" : field.kind === "url" ? "url" : "text"}
        ?disabled=${field.locked}
        @hamie-input=${(e) => {
          const raw = e.detail.value;
          const numeric = ["integer", "number"].includes(field.kind) && raw !== "" ? Number(raw) : raw;
          this._onFieldChange(key, numeric);
        }}
      ></hamie-input>`;
    }
    return html`
      <div class="field ${field.kind === "boolean" ? "boolean" : ""}">
        <label>${field.label}${field.locked ? " (fixed)" : ""}</label>
        ${control}
        ${field.description ? html`<span class="description">${field.description}</span>` : null}
        ${error ? html`<span class="field-error">${error}</span>` : null}
      </div>
    `;
  }

  render() {
    if (this._error) {
      return html`<p class="field-error">${this._error}</p>`;
    }
    if (!this._config || !this._draft) {
      return html`<p class="description">Loading…</p>`;
    }

    const section = this._section();
    const enabledKey = `${this.connectorId}_enabled`;
    const approveHostKey = `${this.connectorId}_approve_host`;
    const approveRemoteHostKey = `${this.connectorId}_approve_remote_host`;
    const allKeys = (section.fields || []).map((f) => f.key).filter((key) => !key.endsWith("_allowed_hosts"));
    const basicKeys = (BASIC_FIELD_KEYS[this.connectorId] || []).filter(
      (key) => allKeys.includes(key) && isBasicFieldVisible(this.connectorId, key, this._draft),
    );
    const advancedKeys = allKeys.filter(
      (key) =>
        key !== enabledKey &&
        key !== approveHostKey &&
        key !== approveRemoteHostKey &&
        !basicKeys.includes(key),
    );

    // The universal security header -- identical order and behavior for
    // every connector, always visible, never gated on a test/save error
    // or on which host kind the currently-entered address happens to be.
    const securityHeader = html`
      ${this._renderField(enabledKey)}
      ${this._renderField(approveHostKey)}
    `;

    return html`
      <div class="actions">
        <hamie-button variant="primary" size="sm" ?disabled=${this._saving} @click=${this._onSave}>
          ${this._saving ? "Saving…" : "Save"}
        </hamie-button>
        <hamie-button variant="secondary" size="sm" @click=${this._onCancel}>Cancel</hamie-button>
        <hamie-button variant="secondary" size="sm" ?disabled=${this._testing} @click=${this._onTest}>
          <ha-icon icon="mdi:lan-connect"></ha-icon> ${this._testing ? "Testing…" : "Test Connection"}
        </hamie-button>
        <span class="dirty-flag">${this._dirty ? "Unsaved changes" : "Saved"}</span>
      </div>

      ${this._result ? html`<div class="result ${this._result.ok ? "ok" : "fail"}">${this._result.message}</div>` : null}

      <div class="fields">
        ${securityHeader}
        ${this.connectorId === "n8n" ? this._renderN8nBody(basicKeys) : basicKeys.map((key) => this._renderField(key))}
      </div>

      <button class="disclosure" type="button" aria-expanded=${this._advancedOpen} @click=${() => (this._advancedOpen = !this._advancedOpen)}>
        <ha-icon icon="mdi:chevron-${this._advancedOpen ? "up" : "down"}"></ha-icon>
        ${this._advancedOpen ? "Hide" : "Show"} Advanced Options
      </button>
      ${this._advancedOpen
        ? html`
            <div class="advanced">
              ${this.connectorId === "n8n" ? this._renderN8nAdvanced(advancedKeys) : advancedKeys.map((key) => this._renderField(key))}
              ${this._renderField(approveRemoteHostKey)}
            </div>
          `
        : null}
    `;
  }

  /**
   * n8n's Basic fields, split into the two real, distinct concepts a
   * user reported conflating: the base service connection (already
   * covered by the universal security header + Base URL) versus the
   * *optional* HAMIE -> n8n outbound webhook. Neither implies the other
   * is broken -- see N8nConnector.async_test's own independent
   * health/webhook-readiness facts this mirrors.
   */
  _renderN8nBody(basicKeys) {
    const connectionKeys = basicKeys.filter((key) => N8N_CONNECTION_KEYS.includes(key));
    const outboundKeys = basicKeys.filter((key) => N8N_OUTBOUND_KEYS.includes(key));
    return html`
      ${connectionKeys.map((key) => this._renderField(key))}
      <h3 class="group-heading">HAMIE → n8n</h3>
      <p class="group-help">
        Optional webhook used when HAMIE sends commands or events to n8n.
        This is separate from the n8n service-health connection above.
      </p>
      ${outboundKeys.map((key) => this._renderField(key))}
    `;
  }

  /** n8n's Advanced fields, with the real inbound (n8n -> HAMIE) surface
   * grouped and labeled separately from generic connector tuning. */
  _renderN8nAdvanced(advancedKeys) {
    const inboundKeys = advancedKeys.filter((key) => key.startsWith("n8n_inbound"));
    const otherKeys = advancedKeys.filter((key) => !key.startsWith("n8n_inbound"));
    const inboundEndpoint = this._config?.sections?.n8n?.metadata?.inbound_endpoint;
    return html`
      ${otherKeys.map((key) => this._renderField(key))}
      <h3 class="group-heading">n8n → HAMIE</h3>
      <p class="group-help">Controls for n8n calling back into HAMIE (inbound commands).</p>
      ${inboundEndpoint
        ? html`
            <div class="field">
              <label>Inbound endpoint</label>
              <span class="inbound-endpoint">${inboundEndpoint}</span>
            </div>
          `
        : null}
      ${inboundKeys.map((key) => this._renderField(key))}
    `;
  }
}

if (!customElements.get("hamie-connector-editor")) {
  customElements.define("hamie-connector-editor", HamieConnectorEditor);
}
