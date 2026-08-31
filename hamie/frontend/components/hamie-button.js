/**
 * <hamie-button> — reconstructed 1:1 from App.tsx's `Btn` component.
 *
 * Figma variants: primary/secondary/ghost/danger. Sizes: xs/sm/md.
 * Renders a native <button> (never a <div>) for correct focus/keyboard/
 * screen-reader semantics for free — Figma's own Btn is a real <button>
 * too, so this is a direct port, not an accessibility "improvement".
 */
import { LitElement, css, html, nothing } from "lit";

export class HamieButton extends LitElement {
  // Delegates focus to the real inner <button> -- without this, calling
  // `.focus()` on a <hamie-button> host element (e.g. to return focus to
  // a dialog's trigger after it closes) does nothing at all, since the
  // interactive element actually lives inside this component's own
  // shadow root, not on the host.
  static shadowRootOptions = { ...LitElement.shadowRootOptions, delegatesFocus: true };

  static properties = {
    variant: { type: String }, // "primary" | "secondary" | "ghost" (default) | "danger"
    size: { type: String }, // "xs" | "sm" (default) | "md"
    disabled: { type: Boolean, reflect: true },
  };

  static styles = css`
    :host {
      display: inline-flex;
    }
    button {
      display: inline-flex;
      align-items: center;
      font-family: inherit;
      font-weight: var(--hamie-weight-medium);
      cursor: pointer;
      border: 1px solid transparent;
      transition:
        background-color var(--hamie-motion-fast) var(--hamie-motion-ease),
        color var(--hamie-motion-fast) var(--hamie-motion-ease);
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.5;
    }
    button:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 2px;
    }
    /* --mdc-icon-size is how every other component in the library sizes
     * <ha-icon> (see shared-styles.js and hamie-status/hamie-empty/etc.)
     * -- kept consistent here rather than the width/height override this
     * used to have, which was the only component sizing icons that way. */
    ::slotted(ha-icon) {
      --mdc-icon-size: 0.85em;
    }

    /* Sizes */
    :host([size="xs"]) button {
      padding: var(--hamie-space-1) var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      border-radius: var(--hamie-radius-sm);
      gap: var(--hamie-space-1);
    }
    :host([size="md"]) button {
      padding: var(--hamie-space-2) var(--hamie-space-4);
      font-size: var(--hamie-text-small);
      border-radius: var(--hamie-radius-md);
      gap: var(--hamie-space-2);
    }
    :host(:not([size])) button,
    :host([size="sm"]) button {
      padding: var(--hamie-space-1-5) var(--hamie-space-2-5);
      font-size: var(--hamie-text-micro);
      border-radius: var(--hamie-radius-sm);
      gap: var(--hamie-space-1-5);
    }

    /* Variants */
    :host(:not([variant])) button,
    :host([variant="ghost"]) button {
      background: transparent;
      color: var(--hamie-text-secondary);
    }
    :host(:not([variant])) button:hover:not(:disabled),
    :host([variant="ghost"]) button:hover:not(:disabled) {
      background: var(--hamie-surface-hover);
      color: var(--hamie-text-primary);
    }

    :host([variant="primary"]) button {
      background: var(--hamie-accent-fill-loud);
      color: var(--hamie-accent-on);
    }
    :host([variant="primary"]) button:hover:not(:disabled) {
      filter: brightness(1.1);
    }

    :host([variant="secondary"]) button {
      background: var(--hamie-surface-raised);
      color: var(--hamie-text-primary);
      border-color: var(--hamie-border-normal);
    }
    :host([variant="secondary"]) button:hover:not(:disabled) {
      background: var(--hamie-surface-hover);
    }

    :host([variant="danger"]) button {
      background: var(--hamie-danger-fill);
      color: var(--hamie-danger);
      border-color: var(--hamie-danger-border);
    }
    :host([variant="danger"]) button:hover:not(:disabled) {
      filter: brightness(1.1);
    }
  `;

  render() {
    // An `aria-label` set on this host element (e.g. an icon-only
    // dismiss button) has no effect on its own -- the host has no
    // implicit ARIA role, and the real interactive element is the
    // native <button> rendered inside this shadow root, which needs
    // the name forwarded onto it directly.
    const label = this.getAttribute("aria-label");
    return html`
      <button ?disabled=${this.disabled} aria-label=${label || nothing}>
        <slot></slot>
      </button>
    `;
  }
}

if (!customElements.get("hamie-button")) {
  customElements.define("hamie-button", HamieButton);
}
