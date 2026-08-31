/**
 * <hamie-review-item> — one Review triage row: identity, HAMIE's
 * recommendation, confidence/risk, evidence for/against, and an explicit
 * external-consumer-uncertainty note -- never a destructive action (spec:
 * "No destructive actions available from here — recommendations only,
 * matching the verified safety gate"). The only controls this component
 * ever renders are read/navigate ones (View in Issues / Open in Review
 * Queue), slotted in by the caller so this component itself never wires
 * a WS call it has no business making.
 */
import { LitElement, css, html } from "lit";

import "./hamie-card.js";
import "./hamie-entity-identity.js";
import "./hamie-confidence-indicator.js";
import "./hamie-evidence-panel.js";
import "./hamie-status.js";
import "./hamie-disclosure.js";

const RISK_TONE = { low: "healthy", medium: "warning", high: "critical", unknown: "unknown" };

export class HamieReviewItem extends LitElement {
  static properties = {
    name: { type: String },
    entityId: { type: String, attribute: "entity-id" },
    integration: { type: String },
    recommendation: { type: String },
    confidenceLevel: { type: String, attribute: "confidence-level" },
    confidenceFactors: { type: Array, attribute: false },
    risk: { type: String }, // "low" | "medium" | "high" | "unknown"
    evidenceFor: { type: Array, attribute: false },
    evidenceAgainst: { type: Array, attribute: false },
    externalConsumerNote: { type: String, attribute: "external-consumer-note" },
  };

  static styles = css`
    :host {
      display: block;
    }
    .head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-3);
    }
    .badges {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
    }
    .recommendation {
      margin: 0 0 var(--hamie-space-3);
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
      line-height: 1.6;
    }
    .risk-pill {
      display: inline-flex;
      align-items: center;
      padding: var(--hamie-space-half) var(--hamie-space-2);
      border-radius: var(--hamie-radius-sm);
      font-size: var(--hamie-text-caption);
      font-weight: var(--hamie-weight-bold);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
    }
    .external-note {
      margin: var(--hamie-space-3) 0 0;
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-evidence-fill);
      color: var(--hamie-text-primary);
      font-size: var(--hamie-text-micro);
      display: flex;
      align-items: flex-start;
      gap: var(--hamie-space-2);
    }
    .external-note ha-icon {
      --mdc-icon-size: 14px;
      color: var(--hamie-status-evidence);
      flex-shrink: 0;
      margin-top: 1px;
    }
    .actions {
      display: flex;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-3);
    }
  `;

  render() {
    const risk = this.risk || "unknown";
    const riskTone = RISK_TONE[risk] || "unknown";
    return html`
      <hamie-card padding="md">
        <div class="head">
          <hamie-entity-identity name=${this.name || ""} entity-id=${this.entityId || ""} integration=${this.integration || ""}></hamie-entity-identity>
          <span class="badges">
            <span class="risk-pill" style="background: var(--hamie-status-${riskTone}-fill); color: var(--hamie-status-${riskTone})">
              Risk: ${risk}
            </span>
          </span>
        </div>

        ${this.recommendation ? html`<p class="recommendation">${this.recommendation}</p>` : null}

        <hamie-confidence-indicator level=${this.confidenceLevel || ""} .factors=${this.confidenceFactors || []}></hamie-confidence-indicator>

        <hamie-disclosure label="Evidence">
          <hamie-evidence-panel .for=${this.evidenceFor || []} .against=${this.evidenceAgainst || []}></hamie-evidence-panel>
        </hamie-disclosure>

        ${this.externalConsumerNote
          ? html`
              <p class="external-note">
                <ha-icon icon="mdi:account-question-outline"></ha-icon>
                ${this.externalConsumerNote}
              </p>
            `
          : null}

        <div class="actions"><slot name="actions"></slot></div>
      </hamie-card>
    `;
  }
}

if (!customElements.get("hamie-review-item")) {
  customElements.define("hamie-review-item", HamieReviewItem);
}
