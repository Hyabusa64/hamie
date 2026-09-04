/**
 * <hamie-view-remediation> — the Review Queue for the Phase 2B remediation
 * engine (Phase 2C). No Figma source: this is a real HAMIE-only capability
 * with no corresponding screen in the extracted design project, built
 * entirely from the existing component library (hamie-card, hamie-status,
 * hamie-button, hamie-dialog, hamie-select, hamie-switch) so it reads as
 * part of the same visual language, matching hamie-view-groups.js's own
 * precedent for a real-but-undesigned screen.
 *
 * Every field and command here was verified against
 * presentation/remediation_api.py + application/remediation/service.py
 * before writing this view, not guessed:
 *
 * - The registered `hamie/remediation/*` commands are the *only* way this view
 *   talks to the backend. It never touches an adapter, never selects an
 *   action type, and never fabricates an approval -- every mutation
 *   (plan/create, preview/generate, approve, reject, revoke, execute)
 *   requires a fresh idempotency token and, for approve, the exact
 *   `plan_fingerprint`/`preview_digest` the server just returned (never
 *   user-typed), so a stale local copy is rejected by the server rather
 *   than silently accepted.
 * - Approve and Execute are two separate, explicit actions -- creating or
 *   previewing a plan never approves it, and approving a plan never
 *   executes it. There is no "Approve All" control; batch execution is
 *   out of scope for this phase.
 * - `status` is always whatever the server returned on the most recent
 *   load, never inferred client-side or optimistically updated -- every
 *   action reloads the detail from the server before rendering its
 *   result, and a failed action never shows a success state.
 * - An unsupported plan (`execution_supported: false`) never renders an
 *   Approve or Execute control at all; only its `unsupported_reason`.
 */
import { LitElement, css, html } from "lit";

import { relativeTime } from "../format.js";
import { friendlyError } from "../errors.js";
import { idempotencyToken } from "../idempotency.js";
import "../components/hamie-page-header.js";
import "../components/hamie-card.js";
import "../components/hamie-status.js";
import "../components/hamie-button.js";
import "../components/hamie-dialog.js";
import "../components/hamie-select.js";
import "../components/hamie-switch.js";
import "../components/hamie-input.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";
import "../components/hamie-disclosure.js";
import "../components/hamie-issue-row.js";

const PAGE_SIZE = 25;

// Review Queue tabs (mission redesign section 7): each maps to a real
// backend dimension -- `status` (server-filterable, one value per WS
// call) for Ready/Approved/History, and the durable maintenance-work
// `lifecycle_state` for Needs Evidence/Blocked, which is a genuinely
// separate concept (non-actionable work HAMIE found but cannot yet turn
// into a plan) from the `items`/status queue at all. History and Blocked
// combine several real status values the server can't filter by in one
// call, so those two fetch a broader page and filter client-side --
// Review Queue volume is bounded by actionable-plan count, not the
// 6,500-entity/500-finding scale Findings has to handle.
const TABS = [
  { id: "ready", label: "Ready" },
  { id: "needs_evidence", label: "Needs Evidence" },
  { id: "blocked", label: "Blocked" },
  { id: "approved", label: "Approved" },
  { id: "history", label: "History" },
];
const HISTORY_STATUSES = new Set(["verified", "failed", "rolled_back", "rollback_failed", "rejected", "snoozed"]);

// Maps every real queue status to one of hamie-status's known chip
// colors -- the label text (set separately, never color alone) is what
// actually communicates the status; see STATUS_LABELS below.
const STATUS_CHIP = {
  needs_review: "warning",
  snoozed: "idle",
  approved: "active",
  blocked: "critical",
  executing: "running",
  verified: "healthy",
  failed: "critical",
  rolled_back: "warning",
  rollback_failed: "critical",
  rejected: "idle",
};

const STATUS_LABELS = {
  needs_review: "Needs Review",
  snoozed: "Snoozed",
  approved: "Approved",
  blocked: "Blocked",
  executing: "Executing",
  verified: "Verified",
  failed: "Failed",
  rolled_back: "Rolled Back",
  rollback_failed: "Rollback Failed",
  rejected: "Rejected",
};

const DEPENDENCY_LABELS = {
  not_started: "Not checked",
  in_progress: "Checking…",
  complete: "Checked",
  partial: "Partially checked",
  failed: "Source unavailable",
};
const WORK_ITEM_LIFECYCLE_LABELS = {
  needs_evidence: "Needs evidence",
  dependency_blocked: "Blocked",
  ai_investigation: "Needs investigation",
  manual_repair: "Manual repair",
  snoozed: "Snoozed",
  completed: "Completed",
  superseded: "Superseded",
};
// Same purple "evidence" tone Overview's cleanup-candidate donut already
// uses for this exact concept (design/tokens.css's --hamie-status-evidence)
// -- previously this row hardcoded status="info" regardless of lifecycle
// state, so "Needs evidence" read as plain info-blue here but purple on
// Overview for the identical state.
const WORK_ITEM_LIFECYCLE_TONE = {
  needs_evidence: "evidence",
  dependency_blocked: "info",
  ai_investigation: "warning",
  manual_repair: "warning",
  snoozed: "unknown",
  completed: "healthy",
  superseded: "unknown",
};

// A few real action_type values (domain/remediation_catalog.py) get a
// specific, human phrase; everything else is humanized generically
// (strip a "domain." prefix, underscores -> spaces, title case) rather
// than hand-maintaining a label for the full catalog.
const ACTION_TYPE_LABELS = {
  disable_entity_batch: "Disable unused entities",
  disable_unused_entity: "Disable unused entity",
  enable_entity: "Re-enable entity",
  "hamie.mark_for_manual_remediation": "Flag for manual review",
};

