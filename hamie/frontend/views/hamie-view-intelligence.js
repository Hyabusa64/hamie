/**
 * <hamie-view-intelligence> — reconstructed from App.tsx's `AIPage`.
 *
 * Real-data reconciliation:
 * - "Engine active" chip / Model card: real `ai_connection_method` +
 *   `ai_task_entity_id`/`ollama_model` from configuration (the same
 *   fields the AI Task executor actually uses -- see
 *   connectors/manager.py's ai_connection_method/ai_provider_ready).
 * - "Insights" metric: Figma's "147, last 30 days" has no equivalent
 *   concept -- HAMIE doesn't track a rolling insight count. Replaced
 *   with a real, honestly-derived count: total real recommendations
 *   whose real `created_at` falls within the last 30 days.
 * - "Accuracy / Validated predictions" metric: no equivalent at all --
 *   HAMIE does not track prediction validation or accuracy anywhere.
 *   Omitted entirely rather than filling the slot with an invented
 *   number (2 honest metrics instead of 3 with one fabricated).
 * - "Recent insights" (typed pattern/anomaly/prediction/efficiency,
 *   with confidence %): real recommendations have no "type" field at
 *   all -- confirmed HAMIE produces exactly one kind of structured
 *   advisory output, not four typed categories. This is in fact the
 *   same underlying real data as the Recommendations screen (Figma
 *   splits one real capability into two mock-data-backed pages). Shown
 *   here as a real, untyped preview (heading = summary, confidence =
 *   real field) with a link to the full Recommendations screen, rather
 *   than duplicating full recommendation management on two pages or
 *   inventing a type taxonomy that doesn't exist.
 *
 * Functionality-pass fix: `hamie/configuration/get` requires
 * `schema_version` (`vol.Required`, presentation/api.py) -- this view
 * never sent it at all, so every load failed schema validation before
 * this screen could ever render real data. Fixed to send the real
 * current schema version (configuration.py CONFIGURATION_SCHEMA_VERSION
 * = 2, the same value hamie-panel.js already sends).
 */
import { LitElement, css, html } from "lit";

import { relativeTime } from "../format.js";
import { friendlyError } from "../errors.js";
import "../components/hamie-card.js";
import "../components/hamie-metric.js";
import "../components/hamie-section.js";
import "../components/hamie-status.js";
import "../components/hamie-button.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";

