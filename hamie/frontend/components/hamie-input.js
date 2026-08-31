/**
 * <hamie-input> — reconstructed 1:1 from App.tsx's `Input`.
 * Text input, optional leading icon. Dispatches a bubbling, composed
 * "hamie-input" CustomEvent with `{ value }` on every keystroke (mirrors
 * Figma's onChange(value) callback prop, adapted to DOM event convention
 * since Lit components communicate outward via events, not callback props).
 */
import { LitElement, css, html } from "lit";

export class HamieInput extends LitElement {
  static properties = {
    value: { type: String },
    placeholder: { type: String },
    icon: { type: String }, // mdi:* icon name
    type: { type: String }, // "text" (default) | "password" | "url"
    disabled: { type: Boolean, reflect: true },
  };

  static styles = css`
    :host {
      display: block;
      position: relative;
    }
    ha-icon {
      position: absolute;
      left: var(--hamie-space-2-5);
      top: 50%;
      transform: translateY(-50%);
      --mdc-icon-size: 12px;
      color: var(--hamie-text-secondary);
      pointer-events: none;
    }
    input {
      width: 100%;
      box-sizing: border-box;
      font-family: inherit;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
      background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-normal);
      border-radius: var(--hamie-radius-md);
      padding: var(--hamie-space-1-5) var(--hamie-space-3);
      transition: border-color var(--hamie-motion-fast) var(--hamie-motion-ease);
    }
    :host([icon]) input {
      padding-left: calc(var(--hamie-space-2-5) + 12px + var(--hamie-space-1-5));
    }
    input::placeholder {
      color: var(--hamie-text-secondary);
    }
    input:focus {
      outline: none;
      border-color: var(--hamie-accent);
    }
    input:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  `;

  _onInput(event) {
    this.value = event.target.value;
    this.dispatchEvent(
      new CustomEvent("hamie-input", {
        detail: { value: this.value },
        bubbles: true,
        composed: true,
      }),
    );
  }

  render() {
    return html`
      ${this.icon ? html`<ha-icon icon=${this.icon}></ha-icon>` : null}
      <input
        type=${this.type || "text"}
        .value=${this.value || ""}
        placeholder=${this.placeholder || ""}
        ?disabled=${this.disabled}
        @input=${this._onInput}
      />
    `;
  }
}

if (!customElements.get("hamie-input")) {
  customElements.define("hamie-input", HamieInput);
}
