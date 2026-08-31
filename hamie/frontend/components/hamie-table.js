/**
 * <hamie-table> — reconstructed 1:1 from App.tsx's `Table` + `TR`.
 *
 * `columns`: string[] of header labels.
 * `rows`: array of arrays; each cell may be a string or a Lit
 * TemplateResult (so callers can embed <hamie-status>, <ha-icon>, etc.,
 * exactly like Figma embeds JSX inside table cells).
 * When `rows` is empty, callers fill the "empty" slot (e.g. with
 * <hamie-empty>) rather than this component inventing its own empty copy.
 *
 * Figma's table has no responsive treatment at all (it was never designed
 * for a narrow viewport). Verified in real Chromium at a 390px viewport:
 * without help, the fixed nowrap columns overflow and clip content with
 * no way to reach it. Wrapped in a horizontally-scrollable container so
 * every column stays reachable (via swipe/scroll) instead of being cut
 * off -- fixed once here so every current and future screen using
 * hamie-table gets it for free.
 */
import { LitElement, css, html } from "lit";
import { repeat } from "lit/directives/repeat.js";

export class HamieTable extends LitElement {
  static properties = {
    columns: { type: Array },
    rows: { type: Array }, // [{ id, cells: [...] }]
  };

  static styles = css`
    :host {
      display: block;
    }
    .scroll {
      overflow-x: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
    }
    thead tr {
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    th {
      padding: var(--hamie-space-2-5) var(--hamie-space-4);
      text-align: left;
      font-size: var(--hamie-text-caption);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-text-secondary);
      white-space: nowrap;
    }
    tbody tr {
      border-bottom: 1px solid var(--hamie-surface-raised);
      transition: background-color var(--hamie-motion-fast) var(--hamie-motion-ease);
    }
    tbody tr:last-child {
      border-bottom: none;
    }
    tbody tr:hover {
      background: var(--hamie-surface-hover);
    }
    td {
      padding: var(--hamie-space-2-5) var(--hamie-space-4);
      font-size: var(--hamie-text-small);
      white-space: nowrap;
    }
  `;

  render() {
    const rows = this.rows || [];
    if (rows.length === 0) {
      return html`<slot name="empty"></slot>`;
    }
    return html`
      <div class="scroll">
        <table>
          <thead>
            <tr>
              ${(this.columns || []).map((col) => html`<th>${col}</th>`)}
            </tr>
          </thead>
          <tbody>
            ${repeat(
              rows,
              (row) => row.id,
              (row) => html`<tr>${row.cells.map((cell) => html`<td>${cell}</td>`)}</tr>`,
            )}
          </tbody>
        </table>
      </div>
    `;
  }
}

if (!customElements.get("hamie-table")) {
  customElements.define("hamie-table", HamieTable);
}
