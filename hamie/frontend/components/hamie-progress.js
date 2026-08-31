/**
 * <hamie-progress> — a small inline progress surface for Scan/Clean Up
 * feedback: a label, an optional stage line, and a bar. Determinate when
 * `value` (0-100) is set; indeterminate (a sliding highlight) otherwise,
 * since neither the scan nor the cleanup pipeline reports real percent
 * completion today -- an indeterminate bar is honest about that, never a
 * fabricated percentage.
 */
import { LitElement, css, html } from "lit";

export class HamieProgress extends LitElement {
  static properties = {
    label: { type: String },
    stage: { type: String },
    value: { type: Number }, // 0-100, omit for indeterminate
  };

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-3) var(--hamie-space-4);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-surface-raised);
    }
    .row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: var(--hamie-space-2);
      margin-bottom: var(--hamie-space-2);
    }
    .label {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .stage {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .track {
      position: relative;
      height: 4px;
      overflow: hidden;
      border-radius: var(--hamie-radius-pill);
      background: var(--hamie-surface-hover);
    }
    .fill {
      position: absolute;
      inset: 0 auto 0 0;
      border-radius: var(--hamie-radius-pill);
      background: var(--hamie-accent);
    }
    :host(:not([value])) .fill,
    .fill.indeterminate {
      width: 40%;
      animation: hamie-progress-slide 1.2s var(--hamie-motion-ease) infinite;
    }
    @keyframes hamie-progress-slide {
      0% {
        left: -40%;
      }
      100% {
        left: 100%;
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .fill.indeterminate {
        animation: none;
        left: 0;
        width: 100%;
        opacity: 0.5;
      }
    }
  `;

  render() {
    const determinate = typeof this.value === "number" && !Number.isNaN(this.value);
    const pct = determinate ? Math.max(0, Math.min(100, this.value)) : null;
    return html`
      <div class="row">
        <span class="label">${this.label}</span>
        ${determinate ? html`<span class="stage">${pct}%</span>` : null}
      </div>
      ${this.stage ? html`<p class="stage" style="margin: 0 0 var(--hamie-space-2)">${this.stage}</p>` : null}
      <div class="track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow=${determinate ? pct : ""} aria-label=${this.label || "Progress"}>
        <div class=${determinate ? "fill" : "fill indeterminate"} style=${determinate ? `width:${pct}%` : ""}></div>
      </div>
    `;
  }
}

if (!customElements.get("hamie-progress")) {
  customElements.define("hamie-progress", HamieProgress);
}