function humanizeActionType(actionType) {
  if (ACTION_TYPE_LABELS[actionType]) return ACTION_TYPE_LABELS[actionType];
  const bare = actionType.includes(".") ? actionType.split(".").at(-1) : actionType;
  const words = bare.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function truncatedDigest(value) {
  return value ? `${value.slice(0, 16)}…` : "—";
}

export class HamieViewRemediation extends LitElement {
  static properties = {
    hass: { attribute: false },
    // Set by hamie-app.js when Overview's "attention" row or next-action
    // card navigates here -- picks the starting tab (see connectedCallback).
    focusStatus: { type: String },
    _items: { state: true },
    _total: { state: true },
    _sectionCounts: { state: true },
    _maintenanceWorkItems: { state: true },
    _capabilities: { state: true },
    _offset: { state: true },
    _activeTab: { state: true },
    _expandedBatches: { state: true },
    _error: { state: true },
    _actionError: { state: true },
    _busy: { state: true }, // recommendation_id currently mid-action, or true for a dialog action
    _detail: { state: true }, // full DetailResult for _detailRecommendationId
    _detailRecommendationId: { state: true },
    _detailLoading: { state: true },
    _pendingReject: { state: true }, // { remediation_plan_id } once Reject is clicked
    _rejectReason: { state: true },
    _pendingRevoke: { state: true }, // { approval_id } once Revoke is clicked
    _revokeReason: { state: true },
    _pendingApprove: { state: true }, // { plan, preview } once Approve is clicked
    _destructiveAck: { state: true },
    _backupAck: { state: true },
    _pendingExecute: { state: true }, // { plan, approval } once Execute is clicked
    _executeConfirmed: { state: true },
    _pendingRollback: { state: true }, // { plan, execution, affectedObject }
    _pendingSnooze: { state: true },
    _snoozeDuration: { state: true },
    _snoozeReason: { state: true },
    _snoozeUntil: { state: true },
    _gatherEvidenceResult: { state: true }, // { work_item_id, resolved, still_missing } from the last gather_evidence call
  };

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .header {
      margin-bottom: var(--hamie-space-4);
    }
    h1 {
      margin: 0;
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .subtitle {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .action-error {
      margin-bottom: var(--hamie-space-3);
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
    .tabs {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1);
      margin-bottom: var(--hamie-space-4);
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .tabs button {
      padding: var(--hamie-space-2) var(--hamie-space-1);
      margin-right: var(--hamie-space-4);
      border: 0;
      border-bottom: 2px solid transparent;
      background: transparent;
      color: var(--hamie-text-secondary);
      font: var(--hamie-weight-medium) var(--hamie-text-small)/1.2 inherit;
      cursor: pointer;
    }
    .tabs button[aria-selected="true"] {
      color: var(--hamie-text-primary);
      border-bottom-color: var(--hamie-accent);
    }
    .tab-count {
      color: var(--hamie-text-secondary);
      font-size: var(--hamie-text-micro);
    }
    .list {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-2-5);
    }
    .batch-members {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-2-5);
      margin: 0 0 var(--hamie-space-3) var(--hamie-space-5);
      padding-left: var(--hamie-space-3);
      border-left: 2px solid var(--hamie-border-hairline);
    }
    .row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .title {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .meta {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .badges {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      flex-shrink: 0;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      margin-top: var(--hamie-space-2);
      flex-wrap: wrap;
    }
    .unsupported-reason {
      margin-top: var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-status-critical);
    }
    .pager {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--hamie-space-3) 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .detail-section {
      margin-top: var(--hamie-space-3);
    }
    .detail-section h3 {
      margin: 0 0 var(--hamie-space-1);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .detail-meta {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.8;
    }
    .detail-list {
      margin: 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
    .fingerprint {
      font-family: var(--hamie-font-code);
      font-size: var(--hamie-text-caption);
    }
    .step {
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-md);
      padding: var(--hamie-space-2) var(--hamie-space-2-5);
      margin-bottom: var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
    }
    .step-warning {
      color: var(--hamie-status-warning);
    }
    .ack-row {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2-5);
      margin-top: var(--hamie-space-3);
    }
    .ack-row label {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
    }
    .dialog-reason {
      margin-top: var(--hamie-space-3);
    }
    .dialog-reason label {
      display: block;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      margin-bottom: var(--hamie-space-1);
    }
    .confirm-summary {
      background: var(--hamie-surface-raised);
      border-radius: var(--hamie-radius-md);
      padding: var(--hamie-space-3);
      font-size: var(--hamie-text-small);
      line-height: 1.8;
    }
  `;

  constructor() {
    super();
    this._offset = 0;
    this._sectionCounts = {};
    this._maintenanceWorkItems = [];
    this._activeTab = "ready";
    this._expandedBatches = new Set();
  }

  connectedCallback() {
    super.connectedCallback();
    // `focusStatus` (set by hamie-app.js when the Overview "attention"
    // row or a next-action button navigates here) picks the starting
    // tab from real backend section names: ready_for_review/
    // awaiting_approval/ready_to_execute all land on "ready" (nothing
    // more specific to distinguish), no value at all keeps the default.
    if (this.focusStatus === "ready_to_execute") this._activeTab = "approved";
    this._load();
  }

  // Ready/Approved map onto one real `status` value each and are
  // fetched server-side, paginated. Blocked/History each combine
  // several real status values the server can only filter by one at a
  // time -- fetched as one broader, unfiltered-by-status page and
  // narrowed client-side (see TABS' own comment for why this is an
  // acceptable, bounded trade-off here).
  _statusForTab(tab) {
    if (tab === "ready") return "needs_review";
    if (tab === "approved") return "approved";
    return undefined;
  }

  async _load() {
    if (!this.hass) return;
    try {
      const status = this._statusForTab(this._activeTab);
      const [result, capabilities] = await Promise.all([
        this.hass.callWS({
          type: "hamie/remediation/queue/list",
          ...(status ? { status } : {}),
          offset: this._offset,
          limit: PAGE_SIZE,
        }),
        this.hass.callWS({ type: "hamie/remediation/capabilities" }),
      ]);
      let items = result.items;
      let total = result.total;
      if (this._activeTab === "blocked") {
        items = items.filter((item) => item.status === "blocked");
        total = items.length;
      } else if (this._activeTab === "history") {
        items = items.filter((item) => HISTORY_STATUSES.has(item.status));
        total = items.length;
      }
      this._items = items;
      this._capabilities = capabilities;
      this._total = total;
      this._sectionCounts = result.section_counts || {};
      this._maintenanceWorkItems = result.maintenance_work_items || [];
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "The remediation queue is temporarily unavailable.");
    }
  }

  _setTab(tab) {
    this._activeTab = tab;
    this._offset = 0;
    this._expandedBatches = new Set();
    this._load();
  }

  _toggleBatch(key) {
    const next = new Set(this._expandedBatches);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    this._expandedBatches = next;
  }

  // Batch-first grouping (mission redesign section 8): the Ready tab's
  // items grouped by their real `action_type` (e.g. disable_entity_batch)
  // -- the actual remediation action a user would approve, not an
  // artificial category. Each group's members are further broken down
  // by title so a user sees "127 items" as a small number of named
  // batches instead of 127 individual rows to scroll through.
  _readyBatches(items) {
    const byAction = new Map();
    for (const item of items) {
      const key = item.action_type || "other";
      if (!byAction.has(key)) byAction.set(key, []);
      byAction.get(key).push(item);
    }
    return [...byAction.entries()]
      .map(([actionType, members]) => ({ actionType, members }))
      .sort((a, b) => b.members.length - a.members.length);
  }

  _nextPage() {
    this._offset += PAGE_SIZE;
    this._load();
  }

  _previousPage() {
    this._offset = Math.max(0, this._offset - PAGE_SIZE);
    this._load();
  }

  async _openDetail(recommendationId) {
    this._detailRecommendationId = recommendationId;
    this._detailLoading = true;
    await this._reloadDetail();
    this._detailLoading = false;
  }

  async _reloadDetail() {
    if (!this.hass || !this._detailRecommendationId) return;
    try {
      this._detail = await this.hass.callWS({
        type: "hamie/remediation/detail/get",
        recommendation_id: this._detailRecommendationId,
      });
      this._actionError = null;
    } catch (err) {
      this._actionError = friendlyError(err, "That detail could not be loaded.");
    }
  }

  _closeDetail() {
    this._detail = null;
    this._detailRecommendationId = null;
  }

  async _refreshEvidence() {
    if (!this.hass || this._busy) return;
    this._busy = "refresh_evidence";
    this._actionError = null;
    try {
      await this.hass.callService("hamie", "scan", {});
      await this._load();
      if (this._detailRecommendationId) await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "Evidence could not be refreshed.");
    } finally {
      this._busy = null;
    }
  }

  _setSnoozeDuration(value) {
    this._snoozeDuration = String(value);
    this._snoozeUntil = new Date(Date.now() + Number(value) * 60_000).toISOString();
  }

  _openSnooze(item) {
    this._pendingSnooze = { item };
    this._snoozeReason = "";
    this._setSnoozeDuration("1440");
  }

  _cancelSnooze() {
    this._pendingSnooze = null;
    this._snoozeReason = "";
    this._snoozeUntil = null;
  }

  async _confirmSnooze() {
    if (!this.hass || !this._pendingSnooze || this._busy || !this._snoozeUntil) return;
    const { item } = this._pendingSnooze;
    this._busy = item.plan_id;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/snooze",
        remediation_plan_id: item.plan_id,
        snooze_until: this._snoozeUntil,
        ...(this._snoozeReason.trim() ? { reason: this._snoozeReason.trim() } : {}),
        idempotency_token: idempotencyToken(),
      });
      this._cancelSnooze();
      await this._load();
      if (this._detailRecommendationId) await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That proposal could not be snoozed.");
    } finally {
      this._busy = null;
    }
  }

  async _gatherEvidence(item) {
    if (!this.hass || this._busy || !item.work_item_id) return;
    this._busy = item.work_item_id;
    this._actionError = null;
    try {
      const result = await this.hass.callWS({
        type: "hamie/remediation/gather_evidence",
        work_item_id: item.work_item_id,
      });
      this._gatherEvidenceResult = { title: item.title, ...result };
      await this._load();
    } catch (err) {
      this._actionError = friendlyError(err, "Evidence could not be gathered for that item.");
    } finally {
      this._busy = null;
    }
  }

  async _resumePlan(item) {
    if (!this.hass || this._busy || !item.plan_id) return;
    this._busy = item.plan_id;
    this._actionError = null;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/resume",
        remediation_plan_id: item.plan_id,
        idempotency_token: idempotencyToken(),
      });
      await this._load();
      if (this._detailRecommendationId) await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That proposal could not be resumed.");
    } finally {
      this._busy = null;
    }
  }

  async _createOrRefreshPlan(recommendationId) {
    if (!this.hass || this._busy) return;
    this._busy = recommendationId;
    this._actionError = null;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/plan/create",
        recommendation_id: recommendationId,
        idempotency_token: idempotencyToken(),
      });
      await this._load();
      if (this._detailRecommendationId === recommendationId) {
        await this._reloadDetail();
      }
    } catch (err) {
      this._actionError = friendlyError(err, "That plan could not be created.");
    } finally {
      this._busy = null;
    }
  }

  async _generatePreview(plan) {
    if (!this.hass || this._busy) return;
    this._busy = plan.remediation_plan_id;
    this._actionError = null;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/preview/generate",
        remediation_plan_id: plan.remediation_plan_id,
        idempotency_token: idempotencyToken(),
      });
      await this._load();
      await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That preview could not be generated.");
    } finally {
      this._busy = null;
    }
  }

  _openApprove(plan) {
    // Fresh preview must exist and its digest must be persisted on the
    // plan already -- Generate Preview always runs first, so this is
    // read from the just-reloaded detail, never typed by hand.
    this._destructiveAck = false;
    this._backupAck = false;
    this._pendingApprove = { plan };
  }

  _cancelApprove() {
    this._pendingApprove = null;
  }

  async _confirmApprove() {
    if (!this.hass || !this._pendingApprove) return;
    const { plan } = this._pendingApprove;
    this._busy = plan.remediation_plan_id;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/approve",
        remediation_plan_id: plan.remediation_plan_id,
        plan_fingerprint: plan.plan_fingerprint,
        preview_digest: plan.preview_digest,
        destructive_acknowledged: this._destructiveAck,
        backup_acknowledged: this._backupAck,
        warnings_acknowledged: [],
        idempotency_token: idempotencyToken(),
      });
      this._pendingApprove = null;
      await this._load();
      await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That plan could not be approved.");
    } finally {
      this._busy = null;
    }
  }

  _openReject(plan) {
    this._rejectReason = "";
    this._pendingReject = { plan };
  }

  _cancelReject() {
    this._pendingReject = null;
    this._rejectReason = "";
  }

  async _confirmReject() {
    if (!this.hass || !this._pendingReject) return;
    const { plan } = this._pendingReject;
    this._busy = plan.remediation_plan_id;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/reject",
        remediation_plan_id: plan.remediation_plan_id,
        reason: this._rejectReason.trim(),
        idempotency_token: idempotencyToken(),
      });
      this._pendingReject = null;
      this._rejectReason = "";
      await this._load();
      await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That plan could not be rejected.");
    } finally {
      this._busy = null;
    }
  }

  _openRevoke(approval) {
    this._revokeReason = "";
    this._pendingRevoke = { approval };
  }

  _cancelRevoke() {
    this._pendingRevoke = null;
    this._revokeReason = "";
  }

  async _confirmRevoke() {
    if (!this.hass || !this._pendingRevoke) return;
    const { approval } = this._pendingRevoke;
    this._busy = approval.approval_id;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/revoke",
        approval_id: approval.approval_id,
        reason: this._revokeReason.trim(),
        idempotency_token: idempotencyToken(),
      });
      this._pendingRevoke = null;
      this._revokeReason = "";
      await this._load();
      await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That approval could not be revoked.");
    } finally {
      this._busy = null;
    }
  }

  _openExecute(plan, approval) {
    this._executeConfirmed = false;
    const affectedObject =
      this._detail?.recommendation?.affected_object?.source_id ?? plan.recommendation_id;
    this._pendingExecute = { plan, approval, affectedObject };
  }

  _cancelExecute() {
    this._pendingExecute = null;
  }

  async _confirmExecute() {
    if (!this.hass || !this._pendingExecute || !this._executeConfirmed) return;
    const { plan, approval } = this._pendingExecute;
    this._busy = plan.remediation_plan_id;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/execute",
        remediation_plan_id: plan.remediation_plan_id,
        approval_id: approval.approval_id,
        idempotency_token: idempotencyToken(),
        confirmed: true,
      });
      this._pendingExecute = null;
      await this._load();
      await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That remediation could not be executed.");
    } finally {
      this._busy = null;
    }
  }

  // A plan/preview loaded strictly before the currently-displayed
  // approval was granted, or that has since been refreshed, no longer
  // matches the approval's own bound fingerprint/digest -- the queue's
  // own `status` already reflects this server-side, but Execute is also
  // independently gated here so a stale client render can never enable
  // it even for one frame.
  _openRollback(plan, execution) {
    const affectedObject =
      this._detail?.recommendation?.affected_object?.source_id ?? plan.recommendation_id;
    this._pendingRollback = { plan, execution, affectedObject };
  }

  _cancelRollback() {
    this._pendingRollback = null;
  }

  async _confirmRollback() {
    if (!this.hass || !this._pendingRollback) return;
    const { plan, execution } = this._pendingRollback;
    this._busy = plan.remediation_plan_id;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/rollback",
        remediation_plan_id: plan.remediation_plan_id,
        execution_id: execution.execution_id,
        idempotency_token: idempotencyToken(),
        confirmed: true,
      });
      this._pendingRollback = null;
      await this._load();
      await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That verified repair could not be rolled back.");
    } finally {
      this._busy = null;
    }
  }

  _approvalIsValidFor(plan, approval) {
    if (!approval || approval.state !== "granted" || approval.revoked_at) return false;
    return (
      approval.plan_fingerprint === plan.plan_fingerprint &&
      approval.preview_digest === plan.preview_digest &&
      new Date(approval.expires_at).getTime() > Date.now()
    );
  }

  render() {
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="Review Queue is unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._items) {
      return html`<hamie-loading .lines=${4}></hamie-loading>`;
    }

    const readyCount = this._sectionCounts.ready_for_review || 0;
    const needsEvidenceItems = this._maintenanceWorkItems.filter((item) => item.lifecycle_state === "needs_evidence");
    const blockedWorkItems = this._maintenanceWorkItems.filter(
      (item) => item.lifecycle_state === "dependency_blocked" || item.lifecycle_state === "ai_investigation" || item.lifecycle_state === "manual_repair",
    );
    const tabCounts = {
      ready: this._activeTab === "ready" ? this._total : undefined,
      needs_evidence: needsEvidenceItems.length,
      blocked: (this._activeTab === "blocked" ? this._total : 0) + blockedWorkItems.length,
      approved: this._activeTab === "approved" ? this._total : undefined,
      history: this._activeTab === "history" ? this._total : undefined,
    };

    return html`
      <hamie-page-header
        heading="Review Queue"
        subtitle="${readyCount} item${readyCount === 1 ? "" : "s"} need your decision"
      >
        <div slot="actions">
          <hamie-button variant="secondary" size="xs" ?disabled=${Boolean(this._busy)} @click=${this._refreshEvidence}>
            Refresh evidence
          </hamie-button>
        </div>
      </hamie-page-header>

      ${this._actionError
        ? html`
            <div class="action-error">
              <span role="alert">${this._actionError}</span>
              <hamie-button variant="ghost" size="xs" aria-label="Dismiss error" @click=${() => (this._actionError = null)}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          `
        : null}

      <div class="tabs" role="tablist" aria-label="Review Queue status">
        ${TABS.map(
          (tab) => html`
            <button
              role="tab"
              aria-selected=${tab.id === this._activeTab ? "true" : "false"}
              @click=${() => this._setTab(tab.id)}
            >
              ${tab.label}${tabCounts[tab.id] ? html` <span class="tab-count">${tabCounts[tab.id]}</span>` : null}
            </button>
          `,
        )}
      </div>

      ${this._gatherEvidenceResult ? this._renderGatherEvidenceResult() : null}

      ${this._renderTabContent(needsEvidenceItems, blockedWorkItems)}

      ${this._detailRecommendationId ? this._renderDetailDialog() : null}
      ${this._pendingApprove ? this._renderApproveDialog() : null}
      ${this._pendingReject ? this._renderRejectDialog() : null}
      ${this._pendingRevoke ? this._renderRevokeDialog() : null}
      ${this._pendingExecute ? this._renderExecuteDialog() : null}
      ${this._pendingRollback ? this._renderRollbackDialog() : null}
      ${this._pendingSnooze ? this._renderSnoozeDialog() : null}
    `;
  }

  _renderPager() {
    return html`
      <div class="pager">
        <hamie-button variant="ghost" size="xs" ?disabled=${this._offset === 0} @click=${this._previousPage}>Previous</hamie-button>
        <span>${this._total === 0 ? 0 : this._offset + 1}–${Math.min(this._offset + PAGE_SIZE, this._total)} of ${this._total}</span>
        <hamie-button variant="ghost" size="xs" ?disabled=${this._offset + PAGE_SIZE >= this._total} @click=${this._nextPage}>Next</hamie-button>
      </div>
    `;
  }

  _renderTabContent(needsEvidenceItems, blockedWorkItems) {
    if (this._activeTab === "needs_evidence") {
      return needsEvidenceItems.length
        ? html`<div class="list">${needsEvidenceItems.map((item) => this._renderMaintenanceWorkRow(item))}</div>`
        : html`<hamie-card padding="md"><hamie-empty tone="positive" heading="Nothing needs more evidence right now"></hamie-empty></hamie-card>`;
    }
    if (this._activeTab === "blocked") {
      const hasAny = this._items.length || blockedWorkItems.length;
      return !hasAny
        ? html`<hamie-card padding="md"><hamie-empty tone="positive" heading="Nothing is blocked right now"></hamie-empty></hamie-card>`
        : html`
            <div class="list">
              ${blockedWorkItems.map((item) => this._renderMaintenanceWorkRow(item))}
              ${this._items.map((item) => this._renderRow(item))}
            </div>
          `;
    }
    if (this._activeTab === "ready") {
      if (!this._items.length) {
        return html`<hamie-card padding="md"><hamie-empty tone="positive" heading="Nothing needs review right now"></hamie-empty></hamie-card>`;
      }
      return html`
        <div class="list">${this._readyBatches(this._items).map((batch) => this._renderBatch(batch))}</div>
        ${this._renderPager()}
      `;
    }
    // approved / history: a flat, real status-filtered list -- no
    // batching, since these are already-decided or completed items a
    // user reviews individually, not a pile of similar new work.
    return this._items.length
      ? html`
          <div class="list">${this._items.map((item) => this._renderRow(item))}</div>
          ${this._renderPager()}
        `
      : html`<hamie-card padding="md"><hamie-empty tone="neutral" heading="Nothing here yet"></hamie-empty></hamie-card>`;
  }

  _renderBatch(batch) {
    const key = batch.actionType;
    // A small batch (few enough items that hiding them saves nothing)
    // starts expanded; a large one starts collapsed. Either way the
    // Review/Collapse button always toggles it, tracked as a diff from
    // that size-based default rather than an absolute expanded/collapsed
    // set, so both directions work regardless of batch size.
    const defaultExpanded = batch.members.length <= 5;
    const expanded = this._expandedBatches.has(key) !== defaultExpanded;
    const label = humanizeActionType(batch.actionType);
    // Sub-counts by each member's own title (spec's own "Dreame Vacuum
    // 74 / Dreo 18" example): the only real per-item grouping label
    // available here without a second fetch -- good enough for a
    // sub-breakdown, not claimed as authoritative integration metadata.
    const byTitle = new Map();
    for (const item of batch.members) {
      byTitle.set(item.title, (byTitle.get(item.title) || 0) + 1);
    }
    // Bounded to the 5 largest sub-groups -- a batch can plausibly have
    // as many distinct titles as members, and rendering all of them
    // (rather than "88 individual rows to scroll through") would just
    // recreate the exact wall-of-text problem this view exists to fix.
    const subCounts = [...byTitle.entries()].sort((a, b) => b[1] - a[1]);
    const shownSubCounts = subCounts.slice(0, 5);
    const remainingSubCounts = subCounts.length - shownSubCounts.length;
    return html`
      <hamie-card padding="md">
        <div class="row">
          <div>
            <p class="title">${label}</p>
            <p class="meta">${batch.members.length} item${batch.members.length === 1 ? "" : "s"}</p>
            ${subCounts.length > 1
              ? html`<p class="meta">
                  ${shownSubCounts.map(([title, count]) => `${title} ${count}`).join(" · ")}${remainingSubCounts > 0 ? `, +${remainingSubCounts} more` : ""}
                </p>`
              : null}
          </div>
          <hamie-button variant="secondary" size="xs" @click=${() => this._toggleBatch(key)}>
            ${expanded ? "Collapse" : `Review ${batch.members.length}`}
          </hamie-button>
        </div>
      </hamie-card>
      ${expanded ? html`<div class="batch-members">${batch.members.map((item) => this._renderRow(item))}</div>` : null}
    `;
  }

  _renderMaintenanceWorkSection() {
    return html`
      <hamie-section heading="Maintenance work (not yet executable)"></hamie-section>
      <p class="subtitle">
        ${this._maintenanceWorkItems.length} item${this._maintenanceWorkItems.length === 1 ? "" : "s"}
        HAMIE found but cannot act on automatically yet -- durable, not lost when this page reloads.
      </p>
      <div class="list">
        ${this._maintenanceWorkItems.map((item) => this._renderMaintenanceWorkRow(item))}
      </div>
    `;
  }

  _renderGatherEvidenceResult() {
    const result = this._gatherEvidenceResult;
    return html`
      <div class="action-error" style="background: var(--hamie-status-info-fill); color: var(--hamie-text-primary);">
        <span>
          ${result.resolved
            ? `"${result.title}" -- evidence gathered, now actionable and moved to the review queue.`
            : `"${result.title}" -- evidence gathered, still blocked${result.still_missing?.length ? `: missing ${result.still_missing.join(", ")}` : ""}.`}
        </span>
        <hamie-button variant="ghost" size="xs" @click=${() => (this._gatherEvidenceResult = null)}>Dismiss</hamie-button>
      </div>
    `;
  }

  _renderMaintenanceWorkRow(item) {
    const shown = item.affected_entity_ids.slice(0, 5);
    const more = item.entity_count - shown.length;
    const busy = this._busy === item.work_item_id;
    return html`
      <hamie-card padding="md">
        <div class="row">
          <div>
            <p class="title">${item.title} (${item.entity_count})</p>
            <p class="meta">${item.reason}</p>
            <p class="meta">${shown.join(", ")}${more > 0 ? `, +${more} more` : ""}</p>
          </div>
          <div class="badges">
            <hamie-status
              status=${WORK_ITEM_LIFECYCLE_TONE[item.lifecycle_state] || "info"}
              label=${WORK_ITEM_LIFECYCLE_LABELS[item.lifecycle_state] || item.lifecycle_state}
            ></hamie-status>
          </div>
        </div>
        <div class="actions">
          <hamie-button
            variant="secondary"
            size="xs"
            ?disabled=${busy}
            @click=${() => this._gatherEvidence(item)}
          >
            ${busy ? "Gathering evidence…" : "Gather Evidence"}
          </hamie-button>
        </div>
      </hamie-card>
    `;
  }

  _renderRow(item) {
    const busy = this._busy === item.recommendation_id || this._busy === item.plan_id;
    return html`
      <hamie-card padding="md">
        <div class="row">
          <div>
            <p class="title">${item.title}</p>
            <p class="meta">
              ${item.category} / ${item.subtype} · ${item.affected_object} · risk ${item.risk_level} · confidence ${item.confidence}
              · dependencies: ${DEPENDENCY_LABELS[item.dependency_status] || item.dependency_status}
              · updated ${relativeTime(item.updated_at)}
            </p>
          </div>
          <div class="badges">
            <hamie-status status=${STATUS_CHIP[item.status] || "unknown"} label=${STATUS_LABELS[item.status] || item.status}></hamie-status>
          </div>
        </div>
        ${!item.execution_supported && item.unsupported_reason
          ? html`<p class="unsupported-reason">${item.unsupported_reason}</p>`
          : null}
        ${item.section === "snoozed" && item.snooze_until
          ? html`<p class="meta">Snoozed until ${new Date(item.snooze_until).toLocaleString()}${item.snooze_reason ? ` · ${item.snooze_reason}` : ""}</p>`
          : null}
        <div class="actions">
          <hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._openDetail(item.recommendation_id)}>
            Inspect
          </hamie-button>
          <hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._createOrRefreshPlan(item.recommendation_id)}>
            ${item.plan_id ? "Review proposal" : "Create repair proposal"}
          </hamie-button>
          ${item.plan_id && ["ready_for_review", "needs_more_evidence", "awaiting_backup", "awaiting_approval"].includes(item.section)
            ? html`<hamie-button variant="ghost" size="xs" ?disabled=${busy} @click=${() => this._openSnooze(item)}>Snooze</hamie-button>`
            : null}
          ${item.plan_id && item.section === "snoozed"
            ? html`<hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._resumePlan(item)}>Resume now</hamie-button>`
            : null}
        </div>
      </hamie-card>
    `;
  }

  _renderDetailDialog() {
    if (this._detailLoading || !this._detail) {
      return html`
        <hamie-dialog open heading="Loading…" @hamie-dialog-closed=${this._closeDetail}>
          <hamie-loading .lines=${3}></hamie-loading>
        </hamie-dialog>
      `;
    }
    const { recommendation, plan, approval, executions, rollbacks, status } = this._detail;
    const dep = recommendation.dependency_analysis;
    const approvalValid = plan && this._approvalIsValidFor(plan, approval);
    const busy = this._busy === recommendation.recommendation_id || (plan && this._busy === plan.remediation_plan_id);
    const latestExecution = executions?.length ? executions[executions.length - 1] : null;
    const rollbackAvailable =
      plan?.rollback_plan?.supported &&
      latestExecution?.outcome === "succeeded" &&
      !(rollbacks?.length);

    return html`
      <hamie-dialog open heading="${recommendation.title}" @hamie-dialog-closed=${this._closeDetail}>
        <hamie-status status=${STATUS_CHIP[status] || "unknown"} label=${STATUS_LABELS[status] || status}></hamie-status>

        <div class="detail-section">
          <h3>Recommendation</h3>
          <p class="detail-meta">
            ${recommendation.category} / ${recommendation.subtype}<br />
            Affected: ${recommendation.affected_object.source_id}<br />
            Risk: ${recommendation.risk.risk.overall} · Confidence: ${recommendation.confidence.level}
          </p>
          <p>${recommendation.summary}</p>
        </div>

        <div class="detail-section">
          <h3>Dependencies</h3>
          <p class="detail-meta">
            Status: ${DEPENDENCY_LABELS[dep.status] || dep.status} · Confidence: ${dep.confidence}<br />
            ${dep.safe_to_delete === false ? "Deletion not permitted -- dependents exist or have not been ruled out." : ""}
          </p>
          ${dep.inbound_references?.length
            ? html`
                <p class="detail-meta">Dependents:</p>
                <ul class="detail-list">${dep.inbound_references.map((ref) => html`<li>${ref}</li>`)}</ul>
              `
            : html`<p class="detail-meta">No known dependents.</p>`}
          ${dep.unknown_dependencies?.length
            ? html`
                <p class="detail-meta step-warning">Unresolved checks:</p>
                <ul class="detail-list">${dep.unknown_dependencies.map((item) => html`<li>${item}</li>`)}</ul>
              `
            : null}
        </div>

        ${plan
          ? html`
              <div class="detail-section">
                <h3>Plan</h3>
                <p class="detail-meta">
                  Fingerprint: <span class="fingerprint">${truncatedDigest(plan.plan_fingerprint)}</span><br />
                  Action: ${plan.actions?.[0]?.action_type ?? "—"} · Destructive: ${plan.risk.destructive ? "Yes" : "No"}
                  · Rollback: ${plan.risk.rollback_support} · Backup required: ${plan.requires_backup ? "Yes" : "No"}<br />
                  Expected impact: ${plan.risk.expected_user_visible_impact}
                </p>
                ${!plan.execution_supported
                  ? html`<p class="unsupported-reason">${plan.unsupported_reason}</p>`
                  : null}
                ${plan.requires_backup
                  ? html`
                      <div class="step">
                        <strong>Backup provider unavailable</strong>
                        <p class="detail-meta">
                          HAMIE cannot prepare or verify the required Home Assistant backup in this environment.
                          This proposal cannot be approved or executed until a supported backup provider is configured.
                        </p>
                        <hamie-button
                          variant="secondary"
                          size="xs"
                          disabled
                          title="No supported Home Assistant backup provider is configured"
                        >
                          Prepare backup
                        </hamie-button>
                      </div>
                    `
                  : null}
              </div>

              ${plan.preview_digest
                ? html`
                    <div class="detail-section">
                      <h3>Preview</h3>
                      <p class="detail-meta">Digest: <span class="fingerprint">${truncatedDigest(plan.preview_digest)}</span></p>
                    </div>
                  `
                : null}

              ${approval
                ? html`
                    <div class="detail-section">
                      <h3>Approval</h3>
                      <p class="detail-meta">
                        State: ${approval.state}${approval.revoked_at ? " (revoked)" : ""} · Approved by ${approval.approved_by}<br />
                        Decided: ${relativeTime(approval.decided_at)} · Expires: ${approval.expires_at ? relativeTime(approval.expires_at) : "—"}<br />
                        ${approval.rejection_reason ? html`Reason: ${approval.rejection_reason}` : null}
                        ${!approvalValid && approval.state === "granted" && !approval.revoked_at
                          ? html`<br /><span class="step-warning">This approval no longer matches the current plan/preview. Approve again.</span>`
                          : null}
                      </p>
                    </div>
                  `
                : null}

              ${executions?.length
                ? html`
                    <div class="detail-section">
                      <h3>Execution history</h3>
                      ${executions.map(
                        (exec) => html`
                          <div class="step">
                            ${exec.outcome} · started ${relativeTime(exec.started_at)}
                            ${exec.completed_at ? html`· completed ${relativeTime(exec.completed_at)}` : null}
                            ${exec.error ? html`<br /><span class="step-warning">${exec.error}</span>` : null}
                          </div>
                        `,
                      )}
                    </div>
                  `
                : null}

              ${rollbacks?.length
                ? html`
                    <div class="detail-section">
                      <h3>Rollback history</h3>
                      ${rollbacks.map(
                        (rb) => html`
                          <div class="step">
                            ${rb.outcome} · initiated ${relativeTime(rb.initiated_at)} · ${rb.reason}
                            ${rb.outcome === "failed" ? html`<br /><span class="step-warning">Rollback failed -- manual review required.</span>` : null}
                          </div>
                        `,
                      )}
                    </div>
                  `
                : null}

              <div class="actions">
                <hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._createOrRefreshPlan(recommendation.recommendation_id)}>
                  Review proposal
                </hamie-button>
                ${plan.execution_supported && !plan.preview_digest
                  ? html`
                      <hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._generatePreview(plan)}>
                        Preview repair
                      </hamie-button>
                    `
                  : null}
                ${plan.execution_supported && plan.preview_digest && !approvalValid && plan.state !== "rejected"
                  ? html`
                      <hamie-button
                        variant="primary"
                        size="xs"
                        ?disabled=${busy || (plan.requires_backup && !this._capabilities?.backup_provider_available)}
                        title=${plan.requires_backup && !this._capabilities?.backup_provider_available
                          ? "Approval is blocked until a supported backup provider verifies the required backup"
                          : ""}
                        @click=${() => this._openApprove(plan)}
                      >
                        Approve repair
                      </hamie-button>
                      <hamie-button variant="ghost" size="xs" ?disabled=${busy} @click=${() => this._openReject(plan)}>
                        Reject
                      </hamie-button>
                    `
                  : null}
                ${approvalValid
                  ? html`
                      <hamie-button variant="primary" size="xs" ?disabled=${busy} @click=${() => this._openExecute(plan, approval)}>
                        Execute approved repair
                      </hamie-button>
                      <hamie-button variant="ghost" size="xs" ?disabled=${busy} @click=${() => this._openRevoke(approval)}>
                        Revoke Approval
                      </hamie-button>
                    `
                  : null}
                ${rollbackAvailable
                  ? html`
                      <hamie-button variant="danger" size="xs" ?disabled=${busy} @click=${() => this._openRollback(plan, latestExecution)}>
                        Preview rollback
                      </hamie-button>
                    `
                  : null}
                <hamie-button variant="ghost" size="xs" ?disabled=${busy} @click=${this._reloadDetail}>
                  Verify
                </hamie-button>
              </div>
            `
          : html`
              <div class="actions">
                <hamie-button variant="primary" size="xs" @click=${() => this._createOrRefreshPlan(recommendation.recommendation_id)}>
                  Create repair proposal
                </hamie-button>
              </div>
            `}

        <hamie-button slot="primary-action" variant="secondary" size="sm" @click=${this._closeDetail}>
          Close
        </hamie-button>
      </hamie-dialog>
    `;
  }

  _renderApproveDialog() {
    const { plan } = this._pendingApprove;
    const canConfirm =
      (!plan.risk.destructive || this._destructiveAck) &&
      (!plan.requires_backup ||
        (this._capabilities?.backup_provider_available && this._backupAck));
    return html`
      <hamie-dialog
        open
        heading="Approve this repair proposal?"
        cancel-label="Cancel"
        confirm-label="Approve repair"
        .destructive=${plan.risk.destructive}
        .busy=${!!this._busy}
        .errorMessage=${this._actionError || ""}
        .confirmDisabled=${!canConfirm}
        .onConfirm=${() => this._confirmApprove()}
        .onCancel=${() => this._cancelApprove()}
      >
        <p>Approval binds your decision to this exact plan and preview. It does not execute anything.</p>
        <div class="confirm-summary">
          Fingerprint: <span class="fingerprint">${truncatedDigest(plan.plan_fingerprint)}</span><br />
          Preview digest: <span class="fingerprint">${truncatedDigest(plan.preview_digest)}</span>
        </div>
        ${plan.risk.destructive ? html`
          <div class="ack-row">
            <hamie-switch .checked=${this._destructiveAck} @hamie-change=${(e) => (this._destructiveAck = e.detail.checked)}></hamie-switch>
            <label>I understand this action is destructive.</label>
          </div>` : null}
        ${plan.requires_backup ? html`
          <div class="ack-row">
            <hamie-switch .checked=${this._backupAck} @hamie-change=${(e) => (this._backupAck = e.detail.checked)}></hamie-switch>
            <label>I verified the required backup status shown above.</label>
          </div>` : null}
      </hamie-dialog>
    `;
  }

  _renderSnoozeDialog() {
    const { item } = this._pendingSnooze;
    const wakeTime = this._snoozeUntil ? new Date(this._snoozeUntil) : null;
    return html`
      <hamie-dialog
        open
        heading="Snooze this proposal?"
        cancel-label="Cancel"
        confirm-label="Snooze"
        .busy=${!!this._busy}
        .errorMessage=${this._actionError || ""}
        .confirmDisabled=${!this._snoozeUntil}
        .onConfirm=${() => this._confirmSnooze()}
        .onCancel=${() => this._cancelSnooze()}
      >
        <p>
          Snoozing ${item.title} hides this proposal from active review until the selected time.
          It does not approve or execute anything.
        </p>
        <div class="dialog-reason">
          <label for="snooze-duration">Duration</label>
          <hamie-select
            id="snooze-duration"
            .value=${this._snoozeDuration}
            .options=${[
              { value: "60", label: "1 hour" },
              { value: "1440", label: "24 hours" },
              { value: "10080", label: "7 days" },
            ]}
            @hamie-change=${(event) => this._setSnoozeDuration(event.detail.value)}
          ></hamie-select>
        </div>
        <p class="detail-meta">
          Exact wake time:
          <time datetime=${this._snoozeUntil || ""}>${wakeTime ? wakeTime.toLocaleString() : "Unknown"}</time>
        </p>
        <div class="dialog-reason">
          <label for="snooze-reason">Reason (optional)</label>
          <hamie-input
            id="snooze-reason"
            .value=${this._snoozeReason}
            @hamie-input=${(event) => (this._snoozeReason = event.detail.value)}
          ></hamie-input>
        </div>
      </hamie-dialog>
    `;
  }

  _renderRejectDialog() {
    return html`
      <hamie-dialog open heading="Reject this plan?" cancel-label="Cancel" confirm-label="Reject"
        destructive .busy=${!!this._busy} .errorMessage=${this._actionError || ""}
        .confirmDisabled=${!this._rejectReason?.trim()}
        .onConfirm=${() => this._confirmReject()} .onCancel=${() => this._cancelReject()}>
        <div class="dialog-reason">
          <label for="reject-reason">Reason (required)</label>
          <hamie-input id="reject-reason" .value=${this._rejectReason}
            @hamie-input=${(e) => (this._rejectReason = e.detail.value)}></hamie-input>
        </div>
      </hamie-dialog>
    `;
  }

  _renderRevokeDialog() {
    return html`
      <hamie-dialog open heading="Revoke this approval?" cancel-label="Cancel" confirm-label="Revoke approval"
        destructive .busy=${!!this._busy} .errorMessage=${this._actionError || ""}
        .confirmDisabled=${!this._revokeReason?.trim()}
        .onConfirm=${() => this._confirmRevoke()} .onCancel=${() => this._cancelRevoke()}>
        <div class="dialog-reason">
          <label for="revoke-reason">Reason (required)</label>
          <hamie-input id="revoke-reason" .value=${this._revokeReason}
            @hamie-input=${(e) => (this._revokeReason = e.detail.value)}></hamie-input>
        </div>
      </hamie-dialog>
    `;
  }

  _renderExecuteDialog() {
    const { plan, approval, affectedObject } = this._pendingExecute;
    return html`
      <hamie-dialog
        open
        heading="Execute this approved repair?"
        cancel-label="Cancel"
        confirm-label="Execute approved repair"
        .destructive=${plan.risk.destructive}
        .busy=${!!this._busy}
        .errorMessage=${this._actionError || ""}
        .confirmDisabled=${!this._executeConfirmed}
        .typedConfirmationPhrase=${plan.risk.destructive ? affectedObject : ""}
        .onConfirm=${() => this._confirmExecute()}
        .onCancel=${() => this._cancelExecute()}
      >
        <div class="confirm-summary">
          Action: ${plan.actions?.[0]?.action_type ?? "—"}<br />
          Object: ${affectedObject}<br />
          Risk: ${plan.risk.destructive ? "Destructive" : "Not destructive"} · Rollback: ${plan.risk.rollback_support}<br />
          Backup status: ${plan.requires_backup ? "Required -- verification pending" : "Not required"}<br />
          Approved by: ${approval.approved_by}
        </div>
        <p>Verification runs after the single allowlisted operation. A successful API response alone never resolves the finding.</p>
        <div class="ack-row">
          <hamie-switch .checked=${this._executeConfirmed} @hamie-change=${(e) => (this._executeConfirmed = e.detail.checked)}></hamie-switch>
          <label>I understand and want to execute this approved repair now.</label>
        </div>
      </hamie-dialog>
    `;
  }

  _renderRollbackDialog() {
    const { plan, execution, affectedObject } = this._pendingRollback;
    const rollbackStep = plan.rollback_plan?.steps?.[0];
    return html`
      <hamie-dialog
        open
        heading="Roll back this verified repair?"
        cancel-label="Cancel"
        confirm-label="Roll back"
        destructive
        .busy=${!!this._busy}
        .errorMessage=${this._actionError || ""}
        .typedConfirmationPhrase=${affectedObject}
        .onConfirm=${() => this._confirmRollback()}
        .onCancel=${() => this._cancelRollback()}
      >
        <p>This creates a new audited operation. It never erases the original execution evidence.</p>
        <div class="confirm-summary">
          Target: ${affectedObject}<br />
          Original execution: ${execution.execution_id}<br />
          Current operation: ${plan.actions?.[0]?.action_type ?? "—"}<br />
          Rollback operation: ${rollbackStep?.action_type ?? "restore exact prior state"}<br />
          Verification: ${plan.rollback_plan?.verification ?? "Verify the prior state was restored"}
        </div>
      </hamie-dialog>
    `;
  }

}
if (!customElements.get("hamie-view-remediation")) {
  customElements.define("hamie-view-remediation", HamieViewRemediation);
}
