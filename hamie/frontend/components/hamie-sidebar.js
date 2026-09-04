/** HAMIE navigation with a session-persistent Advanced disclosure. */
import { LitElement, css, html } from "lit";
import "./hamie-status.js";

export class HamieSidebar extends LitElement {
  static properties = {
    items: { type: Array },
    activeId: { type: String },
    statusText: { type: String },
    statusOk: { type: Boolean },
    _advancedExpanded: { state: true },
  };

  static styles = css`
    :host {
      display: flex; flex-direction: column; width: var(--hamie-sidebar-width);
      flex-shrink: 0; height: 100%; box-sizing: border-box;
      background: var(--hamie-surface-sidebar); border-right: 1px solid var(--hamie-border-hairline);
    }
    .logo {
      display: flex; align-items: center; gap: var(--hamie-space-2-5);
      padding: var(--hamie-space-4); border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .mark {
      display: flex; align-items: center; justify-content: center; flex-shrink: 0;
      width: 28px; height: 28px; border-radius: var(--hamie-radius-md);
      background: var(--hamie-accent-fill-loud);
    }
    .name {
      color: var(--hamie-text-primary); font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium); line-height: 1;
    }
    .version {
      margin-top: 2px; color: var(--hamie-text-secondary);
      font: var(--hamie-text-caption)/1 var(--hamie-font-code);
    }
    nav {
      display: flex; flex: 1; flex-direction: column; gap: 2px;
      overflow-y: auto; padding: var(--hamie-space-3) var(--hamie-space-2);
    }
    button {
      display: flex; align-items: center; gap: var(--hamie-space-2-5);
      width: 100%; box-sizing: border-box; padding: 7px var(--hamie-space-2-5);
      border: 0; border-radius: var(--hamie-radius-md);
      color: var(--hamie-text-secondary); background: transparent; cursor: pointer;
      font: var(--hamie-weight-medium) var(--hamie-text-small)/1.3 inherit; text-align: left;
    }
    button:hover { color: var(--hamie-text-primary); background: var(--hamie-surface-hover); }
    button[aria-current="page"] { color: var(--hamie-accent); background: var(--hamie-accent-fill-quiet); }
    button:focus-visible { outline: 2px solid var(--hamie-accent); outline-offset: -2px; }
    .label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .badge {
      padding: 1px var(--hamie-space-1-5); border-radius: var(--hamie-radius-pill);
      color: var(--hamie-accent-on); background: var(--hamie-accent-fill-loud);
      font-size: var(--hamie-text-micro); font-weight: var(--hamie-weight-bold);
    }
    .children { display: grid; gap: 2px; }
    .children button { padding-left: calc(var(--hamie-space-2-5) + 24px); }
    .chevron { margin-left: auto; }
    ha-icon { --mdc-icon-size: 14px; flex-shrink: 0; }
    .footer { padding: var(--hamie-space-3); border-top: 1px solid var(--hamie-border-hairline); }
    .divider { height: 1px; margin: var(--hamie-space-2) var(--hamie-space-2-5); background: var(--hamie-border-hairline); border: 0; }
  `;

  constructor() {
    super();
    this._advancedExpanded = sessionStorage.getItem("hamieAdvancedExpanded") === "true";
  }

  updated(changed) {
    const activeIsAdvanced = (this.items || []).some((item) => item.children?.some((child) => child.id === this.activeId));
    if (changed.has("activeId") && activeIsAdvanced && !this._advancedExpanded) {
      this._advancedExpanded = true;
      sessionStorage.setItem("hamieAdvancedExpanded", "true");
    }
  }

  _onNavigate(id) {
    this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id }, bubbles: true, composed: true }));
  }

  _toggleAdvanced() {
    this._advancedExpanded = !this._advancedExpanded;
    sessionStorage.setItem("hamieAdvancedExpanded", String(this._advancedExpanded));
  }

  _renderItem(item) {
    if (!item.children) return html`
      <button aria-current=${item.id === this.activeId ? "page" : "false"} @click=${() => this._onNavigate(item.id)}>
        <ha-icon icon=${item.icon}></ha-icon>
        <span class="label">${item.label}</span>
        ${item.badge ? html`<span class="badge">${item.badge}</span>` : null}
      </button>`;
    return html`
      <button aria-expanded=${String(this._advancedExpanded)} aria-controls="hamie-advanced-navigation" @click=${this._toggleAdvanced}>
        <ha-icon icon=${item.icon}></ha-icon>
        <span class="label">${item.label}</span>
        ${item.badge ? html`<span class="badge">${item.badge}</span>` : null}
        <ha-icon class="chevron" icon=${this._advancedExpanded ? "mdi:chevron-up" : "mdi:chevron-down"}></ha-icon>
      </button>
      ${this._advancedExpanded ? html`
        <div id="hamie-advanced-navigation" class="children" role="group" aria-label="Advanced">
          ${item.children.map((child) => html`
            <button aria-current=${child.id === this.activeId ? "page" : "false"} @click=${() => this._onNavigate(child.id)}>
              <ha-icon icon=${child.icon}></ha-icon>
              <span class="label">${child.label}</span>
            </button>`)}
        </div>` : null}`;
  }

  render() {
    return html`
      <div class="logo">
        <div class="mark"><ha-icon icon="mdi:shield-home"></ha-icon></div>
        <div><div class="name">HAMIE</div><div class="version"><slot name="version"></slot></div></div>
      </div>
      <nav aria-label="HAMIE sections">
        ${(this.items || []).map(
          (item) => html`${item.dividerBefore ? html`<hr class="divider" role="separator" />` : null}${this._renderItem(item)}`,
        )}
      </nav>
      <div class="footer">
        <hamie-status variant="dot" status=${this.statusOk ? "healthy" : "warning"} label=${this.statusText}></hamie-status>
      </div>`;
  }
}

if (!customElements.get("hamie-sidebar")) {
  customElements.define("hamie-sidebar", HamieSidebar);
}
