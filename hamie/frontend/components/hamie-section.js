/**
 * <hamie-section> — reconstructed 1:1 from App.tsx's `SectionHeader`.
 * Title + optional description, optional right-aligned action (slot).
 */
import { LitElement, css, html } from "lit";

export class HamieSection extends LitElement {
  static properties = {
    heading: { type: String },
    description: { type: String },
  };

  static styles = css`
    :host {
      display: block;
      margin-bottom: var(--hamie-space-4);
    }
    .row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
    }
    h2 {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    p {
      margin: var(--hamie-space-half) 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
  `;

  render() {
    return html`
      <div class="row">
        <div>
          <h2>${this.heading}</h2>
          ${this.description ? html`<p>${this.description}</p>` : null}
        </div>
        <slot name="action"></slot>
      </div>
    `;
  }
}

if (!customElements.get("hamie-section")) {
  customElements.define("hamie-section", HamieSection);
}
