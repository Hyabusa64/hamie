/**
 * <hamie-empty> — reconstructed from App.tsx's two inline empty-state
 * patterns (FindingsPage's neutral "no findings match this filter" and
 * RecommendationsPage's positive "All clear"), plus a third tone this
 * project needs that Figma never designed: `unavailable`, an honest
 * "not available" state for backend data that genuinely doesn't exist
 * yet (House Health / Intelligence / Security screens where no fabricated
 * numbers are ever shown — see the design audit's real-data decision).
 * Extending Figma's existing two-tone empty-state pattern to a third tone
 * is a legitimate, documented extension, not a new design language.
 */
import { LitElement, css, html } from "lit";

const TONE_ICON = {
  neutral: "mdi:check-circle-outline",
  positive: "mdi:check-circle",
  unavailable: "mdi:information-outline",
};

export class HamieEmpty extends LitElement {
  static properties = {
    tone: { type: String }, // "neutral" (default) | "positive" | "unavailable"
    heading: { type: String },
    description: { type: String },
  };

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      padding: var(--hamie-space-8) var(--hamie-space-4);
    }
    ha-icon {
      --mdc-icon-size: 24px;
      margin-bottom: var(--hamie-space-3);
    }
    :host([tone="positive"]) ha-icon {
      color: var(--hamie-status-healthy);
    }
    :host(:not([tone])) ha-icon,
    :host([tone="neutral"]) ha-icon {
      color: var(--hamie-text-secondary);
    }
    :host([tone="unavailable"]) ha-icon {
      color: var(--hamie-text-disabled);
    }
    .heading {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .description {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      max-width: 32em;
    }
  `;

  render() {
    const tone = this.tone || "neutral";
    return html`
      <ha-icon icon=${TONE_ICON[tone]}></ha-icon>
      <p class="heading">${this.heading}</p>
      ${this.description ? html`<p class="description">${this.description}</p>` : null}
    `;
  }
}

if (!customElements.get("hamie-empty")) {
  customElements.define("hamie-empty", HamieEmpty);
}
