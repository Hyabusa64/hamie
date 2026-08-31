/**
 * <hamie-confidence-indicator> — how sure HAMIE is about a recommendation,
 * shown separately from severity/priority (a deliberately different axis
 * -- see hamie-view-recommendations.js's module docstring on why
 * confidence and urgency must never be conflated into one badge).
 *
 * New primitive for the Review triage screen (spec: "confidence/risk/
 * external-consumer uncertainty" shown per item). `level` is the real
 * `Confidence.level` value wherever it exists today (findings' plain
 * `confidence` string field, or -- once the backend reload/wiring this
 * pass could not perform lands -- `CanonicalRecommendation.confidence`,
 * see domain/recommendation.py's `ConfidenceLevel`/`ConfidenceFactor`).
 * `factors` (optional, `[{code, effect, rationale}]`) is that same
 * canonical model's per-factor breakdown -- rendered when present,
 * omitted honestly (not padded with placeholders) when the caller only
 * has a bare level string, which is all that is live today.
 */
import { LitElement, css, html } from "lit";

const LEVEL_TONE = { high: "healthy", medium: "warning", low: "critical" };
const LEVEL_LABEL = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" };
const EFFECT_ICON = { supports: "mdi:plus-circle-outline", weakens: "mdi:minus-circle-outline" };

export class HamieConfidenceIndicator extends LitElement {
  static properties = {
    level: { type: String }, // "high" | "medium" | "low" | unset
    factors: { type: Array }, // optional [{ code, effect, rationale }]
  };

  static styles = css`
    :host {
      display: block;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      padding: var(--hamie-space-half) var(--hamie-space-2);
      border-radius: var(--hamie-radius-pill);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
    }
    .dot {
      width: 6px;
      height: 6px;
      border-radius: var(--hamie-radius-circle);
      flex-shrink: 0;
    }
    ul {
      margin: var(--hamie-space-1-5) 0 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
    ha-icon {
      --mdc-icon-size: 12px;
      vertical-align: -1px;
    }
  `;

  render() {
    const level = this.level || "unknown";
    const tone = LEVEL_TONE[level] || "unknown";
    const label = LEVEL_LABEL[level] || "Confidence unknown";
    return html`
      <span class="pill" style="background: var(--hamie-status-${tone}-fill); color: var(--hamie-status-${tone})">
        <span class="dot" style="background: var(--hamie-status-${tone})"></span>
        ${label}
      </span>
      ${this.factors?.length
        ? html`
            <ul>
              ${this.factors.map(
                (item) => html`
                  <li>
                    <ha-icon icon=${EFFECT_ICON[item.effect] || "mdi:circle-small"}></ha-icon>
                    ${item.rationale || item.code}
                  </li>
                `,
              )}
            </ul>
          `
        : null}
    `;
  }
}

if (!customElements.get("hamie-confidence-indicator")) {
  customElements.define("hamie-confidence-indicator", HamieConfidenceIndicator);
}
