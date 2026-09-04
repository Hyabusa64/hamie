/**
 * <hamie-page-header> — the page title + subtitle + trailing actions row
 * every top-level view hand-rolled independently (Overview, Findings,
 * Review Queue, House Health, ...): an h1, a one-line secondary/subtitle
 * paragraph, and a right-aligned actions slot. Consolidated once here as
 * part of the maintenance-console redesign's shared primitive pass.
 */
import { LitElement, css, html } from "lit";

export class HamiePageHeader extends LitElement {
  static properties = {
    heading: { type: String },
    subtitle: { type: String },
  };

  static styles = css`
    :host {
      display: block;
      margin-bottom: var(--hamie-space-5);
    }
    .row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-4);
      flex-wrap: wrap;
    }
    h1 {
      margin: 0;
      font-size: var(--hamie-text-metric);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      letter-spacing: -0.01em;
    }
    .subtitle {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      flex-shrink: 0;
    }
  `;

  render() {
    return html`
      <div class="row">
        <div>
          <h1>${this.heading}</h1>
          ${this.subtitle ? html`<p class="subtitle">${this.subtitle}</p>` : null}
        </div>
        <div class="actions"><slot name="actions"></slot></div>
      </div>
      <slot></slot>
    `;
  }
}

if (!customElements.get("hamie-page-header")) {
  customElements.define("hamie-page-header", HamiePageHeader);
}
