/**
 * <hamie-metric> — reconstructed 1:1 from App.tsx's `MetricCard`.
 * label/value/sub/icon composed on top of <hamie-card>.
 */
import { LitElement, css, html } from "lit";

import { iconBadgeStyles } from "./shared-styles.js";
import "./hamie-card.js";

export class HamieMetric extends LitElement {
  static properties = {
    label: { type: String },
    value: { type: String },
    sub: { type: String },
    icon: { type: String }, // mdi:* icon name
    color: { type: String }, // CSS color value for the value text; defaults to primary text
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
      .label {
        margin: 0;
        font-size: var(--hamie-text-caption);
        font-weight: var(--hamie-weight-medium);
        text-transform: uppercase;
        letter-spacing: var(--hamie-tracking-label);
        color: var(--hamie-text-secondary);
      }
      .value {
        margin: var(--hamie-space-1-5) 0 0;
        font-size: var(--hamie-text-metric);
        font-weight: var(--hamie-weight-medium);
        line-height: 1;
        letter-spacing: -0.01em;
      }
      .sub {
        margin: var(--hamie-space-1-5) 0 0;
        font-size: var(--hamie-text-micro);
        color: var(--hamie-text-secondary);
        line-height: 1.4;
      }
      .icon-badge {
        flex-shrink: 0;
      }
    `,
  ];

  render() {
    return html`
      <hamie-card padding="md">
        <div class="row">
          <div>
            <p class="label">${this.label}</p>
            <p class="value" style=${this.color ? `color: ${this.color}` : ""}>${this.value}</p>
            ${this.sub ? html`<p class="sub">${this.sub}</p>` : null}
          </div>
          ${this.icon
            ? html`<div class="icon-badge"><ha-icon icon=${this.icon}></ha-icon></div>`
            : null}
        </div>
      </hamie-card>
    `;
  }
}

if (!customElements.get("hamie-metric")) {
  customElements.define("hamie-metric", HamieMetric);
}
