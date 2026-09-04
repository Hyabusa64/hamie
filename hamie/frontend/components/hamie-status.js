/**
 * <hamie-status> — reconstructed from App.tsx's `Chip` and `SevIcon`,
 * extended during the design-system stabilization pass with two more
 * variants that were found hand-rolled elsewhere in the library instead
 * of reusing this component:
 *
 * - `variant="priority"`: Figma's Recommendations priority badge
 *   (high/medium/low) was duplicated as hamie-problem-card's own
 *   `.priority` CSS instead of going through here -- same "colored pill"
 *   rendering mechanism as the chip variant, just a different token
 *   family (`--hamie-priority-*` instead of `--hamie-status-*`).
 * - `variant="dot"`: a bare colored dot with adjacent text, no pill
 *   background -- hamie-sidebar's footer status indicator hand-rolled
 *   the exact same 6px-dot pattern this component's chip variant already
 *   has internally.
 *
 * Figma's `Status` union (healthy/warning/critical/info/unknown/active/
 * offline/running/idle) drives the default colored-dot pill everywhere
 * except the findings-table "Severity" column, which instead uses a
 * plain icon+text pair over a 3-value `Severity` subset (critical/
 * warning/info) -- `variant="severity"`, per the audit's Lit-mapping
 * plan rather than a separate near-duplicate component.
 *
 * Icons use Home Assistant's native <ha-icon> (mdi:*) in place of
 * lucide-react — mdi:alert-circle / mdi:alert / mdi:information are the
 * closest equivalents to lucide's AlertCircle / AlertTriangle / Info.
 */
import { LitElement, css, html } from "lit";

const LABELS = {
  healthy: "Healthy",
  warning: "Warning",
  critical: "Critical",
  info: "Info",
  unknown: "Unknown",
  active: "Active",
  offline: "Offline",
  running: "Running",
  idle: "Idle",
};

const SEVERITY_ICON = {
  critical: "mdi:alert-circle",
  warning: "mdi:alert",
  info: "mdi:information",
};

const PRIORITY_LABELS = { high: "High", medium: "Medium", low: "Low" };

export class HamieStatus extends LitElement {
  static properties = {
    status: { type: String }, // Status value, or Severity/priority value depending on variant
    label: { type: String },
    variant: { type: String }, // "chip" (default) | "severity" | "priority" | "dot"
  };

  static styles = css`
    :host {
      display: inline-flex;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      padding: var(--hamie-space-half) var(--hamie-space-2);
      border-radius: var(--hamie-radius-pill);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
    }
    .priority {
      display: inline-flex;
      align-items: center;
      padding: var(--hamie-space-half) var(--hamie-space-1-5);
      border-radius: var(--hamie-radius-sm);
      font-size: var(--hamie-text-caption);
      font-weight: var(--hamie-weight-bold);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
    }
    .dot-row {
      display: inline-flex;
      align-items: center;
      gap: var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .dot {
      width: 6px;
      height: 6px;
      border-radius: var(--hamie-radius-circle);
      flex-shrink: 0;
    }
    .severity {
      display: inline-flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      text-transform: capitalize;
    }
    ha-icon {
      --mdc-icon-size: 14px;
      flex-shrink: 0;
    }
  `;

  render() {
    const status = this.status || "unknown";

    if (this.variant === "severity") {
      return html`
        <span class="severity" style="color: var(--hamie-status-${status}, var(--hamie-status-unknown))">
          <ha-icon icon=${SEVERITY_ICON[status] || "mdi:information"}></ha-icon>
          ${this.label || status}
        </span>
      `;
    }

    if (this.variant === "priority") {
      return html`
        <span
          class="priority"
          style="background: var(--hamie-priority-${status}-fill, var(--hamie-priority-low-fill)); color: var(--hamie-priority-${status}, var(--hamie-priority-low))"
        >
          ${this.label || PRIORITY_LABELS[status] || status}
        </span>
      `;
    }

    if (this.variant === "dot") {
      return html`
        <span class="dot-row">
          <span class="dot" style="background: var(--hamie-status-${status}, var(--hamie-status-unknown))"></span>
          ${this.label || LABELS[status] || status}
        </span>
      `;
    }

    return html`
      <span
        class="chip"
        style="background: var(--hamie-status-${status}-fill, var(--hamie-status-unknown-fill)); color: var(--hamie-status-${status}, var(--hamie-status-unknown))"
      >
        <span class="dot" style="background: var(--hamie-status-${status}, var(--hamie-status-unknown))"></span>
        ${this.label || LABELS[status] || status}
      </span>
    `;
  }
}

if (!customElements.get("hamie-status")) {
  customElements.define("hamie-status", HamieStatus);
}
