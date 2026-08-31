/** Evidence-backed security decisions. Unsupported evidence sources fail closed. */
import { LitElement, css, html } from "lit";

import { friendlyError } from "../errors.js";
import "../components/hamie-page-header.js";
import "../components/hamie-card.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";
import "../components/hamie-status.js";

export class HamieViewSecurity extends LitElement {
  static properties = {
    hass: { attribute: false },
    _page: { state: true },
    _error: { state: true },
  };

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    h2 { margin: 0; font-size: var(--hamie-text-small); color: var(--hamie-text-primary); }
    .meta {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .summary {
      display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: var(--hamie-space-3); margin: var(--hamie-space-4) 0;
    }
    .metric { font-size: var(--hamie-text-metric); font-weight: var(--hamie-weight-bold); margin-top: var(--hamie-space-1); }
    .stack { display: grid; gap: var(--hamie-space-3); }
    .finding-head { display: flex; justify-content: space-between; gap: var(--hamie-space-3); }
    .decision-grid {
      display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--hamie-space-3); margin-top: var(--hamie-space-3);
    }
    .label {
      display: block; margin-bottom: 4px; text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label); font-size: var(--hamie-text-caption);
      color: var(--hamie-text-secondary);
    }
    p, li { font-size: var(--hamie-text-small); color: var(--hamie-text-secondary); line-height: 1.55; }
    ul, ol { margin: 4px 0 0; padding-left: 1.2rem; }
    .sources { margin-top: var(--hamie-space-4); }
    @media (max-width: 700px) {
      .summary, .decision-grid { grid-template-columns: 1fr; }
    }
  `;

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  updated(changed) {
    if (changed.has("hass") && this.hass && !this._page) this._load();
  }

  async _load() {
    if (!this.hass) return;
    try {
      this._page = await this.hass.callWS({ type: "hamie/security/findings" });
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Security evidence is temporarily unavailable.");
    }
  }

  render() {
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="Security evidence is unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._page) return html`<hamie-loading .lines=${4}></hamie-loading>`;

    const highRisk = this._page.items.filter((item) => item.risk === "high" || item.risk === "critical").length;
    const manualOnly = this._page.items.filter((item) => item.execution_capability !== "Proposal available").length;
    return html`
      <hamie-page-header heading="Security" subtitle="Evidence-backed risks and decision-ready remediation state"></hamie-page-header>

      <div class="summary">
        <hamie-card padding="md"><span class="label">Open findings</span><div class="metric">${this._page.total}</div></hamie-card>
        <hamie-card padding="md"><span class="label">High risk</span><div class="metric">${highRisk}</div></hamie-card>
        <hamie-card padding="md"><span class="label">Manual only</span><div class="metric">${manualOnly}</div></hamie-card>
      </div>

      <div class="stack">
        ${this._page.items.length === 0
          ? html`<hamie-card padding="md"><hamie-empty
              tone="positive"
              heading="No supported security findings"
              description="HAMIE found no risks in the security evidence it can currently inspect. This is not a full host or Home Assistant security audit."
            ></hamie-empty></hamie-card>`
          : this._page.items.map((item) => html`
              <hamie-card padding="md">
                <div class="finding-head">
                  <div>
                    <h2>${item.title}</h2>
                    <p class="meta">${item.affected_object} · ${item.exposure}</p>
                  </div>
                  <hamie-status status=${item.risk === "critical" ? "critical" : "warning"} label="${item.risk} risk"></hamie-status>
                </div>
                <div class="decision-grid">
                  <div>
                    <span class="label">Evidence</span>
                    <ul>${item.evidence.map((value) => html`<li>${value}</li>`)}</ul>
                  </div>
                  <div>
                    <span class="label">Recommended action</span>
                    <p>${item.recommended_action}</p>
                    <p><strong>${item.execution_capability}</strong> · ${item.confidence} confidence</p>
                  </div>
                  <div>
                    <span class="label">Manual steps</span>
                    <ol>${item.manual_steps.map((value) => html`<li>${value}</li>`)}</ol>
                  </div>
                  <div>
                    <span class="label">Verification plan</span>
                    <ol>${item.verification_plan.map((value) => html`<li>${value}</li>`)}</ol>
                  </div>
                </div>
              </hamie-card>
            `)}
      </div>

      <hamie-card class="sources" padding="md">
        <h2>Evidence coverage</h2>
        <p>Checked: ${this._page.evidence_sources.join(", ")}.</p>
        <p>Not available: ${this._page.unavailable_sources.join(", ")}. HAMIE does not infer findings from these missing sources.</p>
      </hamie-card>
    `;
  }
}

if (!customElements.get("hamie-view-security")) {
  customElements.define("hamie-view-security", HamieViewSecurity);
}
