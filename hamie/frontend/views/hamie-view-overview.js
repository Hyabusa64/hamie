/**
 * <hamie-view-overview> — the maintenance-console redesign's Overview,
 * reproducing the approved dashboard reference: a status header, a
 * two-column top row (Home Health | Recommended next step), a compact
 * full-width Needs attention strip, and a two-column bottom row
 * (Top issues | Cleanup candidates) -- answering "is my home healthy /
 * what needs attention / what can HAMIE clean up / what decision do I
 * need to make" without forcing the reader to interpret a dozen
 * independent statistics first.
 *
 * Every number here is real, already-computed state. The five Home
 * Health dimensions split into two provenances, documented at each
 * derivation:
 * - Operational Health and Registry Cleanliness are real backend fields
 *   (`hamie/explorer/overview`'s `operational_health`/
 *   `registry_cleanliness`, computed in application/runtime_projection.
 *   py from the real per-finding entity_category evidence item) --
 *   Operational Health deliberately excludes diagnostic/optional-entity
 *   unavailability entirely, so hundreds of stale diagnostic sensors
 *   never make the house look operationally broken.
 * - "Maintenance" reuses the existing whole-house `availability_health`
 *   field verbatim -- the unsplit figure Operational/Registry are a
 *   documented breakdown of.
 * - Automation and Security are computed here from other already-real
 *   data already being fetched for other Overview surfaces (active
 *   automation ratio from `hass.states`; real security finding count
 *   from `hamie/security/findings`) rather than adding two more
 *   backend fields for data already available client-side.
 *
 * Group/finding display names, and the header's real "N integrations"
 * count, are resolved through ha-registry.js against Home Assistant's
 * own device/config-entry/area registries (real, already-configured
 * metadata) so a group never has to show a raw config-entry id as its
 * name.
 */
import { LitElement, css, html } from "lit";

import { relativeTime, timeOfDayGreeting } from "../format.js";
import { friendlyError } from "../errors.js";
import { primeHaRegistry, resolveDisplayName, configEntryCount } from "../ha-registry.js";
import { groupingReasonLabel } from "../grouping-reason.js";
import "../components/hamie-page-header.js";
import "../components/hamie-status-summary.js";
import "../components/hamie-action-card.js";
import "../components/hamie-issue-row.js";
import "../components/hamie-donut.js";
import "../components/hamie-card.js";
import "../components/hamie-button.js";
import "../components/hamie-section.js";
import "../components/hamie-status.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";
import "../components/hamie-progress.js";
import "../components/hamie-disclosure.js";
import "../components/hamie-cleanup-review.js";

const CONNECTOR_ICON = {
  ollama: "mdi:brain",
  n8n: "mdi:sitemap-outline",
  mcp: "mdi:server-network-outline",
  hkg: "mdi:graph-outline",
};

// Connector heartbeat status wording -- distinct from the generic
// healthy/warning/critical tone tokens so a degraded connector reads as
// "Degraded", not the unrelated finding-severity word "Warning".
const CONNECTOR_STATUS_TONE = {
  healthy: "healthy",
  degraded: "warning",
  error: "critical",
  disabled: "offline",
  unknown: "unknown",
};
const CONNECTOR_STATUS_LABEL = {
  healthy: "Healthy",
  degraded: "Degraded",
  error: "Offline",
  disabled: "Disabled",
  unknown: "Checking…",
};

