/**
 * <hamie-card> — reconstructed 1:1 from App.tsx's `Card` component.
 *
 * Figma: `bg-[#1a1d24] border border-white/[0.06] rounded-lg`. Flat,
 * bordered surface — no shadow (see design/elevation.css for why).
 */
import { LitElement, css, html } from "lit";

export class HamieCard extends LitElement {
  static properties = {
    padding: { type: String }, // "none" | "sm" | "md" (default)
  };

  static styles = css`
    :host {
      display: block;
      background: var(--hamie-surface-card);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg);
    }
    :host([padding="sm"]) .content {
      padding: var(--hamie-space-3);
    }
    :host([padding="md"]) .content,
    :host(:not([padding])) .content {
      padding: var(--hamie-space-4);
    }
    :host([padding="none"]) .content {
      padding: 0;
    }
  `;

  render() {
    return html`<div class="content"><slot></slot></div>`;
  }
}

if (!customElements.get("hamie-card")) {
  customElements.define("hamie-card", HamieCard);
}
