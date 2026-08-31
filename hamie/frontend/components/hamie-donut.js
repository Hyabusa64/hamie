/**
 * <hamie-donut> — a small, lightweight donut chart: pure inline SVG, no
 * charting library, no canvas, no animation required. `.segments` is
 * `[{ label, value, tone }]` (tone a real --hamie-status-* token name).
 * Every count is also in the accessible text legend, never conveyed by
 * color alone. Handles zero-total, one-category, and large-imbalance
 * counts without special-casing by the caller.
 */
import { LitElement, css, html, svg } from "lit";

const SIZE = 120;
const STROKE = 16;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export class HamieDonut extends LitElement {
  static properties = {
    segments: { type: Array }, // [{ label, value, tone }]
  };

  static styles = css`
    :host {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-4);
    }
    svg {
      flex-shrink: 0;
      transform: rotate(-90deg);
    }
    .track {
      fill: none;
      stroke: var(--hamie-surface-hover);
    }
    .segment {
      fill: none;
    }
    .legend {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-1-5);
      font-size: var(--hamie-text-micro);
    }
    .legend-row {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      color: var(--hamie-text-secondary);
    }
    .swatch {
      width: 8px;
      height: 8px;
      border-radius: var(--hamie-radius-circle);
      flex-shrink: 0;
    }
    .legend-value {
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
  `;

  render() {
    const segments = (this.segments || []).filter((item) => item.value > 0);
    const total = segments.reduce((sum, item) => sum + item.value, 0);
    let offset = 0;
    const arcs = total
      ? segments.map((item) => {
          const fraction = item.value / total;
          const dash = fraction * CIRCUMFERENCE;
          const arc = svg`
            <circle
              class="segment"
              cx=${SIZE / 2}
              cy=${SIZE / 2}
              r=${RADIUS}
              stroke="var(--hamie-status-${item.tone})"
              stroke-width=${STROKE}
              stroke-dasharray="${dash} ${CIRCUMFERENCE - dash}"
              stroke-dashoffset=${-offset}
            ></circle>
          `;
          offset += dash;
          return arc;
        })
      : [];

    return html`
      <svg viewBox="0 0 ${SIZE} ${SIZE}" width=${SIZE} height=${SIZE} role="img" aria-label="Cleanup candidate breakdown">
        <circle class="track" cx=${SIZE / 2} cy=${SIZE / 2} r=${RADIUS} stroke-width=${STROKE}></circle>
        ${arcs}
      </svg>
      <ul class="legend" style="list-style: none; margin: 0; padding: 0;">
        ${(this.segments || []).map(
          (item) => html`
            <li class="legend-row">
              <span class="swatch" style="background: var(--hamie-status-${item.tone})"></span>
              <span class="legend-value">${item.value}</span>
              ${item.label}
            </li>
          `,
        )}
      </ul>
    `;
  }
}

if (!customElements.get("hamie-donut")) {
  customElements.define("hamie-donut", HamieDonut);
}
