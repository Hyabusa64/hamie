/**
 * <hamie-drawer> — right-side detail panel on desktop, full-screen sheet
 * on mobile/tablet. Shares hamie-dialog's accessible-dialog machinery
 * (focus trap, ESC-to-close, backdrop click, focus-return) rather than
 * re-implementing it: the two components solve the same "modal overlay
 * with owned focus lifecycle" problem, just with different geometry
 * (centered card vs. edge-anchored panel) and no forced confirm/cancel
 * footer -- a drawer is for routine inspection (Finding/Group/Batch
 * detail), not a confirmation gate.
 */
import { LitElement, css, html } from "lit";

export class HamieDrawer extends LitElement {
  static properties = {
    open: { type: Boolean, reflect: true },
    wide: { type: Boolean, reflect: true },
    heading: { type: String },
    description: { type: String },
    onClose: { attribute: false },
    focusReturnTarget: { attribute: false },
  };

  static styles = css`
    :host {
      position: fixed;
      inset: 0;
      z-index: 1000;
      display: none;
    }
    :host([open]) {
      display: block;
    }
    .backdrop {
      position: absolute;
      inset: 0;
      background: rgba(0, 0, 0, 0.5);
      animation: hamie-fade-in var(--hamie-motion-normal) var(--hamie-motion-ease);
    }
    .panel {
      position: absolute;
      top: 0;
      right: 0;
      bottom: 0;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      width: min(420px, 100vw);
      color: var(--hamie-text-primary);
      background: var(--hamie-surface-card);
      border-left: 1px solid var(--hamie-border-hairline);
      box-shadow: var(--hamie-elevation-popover);
      animation: hamie-slide-in var(--hamie-motion-normal) var(--hamie-motion-ease);
    }
    :host([wide]) .panel {
      width: min(1000px, 100vw);
    }
    @keyframes hamie-fade-in {
      from {
        opacity: 0;
      }
    }
    @keyframes hamie-slide-in {
      from {
        transform: translateX(100%);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .backdrop,
      .panel {
        animation: none;
      }
    }
    header {
      display: flex;
      align-items: flex-start;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-4);
      border-bottom: 1px solid var(--hamie-border-hairline);
      flex-shrink: 0;
    }
    .heading-wrap {
      flex: 1;
      min-width: 0;
    }
    h2 {
      margin: 0;
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium);
      overflow-wrap: anywhere;
    }
    .description {
      margin: 4px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      overflow-wrap: anywhere;
    }
    .close {
      width: 32px;
      height: 32px;
      flex-shrink: 0;
      border: 0;
      border-radius: var(--hamie-radius-md);
      color: var(--hamie-text-secondary);
      background: transparent;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .close:hover {
      background: var(--hamie-surface-hover);
      color: var(--hamie-text-primary);
    }
    .close:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 2px;
    }
    .body {
      flex: 1;
      overflow-y: auto;
      padding: var(--hamie-space-4);
    }
    @media (max-width: 600px) {
      .panel {
        top: auto;
        left: 0;
        width: 100vw;
        height: min(92vh, 100%);
        border-left: 0;
        border-top: 1px solid var(--hamie-border-hairline);
        border-radius: var(--hamie-radius-lg) var(--hamie-radius-lg) 0 0;
      }
      @keyframes hamie-slide-in {
        from {
          transform: translateY(100%);
        }
      }
    }
  `;

  connectedCallback() {
    this._returnTarget = this.focusReturnTarget || this.getRootNode()?.activeElement || document.activeElement;
    super.connectedCallback();
    document.addEventListener("keydown", this._onKeyDown, true);
  }

  disconnectedCallback() {
    document.removeEventListener("keydown", this._onKeyDown, true);
    super.disconnectedCallback();
  }

  firstUpdated() {
    queueMicrotask(() => this.shadowRoot?.querySelector(".panel")?.focus());
  }

  _focusables() {
    const selector = 'button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[href],[tabindex]:not([tabindex="-1"])';
    return [...this.shadowRoot.querySelectorAll(selector), ...this.querySelectorAll(selector)].filter(
      (item) => item.getClientRects().length,
    );
  }

  _onKeyDown = (event) => {
    if (!this.open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      this._close("escape");
      return;
    }
    if (event.key !== "Tab") return;
    const items = this._focusables();
    if (!items.length) return;
    const active = this.shadowRoot.activeElement || document.activeElement;
    if (event.shiftKey && active === items[0]) {
      event.preventDefault();
      items.at(-1).focus();
    } else if (!event.shiftKey && active === items.at(-1)) {
      event.preventDefault();
      items[0].focus();
    }
  };

  _close(reason) {
    this.onClose?.(reason);
    this.dispatchEvent(new CustomEvent("hamie-drawer-closed", { detail: { reason }, bubbles: true, composed: true }));
    const target = this.focusReturnTarget || this._returnTarget;
    queueMicrotask(() => target?.focus?.());
  }

  render() {
    if (!this.open) return null;
    return html`
      <div class="backdrop" @mousedown=${(event) => event.target === event.currentTarget && this._close("backdrop")}></div>
      <section
        class="panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="hamie-drawer-title"
        tabindex="-1"
      >
        <header>
          <div class="heading-wrap">
            <h2 id="hamie-drawer-title">${this.heading}</h2>
            ${this.description ? html`<p class="description">${this.description}</p>` : null}
          </div>
          <button class="close" type="button" aria-label="Close" @click=${() => this._close("close")}>
            <ha-icon icon="mdi:close"></ha-icon>
          </button>
        </header>
        <div class="body"><slot></slot></div>
      </section>
    `;
  }
}

if (!customElements.get("hamie-drawer")) {
  customElements.define("hamie-drawer", HamieDrawer);
}
