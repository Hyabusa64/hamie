/**
 * <hamie-loading> — no Figma source (App.tsx's data is static/mock, so it
 * never needed a loading state). Real HAMIE data comes over a WebSocket
 * with real latency, so this is a legitimate, documented extension of
 * the reconstructed system: a subtle pulsing skeleton block using the
 * same surface/radius/motion tokens as every other component, so it
 * reads as part of the same design language rather than a bolted-on
 * spinner.
 */
import { LitElement, css, html } from "lit";

export class HamieLoading extends LitElement {
  static properties = {
    lines: { type: Number }, // number of skeleton bars, default 1
    label: { type: String }, // visually-hidden text for screen readers
  };

  static styles = css`
    :host {
      display: block;
    }
    .bar {
      height: 12px;
      border-radius: var(--hamie-radius-sm);
      background: var(--hamie-surface-raised);
      animation: hamie-pulse 1.4s var(--hamie-motion-ease) infinite;
    }
    .bar + .bar {
      margin-top: var(--hamie-space-2);
    }
    .bar:nth-child(3n + 2) {
      width: 85%;
    }
    .bar:nth-child(3n + 3) {
      width: 60%;
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
    }
    @keyframes hamie-pulse {
      0%,
      100% {
        opacity: 1;
      }
      50% {
        opacity: 0.4;
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .bar {
        animation: none;
      }
    }
  `;

  render() {
    const count = this.lines && this.lines > 0 ? this.lines : 1;
    return html`
      <div role="status" aria-live="polite">
        <span class="sr-only">${this.label || "Loading"}</span>
        ${Array.from({ length: count }, () => html`<div class="bar" aria-hidden="true"></div>`)}
      </div>
    `;
  }
}

if (!customElements.get("hamie-loading")) {
  customElements.define("hamie-loading", HamieLoading);
}
