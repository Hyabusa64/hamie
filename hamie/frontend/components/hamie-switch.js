/**
 * <hamie-switch> — reconstructed 1:1 from App.tsx's `Toggle`.
 *
 * Home Assistant's own <ha-switch> is globally available on the same page
 * (custom panels render in HA's own document, not an iframe, confirmed
 * against the current production panel's existing <ha-icon> usage) and
 * was considered, but its Material/MWC proportions and color defaults
 * don't reproduce Figma's specific 36x20px pill + sliding-thumb look
 * closely enough to hit the required 95% similarity target — so this is
 * a deliberate custom reconstruction, not a missed reuse opportunity.
 */
import { LitElement, css, html } from "lit";

export class HamieSwitch extends LitElement {
  static properties = {
    checked: { type: Boolean, reflect: true },
    disabled: { type: Boolean, reflect: true },
  };

  // Without an explicit default, `checked`/`disabled` start life as
  // `undefined` rather than `false` -- and since the `?checked=${...}`
  // binding a parent uses only ever *toggles the attribute*, a switch
  // whose real value is false from first render (never flipped true)
  // never gets an attributeChangedCallback at all, so the property is
  // left `undefined` forever instead of `false`. Any code that reads
  // `.checked` directly (not just `aria-checked` in this render(), which
  // happened to mask it by coercing with `? "true" : "false"`) would see
  // the wrong type for an off switch that was never touched.
  constructor() {
    super();
    this.checked = false;
    this.disabled = false;
  }

  static styles = css`
    :host {
      display: inline-flex;
    }
    button {
      position: relative;
      width: 36px;
      height: 20px;
      border-radius: var(--hamie-radius-pill);
      border: none;
      padding: 0;
      cursor: pointer;
      background: var(--hamie-surface-raised);
      transition: background-color var(--hamie-motion-fast) var(--hamie-motion-ease);
      flex-shrink: 0;
    }
    button[aria-checked="true"] {
      background: var(--hamie-accent-fill-loud);
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    button:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 2px;
    }
    .thumb {
      position: absolute;
      top: 2px;
      left: 2px;
      width: 16px;
      height: 16px;
      border-radius: var(--hamie-radius-circle);
      background: var(--hamie-accent-on);
      transition: transform var(--hamie-motion-fast) var(--hamie-motion-ease);
    }
    button[aria-checked="true"] .thumb {
      transform: translateX(16px);
    }
  `;

  _toggle() {
    if (this.disabled) return;
    this.checked = !this.checked;
    this.dispatchEvent(
      new CustomEvent("hamie-change", {
        detail: { checked: this.checked },
        bubbles: true,
        composed: true,
      }),
    );
  }

  render() {
    return html`
      <button
        type="button"
        role="switch"
        aria-checked=${this.checked ? "true" : "false"}
        ?disabled=${this.disabled}
        @click=${this._toggle}
      >
        <span class="thumb"></span>
      </button>
    `;
  }
}

if (!customElements.get("hamie-switch")) {
  customElements.define("hamie-switch", HamieSwitch);
}
