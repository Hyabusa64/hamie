/**
 * <hamie-issue-row> — one compact, clickable row: optional leading icon,
 * title + meta text, optional trailing content (status/count/chevron).
 * The shared shape behind "Top issues" (Overview), Findings' issue-inbox
 * rows, and Review Queue's batch rows -- replacing three independently
 * hand-rolled row layouts (and, for Findings specifically, hundreds of
 * near-identical severity chips) with one primitive.
 *
 * Renders a real <button> (not a clickable <div>) when `interactive` is
 * set, so keyboard/screen-reader users get a real, focusable, announced
 * control -- consistent with hamie-button's own real-<button> discipline.
 */
import { LitElement, css, html } from "lit";

export class HamieIssueRow extends LitElement {
  static properties = {
    title: { type: String },
    meta: { type: String },
    interactive: { type: Boolean, reflect: true },
  };

  static styles = css`
    :host {
      display: block;
    }
    .row {
      display: flex;
      align-items: center;
      width: 100%;
      box-sizing: border-box;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-2-5) var(--hamie-space-1);
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      text-align: left;
      border-radius: var(--hamie-radius-md);
    }
    :host([interactive]) .row {
      cursor: pointer;
    }
    :host([interactive]) .row:hover {
      background: var(--hamie-surface-hover);
    }
    .row:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: -2px;
    }
    .leading {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .leading:empty {
      display: none;
    }
    .main {
      flex: 1;
      min-width: 0;
    }
    .title {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .meta {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    ::slotted([slot="extra"]) {
      display: block;
      margin-top: 2px;
    }
    .trailing {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
    }
    /* Below phone width, trailing content (a status label + chevron,
     * routinely 20+ characters) no longer fits beside the row's main
     * content without crushing it -- drop to its own line instead of
     * shrinking text further (spec: "stacked rows", not shrunk cards). */
    @media (max-width: 480px) {
      .row {
        flex-wrap: wrap;
      }
      .trailing {
        width: 100%;
        justify-content: flex-end;
        margin-top: var(--hamie-space-1);
      }
    }
  `;

  _onClick(event) {
    if (!this.interactive) return;
    this.dispatchEvent(new CustomEvent("hamie-row-click", { bubbles: true, composed: true }));
    event.stopPropagation();
  }

  render() {
    const inner = html`
      <span class="leading"><slot name="leading"></slot></span>
      <span class="main">
        <p class="title">${this.title}</p>
        ${this.meta ? html`<p class="meta">${this.meta}</p>` : null}
        <slot name="extra"></slot>
      </span>
      <span class="trailing"><slot name="trailing"></slot></span>
    `;
    return this.interactive
      ? html`<button type="button" class="row" @click=${this._onClick}>${inner}</button>`
      : html`<div class="row">${inner}</div>`;
  }
}

if (!customElements.get("hamie-issue-row")) {
  customElements.define("hamie-issue-row", HamieIssueRow);
}
