/**
 * <hamie-ai-provider-editor> — real editable Settings→Ollama/AI provider
 * form (capability-matrix #34), embedded inline in the Ollama card on the
 * Settings screen behind an "Edit" button. Nothing about the approved
 * global shell/nav changes -- this is scoped entirely to the one section
 * the audit found had no real native-flow equivalent.
 *
 * Architectural decision (documented per the explicit instruction to
 * record why this preserves parity, not just that it does):
 *
 * `config_flow.py`'s native Options Flow was the first option considered,
 * and rejected for this one section specifically. Its `ollama` step is a
 * single generic `_connector_step` (identical machinery to n8n/mcp/hkg)
 * that renders one static voluptuous form per HTTP round trip. The real
 * legacy UX this section requires is fundamentally incompatible with
 * that model:
 *   - the connection-method selector must instantly swap which fields are
 *     "Basic" vs "Advanced" the moment it changes (native flow can only
 *     redraw on the next step submission, not live);
 *   - Ollama model discovery is a live "Test Connection" round trip that
 *     populates a client-side searchable list -- "search as you type"
 *     over that list has no native-flow equivalent at all (a step form
 *     cannot filter its own options without a server round trip per
 *     keystroke, which is not the same interaction);
 *   - the status line (Ready / Not configured / Entity unavailable /
 *     Unsupported / Disabled / Test failed) needs to react live to
 *     several other fields at once.
 * Reimplementing this depth in `config_flow.py` would mean either
 * degrading the UX (round-tripping on every interaction) or building a
 * bespoke reactive layer server-side that native Options Flow has no
 * facility for -- neither "fully preserves capability and UX", which is
 * the user's own bar for choosing to extend the native flow instead.
 *
 * So: a dedicated UI 3.0 view, using only real, already-existing backend
 * APIs (no new backend code) -- `hamie/configuration/get` (schema-driven
 * field specs, same ones the read-only Settings view already renders),
 * `hamie/ai_providers/discover` (live AI Task entity list),
 * `hamie/configuration/test` (unsaved-values connection test; for Ollama
 * this is also real model discovery -- OllamaConnector.async_test()
 * returns the provider's model catalog), `hamie/ai_providers/test` (HA
 * AI Task method test), and `hamie/configuration/save` (the same
 * `expected_revision` + idempotency-token-guarded save every other
 * section already uses). Field layout and visibility rules were
 * originally ported from hamie-panel.js's `_aiProviderSettingsForm()`/
 * `_basicSettingsKeys()`/`_ollamaModelField()`.
 *
 * "Allow connection to this local-network host" production defect fix
 * (0.2.4-beta.13): this control always existed as a real field
 * (configuration.py's `ollama_approve_host`) but was previously only
 * ever rendered once a `host_not_allowed` error from a failed Test
 * Connection/Save was already present -- so enabling Ollama at the
 * overwhelmingly common real address shape (a private-network IP) left
 * the user needing to fail a test first before the control that fixed
 * it ever appeared. It is now always rendered directly below Enabled,
 * before "Connection method" -- see connector-security.js for the
 * shared auto-enable-on-first-transition rule this editor and
 * hamie-connector-editor.js (n8n/MCP/HKG) both use.
 */
import { LitElement, css, html } from "lit";

import { friendlyError } from "../errors.js";
import { applyEnabledTransition } from "../connector-security.js";
import { idempotencyToken } from "../idempotency.js";
import "../components/hamie-input.js";
import "../components/hamie-select.js";
import "../components/hamie-switch.js";
import "../components/hamie-button.js";

const FIELD_ERROR_MESSAGES = {
  required: "This field is required.",
  invalid_url: "Enter a valid HTTP or HTTPS address without embedded credentials.",
  host_not_allowed: "This host needs explicit approval before HAMIE can connect.",
  unsafe_host: "This address range is blocked by HAMIE's host policy.",
  credential_required: "Enter the required credential and choose Replace.",
  model_not_found: "Select a model returned by the provider, or use Advanced manual entry.",
  invalid_authentication: "Review the authentication method and credential.",
  below_minimum: "The value is below the supported minimum.",
  above_maximum: "The value exceeds the supported maximum.",
  invalid_type: "Enter a value in the expected format.",
};

