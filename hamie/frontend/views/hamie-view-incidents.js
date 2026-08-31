/** Root-cause incident workbench. Raw findings remain a drill-down. */
import { LitElement, css, html } from "lit";

import { friendlyError } from "../errors.js";
import "../components/hamie-button.js";
import "../components/hamie-card.js";
import "../components/hamie-empty.js";
import "../components/hamie-input.js";
import "../components/hamie-loading.js";
import "../components/hamie-page-header.js";
import "../components/hamie-section.js";
import "../components/hamie-status.js";

const PRIORITY_TONE = {
  p0: "critical",
  p1: "critical",
  p2: "warning",
  p3: "info",
  info: "unknown",
};

const EVIDENCE_LABEL = {
  verified: "Verified",
  strongly_inferred: "Strongly inferred",
  possible: "Possible",
  insufficient_evidence: "Needs evidence",
  not_a_problem: "Not a problem",
};

export class HamieViewIncidents extends LitElement {
  static properties = {
    hass: { attribute: false },
    _result: { state: true },
    _error: { state: true },
    _search: { state: true },
    _busyId: { state: true },
  };

  static styles = css`
    :host { display: block; padding: var(--hamie-space-5); max-width: var(--hamie-content-max-wide); }
    .stack { display: grid; gap: var(--hamie-space-4); }
    .toolbar { display: flex; gap: var(--hamie-space-3); align-items: end; }
    hamie-input { flex: 1; }
    .incident { display: grid; gap: var(--hamie-space-3); }
    .title-row { display: flex; gap: var(--hamie-space-2); align-items: center; flex-wrap: wrap; }
    h3 { margin: 0; font-size: var(--hamie-text-title); }
    .meta { color: var(--hamie-text-secondary); font-size: var(--hamie-text-small); }
    .root { margin: 0; line-height: 1.5; }
    .label { color: var(--hamie-text-secondary); font-size: var(--hamie-text-caption); text-transform: uppercase; letter-spacing: .04em; }
    .actions { display: flex; flex-wrap: wrap; gap: var(--hamie-space-2); }
    .error { color: var(--hamie-status-critical); }
    @media (max-width: 600px) { .toolbar { align-items: stretch; flex-direction: column; } }
  `;

  constructor() {
    super();
    this._result = null;
    this._error = null;
    this._search = "";
    this._busyId = null;
    this._onLiveUpdate = () => this._load();
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("hamie-live-update", this._onLiveUpdate);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("hamie-live-update", this._onLiveUpdate);
  }

  updated(changed) {
    if (changed.has("hass") && this.hass) this._load();
  }

  async _load() {
    if (!this.hass) return;
    try {
      this._result = await this.hass.callWS({
        type: "hamie/incidents/list",
        lifecycle: "active",
        search: this._search,
        limit: 100,
      });
      this._error = null;
    } catch (error) {
      this._error = friendlyError(error);
    }
  }

  async _setLifecycle(incident, lifecycle) {
    this._busyId = incident.incident_id;
    try {
      await this.hass.callWS({
        type: "hamie/incidents/lifecycle",
        incident_id: incident.incident_id,
        lifecycle,
        expected_revision: incident.content_revision,
        idempotency_token: crypto.randomUUID(),
      });
      await this._load();
      this.dispatchEvent(new CustomEvent("hamie-data-changed", { bubbles: true, composed: true }));
    } catch (error) {
      this._error = friendlyError(error);
    } finally {
      this._busyId = null;
    }
  }

  _openFinding(incident) {
    const findingId = incident.finding_ids?.[0];
    if (!findingId) return;
    this.dispatchEvent(new CustomEvent("hamie-navigate-finding", {
      detail: { findingId }, bubbles: true, composed: true,
    }));
  }

  render() {
    const items = this._result?.items || [];
    return html`
      <div class="stack">
        <hamie-page-header
          heading="Incidents"
          subtitle="Root-cause engineering problems, reduced from raw findings by deterministic evidence."
        ></hamie-page-header>
        <div class="toolbar">
          <hamie-input
            placeholder="Search incidents"
            .value=${this._search}
            @hamie-input=${(event) => { this._search = event.detail.value; }}
          ></hamie-input>
          <hamie-button variant="secondary" @click=${this._load}>Search</hamie-button>
        </div>
        ${this._error ? html`<p class="error">${this._error}</p>` : null}
        ${!this._result
          ? html`<hamie-loading label="Loading incidents"></hamie-loading>`
          : items.length === 0
            ? html`<hamie-empty heading="No active incidents" description="Run a scan to refresh deterministic evidence."></hamie-empty>`
            : items.map((incident) => html`
                <hamie-card padding="md">
                  <article class="incident">
                    <div class="title-row">
                      <hamie-status status=${PRIORITY_TONE[incident.priority] || "unknown"} label=${incident.priority.toUpperCase()}></hamie-status>
                      <h3>${incident.title}</h3>
                    </div>
                    <div class="meta">
                      ${EVIDENCE_LABEL[incident.evidence_status] || incident.evidence_status}
                      · ${Math.round(incident.confidence * 100)}% confidence
                      · ${incident.affected_subject_count} affected object${incident.affected_subject_count === 1 ? "" : "s"}
                      · ${incident.lifecycle}
                    </div>
                    <div>
                      <div class="label">Root cause</div>
                      <p class="root">${incident.root_cause}</p>
                    </div>
                    <div>
                      <div class="label">Evidence</div>
                      <p class="root">${incident.hypotheses?.[0]?.rationale || "No supporting rationale captured."}</p>
                    </div>
                    <div>
                      <div class="label">Affected systems</div>
                      <p class="root">${incident.affected_systems?.length ? incident.affected_systems.join(", ") : "No system mapping captured."}</p>
                    </div>
                    <div>
                      <div class="label">Recommended next step</div>
                      <p class="root">${incident.recommended_next_step}</p>
                    </div>
                    <div class="actions">
                      <hamie-button size="sm" variant="secondary" ?disabled=${this._busyId === incident.incident_id} @click=${() => this._setLifecycle(incident, "investigating")}>Investigate deeper</hamie-button>
                      <hamie-button size="sm" variant="secondary" ?disabled=${this._busyId === incident.incident_id} @click=${() => this._setLifecycle(incident, "confirmed")}>Confirm root cause</hamie-button>
                      <hamie-button size="sm" variant="ghost" @click=${() => this._openFinding(incident)}>View raw evidence</hamie-button>
                      <hamie-button size="sm" variant="ghost" ?disabled=${this._busyId === incident.incident_id} @click=${() => this._setLifecycle(incident, "ignored")}>Ignore</hamie-button>
                      <hamie-button size="sm" variant="ghost" ?disabled=${this._busyId === incident.incident_id} @click=${() => this._setLifecycle(incident, "dismissed")}>Dismiss</hamie-button>
                    </div>
                  </article>
                </hamie-card>
              `)}
      </div>
    `;
  }
}

if (!customElements.get("hamie-view-incidents")) {
  customElements.define("hamie-view-incidents", HamieViewIncidents);
}