export class HamieViewOverview extends LitElement {
  static properties = {
    hass: { attribute: false },
    _overview: { state: true },
    _reviewQueue: { state: true },
    _security: { state: true },
    _scheduler: { state: true },
    _error: { state: true },
    _scanning: { state: true },
    _cleanupRunning: { state: true },
    _cleanupSummary: { state: true },
    _cleanupError: { state: true },
    _registryReady: { state: true },
    _reviewOpen: { state: true },
  };

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .stack {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-4);
    }
    .grid-top {
      display: grid;
      grid-template-columns: 3fr 2fr;
      gap: var(--hamie-space-4);
      align-items: stretch;
    }
    .grid-bottom {
      display: grid;
      grid-template-columns: 3fr 2fr;
      gap: var(--hamie-space-4);
      align-items: start;
    }
    @media (max-width: 1100px) {
      .grid-top,
      .grid-bottom {
        grid-template-columns: 1fr;
      }
    }
    .cleanup-panel {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
      height: 100%;
      box-sizing: border-box;
    }
    .cleanup-panel-primary {
      display: flex;
      align-items: baseline;
      gap: var(--hamie-space-2);
    }
    .cleanup-panel-value {
      font-size: var(--hamie-text-display);
      font-weight: var(--hamie-weight-bold);
      color: var(--hamie-status-healthy);
      line-height: 1;
    }
    .cleanup-panel-label {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .cleanup-panel-explainer {
      margin: 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.5;
    }
    .type-badge {
      padding: 0 var(--hamie-space-1-5);
      border-radius: var(--hamie-radius-sm);
      background: var(--hamie-surface-raised);
      color: var(--hamie-text-secondary);
      font-size: var(--hamie-text-caption);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
    }
    .issue-count {
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-bold);
      color: var(--hamie-text-primary);
    }
    .issue-count-label {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .banner {
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
      font-size: var(--hamie-text-small);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .attention {
      padding: var(--hamie-space-3) var(--hamie-space-4);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg);
    }
    .attention-stats {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: var(--hamie-space-5);
      margin-top: var(--hamie-space-2);
    }
    .attention-stat {
      display: flex;
      align-items: baseline;
      gap: var(--hamie-space-1-5);
      background: none;
      border: 0;
      padding: 0;
      font: inherit;
      color: inherit;
      cursor: default;
    }
    button.attention-stat {
      cursor: pointer;
      border-radius: var(--hamie-radius-sm);
    }
    button.attention-stat:hover {
      color: var(--hamie-accent);
    }
    button.attention-stat:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 3px;
    }
    button.attention-stat:disabled {
      cursor: default;
      opacity: 0.6;
    }
    .attention-hint {
      margin: var(--hamie-space-2) 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .attention-value {
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-bold);
      color: var(--hamie-text-primary);
    }
    .attention-value.strong {
      color: var(--hamie-accent);
    }
    .attention-value.critical {
      color: var(--hamie-status-critical);
    }
    .attention-label {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .top-issues-list {
      display: flex;
      flex-direction: column;
    }
    .top-issues-list > * + * {
      border-top: 1px solid var(--hamie-border-hairline);
    }
    .issue-icon {
      width: 32px;
      height: 32px;
      border-radius: var(--hamie-radius-md);
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--hamie-surface-raised);
    }
    .issue-icon ha-icon {
      --mdc-icon-size: 16px;
      color: var(--hamie-text-secondary);
    }
    .cleanup-result {
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg);
      padding: var(--hamie-space-4);
    }
    .cleanup-result-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .cleanup-result-heading {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .cleanup-result-sub {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .cleanup-detail-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: var(--hamie-space-3);
      margin-top: var(--hamie-space-3);
    }
    .cleanup-detail-tile .value {
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .cleanup-detail-tile .label {
      font-size: var(--hamie-text-caption);
      color: var(--hamie-text-secondary);
    }
    .connectors-row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-2);
    }
    .connector-chip {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      padding: var(--hamie-space-1-5) var(--hamie-space-3);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-pill);
      font-size: var(--hamie-text-micro);
      background: none;
      color: inherit;
      font-family: inherit;
      cursor: pointer;
    }
    .connector-chip:hover {
      border-color: var(--hamie-accent);
    }
    .connector-chip:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 2px;
    }
    .connector-chip[data-disabled] {
      opacity: 0.55;
    }
    .connector-chip ha-icon {
      --mdc-icon-size: 14px;
    }
    @media (max-width: 700px) {
      .connectors-row {
        display: none;
      }
    }
    .hamie-health-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: var(--hamie-space-3);
    }
    .hamie-health-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-2);
      padding: var(--hamie-space-2) 0;
      border-bottom: 1px solid var(--hamie-border-hairline);
      font-size: var(--hamie-text-small);
    }
    .hamie-health-row:last-child {
      border-bottom: none;
    }
    .hamie-health-label {
      color: var(--hamie-text-secondary);
    }
    .hamie-health-value {
      color: var(--hamie-text-primary);
      text-align: right;
    }
    .pending-note {
      font-size: var(--hamie-text-caption);
      color: var(--hamie-text-secondary);
      font-style: italic;
    }
  `;

  connectedCallback() {
    super.connectedCallback();
    this._load();
    // Live-update channel (see hamie-app.js's _subscribeLiveUpdates) --
    // connector heartbeat and automatic scan completion reach this view
    // without a manual refresh.
    this._onLiveUpdate = () => this._load();
    window.addEventListener("hamie-live-update", this._onLiveUpdate);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("hamie-live-update", this._onLiveUpdate);
  }

  async _load() {
    if (!this.hass) return;
    try {
      const [overview, reviewQueue, security, scheduler] = await Promise.all([
        this.hass.callWS({ type: "hamie/explorer/overview" }),
        this.hass.callWS({ type: "hamie/remediation/queue/list", offset: 0, limit: 5 }).catch(() => null),
        this.hass.callWS({ type: "hamie/security/findings" }).catch(() => null),
        this.hass.callWS({ type: "hamie/scheduler/status" }).catch(() => null),
      ]);
      this._overview = overview;
      this._reviewQueue = reviewQueue;
      this._security = security;
      this._scheduler = scheduler;
      this._error = null;
      primeHaRegistry(this.hass).then(() => {
        this._registryReady = true;
      });
    } catch (err) {
      this._error = friendlyError(err, "Overview data is temporarily unavailable.");
    }
  }

  _onViewGroups() {
    this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "groups" }, bubbles: true, composed: true }));
  }

  _onViewReviewQueue(status) {
    this.dispatchEvent(
      new CustomEvent("hamie-navigate", { detail: { id: "remediation", status }, bubbles: true, composed: true }),
    );
  }

  async _onScanNow() {
    if (!this.hass) return;
    this._scanning = true;
    try {
      await this.hass.callService("hamie", "scan", {});
      await this._load();
      this.dispatchEvent(new CustomEvent("hamie-data-changed", { bubbles: true, composed: true }));
    } catch (err) {
      this._error = friendlyError(err, "The scan could not be completed.");
    } finally {
      this._scanning = false;
    }
  }

  async _onCleanUp() {
    if (!this.hass || this._cleanupRunning) return;
    this._cleanupRunning = true;
    this._cleanupError = null;
    this._cleanupSummary = null;
    try {
      this._cleanupSummary = await this.hass.callWS({ type: "hamie/cleanup/run" });
      await this._load();
      this.dispatchEvent(new CustomEvent("hamie-data-changed", { bubbles: true, composed: true }));
      // Mission: "Clean Up must end in a decision workspace" -- a
      // successful run with reviewable work opens it automatically
      // rather than leaving the user to hunt for Review Queue. A run
      // that genuinely found nothing to review (rare, but real -- an
      // already-clean house) still shows the summary banner below
      // instead of an empty drawer.
      const hasReviewableWork =
        (this._cleanupSummary.batches || []).some((batch) => batch.remediation_plan_id && !batch.auto_executed) ||
        (this._cleanupSummary.persisted_maintenance_work_items || []).some((item) => item.lifecycle_state !== "completed");
      if (hasReviewableWork) this._reviewOpen = true;
    } catch (err) {
      this._cleanupError = friendlyError(err, "Clean up could not be completed.");
    } finally {
      this._cleanupRunning = false;
    }
  }

  _entityCount() {
    return this.hass?.states ? Object.keys(this.hass.states).length : null;
  }

  _activeAutomationCount() {
    if (!this.hass?.states) return null;
    return Object.values(this.hass.states).filter(
      (state) => state.entity_id.startsWith("automation.") && state.state === "on",
    ).length;
  }

  _totalAutomationCount() {
    if (!this.hass?.states) return null;
    return Object.values(this.hass.states).filter((state) => state.entity_id.startsWith("automation.")).length;
  }

  // Real, already-configured Home Assistant integration count (distinct
  // config entries), primed via the same registry fetch used for group
  // display-name resolution -- null (rendered as "—") until that
  // primes, never a placeholder number.
  _integrationsCount() {
    return configEntryCount();
  }

  // Automation Health: the real fraction of this installation's own
  // automation.* entities that are currently enabled/active, from
  // hass.states directly -- not "broken reference" detection (HAMIE has
  // no per-scan dependency capture cheap enough to run on every scan at
  // 6,500-entity scale), but a real, always-available, honestly-labeled
  // proxy for the same underlying question.
  _automationHealth() {
    const total = this._totalAutomationCount();
    const active = this._activeAutomationCount();
    if (!total) return null;
    return Math.round((100 * active) / total);
  }

  // Security Health: derived from the real hamie/security/findings
  // count already fetched for this same page -- each real finding costs
  // 20 points, floor 0. A simple, deterministic, documented formula,
  // never a fabricated score.
  _securityHealth() {
    if (!this._security) return null;
    return Math.max(0, 100 - 20 * this._security.total);
  }

  // Deterministic single "what should I do next" choice from real,
  // already-loaded state -- never a second, independent priority
  // heuristic duplicating the classifier; this only reads counts the
  // classifier/queue service already produced.
  _nextAction(overview, queueCounts, workItems, hasScanned, cleanupAnalyzed, cleanupEverRan) {
    const readyToExecute = queueCounts.ready_to_execute || 0;
    if (readyToExecute > 0) {
      return {
        icon: "mdi:rocket-launch-outline",
        heading: `${readyToExecute} approved fix${readyToExecute === 1 ? "" : "es"} ${readyToExecute === 1 ? "is" : "are"} ready`,
        description: "These were reviewed and approved and are waiting to run.",
        actionLabel: "Execute",
        onAction: () => this._onViewReviewQueue("ready_to_execute"),
      };
    }
    const safeCleanup = (queueCounts.ready_for_review || 0) + (queueCounts.awaiting_approval || 0);
    if (safeCleanup > 0) {
      return {
        icon: "mdi:broom",
        heading: `${safeCleanup} item${safeCleanup === 1 ? "" : "s"} appear${safeCleanup === 1 ? "s" : ""} safe to disable`,
        description: "No local Home Assistant dependencies were found for these.",
        actionLabel: "Review cleanup",
        onAction: () => this._onViewReviewQueue("ready_for_review"),
      };
    }
    const needsEvidence = workItems.filter((item) => item.lifecycle_state === "needs_evidence").length;
    if (needsEvidence > 0) {
      return {
        icon: "mdi:magnify-scan",
        heading: `${needsEvidence} item${needsEvidence === 1 ? "" : "s"} need${needsEvidence === 1 ? "s" : ""} more evidence`,
        description: "HAMIE couldn't fully verify these are safe to touch yet.",
        actionLabel: "Gather evidence",
        onAction: () => this._onViewReviewQueue(),
      };
    }
    // Freshness-aware: a cleanup analysis that already ran against
    // now-superseded evidence (a newer scan happened since) is "stale",
    // never re-presented as "haven't been analyzed yet" -- and a
    // current, completed analysis that genuinely found nothing
    // actionable must never fall through to "haven't been analyzed"
    // either (mission: "Do not continue saying 'haven't been analyzed'
    // after a successful cleanup classification").
    if ((overview.open_findings || 0) > 0 && !cleanupAnalyzed) {
      if (cleanupEverRan) {
        return {
          icon: "mdi:refresh",
          heading: "Maintenance evidence changed",
          description: "Home Assistant changed since the last cleanup analysis.",
          actionLabel: this._cleanupRunning ? "Analyzing…" : "Refresh cleanup",
          onAction: () => this._onCleanUp(),
        };
      }
      return {
        icon: "mdi:broom",
        heading: `${overview.open_findings} finding${overview.open_findings === 1 ? "" : "s"} ${overview.open_findings === 1 ? "hasn't" : "haven't"} been analyzed for cleanup yet`,
        description: "Clean Up classifies every open finding and proposes what's safe to disable.",
        actionLabel: this._cleanupRunning ? "Analyzing…" : "Clean Up",
        onAction: () => this._onCleanUp(),
      };
    }
    if (!hasScanned) {
      return {
        icon: "mdi:magnify",
        heading: "Run your first scan",
        description: "HAMIE hasn't scanned this Home Assistant installation yet.",
        actionLabel: this._scanning ? "Scanning…" : "Scan now",
        onAction: () => this._onScanNow(),
      };
    }
    return null;
  }

  _renderCleanupResult() {
    const summary = this._cleanupSummary;
    const safeCleanup = summary.actionable_candidate_count || 0;
    const autoDisabled = summary.entities_auto_disabled || 0;
    const workItems = summary.maintenance_work_items || [];
    const counts = summary.classification_counts || {};
    const hasReviewableWork = safeCleanup > 0 || autoDisabled > 0 || workItems.length > 0;
    const heading = autoDisabled > 0
      ? `${autoDisabled} entit${autoDisabled === 1 ? "y" : "ies"} disabled automatically`
      : safeCleanup > 0
        ? "Cleanup review ready"
        : workItems.length > 0
          ? "Investigation needed"
          : "No maintenance needed";
    return html`
      <div class="cleanup-result">
        <div class="cleanup-result-row">
          <div>
            <p class="cleanup-result-heading">${heading}</p>
            <p class="cleanup-result-sub">
              ${summary.total_findings_considered} finding${summary.total_findings_considered === 1 ? "" : "s"} analyzed
            </p>
          </div>
          ${hasReviewableWork
            ? html`<hamie-button variant="primary" size="sm" @click=${() => (this._reviewOpen = true)}>Review</hamie-button>`
            : html`<hamie-button variant="ghost" size="xs" @click=${() => (this._cleanupSummary = null)}>Dismiss</hamie-button>`}
        </div>
        <hamie-disclosure label="Details">
          <div class="cleanup-detail-grid">
            <div class="cleanup-detail-tile"><div class="value">${safeCleanup}</div><div class="label">Safe candidates</div></div>
            <div class="cleanup-detail-tile"><div class="value">${counts.blocked_dependency || 0}</div><div class="label">Protected</div></div>
            <div class="cleanup-detail-tile"><div class="value">${counts.blocked_uncertain || 0}</div><div class="label">Needs evidence</div></div>
            <div class="cleanup-detail-tile"><div class="value">${counts.transient_issue || 0}</div><div class="label">Transient</div></div>
            <div class="cleanup-detail-tile"><div class="value">${(counts.expected_behavior || 0) + (counts.already_clean || 0)}</div><div class="label">Expected</div></div>
            <div class="cleanup-detail-tile"><div class="value">${(counts.manual_review || 0) + (counts.parent_integration_failure || 0)}</div><div class="label">Manual review</div></div>
          </div>
          ${summary.dependency_unscanned_sources?.length
            ? html`<p class="cleanup-result-sub" style="margin-top: var(--hamie-space-3)">
                Not checked: ${summary.dependency_unscanned_sources.join(", ")}.
              </p>`
            : null}
        </hamie-disclosure>
      </div>
    `;
  }

  _groupDisplayName(group) {
    const facets = group.facets || {};
    return resolveDisplayName(
      {
        configEntryId: facets.config_entry_id?.[0],
        deviceId: facets.device_id?.[0],
        integrationDomain: facets.integration_domain?.[0],
      },
      group.title,
    );
  }

  render() {
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="Overview data is unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._overview) {
      return html`<hamie-loading .lines=${4}></hamie-loading>`;
    }

    const overview = this._overview;
    const entities = this._entityCount();
    const automations = this._activeAutomationCount();
    const health = overview.availability_health;
    const hasScanned = Boolean(overview.last_scan);
    const hasHealth = health !== null && health !== undefined;
    // Operational Health -- not the whole-house Maintenance figure -- is
    // the signal that decides tone and wording (mission: operational
    // health vs maintenance debt must read as two different things, never
    // one alarmist blend). It already excludes diagnostic/optional entity
    // clutter (see runtime_projection.py), so hundreds of stale diagnostic
    // sensors never make a functioning house look broken.
    const operational = overview.operational_health;
    const hasOperational = operational !== null && operational !== undefined;
    const operationalHealthy = hasOperational && operational >= 90;
    const tone = !hasScanned || !hasOperational ? "unknown" : operationalHealthy ? "healthy" : operational >= 70 ? "warning" : "critical";

    const queueCounts = this._reviewQueue?.section_counts || {};
    const workItems = this._reviewQueue?.maintenance_work_items || [];
    const safeCleanup = (queueCounts.ready_for_review || 0) + (queueCounts.awaiting_approval || 0) + (queueCounts.ready_to_execute || 0);
    const protectedCount = workItems.filter((item) => item.lifecycle_state === "dependency_blocked").length;
    const needsEvidenceCount = workItems.filter((item) => item.lifecycle_state === "needs_evidence").length;
    const hasMaintenanceDebt = safeCleanup + needsEvidenceCount + protectedCount + (overview.open_findings || 0) > 0;
    // Cleanup freshness (mission: never show a fake zero for "not yet
    // analyzed"). `last_cleanup_scan_id` (hamie/remediation/queue/list)
    // is only set once `hamie/cleanup/run` has completed at least once;
    // it must match the CURRENT scan's id, not just be non-null, or a
    // cleanup pass against now-superseded evidence would misreport as
    // current.
    const cleanupAnalyzed =
      Boolean(this._reviewQueue?.last_cleanup_scan_id) &&
      this._reviewQueue.last_cleanup_scan_id === overview.last_scan_id;

    // "not yet scanned" / "of unknown health" / "last scan completed X" /
    // "no scan has completed yet" are exact, deliberately preserved
    // phrases from a real regression fix (mission Part 17): a scan can
    // complete with zero covered entities, leaving `last_scan` set but
    // health fields still null, and every clause must agree about which of
    // those happened rather than contradicting each other -- `hasScanned`
    // is the one signal all of them read.
    const healthWord = !hasScanned
      ? "not yet scanned"
      : !hasOperational
        ? "of unknown health"
        : !operationalHealthy
          ? "in need of attention"
          : hasMaintenanceDebt
            ? "mostly healthy"
            : "healthy";
    const scanClause = hasScanned ? `last scan completed ${relativeTime(overview.last_scan)}` : "no scan has completed yet";
    const statusText = !hasScanned || !hasOperational
      ? "Your home's health is not yet known"
      : operationalHealthy
        ? hasMaintenanceDebt
          ? "Your home is mostly healthy"
          : "Your home is healthy"
        : "Your home needs attention";

    const connectors = overview.connectors || [];

    const dimensionTone = (value) => (value == null ? "unknown" : value >= 90 ? "healthy" : value >= 70 ? "warning" : "critical");
    const dimensions = [
      { label: "Operational", value: overview.operational_health, tone: dimensionTone(overview.operational_health) },
      { label: "Maintenance", value: hasHealth ? health : null, tone: dimensionTone(hasHealth ? health : null) },
      { label: "Registry", value: overview.registry_cleanliness, tone: dimensionTone(overview.registry_cleanliness) },
      { label: "Automation", value: this._automationHealth(), tone: dimensionTone(this._automationHealth()) },
      { label: "Security", value: this._securityHealth(), tone: dimensionTone(this._securityHealth()) },
    ];

    const nextAction = this._nextAction(
      overview,
      queueCounts,
      workItems,
      hasScanned,
      cleanupAnalyzed,
      Boolean(this._reviewQueue?.last_cleanup_scan_id),
    );
    const topIssues = (overview.highest_priority_incidents || []).slice(0, 5);
    const integrations = this._integrationsCount();

    const cleanupSegments = [
      { label: "Safe to disable", value: safeCleanup, tone: "healthy" },
      { label: "Protected", value: protectedCount, tone: "info" },
      { label: "Needs evidence", value: needsEvidenceCount, tone: "evidence" },
      { label: "Blocked", value: queueCounts.failed || 0, tone: "warning" },
    ];
    const cleanupTotal = cleanupSegments.reduce((sum, item) => sum + item.value, 0);

    return html`
      <div class="stack">
        <hamie-page-header
          heading=${timeOfDayGreeting()}
          subtitle="Your home is ${healthWord} — ${scanClause}${entities != null ? ` · ${entities.toLocaleString()} entities` : ""}${automations != null ? ` · ${automations} automations` : ""}${integrations != null ? ` · ${integrations} integrations` : ""}"
        >
          <div slot="actions">
            <hamie-button variant="secondary" size="sm" ?disabled=${this._scanning} @click=${this._onScanNow}>
              <ha-icon icon="mdi:refresh"></ha-icon> ${this._scanning ? "Scanning…" : "Scan"}
            </hamie-button>
            <hamie-button variant="primary" size="sm" ?disabled=${this._cleanupRunning} @click=${this._onCleanUp}>
              <ha-icon icon="mdi:broom"></ha-icon> ${this._cleanupRunning ? "Analyzing…" : "Clean Up"}
            </hamie-button>
          </div>
          ${connectors.length
            ? html`
                <div class="connectors-row">
                  ${connectors.map((connector) => {
                    const status = connector.enabled ? connector.status : "disabled";
                    const token = CONNECTOR_STATUS_TONE[status] || "unknown";
                    const statusLabel = CONNECTOR_STATUS_LABEL[status] || status;
                    const label = connector.enabled
                      ? `${connector.connector_id}: ${statusLabel}${connector.latency_ms != null ? ` · ${connector.latency_ms} ms` : ""}`
                      : `${connector.connector_id}: Disabled`;
                    return html`
                      <button
                        type="button"
                        class="connector-chip"
                        ?data-disabled=${!connector.enabled}
                        title=${label}
                        aria-label=${label}
                        @click=${() => this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "connectors" }, bubbles: true, composed: true }))}
                      >
                        <ha-icon icon=${CONNECTOR_ICON[connector.connector_id] || "mdi:puzzle-outline"} style="color: var(--hamie-status-${token})"></ha-icon>
                        ${connector.connector_id}
                        ${connector.enabled
                          ? html`<hamie-status variant="dot" status=${token} label=${statusLabel}></hamie-status>`
                          : null}
                      </button>
                    `;
                  })}
                </div>
              `
            : null}
        </hamie-page-header>

        ${this._cleanupError
          ? html`
              <div class="banner">
                <span>${this._cleanupError}</span>
                <hamie-button variant="ghost" size="xs" @click=${() => (this._cleanupError = null)}>Dismiss</hamie-button>
              </div>
            `
          : null}
        ${this._cleanupRunning ? html`<hamie-progress label="Cleaning analysis" stage="Checking dependencies…"></hamie-progress>` : null}
        ${this._cleanupSummary && !this._cleanupRunning ? this._renderCleanupResult() : null}

        <div class="grid-top">
          <hamie-status-summary
            .score=${hasHealth ? health : undefined}
            score-label="Home Health"
            status-text=${statusText}
            tone=${tone}
            .dimensions=${dimensions}
          ></hamie-status-summary>

          ${nextAction
            ? html`
                <hamie-action-card icon=${nextAction.icon} heading=${nextAction.heading} description=${nextAction.description}>
                  <hamie-button variant="primary" size="sm" @click=${nextAction.onAction}>${nextAction.actionLabel}</hamie-button>
                </hamie-action-card>
              `
            : null}
        </div>

        <div class="attention">
          <hamie-section heading="Needs attention"></hamie-section>
          <div class="attention-stats">
            <button type="button" class="attention-stat" @click=${() => this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "incidents" }, bubbles: true, composed: true }))}>
              <span class="attention-value">${overview.active_incidents || 0}</span>
              <span class="attention-label">incidents</span>
            </button>
            <button
              type="button"
              class="attention-stat"
              ?disabled=${!cleanupAnalyzed}
              @click=${() => this._onViewReviewQueue("ready_for_review")}
            >
              <span class="attention-value strong">${cleanupAnalyzed ? safeCleanup : "—"}</span>
              <span class="attention-label">safe cleanup</span>
            </button>
            <button
              type="button"
              class="attention-stat"
              ?disabled=${!cleanupAnalyzed}
              @click=${() => this._onViewReviewQueue()}
            >
              <span class="attention-value">${cleanupAnalyzed ? protectedCount : "—"}</span>
              <span class="attention-label">protected</span>
            </button>
            <button
              type="button"
              class="attention-stat"
              ?disabled=${!cleanupAnalyzed}
              @click=${() => this._onViewReviewQueue()}
            >
              <span class="attention-value">${cleanupAnalyzed ? needsEvidenceCount : "—"}</span>
              <span class="attention-label">need more evidence</span>
            </button>
            <span class="attention-stat">
              <span class="attention-value ${overview.critical_findings ? "critical" : ""}">${overview.critical_findings || 0}</span>
              <span class="attention-label">critical</span>
            </span>
          </div>
          ${!cleanupAnalyzed && overview.open_findings > 0
            ? html`<p class="attention-hint">${overview.open_findings} finding${overview.open_findings === 1 ? "" : "s"} haven't been classified for cleanup yet -- run Clean Up to see safe/protected/needs-evidence counts.</p>`
            : null}
        </div>

        <hamie-card padding="md">
          <hamie-section
            heading="HAMIE health"
            description="HAMIE's own scan and evidence-source status -- separate from your home's health above."
          ></hamie-section>
          <div class="hamie-health-grid">
            <div>
              <div class="hamie-health-row">
                <span class="hamie-health-label">Last scan</span>
                <span class="hamie-health-value">${overview.last_scan ? relativeTime(overview.last_scan) : "Never"}</span>
              </div>
              <div class="hamie-health-row">
                <span class="hamie-health-label">Next scan</span>
                <span class="hamie-health-value">
                  ${this._scheduler?.auto_scan_enabled
                    ? this._scheduler.next_scan_seconds != null
                      ? `In ${Math.max(0, Math.round(this._scheduler.next_scan_seconds / 60))} min`
                      : "Pending first scan"
                    : "Automatic scanning is off"}
                </span>
              </div>
              <div class="hamie-health-row">
                <span class="hamie-health-label">Scan coverage</span>
                <span class="hamie-health-value">${overview.coverage || "unknown"}</span>
              </div>
              ${this._scheduler?.last_scan_error_summary
                ? html`
                    <div class="hamie-health-row">
                      <span class="hamie-health-label">Last scan error</span>
                      <span class="hamie-health-value" style="color: var(--hamie-status-critical)">${this._scheduler.last_scan_error_summary}</span>
                    </div>
                  `
                : null}
            </div>
            <div>
              <div class="hamie-health-row">
                <span class="hamie-health-label">Temporal (recorder) evidence</span>
                <span class="hamie-health-value"><hamie-status variant="dot" status="unknown" label="Pending activation"></hamie-status></span>
              </div>
              <div class="hamie-health-row">
                <span class="hamie-health-label">Source-definition index</span>
                <span class="hamie-health-value"><hamie-status variant="dot" status="unknown" label="Pending activation"></hamie-status></span>
              </div>
              <div class="hamie-health-row">
                <span class="hamie-health-label">Duplicate/migration index</span>
                <span class="hamie-health-value"><hamie-status variant="dot" status="unknown" label="Pending activation"></hamie-status></span>
              </div>
              <p class="pending-note">
                These three evidence sources exist in HAMIE's installed code but are not yet wired into a running scan or served by any command -- shown honestly as pending rather than omitted.
              </p>
            </div>
          </div>
        </hamie-card>

        <div class="grid-bottom">
          <div>
            <hamie-section heading="Top issues"></hamie-section>
            ${topIssues.length === 0
              ? html`<hamie-empty tone="positive" heading="No issues found"></hamie-empty>`
              : html`
                  <div class="top-issues-list">
                    ${topIssues.map((incident) => {
                      const status = ["p0", "p1"].includes(incident.priority) ? "critical" : incident.priority === "p2" ? "warning" : "info";
                      return html`
                        <hamie-issue-row
                          interactive
                          title=${incident.title}
                          meta="${incident.evidence_status.replaceAll("_", " ")}"
                          @hamie-row-click=${() => this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "incidents" }, bubbles: true, composed: true }))}
                        >
                          <span slot="leading" class="issue-icon"><ha-icon icon="mdi:alert-decagram-outline"></ha-icon></span>
                          <span slot="extra" class="issue-count">${incident.affected_subject_count}</span>
                          <span slot="extra" class="issue-count-label">affected</span>
                          <hamie-status slot="trailing" status=${status} label=${incident.priority.toUpperCase()}></hamie-status>
                          <ha-icon slot="trailing" icon="mdi:chevron-right"></ha-icon>
                        </hamie-issue-row>
                      `;
                    })}
                  </div>
                  <hamie-button variant="ghost" size="xs" @click=${() => this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "incidents" }, bubbles: true, composed: true }))}>
                    View all ${overview.active_incidents ?? topIssues.length} incidents <ha-icon icon="mdi:arrow-right"></ha-icon>
                  </hamie-button>
                `}
          </div>

          <hamie-card padding="md">
            <div class="cleanup-panel">
              <hamie-section heading="Cleanup candidates"></hamie-section>
              ${!cleanupAnalyzed
                ? html`
                    <div class="cleanup-panel-primary">
                      <span class="cleanup-panel-value">—</span>
                      <span class="cleanup-panel-label">Not analyzed</span>
                    </div>
                    <p class="cleanup-panel-explainer">Run Clean Up to classify current maintenance findings.</p>
                    <hamie-button variant="primary" size="sm" ?disabled=${this._cleanupRunning} @click=${this._onCleanUp}>
                      ${this._cleanupRunning ? "Analyzing…" : "Clean Up"}
                    </hamie-button>
                  `
                : html`
                    <div class="cleanup-panel-primary">
                      <span class="cleanup-panel-value">${safeCleanup}</span>
                      <span class="cleanup-panel-label">Safe to disable</span>
                    </div>
                    ${cleanupTotal > 0
                      ? html`<hamie-donut .segments=${cleanupSegments}></hamie-donut>`
                      : null}
                    <p class="cleanup-panel-explainer">
                      ${safeCleanup > 0
                        ? "These entities appear unused and can be disabled without impacting your automations or dashboards."
                        : needsEvidenceCount > 0
                          ? `No safe cleanup candidates found. ${needsEvidenceCount} item${needsEvidenceCount === 1 ? "" : "s"} need more evidence before HAMIE can recommend a change.`
                          : "No safe cleanup candidates found. HAMIE found no cleanup work requiring your attention."}
                    </p>
                    <hamie-button variant="secondary" size="sm" @click=${() => this._onViewReviewQueue()}>
                      Go to Review Queue <ha-icon icon="mdi:arrow-right"></ha-icon>
                    </hamie-button>
                  `}
            </div>
          </hamie-card>
        </div>
      </div>

      <hamie-cleanup-review
        .hass=${this.hass}
        .open=${Boolean(this._reviewOpen)}
        .summary=${this._cleanupSummary}
        @hamie-cleanup-review-closed=${() => (this._reviewOpen = false)}
        @hamie-data-changed=${() => this._load()}
      ></hamie-cleanup-review>
    `;
  }
}

if (!customElements.get("hamie-view-overview")) {
  customElements.define("hamie-view-overview", HamieViewOverview);
}
