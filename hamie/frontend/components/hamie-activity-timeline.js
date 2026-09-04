/**
 * <hamie-activity-timeline> — chronological operational timeline (spec:
 * "findings opened/resolved, scans, analyzer failures, review decisions
 * -- not a raw log dump"). New primitive; the existing Audit screen
 * (hamie-view-audit.js) renders the identical real `hamie/audit/list`
 * data as a <hamie-table> instead -- same real fields, genuinely
 * different presentation for a genuinely different reading mode (a
 * scannable table for filtering/exporting vs. a connected day-grouped
 * timeline for "what happened recently").
 *
 * `items`: `[{ id, heading, meta, time (ISO), tone, icon }]`. `tone` is
 * a real `--hamie-status-*` token name (this component never invents a
 * new palette); `time` renders through `relativeTime()` at the call
 * site, not here, so every caller keeps one real formatting convention
 * (format.js) instead of a second one living inside this component.
 */
import { LitElement, css, html } from "lit";

export class HamieActivityTimeline extends LitElement {
  static properties = {
    items: { type: Array }, // [{ id, heading, meta, timeLabel, tone, icon }]
    interactive: { type: Boolean, reflect: true },
  };

  static styles = css`
    :host {
      display: block;
    }
    .row {
      position: relative;
      display: flex;
      gap: var(--hamie-space-3);
      padding: 0 0 var(--hamie-space-4);
    }
    .row:last-child {
      padding-bottom: 0;
    }
    .rail {
      position: relative;
      flex-shrink: 0;
      width: 24px;
      display: flex;
      justify-content: center;
    }
    .dot {
      z-index: 1;
      width: 24px;
      height: 24px;
      border-radius: var(--hamie-radius-circle);
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .dot ha-icon {
      --mdc-icon-size: 12px;
    }
    .line {
      position: absolute;
      top: 24px;
      bottom: -16px;
      width: 1px;
      background: var(--hamie-border-hairline);
    }
    .row:last-child .line {
      display: none;
    }
    .body {
      flex: 1;
      min-width: 0;
      padding-top: 2px;
    }
    .top {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .heading {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .time {
      flex-shrink: 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      font-family: var(--hamie-font-code);
    }
    .meta {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    button.body {
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      text-align: left;
      cursor: pointer;
      border-radius: var(--hamie-radius-sm);
    }
    button.body:hover .heading {
      color: var(--hamie-accent);
    }
    button.body:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 2px;
    }
  `;

  _onClick(id) {
    if (!this.interactive) return;
    this.dispatchEvent(new CustomEvent("hamie-timeline-click", { detail: { id }, bubbles: true, composed: true }));
  }

  render() {
    const items = this.items || [];
    return html`
      ${items.map((item) => {
        const body = html`
          <span class="top">
            <p class="heading">${item.heading}</p>
            <span class="time">${item.timeLabel}</span>
          </span>
          ${item.meta ? html`<p class="meta">${item.meta}</p>` : null}
        `;
        return html`
          <div class="row">
            <span class="rail">
              <span class="dot" style="background: var(--hamie-status-${item.tone || "unknown"}-fill)">
                <ha-icon icon=${item.icon || "mdi:circle-small"} style="color: var(--hamie-status-${item.tone || "unknown"})"></ha-icon>
              </span>
              <span class="line"></span>
            </span>
            ${this.interactive
              ? html`<button type="button" class="body" @click=${() => this._onClick(item.id)}>${body}</button>`
              : html`<span class="body">${body}</span>`}
          </div>
        `;
      })}
    `;
  }
}

if (!customElements.get("hamie-activity-timeline")) {
  customElements.define("hamie-activity-timeline", HamieActivityTimeline);
}