function fieldErrorMessage(code) {
  return FIELD_ERROR_MESSAGES[code] || String(code).replaceAll("_", " ");
}

// Rendered in this exact order in Advanced (the manual-model field is
// spliced in separately, matching hamie-panel.js's field ordering).
const ADVANCED_FIELD_KEYS = [
  "ollama_provider_type",
  "ollama_approve_remote_host",
  "ollama_api_key",
  "ollama_credential_action",
  "ollama_confirm_remove_credential",
  "ollama_timeout",
  "ollama_verify_tls",
  "ollama_maximum_input_characters",
  "ai_maximum_advisory_groups_per_run",
  "ai_maximum_findings_per_group",
  "ai_maximum_estimated_tokens",
  "ai_minimum_confidence_threshold",
  "ollama_maximum_output_tokens",
  "ollama_temperature",
  "ollama_think",
  "ollama_analyze_findings",
  "ollama_analyze_groups",
  "ollama_prioritize_findings",
  "ollama_suggest_troubleshooting_checks",
  "ollama_suggest_non_executing_repair_plans",
  "ollama_automatic_analysis",
];

export class HamieAiProviderEditor extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _providers: { state: true },
    _draft: { state: true },
    _errors: { state: true },
    _dirty: { state: true },
    _advancedOpen: { state: true },
    _discoveredModels: { state: true },
    _modelSearch: { state: true },
    _result: { state: true },
    _saving: { state: true },
    _testing: { state: true },
    _error: { state: true },
  };

  static styles = css`
    :host {
      display: block;
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
    .status-value {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
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
      margin: var(--hamie-space-2) 0;
    }
    .advanced {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
      padding-top: var(--hamie-space-2);
      border-top: 1px solid var(--hamie-border-hairline);
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
  `;

  constructor() {
    super();
    this._modelSearch = "";
    this._discoveredModels = [];
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
    if (!this.hass) return;
    try {
      const [config, providers] = await Promise.all([
        this.hass.callWS({ type: "hamie/configuration/get", schema_version: 2 }),
        this.hass
          .callWS({ type: "hamie/ai_providers/discover" })
          .catch(() => ({ ai_task_available: false, ai_task_entities: [] })),
      ]);
      this._config = config;
      this._providers = providers;
      this._resetDraft();
      // Seed the model list from what Ollama last discovered this process
      // lifetime (ConnectorManager.discovered_models, surfaced via
      // configuration/get's ollama section metadata) -- so an already-
      // tested, already-healthy connection shows its real models on page
      // load instead of always demanding a fresh Test Connection click.
      const cached = config.sections?.ollama?.metadata?.discovered_models;
      if (Array.isArray(cached) && cached.length) {
        this._discoveredModels = [...cached].sort((left, right) => left.localeCompare(right));
      }
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "AI provider settings are temporarily unavailable.");
    }
  }

  _resetDraft() {
    const section = this._config.sections?.ollama;
    const values = structuredClone(section?.values || {});
    for (const field of section?.fields || []) {
      if (field.secret) values[field.key] = "";
    }
    this._draft = values;
    this._errors = {};
    this._dirty = false;
    this._result = undefined;
    this._discoveredModels = [];
    this._modelSearch = "";
    this._approveHostManuallyChanged = false;
  }

  _fieldsByKey() {
    return Object.fromEntries((this._config.sections?.ollama?.fields || []).map((field) => [field.key, field]));
  }

  _onFieldChange(key, value) {
    if (key === "ollama_approve_host") {
      this._approveHostManuallyChanged = true;
    }
    this._draft =
      key === "ollama_enabled"
        ? applyEnabledTransition({
            draft: this._draft,
            enabledKey: "ollama_enabled",
            approveHostKey: "ollama_approve_host",
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
    if (key === "ollama_base_url") {
      this._discoveredModels = [];
      this._modelSearch = "";
    }
  }

  _statusLine() {
    const method = this._draft.ai_connection_method || "direct";
    const providers = this._providers || { ai_task_available: false, ai_task_entities: [] };
    if (!this._draft.ollama_enabled) return "Disabled";
    if (this._result?.ok === false) return "Test failed";
    if (method === "ha_ai_task") {
      if (!providers.ai_task_available) return "Unsupported — AI Task is not installed";
      if (!this._draft.ai_task_entity_id) return "Not configured";
      const known = providers.ai_task_entities.some((entity) => entity.entity_id === this._draft.ai_task_entity_id);
      if (!known) return "Entity unavailable";
      return "Ready";
    }
    if (!this._draft.ollama_model) return "Not configured -- no model selected";
    if (this._discoveredModels.length && !this._discoveredModels.includes(this._draft.ollama_model)) {
      return `Ready, but "${this._draft.ollama_model}" was not in the last discovered model list`;
    }
    return "Ready (direct connection -- deprecated advanced fallback)";
  }

  _buildSaveValues() {
    const section = this._config.sections.ollama;
    const values = {};
    for (const field of section.fields || []) {
      const hasDraft = Object.prototype.hasOwnProperty.call(this._draft, field.key);
      values[field.key] = field.locked
        ? section.values[field.key] ?? field.default
        : structuredClone(hasDraft ? this._draft[field.key] : field.default);
    }
    if (values.ollama_api_key && values.ollama_credential_action === "keep") {
      values.ollama_credential_action = "replace";
    }
    return values;
  }

  async _onSave() {
    this._saving = true;
    try {
      const result = await this.hass.callWS({
        type: "hamie/configuration/save",
        schema_version: 2,
        section: "ollama",
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
          sections: { ...this._config.sections, ollama: result.section_state },
        };
      }
      this._resetDraft();
      this._result = { ok: true, message: result.saved ? "Settings saved." : "No settings changed." };
      this.dispatchEvent(new CustomEvent("hamie-ai-provider-saved", { bubbles: true, composed: true }));
    } catch (err) {
      this._applyFailure({ error_code: err?.code });
    } finally {
      this._saving = false;
    }
  }

  _onCancel() {
    this.dispatchEvent(new CustomEvent("hamie-ai-provider-cancelled", { bubbles: true, composed: true }));
  }

  async _onTest() {
    this._testing = true;
    try {
      const method = this._draft.ai_connection_method || "direct";
      if (method !== "direct") {
        await this._testNativeProvider(method);
        return;
      }
      const result = await this.hass.callWS({
        type: "hamie/configuration/test",
        schema_version: 2,
        connector_id: "ollama",
        values: this._buildSaveValues(),
      });
      if (result.ok === false || result.connected === false) {
        this._applyFailure(result, result.error_code || "unreachable");
        return;
      }
      this._discoveredModels = [...(result.models || [])].slice(0, 100).sort((left, right) => left.localeCompare(right));
      this._modelSearch = "";
      this._result = { ok: true, message: "Connection test succeeded without saving." };
    } catch (err) {
      this._applyFailure({ error_code: err?.code }, err?.code || "unreachable");
    } finally {
      this._testing = false;
    }
  }

  async _testNativeProvider(method) {
    const entityId = this._draft.ai_task_entity_id;
    if (!entityId) {
      this._applyFailure({ field_errors: { ai_task_entity_id: "required" } }, "required");
      return;
    }
    try {
      const result = await this.hass.callWS({
        type: "hamie/ai_providers/test",
        connection_method: method,
        entity_id: entityId,
      });
      if (result.ok === false || result.connected === false) {
        this._applyFailure(result, result.error_code || "unreachable");
        return;
      }
      this._result = { ok: true, message: `Connection test succeeded without saving. Latency ${result.latency_ms} ms.` };
    } catch (err) {
      this._applyFailure({ error_code: err?.code }, err?.code || "unreachable");
    }
  }

  _applyFailure(result, fallbackCode = "configuration_failed") {
    this._errors = structuredClone(result?.field_errors || {});
    if (Object.keys(this._errors).length) this._advancedOpen = true;
    this._result = { ok: false, message: result?.message || fieldErrorMessage(result?.error_code || fallbackCode) };
  }

  _renderField(key, { label } = {}) {
    const field = this._fieldsByKey()[key];
    if (!field) return null;
    const value = this._draft[key] ?? field.default ?? "";
    const error = this._errors[key] ? fieldErrorMessage(this._errors[key]) : "";
    let control;
    if (field.kind === "boolean") {
      control = html`<hamie-switch ?checked=${Boolean(value)} @hamie-change=${(e) => this._onFieldChange(key, e.detail.checked)}></hamie-switch>`;
    } else if (field.kind === "select") {
      const options = (field.choices || []).map((choice) => ({ value: choice, label: String(choice).replaceAll("_", " ") }));
      control = html`<hamie-select .value=${value} .options=${options} @hamie-change=${(e) => this._onFieldChange(key, e.detail.value)}></hamie-select>`;
    } else {
      control = html`<hamie-input
        .value=${String(value)}
        type=${field.secret ? "password" : field.kind === "url" ? "url" : "text"}
        @hamie-input=${(e) => {
          const raw = e.detail.value;
          const numeric = ["integer", "number"].includes(field.kind) && raw !== "" ? Number(raw) : raw;
          this._onFieldChange(key, numeric);
        }}
      ></hamie-input>`;
    }
    return html`
      <div class="field ${field.kind === "boolean" ? "boolean" : ""}">
        <label>${label || field.label}</label>
        ${control}
        ${field.description ? html`<span class="description">${field.description}</span>` : null}
        ${error ? html`<span class="field-error">${error}</span>` : null}
      </div>
    `;
  }

  _renderModelField() {
    const value = this._draft.ollama_model || "";
    const error = this._errors.ollama_model ? fieldErrorMessage(this._errors.ollama_model) : "";
    if (!this._discoveredModels.length) {
      return html`
        <div class="field">
          <label>Model</label>
          <span class="description">
            ${value
              ? `Currently set to "${value}". Test Connection to discover available models and confirm it's still available.`
              : "Test Connection to discover available models."}
          </span>
          ${error ? html`<span class="field-error">${error}</span>` : null}
        </div>
      `;
    }
    const configuredModelMissing = value && !this._discoveredModels.includes(value);
    const query = this._modelSearch.trim().toLocaleLowerCase();
    let filtered = this._discoveredModels.filter((model) => model.toLocaleLowerCase().includes(query));
    if (value && this._discoveredModels.includes(value) && !filtered.includes(value)) filtered = [value, ...filtered];
    const options = [{ value: "", label: "Select a discovered model" }, ...filtered.map((model) => ({ value: model, label: model }))];
    return html`
      <div class="field">
        <label>Search models</label>
        <hamie-input .value=${this._modelSearch} placeholder="Filter discovered models" @hamie-input=${(e) => (this._modelSearch = e.detail.value)}></hamie-input>
        <label>Model</label>
        <hamie-select .value=${value} .options=${options} @hamie-change=${(e) => this._onFieldChange("ollama_model", e.detail.value)}></hamie-select>
        ${configuredModelMissing
          ? html`<span class="field-error">"${value}" was not in the last discovered model list. It may no longer be available on this provider -- select one of the discovered models above, or retest.</span>`
          : null}
        ${error ? html`<span class="field-error">${error}</span>` : null}
      </div>
    `;
  }

  _renderManualModelField() {
    const value = this._draft.ollama_model || "";
    return html`
      <div class="field">
        <label>Manual model identifier</label>
        <hamie-input .value=${value} @hamie-input=${(e) => this._onFieldChange("ollama_model", e.detail.value)}></hamie-input>
        <span class="description">Advanced fallback when model discovery is unavailable.</span>
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

    const method = this._draft.ai_connection_method || "direct";
    const providers = this._providers || { ai_task_available: false, ai_task_entities: [] };
    const methodField = this._fieldsByKey().ai_connection_method;
    const methodOptions = [
      providers.ai_task_available ? { value: "ha_ai_task", label: "Home Assistant AI Task (recommended)" } : null,
      { value: "direct", label: "Legacy direct provider — deprecated compatibility fallback" },
    ].filter(Boolean);
    const credentialConfigured = this._config.sections.ollama.values?.ollama_credential_configured;

    // Leaving the API key blank is a genuine, first-class configuration
    // -- the expected setup for a local, unauthenticated Ollama instance
    // (OllamaConnector never sends an Authorization header unless an
    // api_key is actually set) -- not a half-finished credential. Stated
    // explicitly here rather than left implicit in a blank password
    // field, so it never reads as an oversight.
    const noAuthConfigured = !this._draft.ollama_api_key && !credentialConfigured;
    const authNote = noAuthConfigured
      ? html`<span class="description">No API key configured -- this connects without authentication. That's the expected, fully supported setup for a local Ollama instance.</span>`
      : html`<span class="description">An API key is configured for this connection.</span>`;
    let basicDirectFields = null;
    let extraAdvancedFields = null;
    if (method === "direct") {
      basicDirectFields = html`
        ${this._renderField("ollama_base_url", { label: "Address" })}
        ${authNote}
        ${this._renderModelField()}
      `;
    } else {
      extraAdvancedFields = html`
        ${this._renderField("ollama_base_url", { label: "Address" })}
        ${authNote}
        ${this._renderModelField()}
      `;
    }

    const entities = providers.ai_task_entities || [];
    const entityValue = this._draft.ai_task_entity_id || "";
    const entityError = this._errors.ai_task_entity_id ? fieldErrorMessage(this._errors.ai_task_entity_id) : "";
    const entityOptions = [
      { value: "", label: entities.length ? "Select a provider" : "No compatible entities found" },
      ...entities.map((entity) => ({ value: entity.entity_id, label: `${entity.name} — ${entity.entity_id}` })),
    ];

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
      ${credentialConfigured === undefined
        ? null
        : html`<p class="credential-note">Authentication: ${credentialConfigured ? "configured (value hidden)" : "not configured"}</p>`}
      ${this._result
        ? html`<div class="result ${this._result.ok ? "ok" : "fail"}">${this._result.message}</div>`
        : null}

      <div class="fields">
        ${this._renderField("ollama_enabled")}
        ${this._renderField("ollama_approve_host")}
        <div class="field">
          <label>Connection method</label>
          <hamie-select .value=${method} .options=${methodOptions} @hamie-change=${(e) => this._onFieldChange("ai_connection_method", e.detail.value)}></hamie-select>
          ${method === "direct"
            ? html`<span class="description">Direct is a deprecated, advanced-only fallback. Home Assistant AI Task is the recommended background-analysis pipeline.</span>`
            : methodField?.description
              ? html`<span class="description">${methodField.description}</span>`
              : null}
        </div>
        ${method === "ha_ai_task"
          ? html`
              <div class="field">
                <label>Provider</label>
                <hamie-select
                  .value=${entityValue}
                  .options=${entityOptions}
                  ?disabled=${!entities.length}
                  @hamie-change=${(e) => this._onFieldChange("ai_task_entity_id", e.detail.value)}
                ></hamie-select>
                ${entityError
                  ? html`<span class="field-error">${entityError}</span>`
                  : html`<span class="description">Discovered from this Home Assistant.</span>`}
              </div>
            `
          : null}
        ${basicDirectFields}
        <div class="field">
          <label>Status</label>
          <span class="status-value">${this._statusLine()}</span>
        </div>
      </div>

      <button class="disclosure" type="button" aria-expanded=${this._advancedOpen} @click=${() => (this._advancedOpen = !this._advancedOpen)}>
        <ha-icon icon="mdi:chevron-${this._advancedOpen ? "up" : "down"}"></ha-icon>
        ${this._advancedOpen ? "Hide" : "Show"} Advanced Options
      </button>
      ${this._advancedOpen
        ? html`
            <div class="advanced">
              ${extraAdvancedFields}
              ${this._renderManualModelField()}
              ${ADVANCED_FIELD_KEYS.map((key) => this._renderField(key))}
            </div>
          `
        : null}
    `;
  }
}

if (!customElements.get("hamie-ai-provider-editor")) {
  customElements.define("hamie-ai-provider-editor", HamieAiProviderEditor);
}
