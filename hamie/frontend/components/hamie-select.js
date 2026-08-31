/**
 * <hamie-select> — reconstructed from App.tsx's inline native <select>
 * usage (Settings: scan interval / model / retention). Figma never wraps
 * this repeated pattern in its own component, but it appears three times
 * with identical styling — componentizing an already-repeated pattern
 * satisfies "no page should introduce duplicated styling", it isn't a new
 * invention.
 */
import { LitElement, css, html } from "lit";

export class HamieSelect extends LitElement {
  static properties = {
    value: { type: String },
    options: { type: Array }, // [{ value, label }]
    disabled: { type: Boolean, reflect: true },
  };

  static styles = css`
    :host {
      display: block;
    }
    select {
      width: 100%;
      box-sizing: border-box;
      font-family: inherit;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
      background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-normal);
      border-radius: var(--hamie-radius-md);
      padding: var(--hamie-space-1-5) var(--hamie-space-2-5);
      cursor: pointer;
    }
    select:focus {
      outline: none;
      border-color: var(--hamie-accent);
    }
    select:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  `;

  _onChange(event) {
    this.value = event.target.value;
    this.dispatchEvent(
      new CustomEvent("hamie-change", {
        detail: { value: this.value },
        bubbles: true,
        composed: true,
      }),
    );
  }

  render() {
    return html`
      <select .value=${this.value || ""} ?disabled=${this.disabled} @change=${this._onChange}>
        ${(this.options || []).map(
          (opt) => html`<option value=${opt.value} ?selected=${opt.value === this.value}>${opt.label}</option>`,
        )}
      </select>
    `;
  }
}

if (!customElements.get("hamie-select")) {
  customElements.define("hamie-select", HamieSelect);
}
