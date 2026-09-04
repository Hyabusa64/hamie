/**
 * <hamie-problem-card> — reconstructed 1:1 from App.tsx's Recommendations
 * card markup (RecommendationsPage's `.map(rec => ...)` block). Named
 * "problem card" per the audit's floor component list; Figma's closest
 * concrete source is the recommendation card (priority badge + title +
 * body + primary action + category chip + dismiss). Real HAMIE findings
 * use the same shape (see the Findings/Recommendations views).
 *
 * Composes <hamie-card> for its shell and <hamie-status variant="priority">
 * for its badge (design-system stabilization pass -- both used to be
 * hand-rolled here, duplicating hamie-card's and hamie-status's CSS).
 *
 * `priority` is optional: Figma's Recommendations always have one, but
 * real HAMIE recommendations have no priority concept at all (only a
 * `confidence` field, a different concept -- how sure the AI is, not how
 * urgent the issue is). Silently defaulting to "low" for data that has
 * no real priority would misrepresent it, so the badge is omitted
 * entirely when no priority is given, rather than guessing.
 *
 * `details` (slot): optional supplementary structured content below the
 * body text -- added for real recommendations, which carry richer
 * structured data (probable causes, recommended checks) than Figma's
 * flat title+body anticipated. Generic, not recommendation-specific.
 */
import { LitElement, css, html } from "lit";

import "./hamie-button.js";
import "./hamie-card.js";
import "./hamie-status.js";

export class HamieProblemCard extends LitElement {
  static properties = {
    priority: { type: String }, // "high" | "medium" | "low" | unset (badge omitted)
    heading: { type: String },
    body: { type: String },
    actionLabel: { type: String },
    category: { type: String },
    dismissible: { type: Boolean },
  };

  static styles = css`
    :host {
      display: block;
    }
    .row {
      display: flex;
      align-items: flex-start;
      gap: var(--hamie-space-3);
    }
    hamie-status[variant="priority"] {
      margin-top: 2px;
      flex-shrink: 0;
    }
    .body {
      flex: 1;
      min-width: 0;
    }
    .title {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .text {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-3);
    }
    .category {
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-secondary);
      background: var(--hamie-surface-raised);
      padding: var(--hamie-space-half) var(--hamie-space-2);
      border-radius: var(--hamie-radius-sm);
    }
    .dismiss {
      flex-shrink: 0;
      margin-top: 2px;
      background: none;
      border: none;
      cursor: pointer;
      color: var(--hamie-text-secondary);
      padding: 0;
    }
    .dismiss:hover {
      color: var(--hamie-text-primary);
    }
    ha-icon {
      --mdc-icon-size: 14px;
    }
    ::slotted([slot="details"]) {
      margin-top: var(--hamie-space-2);
    }
  `;

  _onDismiss() {
    this.dispatchEvent(new CustomEvent("hamie-dismiss", { bubbles: true, composed: true }));
  }

  _onAction() {
    this.dispatchEvent(new CustomEvent("hamie-action", { bubbles: true, composed: true }));
  }

  render() {
    return html`
      <hamie-card padding="md">
        <div class="row">
          ${this.priority
            ? html`<hamie-status variant="priority" status=${this.priority}></hamie-status>`
            : null}
          <div class="body">
            <p class="title">${this.heading}</p>
            <p class="text">${this.body}</p>
            <slot name="details"></slot>
            <div class="actions">
              ${this.actionLabel
                ? html`
                    <hamie-button variant="primary" size="xs" @click=${this._onAction}>
                      ${this.actionLabel} <ha-icon icon="mdi:arrow-right"></ha-icon>
                    </hamie-button>
                  `
                : null}
              ${this.category ? html`<span class="category">${this.category}</span>` : null}
            </div>
          </div>
          ${this.dismissible
            ? html`
                <button class="dismiss" @click=${this._onDismiss} aria-label="Dismiss">
                  <ha-icon icon="mdi:close"></ha-icon>
                </button>
              `
            : null}
        </div>
      </hamie-card>
    `;
  }
}

if (!customElements.get("hamie-problem-card")) {
  customElements.define("hamie-problem-card", HamieProblemCard);
}
