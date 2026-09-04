/**
 * HAMIE-owned confirmation modal.
 *
 * Confirmation actions intentionally do not depend on Home Assistant dialog
 * action slots. HAMIE owns the backdrop, accessible dialog tree, body, footer,
 * focus lifecycle, typed confirmation, busy/error states, and submit lock.
 * Named fallback slots remain only for non-confirmation detail panels.
 */
import { LitElement, css, html } from "lit";

export class HamieDialog extends LitElement {
  static properties = {
    open: { type: Boolean, reflect: true },
    heading: { type: String },
    description: { type: String },
    cancelLabel: { type: String, attribute: "cancel-label" },
    confirmLabel: { type: String, attribute: "confirm-label" },
    destructive: { type: Boolean, reflect: true },
    busy: { type: Boolean, reflect: true },
    errorMessage: { type: String, attribute: "error-message" },
    confirmDisabled: { type: Boolean, attribute: "confirm-disabled" },
    typedConfirmationPhrase: { type: String, attribute: "typed-confirmation-phrase" },
    onConfirm: { attribute: false },
    onCancel: { attribute: false },
    onClose: { attribute: false },
    focusReturnTarget: { attribute: false },
    _typedValue: { state: true },
    _submitting: { state: true },
  };

  static styles = css`
    :host { position: fixed; inset: 0; z-index: 1000; display: none; }
    :host([open]) { display: block; }
    .backdrop {
      position: absolute; inset: 0; display: grid; place-items: center;
      box-sizing: border-box; padding: 16px; background: rgba(0, 0, 0, .62);
    }
    .dialog {
      display: flex; flex-direction: column; overflow: hidden;
      width: min(560px, calc(100vw - 32px)); max-height: calc(100vh - 32px);
      color: var(--hamie-text-primary); background: var(--hamie-surface-card);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg); box-shadow: var(--hamie-elevation-popover);
    }
    header {
      display: flex; align-items: flex-start; gap: var(--hamie-space-3);
      padding: var(--hamie-space-4); border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .heading-wrap { flex: 1; min-width: 0; }
    h2 { margin: 0; font-size: var(--hamie-text-base); }
    .description { margin: 4px 0 0; color: var(--hamie-text-secondary); }
    .close {
      width: 36px; height: 36px; border: 0; border-radius: var(--hamie-radius-md);
      color: inherit; background: transparent; cursor: pointer; font-size: 24px;
    }
    .close:hover { background: var(--hamie-surface-hover); }
    .body {
      overflow: auto; padding: var(--hamie-space-4);
      font-size: var(--hamie-text-small); color: var(--hamie-text-secondary); line-height: 1.6;
    }
    .typed { display: grid; gap: 6px; margin: 0 var(--hamie-space-4) var(--hamie-space-3); }
    .typed input {
      min-height: 40px; padding: 8px; color: inherit; background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-hairline); border-radius: var(--hamie-radius-md);
    }
    .error {
      margin: 0 var(--hamie-space-4) var(--hamie-space-3); padding: var(--hamie-space-2);
      color: var(--hamie-status-critical); background: var(--hamie-status-critical-fill);
      border-radius: var(--hamie-radius-md);
    }
    footer {
      display: flex; align-items: center; justify-content: flex-end; gap: var(--hamie-space-2);
      padding: var(--hamie-space-3) var(--hamie-space-4);
      border-top: 1px solid var(--hamie-border-hairline);
    }
    footer button {
      min-width: 92px; min-height: 40px; padding: 8px 14px; cursor: pointer;
      color: var(--hamie-text-primary); background: transparent;
      border: 1px solid var(--hamie-border-hairline); border-radius: var(--hamie-radius-md);
    }
    footer .confirm {
      color: var(--hamie-accent-on); background: var(--hamie-accent-fill-loud); border-color: transparent;
    }
    :host([destructive]) footer .confirm { background: var(--hamie-status-critical); }
    button:disabled, input:disabled { opacity: .48; cursor: not-allowed; }
    button:focus-visible, input:focus-visible { outline: 2px solid var(--hamie-accent); outline-offset: 2px; }
    @media (max-width: 600px) {
      .backdrop { align-items: end; padding: 0; }
      .dialog { width: 100vw; max-height: 92vh; border-radius: var(--hamie-radius-lg) var(--hamie-radius-lg) 0 0; }
      footer { flex-direction: column-reverse; }
      footer button { width: 100%; }
    }
  `;

