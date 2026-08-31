/**
 * <hamie-status-summary> — the "one elegant summary surface instead of
 * numerous cards" primitive: a large circular score icon on the left, a
 * short status line under it, and either a column of compact labeled
 * rows or a set of thin health-dimension meters on the right. Replaces
 * a wall of equal-weight metric cards with one bordered surface.
 *
 * `score` is `null`/`undefined` when no real score exists yet (never a
 * fabricated number) -- rendered as an honest "Not enough data" instead
 * of a giant dash occupying the whole surface.
 */
import { LitElement, css, html } from "lit";

import "./hamie-mini-meter.js";

export class HamieStatusSummary extends LitElement {
  static properties = {
    score: { type: Number },
    scoreLabel: { type: String, attribute: "score-label" },
    statusText: { type: String, attribute: "status-text" },
    tone: { type: String }, // "healthy" | "warning" | "critical" | "unknown"
    rows: { type: Array }, // [{ label, value, tone }] -- simple label/value rows
    dimensions: { type: Array }, // [{ label, value, tone }] -- rendered as hamie-mini-meter
  };

  static styles = css`
    :host {
      display: block;
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg);
      background: var(--hamie-surface-card);
      padding: var(--hamie-space-5);
    }
    .layout {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-6);
      flex-wrap: wrap;
    }
    .primary {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-3);
      flex-shrink: 0;
    }
    .score-icon {
      width: 56px;
      height: 56px;
      border-radius: var(--hamie-radius-circle);
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .score-icon ha-icon {
      --mdc-icon-size: 26px;
    }
    .score-text {
      display: flex;
      align-items: baseline;
      gap: var(--hamie-space-2);
    }
    .score {
      font-size: var(--hamie-text-display);
      font-weight: var(--hamie-weight-bold);
      line-height: 1;
      letter-spacing: -0.02em;
    }
    .score-max {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .score.unavailable {
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-secondary);
    }
    .primary-text {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .dimensions {
      flex: 1;
      min-width: 220px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 0 var(--hamie-space-5);
    }
    .score-label {
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-text-secondary);
    }
    .status-text {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
    }
    .divider {
      align-self: stretch;
      width: 1px;
      background: var(--hamie-border-hairline);
    }
    .rows {
      flex: 1;
      min-width: 200px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: var(--hamie-space-3) var(--hamie-space-5);
    }
    .metric-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: var(--hamie-space-2);
    }
    .metric-label {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .metric-value {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    @media (max-width: 600px) {
      .layout {
        flex-direction: column;
        align-items: stretch;
      }
      .divider {
        width: auto;
        height: 1px;
      }
    }
  `;

  render() {
    const hasScore = typeof this.score === "number" && !Number.isNaN(this.score);
    const tone = this.tone || "unknown";
    const rows = this.rows || [];
    const dimensions = this.dimensions || [];
    return html`
      <div class="layout">
        <div class="primary">
          ${hasScore
            ? html`
                <span class="score-icon" style="background: var(--hamie-status-${tone}-fill)">
                  <ha-icon icon="mdi:heart-pulse" style="color: var(--hamie-status-${tone})"></ha-icon>
                </span>
              `
            : null}
          <div class="primary-text">
            <span class="score-text">
              <span class="score${hasScore ? "" : " unavailable"}" style=${hasScore ? `color: var(--hamie-status-${tone})` : ""}>
                ${hasScore ? this.score : "Health analysis pending"}
              </span>
              ${hasScore ? html`<span class="score-max">/100</span>` : null}
            </span>
            ${this.statusText ? html`<span class="status-text">${this.statusText}</span>` : null}
          </div>
        </div>
        ${rows.length || dimensions.length ? html`<div class="divider"></div>` : null}
        ${dimensions.length
          ? html`
              <div class="dimensions">
                ${dimensions.map(
                  (dim) => html`<hamie-mini-meter label=${dim.label} .value=${dim.value} tone=${dim.tone || "healthy"}></hamie-mini-meter>`,
                )}
              </div>
            `
          : rows.length
            ? html`
                <div class="rows">
                  ${rows.map(
                    (row) => html`
                      <div class="metric-row">
                        <span class="metric-label">${row.label}</span>
                        <span class="metric-value" style=${row.tone ? `color: var(--hamie-status-${row.tone})` : ""}>${row.value}</span>
                      </div>
                    `,
                  )}
                </div>
              `
            : null}
      </div>
    `;
  }
}

if (!customElements.get("hamie-status-summary")) {
  customElements.define("hamie-status-summary", HamieStatusSummary);
}
