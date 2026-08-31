/**
 * <hamie-disclosure> — a single collapsed-by-default "Label ▾" toggle
 * used everywhere HAMIE hides internal/verbose detail behind progressive
 * disclosure (Technical details, Evidence, Affected objects, the
 * dependency graph). One real <button>+<region> pair with correct
 * aria-expanded/aria-controls semantics, reused instead of every view
 * hand-rolling its own expand/collapse state and markup.
 */
import { LitElement, css, html } from "lit";

let uid = 0;

export class HamieDisclosure extends LitElement {
  static properties = {
    label: { type: String },
    open: { type: Boolean, reflect: true },
  };

  static styles = css`
    :host {
      display: block;
    }
    button {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      width: 100%;
      padding: var(--hamie-space-2) 0;
      border: 0;
      background: transparent;
      color: var(--hamie-text-secondary);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      cursor: pointer;
      text-align: left;
    }
    button:hover {
      color: var(--hamie-text-primary);
    }
    button:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 2px;
      border-radius: var(--hamie-radius-sm);
    }
    ha-icon {
      --mdc-icon-size: 16px;
      transition: transform var(--hamie-motion-fast) var(--hamie-motion-ease);
    }
    :host([open]) ha-icon {
      transform: rotate(180deg);
    }
    .region {
      padding-top: var(--hamie-space-2);
    }
  `;

  constructor() {
    super();
    this.open = false;
    this._id = `hamie-disclosure-${uid++}`;
  }

  _toggle() {
    this.open = !this.open;
  }

  render() {
    return html`
      <button type="button" aria-expanded=${String(this.open)} aria-controls=${this._id} @click=${this._toggle}>
        <ha-icon icon="mdi:chevron-down"></ha-icon>
        ${this.label}
      </button>
      ${this.open ? html`<div id=${this._id} class="region" role="region"><slot></slot></div>` : null}
    `;
  }
}

if (!customElements.get("hamie-disclosure")) {
  customElements.define("hamie-disclosure", HamieDisclosure);
}
