/**
 * <hamie-evidence-panel> — evidence FOR a recommendation shown separately
 * from evidence AGAINST it, per the Review triage screen's spec ("Each
 * item shows evidence FOR and evidence AGAINST the recommendation,
 * separately"). New primitive; no existing component in the library
 * shows two contrasting evidence sets side by side.
 *
 * `for`/`against` are plain string arrays -- deliberately not a richer
 * typed evidence shape, because the only two things live today that
 * actually populate this component (see hamie-view-review.js) are
 * per-finding dependency/classification facts, not the not-yet-wired
 * `CanonicalRecommendation.evidence[]` (domain/recommendation.py). A
 * caller with the richer model can still pass it in as pre-formatted
 * strings without this component needing to know the difference.
 */
import { LitElement, css, html } from "lit";

export class HamieEvidencePanel extends LitElement {
  static properties = {
    for: { type: Array },
    against: { type: Array },
  };

  static styles = css`
    :host {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: var(--hamie-space-4);
    }
    @media (max-width: 600px) {
      :host {
        grid-template-columns: 1fr;
      }
    }
    .column h4 {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      margin: 0 0 var(--hamie-space-1-5);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
    }
    .column.for h4 {
      color: var(--hamie-status-healthy);
    }
    .column.against h4 {
      color: var(--hamie-status-warning);
    }
    ha-icon {
      --mdc-icon-size: 14px;
    }
    ul {
      margin: 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
      line-height: 1.6;
    }
    .empty {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      font-style: italic;
    }
  `;

  _column(tone, heading, icon, items) {
    return html`
      <div class="column ${tone}">
        <h4><ha-icon icon=${icon}></ha-icon> ${heading}</h4>
        ${items?.length ? html`<ul>${items.map((item) => html`<li>${item}</li>`)}</ul>` : html`<p class="empty">None recorded</p>`}
      </div>
    `;
  }

  render() {
    return html`
      ${this._column("for", "Evidence for", "mdi:check-circle-outline", this.for)}
      ${this._column("against", "Evidence against", "mdi:alert-circle-outline", this.against)}
    `;
  }
}

if (!customElements.get("hamie-evidence-panel")) {
  customElements.define("hamie-evidence-panel", HamieEvidencePanel);
}
