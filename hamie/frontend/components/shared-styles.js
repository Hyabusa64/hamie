/**
 * Shared CSS fragments reused across multiple components.
 *
 * These exist because the same distinctive, nameable UI pattern was found
 * duplicated verbatim in more than one component during the design-system
 * stabilization pass (see the audit that added this file) -- not created
 * speculatively. Import into a component's `static styles` array rather
 * than re-declaring the rules.
 */
import { css } from "lit";

// The 28px icon-badge pattern: hamie-metric's icon and hamie-provider-card's
// connector icon were pixel-identical but declared independently.
export const iconBadgeStyles = css`
  .icon-badge {
    width: 28px;
    height: 28px;
    border-radius: var(--hamie-radius-md);
    background: var(--hamie-surface-raised);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  .icon-badge ha-icon {
    --mdc-icon-size: 14px;
    color: var(--hamie-text-secondary);
  }
`;
