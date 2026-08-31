/**
 * <hamie-mini-meter> — one thin labeled horizontal health-dimension
 * meter: a label, a slim bar, and an integer score (0-100, 100 = best
 * for every dimension that uses this, per the maintenance-console
 * redesign's health-panel language). `value` absent/null renders an
 * honest "Not enough data" instead of a fabricated zero-width bar.
 */
import { LitElement, css, html } from "lit";

export class HamieMiniMeter extends LitElement {
  static properties = {
    label: { type: String },
    value: { type: Number }, // 0-100, omit for "not enough data"
    tone: { type: String }, // "healthy" | "warning" | "critical" | "unknown"
  };

  static styles = css`
    :host {
      display: block;
    }
    .row {
      display: grid;
      grid-template-columns: 90px 1fr 28px;
      align-items: center;
      gap: var(--hamie-space-2-5);
      padding: 3px 0;
    }
    .label {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .track {
      height: 5px;
      border-radius: var(--hamie-radius-pill);
      background: var(--hamie-surface-hover);
      overflow: hidden;
    }
    .fill {
      height: 100%;
      border-radius: var(--hamie-radius-pill);
    }
    .value {
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      text-align: right;
    }
    .unavailable {
      font-size: var(--hamie-text-caption);
      color: var(--hamie-text-secondary);
      font-style: italic;
    }
  `;

  render() {
    const hasValue = typeof this.value === "number" && !Number.isNaN(this.value);
    const pct = hasValue ? Math.max(0, Math.min(100, this.value)) : 0;
    const tone = this.tone || "healthy";
    return html`
      <div class="row">
        <span class="label">${this.label}</span>
        ${hasValue
          ? html`
              <span class="track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow=${pct} aria-label=${this.label}>
                <span class="fill" style="width:${pct}%; background: var(--hamie-status-${tone})"></span>
              </span>
              <span class="value">${pct}</span>
            `
          : html`<span class="unavailable" style="grid-column: 2 / -1">Not enough data</span>`}
      </div>
    `;
  }
}

if (!customElements.get("hamie-mini-meter")) {
  customElements.define("hamie-mini-meter", HamieMiniMeter);
}
