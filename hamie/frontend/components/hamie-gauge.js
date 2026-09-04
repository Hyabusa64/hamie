/**
 * <hamie-gauge> — reconstructed 1:1 from App.tsx's `HealthArc`.
 * Not in the spec's floor component list; added because House Health has
 * a real, distinct Figma component with no closer match among the floor
 * set (see the audit's Lit-mapping table). 270° SVG progress ring,
 * 0-100 score, color threshold at 90/70.
 *
 * `score` is `null`/`undefined` before any real scan has ever completed
 * (the real `availability_health` field is only computed once entities
 * have been evaluated). Coercing that to 0 would paint a full red
 * "critical" ring for a system that has simply never been measured --
 * shown as a neutral, honest "no data yet" ring instead.
 */
import { LitElement, css, html, svg } from "lit";

const RADIUS = 54;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const TRACK = CIRCUMFERENCE * 0.75;

export class HamieGauge extends LitElement {
  static properties = {
    score: { type: Number },
  };

  static styles = css`
    :host {
      display: block;
      width: 144px;
      height: 144px;
      position: relative;
    }
    svg {
      transform: rotate(-225deg);
    }
    .label {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
    }
    .score {
      font-size: var(--hamie-text-display);
      font-weight: var(--hamie-weight-medium);
      line-height: 1;
      letter-spacing: -0.01em;
      color: var(--hamie-text-primary);
    }
    .of {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      margin-top: var(--hamie-space-1-5);
    }
  `;

  _color(score) {
    if (score >= 90) return "var(--hamie-status-healthy)";
    if (score >= 70) return "var(--hamie-status-warning)";
    return "var(--hamie-status-critical)";
  }

  render() {
    const hasScore = this.score !== null && this.score !== undefined;
    const score = hasScore ? Math.max(0, Math.min(100, this.score)) : 0;
    const fill = hasScore ? (score / 100) * TRACK : 0;
    const color = hasScore ? this._color(score) : "var(--hamie-border-hairline)";
    return html`
      ${svg`
        <svg width="144" height="144" viewBox="0 0 144 144">
          <circle cx="72" cy="72" r=${RADIUS} fill="none" stroke="var(--hamie-border-hairline)"
            stroke-width="9" stroke-linecap="round" stroke-dasharray="${TRACK} ${CIRCUMFERENCE}" />
          <circle cx="72" cy="72" r=${RADIUS} fill="none" stroke=${color}
            stroke-width="9" stroke-linecap="round" stroke-dasharray="${fill} ${CIRCUMFERENCE}"
            style="transition: stroke-dasharray var(--hamie-motion-slow) var(--hamie-motion-ease)" />
        </svg>
      `}
      <div class="label">
        <span class="score">${hasScore ? score : "—"}</span>
        <span class="of">${hasScore ? "/ 100" : "no data yet"}</span>
      </div>
    `;
  }
}

if (!customElements.get("hamie-gauge")) {
  customElements.define("hamie-gauge", HamieGauge);
}