export class HamieViewIntelligence extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _recommendations: { state: true },
    _error: { state: true },
    _analyzeError: { state: true }, // "Analyze Now"-only failure; keeps existing data visible
    _analyzing: { state: true },
    _coverage: { state: true }, // eligible/selected/skipped accounting from the last analysis
  };

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .analyze-error {
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
    .header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      margin-bottom: var(--hamie-space-5);
    }
    h1 {
      margin: 0;
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .subtitle {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-5);
      max-width: 40rem;
    }
    @media (max-width: 600px) {
      .metrics {
        grid-template-columns: 1fr;
      }
    }
    .insight-row {
      display: flex;
      align-items: flex-start;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-3) 0;
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .insight-row:last-child {
      border-bottom: none;
    }
    .insight-body {
      flex: 1;
      min-width: 0;
    }
    .insight-title {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .insight-meta {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-1);
    }
    .insight-confidence {
      font-size: var(--hamie-text-caption);
      font-family: var(--hamie-font-code);
      color: var(--hamie-text-secondary);
      background: var(--hamie-surface-raised);
      padding: 1px var(--hamie-space-1-5);
      border-radius: var(--hamie-radius-sm);
    }
    .insight-text {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
    .footer-link {
      margin-top: var(--hamie-space-3);
    }
  `;

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  async _load() {
    if (!this.hass) return;
    try {
      const [config, recommendations, overview] = await Promise.all([
        // schema_version is required (presentation/api.py) -- 2 is the
        // real current schema (configuration.py
        // CONFIGURATION_SCHEMA_VERSION).
        this.hass.callWS({ type: "hamie/configuration/get", schema_version: 2 }),
        this.hass.callWS({ type: "hamie/recommendations/list", offset: 0, limit: 25 }),
        this.hass.callWS({ type: "hamie/explorer/overview" }),
      ]);
      this._config = config.sections?.ollama?.values || {};
      this._recommendations = recommendations.items.filter((item) => item.review_state === "new" && !item.stale);
      // Process-lifetime accounting from the last analysis (this session
      // or an earlier one) -- survives a page refresh instead of only
      // being visible immediately after clicking Analyze Now.
      this._coverage = overview.ai_last_coverage || null;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Intelligence data is temporarily unavailable.");
    }
  }

  async _onAnalyzeNow() {
    if (!this.hass) return;
    this._analyzing = true;
    this._analyzeError = null;
    try {
      const result = await this.hass.callWS({ type: "hamie/ai/analyze" });
      this._coverage = result.coverage || null;
      await this._load();
    } catch (err) {
      // Real backend constraint (operations_service.py
      // async_request_ai): a scan-summary request needs at least one
      // tracked finding to analyze -- raises if there are none at all,
      // which is a normal state for a healthy home, not a real failure.
      // A connector-unrelated condition like this (or a genuine
      // connector_disabled/connector_timeout/etc. classification, see
      // frontend/errors.js) must never be confused with "Intelligence
      // data is unavailable" -- that heading is reserved for the page's
      // own load failing, not for one action's outcome.
      const message = friendlyError(err, "There's nothing for HAMIE to analyze right now.");
      if (this._config && this._recommendations) {
        this._analyzeError = message;
      } else {
        this._error = message;
      }
    } finally {
      this._analyzing = false;
    }
  }

  _navigateToRecommendations() {
    this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "recommendations" }, bubbles: true, composed: true }));
  }

  render() {
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="Intelligence data is unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._config || !this._recommendations) {
      return html`<hamie-loading .lines=${4}></hamie-loading>`;
    }

    const method = this._config.ai_connection_method || "direct";
    // Real readiness (connectors/manager.py ai_provider_ready): ha_ai_task
    // requires the configured entity to actually still exist in this
    // Home Assistant, not just a non-empty string in config; direct
    // requires the ollama connector to be enabled, not merely a model
    // name typed into the field.
    const engineReady =
      method === "ha_ai_task"
        ? !!this._config.ai_task_entity_id && !!this.hass?.states?.[this._config.ai_task_entity_id]
        : !!this._config.ollama_enabled;

    const thirtyDaysAgo = Date.now() - 30 * 24 * 3600 * 1000;
    const recentCount = this._recommendations.filter((item) => new Date(item.generated_at).getTime() >= thirtyDaysAgo).length;

    return html`
      <div class="header">
        <div>
          <h1>Intelligence</h1>
          <p class="subtitle">HAMIE AI engine — pattern detection and predictive maintenance</p>
        </div>
        <div class="header-actions">
          <hamie-status status=${engineReady ? "running" : "offline"} label=${engineReady ? "Engine active" : "Not configured"}></hamie-status>
          <hamie-button variant="secondary" size="sm" ?disabled=${this._analyzing || !engineReady} @click=${this._onAnalyzeNow}>
            <ha-icon icon="mdi:creation"></ha-icon> ${this._analyzing ? "Analyzing…" : "Analyze now"}
          </hamie-button>
        </div>
      </div>

      ${this._analyzeError
        ? html`
            <div class="analyze-error" role="alert">
              <span>${this._analyzeError}</span>
              <hamie-button variant="ghost" size="xs" aria-label="Dismiss" @click=${() => (this._analyzeError = null)}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          `
        : null}

      <div class="metrics">
        <hamie-metric
          label="Coverage"
          value=${this._coverage?.coverage || "Not analyzed"}
          sub=${this._coverage
            ? `${this._coverage.groups_analyzed} of ${this._coverage.root_cause_groups_detected} root-cause groups`
            : "Run analysis to measure coverage"}
          icon="mdi:chart-donut"
        ></hamie-metric>
        <hamie-metric
          label="Advisory insights"
          value=${this._recommendations.length}
          sub="${recentCount} in the last 30 days"
          icon="mdi:database-outline"
        ></hamie-metric>
      </div>

      ${this._coverage
        ? html`
            <p class="subtitle" style="margin-bottom: var(--hamie-space-4)">
              ${this._coverage.total_findings} findings detected ·
              ${this._coverage.selected_total} selected ·
              ${this._coverage.groups_analyzed} root-cause groups analyzed ·
              ${this._coverage.skipped_total} deferred ·
              Coverage: ${this._coverage.coverage}. ${this._coverage.selection_reason}
            </p>
          `
        : null}

      <div>
        <hamie-section heading="Recent insights" description="Generated from HAMIE's advisory analysis"></hamie-section>
        <hamie-card padding="md">
          ${this._recommendations.length === 0
            ? html`<hamie-empty tone="neutral" heading="No insights yet"></hamie-empty>`
            : this._recommendations.slice(0, 8).map(
                (item) => html`
                  <div class="insight-row">
                    <ha-icon icon="mdi:lightbulb-on-outline"></ha-icon>
                    <div class="insight-body">
                      <div class="insight-meta">
                        <p class="insight-title">${item.summary}</p>
                        <span class="insight-confidence">${item.confidence} confidence</span>
                      </div>
                      <p class="insight-text">${item.probable_causes?.[0] || ""}</p>
                    </div>
                  </div>
                `,
              )}
          <div class="footer-link">
            <hamie-button variant="ghost" size="xs" @click=${this._navigateToRecommendations}>
              View all recommendations <ha-icon icon="mdi:arrow-right"></ha-icon>
            </hamie-button>
          </div>
        </hamie-card>
      </div>
    `;
  }
}

if (!customElements.get("hamie-view-intelligence")) {
  customElements.define("hamie-view-intelligence", HamieViewIntelligence);
}
