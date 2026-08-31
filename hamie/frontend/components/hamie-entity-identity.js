/**
 * <hamie-entity-identity> — compact "what object is this" identity block:
 * a domain icon, the real friendly name, the raw entity_id in code font,
 * and an optional integration/domain badge. New primitive for the
 * Home/Issues/Review/Search IA pass -- Findings/Search/Review rows each
 * independently hand-rolled a `friendly_name` + `<span class="entity">`
 * pair (see hamie-view-findings.js's `_renderRow`); this consolidates
 * that shape once rather than a fourth copy.
 *
 * Every field is optional/best-effort: `entityId`'s domain (the part
 * before the first ".") drives a small fixed icon map for the handful of
 * domains HAMIE's own findings/search most commonly surface
 * (automation/script/scene/sensor/binary_sensor/device); anything else
 * falls back to a generic entity icon rather than guessing.
 */
import { LitElement, css, html } from "lit";

const DOMAIN_ICON = {
  automation: "mdi:robot-outline",
  script: "mdi:script-text-outline",
  scene: "mdi:palette-outline",
  sensor: "mdi:eye-outline",
  binary_sensor: "mdi:toggle-switch-outline",
  light: "mdi:lightbulb-outline",
  switch: "mdi:toggle-switch-off-outline",
  climate: "mdi:thermostat",
  camera: "mdi:cctv",
  cover: "mdi:blinds-horizontal",
  lock: "mdi:lock-outline",
  media_player: "mdi:cast",
  device_tracker: "mdi:map-marker-outline",
};

function domainOf(entityId) {
  if (!entityId || typeof entityId !== "string") return null;
  const dot = entityId.indexOf(".");
  return dot > 0 ? entityId.slice(0, dot) : null;
}

export class HamieEntityIdentity extends LitElement {
  static properties = {
    name: { type: String },
    entityId: { type: String, attribute: "entity-id" },
    integration: { type: String },
    icon: { type: String }, // explicit mdi:* override; otherwise derived from entityId's domain
    compact: { type: Boolean, reflect: true },
  };

  static styles = css`
    :host {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2-5);
      min-width: 0;
    }
    .icon-badge {
      flex-shrink: 0;
      width: 28px;
      height: 28px;
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-surface-raised);
      display: flex;
      align-items: center;
      justify-content: center;
    }
    :host([compact]) .icon-badge {
      width: 22px;
      height: 22px;
    }
    .icon-badge ha-icon {
      --mdc-icon-size: 14px;
      color: var(--hamie-text-secondary);
    }
    .text {
      min-width: 0;
    }
    .name {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .meta {
      margin: 1px 0 0;
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      overflow: hidden;
    }
    .entity-id {
      font-family: var(--hamie-font-code);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .badge {
      flex-shrink: 0;
      padding: 0 var(--hamie-space-1-5);
      border-radius: var(--hamie-radius-sm);
      background: var(--hamie-surface-raised);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      font-size: var(--hamie-text-caption);
    }
  `;

  render() {
    const domain = domainOf(this.entityId);
    const icon = this.icon || DOMAIN_ICON[domain] || "mdi:help-box-outline";
    return html`
      <span class="icon-badge"><ha-icon icon=${icon}></ha-icon></span>
      <span class="text">
        <p class="name">${this.name || this.entityId || "Unknown"}</p>
        <span class="meta">
          ${this.entityId ? html`<span class="entity-id">${this.entityId}</span>` : null}
          ${this.integration ? html`<span class="badge">${this.integration}</span>` : null}
        </span>
      </span>
    `;
  }
}

if (!customElements.get("hamie-entity-identity")) {
  customElements.define("hamie-entity-identity", HamieEntityIdentity);
}