  constructor() {
    super();
    this.open = false;
    this.cancelLabel = "";
    this.confirmLabel = "";
    this._typedValue = "";
    this._submitting = false;
  }

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
    queueMicrotask(() => this.shadowRoot?.querySelector(".dialog")?.focus());
  }

  _focusables() {
    const selector = 'button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[href],[tabindex]:not([tabindex="-1"])';
    return [...this.shadowRoot.querySelectorAll(selector), ...this.querySelectorAll(selector)]
      .filter((item) => item.getClientRects().length);
  }

  _onKeyDown = (event) => {
    if (!this.open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      this._cancel("escape");
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

  _emit(name, detail) {
    this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
  }

  _cancel(reason) {
    if (this.busy || this._submitting) return;
    this.onCancel?.(reason);
    this.onClose?.(reason);
    this._emit("hamie-cancel", { reason });
    this._emit("hamie-dialog-closed", { reason });
    const target = this.focusReturnTarget || this._returnTarget;
    queueMicrotask(() => target?.focus?.());
  }

  _confirmDisabled() {
    return this.busy || this._submitting || this.confirmDisabled ||
      (this.typedConfirmationPhrase && this._typedValue !== this.typedConfirmationPhrase);
  }

  async _confirm() {
    if (this._confirmDisabled()) return;
    this._submitting = true;
    this.requestUpdate();
    try {
      if (this.onConfirm) await this.onConfirm();
      this._emit("hamie-confirm");
    } finally {
      this._submitting = false;
      this.requestUpdate();
    }
  }

  render() {
    if (!this.open) return null;
    const ownedActions = this.cancelLabel || this.confirmLabel;
    return html`
      <div class="backdrop" @mousedown=${(event) => event.target === event.currentTarget && this._cancel("backdrop")}>
        <section class="dialog" role="dialog" aria-modal="true"
          aria-labelledby="hamie-title" aria-describedby="hamie-body" tabindex="-1"
          @mousedown=${(event) => event.stopPropagation()}>
          <header>
            <div class="heading-wrap">
              <h2 id="hamie-title">${this.heading}</h2>
              ${this.description ? html`<p class="description">${this.description}</p>` : null}
            </div>
            <button class="close" type="button" aria-label="Close"
              ?disabled=${this.busy || this._submitting}
              @click=${() => this._cancel("close")}>&times;</button>
          </header>
          <div id="hamie-body" class="body"><slot></slot></div>
          ${this.typedConfirmationPhrase ? html`
            <label class="typed">
              <span>Type <code>${this.typedConfirmationPhrase}</code> to continue</span>
              <input .value=${this._typedValue}
                ?disabled=${this.busy || this._submitting}
                @input=${(event) => (this._typedValue = event.target.value)}>
            </label>` : null}
          ${this.errorMessage ? html`<p class="error" role="alert">${this.errorMessage}</p>` : null}
          ${ownedActions ? html`
            <footer>
              ${this.cancelLabel ? html`<button type="button"
                ?disabled=${this.busy || this._submitting}
                @click=${() => this._cancel("cancel")}>${this.cancelLabel}</button>` : null}
              ${this.confirmLabel ? html`<button class="confirm" type="button"
                ?disabled=${this._confirmDisabled()} @click=${this._confirm}>
                ${this.busy || this._submitting ? "Working…" : this.confirmLabel}</button>` : null}
            </footer>` : html`
            <footer>
              <slot name="secondary-action"></slot>
              <slot name="primary-action"></slot>
            </footer>`}
        </section>
      </div>
    `;
  }
}

if (!customElements.get("hamie-dialog")) {
  customElements.define("hamie-dialog", HamieDialog);
}
