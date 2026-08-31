/**
 * <hamie-action-card> — the single, prominent "recommended next step"
 * surface: an accent-tinted card with an icon, a headline, a short
 * explanatory subtext, and one or two action buttons (slotted, so each
 * caller wires its own real handlers rather than this component owning
 * navigation/WS calls it has no business knowing about).
 */
import { LitElement, css, html } from "lit";

export class HamieActionCard extends LitElement {
  static properties = {
    icon: { type: String },
    heading: { type: String },
    description: { type: String },
  };

  static styles = css`
    :host {
      display: block;
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg);
      background: linear-gradient(
        to bottom right,
        var(--hamie-accent-fill-quiet),
        var(--hamie-surface-card) 65%
      );
      padding: var(--hamie-space-5);
    }
    .layout {
      display: flex;
      align-items: flex-start;
      gap: var(--hamie-space-4);
    }
    .icon-badge {
      flex-shrink: 0;
      width: 40px;
      height: 40px;
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-accent-fill-loud);
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .icon-badge ha-icon {
      --mdc-icon-size: 20px;
      color: var(--hamie-accent-on);
    }
    .content {
      flex: 1;
      min-width: 0;
    }
    .eyebrow {
      margin: 0 0 var(--hamie-space-1);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-accent);
    }
    .heading {
      margin: 0;
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .description {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      line-height: 1.5;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-3);
    }
  `;

  render() {
    return html`
      <div class="layout">
        ${this.icon
          ? html`<div class="icon-badge"><ha-icon icon=${this.icon}></ha-icon></div>`
          : null}
        <div class="content">
          <p class="eyebrow">Recommended next step</p>
          <p class="heading">${this.heading}</p>
          ${this.description ? html`<p class="description">${this.description}</p>` : null}
          <div class="actions"><slot></slot></div>
        </div>
      </div>
    `;
  }
}

if (!customElements.get("hamie-action-card")) {
  customElements.define("hamie-action-card", HamieActionCard);
}
