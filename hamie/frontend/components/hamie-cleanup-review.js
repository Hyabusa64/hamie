/**
 * <hamie-cleanup-review> — the real decision workspace Clean Up must end
 * in (mission: "Clean Up is a decision workflow", "the central product
 * requirement"). Auto-opens after `hamie/cleanup/run` completes and turns
 * its response into a small number of understandable buckets instead of
 * a wall of findings:
 *
 * - Safe to disable: real `RemediationPlan`s Clean Up already created
 *   (`summary.batches`) -- Disable routes through the exact same
 *   canonical remediation pipeline the Review Queue uses
 *   (preview/generate -> approve -> execute, real WS commands, no
 *   parallel execution path).
 * - Protected / Needs evidence / Integration issue: durable
 *   `MaintenanceWorkRecord`s (`summary.persisted_maintenance_work_items`)
 *   grouped by their real `classification` field. Keep/Unsure call the
 *   new `hamie/maintenance/decide` command, which persists the decision
 *   (Keep is a USER_MANAGED_STATE -- see domain/maintenance_work_record.py
 *   -- so a future Clean Up pass never silently re-nags about the same
 *   unchanged object). Gather Evidence reuses the existing
 *   `hamie/remediation/gather_evidence` command already wired into
 *   Review Queue.
 *
 * Scope note, honestly documented rather than silently shipped as if
 * complete: cleanup batches are proposed as one or two flat
 * ("Safe auto-fix cleanup" / "Cleanup requiring approval") plans, not
 * pre-grouped per integration/device server-side (confirmed in
 * application/cleanup_coordinator.py's `_propose` calls) -- entity-level
 * rows within a batch use `hass.states[id].attributes.friendly_name`
 * (real, already-available client-side for any registered entity) with a
 * humanized-id fallback, but the "Ready to disable" tab does not yet
 * sub-group a batch by device the way the non-actionable buckets'
 * per-record titles already do.
 */
import { LitElement, css, html } from "lit";

import { friendlyError } from "../errors.js";
import { idempotencyToken } from "../idempotency.js";
import "./hamie-drawer.js";
import "./hamie-button.js";
import "./hamie-status.js";
import "./hamie-empty.js";
import "./hamie-dialog.js";

const CLASSIFICATION_TAB = {
  blocked_dependency: "protected",
  blocked_uncertain: "needs_evidence",
  manual_review: "needs_evidence",
  parent_integration_failure: "integration_issue",
};

const TABS = [
  { id: "ready", label: "Safe to disable" },
  { id: "protected", label: "Protected" },
  { id: "needs_evidence", label: "Needs evidence" },
  { id: "integration_issue", label: "Integration issues" },
];

function humanizeEntityId(entityId) {
  const slug = entityId.split(".").slice(1).join(".");
  return slug
    .split(/[_.]/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export class HamieCleanupReview extends LitElement {
  static properties = {
    hass: { attribute: false },
    open: { type: Boolean },
    summary: { attribute: false },
    _tab: { state: true },
    _expandedBatch: { state: true },
    _workItems: { state: true },
    _batches: { state: true },
    _busy: { state: true },
    _actionError: { state: true },
    _pendingDisable: { state: true },
  };

  static styles = css`
    :host {
      display: contents;
    }
    .summary-row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--hamie-space-5);
      padding-bottom: var(--hamie-space-4);
      margin-bottom: var(--hamie-space-4);
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .stat {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .stat strong {
      font-size: var(--hamie-text-metric);
      font-weight: var(--hamie-weight-bold);
      color: var(--hamie-text-primary);
    }
    .stat span {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .tabs {
      display: flex;
      gap: var(--hamie-space-1);
      margin-bottom: var(--hamie-space-4);
      border-bottom: 1px solid var(--hamie-border-hairline);
      overflow-x: auto;
    }
    .tabs button {
      background: none;
      border: 0;
      border-bottom: 2px solid transparent;
      padding: var(--hamie-space-2) var(--hamie-space-3);
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      cursor: pointer;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .tabs button[aria-selected="true"] {
      color: var(--hamie-text-primary);
      border-bottom-color: var(--hamie-accent);
      font-weight: var(--hamie-weight-medium);
    }
    .group-row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-3) 0;
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .group-row:last-child {
      border-bottom: none;
    }
    .group-title {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .group-meta {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      max-width: 60ch;
    }
    .group-actions {
      display: flex;
      gap: var(--hamie-space-2);
      flex-shrink: 0;
      align-items: center;
    }
    .members {
      margin: var(--hamie-space-2) 0 var(--hamie-space-3);
      padding-left: var(--hamie-space-4);
      border-left: 2px solid var(--hamie-border-hairline);
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-1-5);
    }
    .member-row {
      display: flex;
      align-items: baseline;
      gap: var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
    }
    .member-row .name {
      color: var(--hamie-text-primary);
    }
    .member-row .id {
      color: var(--hamie-text-secondary);
      font-family: var(--hamie-font-code);
    }
    .members-more {
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
  `;

  willUpdate(changed) {
    if (changed.has("summary") && this.summary) {
      this._workItems = [...(this.summary.persisted_maintenance_work_items || [])];
      this._batches = [...(this.summary.batches || [])];
      this._tab = this._defaultTab();
      this._expandedBatch = null;
      this._actionError = null;
    }
  }

  _defaultTab() {
    const readyCount = (this._batches || []).filter(
      (batch) => batch.remediation_plan_id && !batch.auto_executed,
    ).length;
    if (readyCount > 0) return "ready";
    const buckets = this._bucketCounts();
    return TABS.find((tab) => tab.id !== "ready" && buckets[tab.id] > 0)?.id || "ready";
  }

  _bucketCounts() {
    const counts = { protected: 0, needs_evidence: 0, integration_issue: 0 };
    for (const item of this._workItems || []) {
      const tab = CLASSIFICATION_TAB[item.classification];
      if (tab && item.lifecycle_state !== "completed") counts[tab] += 1;
    }
    return counts;
  }

  _itemsForTab(tab) {
    return (this._workItems || []).filter(
      (item) => CLASSIFICATION_TAB[item.classification] === tab && item.lifecycle_state !== "completed",
    );
  }

  _readyBatches() {
    return (this._batches || []).filter((batch) => batch.remediation_plan_id && !batch.auto_executed);
  }

  _entityLabel(entityId) {
    const friendly = this.hass?.states?.[entityId]?.attributes?.friendly_name;
    return friendly || humanizeEntityId(entityId);
  }

  async _decide(item, decision) {
    if (!this.hass || this._busy) return;
    this._busy = item.work_item_id;
    this._actionError = null;
    try {
      const updated = await this.hass.callWS({
        type: "hamie/maintenance/decide",
        work_item_id: item.work_item_id,
        decision,
      });
      if (decision === "keep") {
        this._workItems = this._workItems.filter((entry) => entry.work_item_id !== item.work_item_id);
      } else {
        this._workItems = this._workItems.map((entry) =>
          entry.work_item_id === item.work_item_id ? updated : entry,
        );
      }
      this.dispatchEvent(new CustomEvent("hamie-data-changed", { bubbles: true, composed: true }));
    } catch (err) {
      this._actionError = friendlyError(err, "That decision could not be recorded.");
    } finally {
      this._busy = null;
    }
  }

  async _gatherEvidence(item) {
    if (!this.hass || this._busy) return;
    this._busy = item.work_item_id;
    this._actionError = null;
    try {
      const result = await this.hass.callWS({
        type: "hamie/remediation/gather_evidence",
        work_item_id: item.work_item_id,
      });
      if (result.resolved) {
        this._workItems = this._workItems.filter((entry) => entry.work_item_id !== item.work_item_id);
      }
      this.dispatchEvent(new CustomEvent("hamie-data-changed", { bubbles: true, composed: true }));
    } catch (err) {
      this._actionError = friendlyError(err, "Evidence could not be gathered.");
    } finally {
      this._busy = null;
    }
  }

  _openDisable(batch) {
    this._pendingDisable = { batch, step: "confirm" };
  }

  _cancelDisable() {
    this._pendingDisable = null;
  }

  async _confirmDisable() {
    if (!this.hass || !this._pendingDisable) return;
    const { batch } = this._pendingDisable;
    this._busy = batch.remediation_plan_id;
    this._actionError = null;
    try {
      const preview = await this.hass.callWS({
        type: "hamie/remediation/preview/generate",
        remediation_plan_id: batch.remediation_plan_id,
        idempotency_token: idempotencyToken(),
      });
      const approval = await this.hass.callWS({
        type: "hamie/remediation/approve",
        remediation_plan_id: batch.remediation_plan_id,
        plan_fingerprint: preview.plan_fingerprint,
        preview_digest: preview.preview_digest,
        destructive_acknowledged: false,
        backup_acknowledged: false,
        warnings_acknowledged: [],
        idempotency_token: idempotencyToken(),
      });
      await this.hass.callWS({
        type: "hamie/remediation/execute",
        remediation_plan_id: batch.remediation_plan_id,
        approval_id: approval.approval_id,
        idempotency_token: idempotencyToken(),
        confirmed: true,
      });
      this._batches = this._batches.map((entry) =>
        entry.remediation_plan_id === batch.remediation_plan_id
          ? { ...entry, auto_executed: true, execution_succeeded: true }
          : entry,
      );
      this._pendingDisable = null;
      this.dispatchEvent(new CustomEvent("hamie-data-changed", { bubbles: true, composed: true }));
    } catch (err) {
      this._actionError = friendlyError(err, "That batch could not be disabled.");
      this._pendingDisable = null;
    } finally {
      this._busy = null;
    }
  }

  _renderReady() {
    const ready = this._readyBatches();
    if (!ready.length) {
      return html`<hamie-empty tone="positive" heading="Nothing new to disable" description="No batches are currently awaiting approval."></hamie-empty>`;
    }
    return ready.map((batch) => {
      const expanded = this._expandedBatch === batch.remediation_plan_id;
      const members = batch.entity_ids || [];
      const shown = expanded ? members.slice(0, 100) : [];
      return html`
        <div class="group-row" style="flex-direction: column; align-items: stretch">
          <div class="group-row" style="border: none; padding: 0">
            <div>
              <p class="group-title">${batch.batch_label}</p>
              <p class="group-meta">
                ${batch.entity_count} entit${batch.entity_count === 1 ? "y" : "ies"} — no dependencies were found in the sources HAMIE checked. Disabled entities remain in Home Assistant's registry and can be re-enabled later.
              </p>
            </div>
            <div class="group-actions">
              <hamie-button
                variant="ghost"
                size="xs"
                @click=${() => (this._expandedBatch = expanded ? null : batch.remediation_plan_id)}
              >
                ${expanded ? "Collapse" : `Review ${batch.entity_count}`}
              </hamie-button>
              <hamie-button
                variant="primary"
                size="sm"
                ?disabled=${this._busy === batch.remediation_plan_id}
                @click=${() => this._openDisable(batch)}
              >
                Disable ${batch.entity_count}
              </hamie-button>
            </div>
          </div>
          ${expanded
            ? html`
                <div class="members">
                  ${shown.map(
                    (entityId) => html`
                      <div class="member-row">
                        <span class="name">${this._entityLabel(entityId)}</span>
                        <span class="id">${entityId}</span>
                      </div>
                    `,
                  )}
                  ${members.length > shown.length
                    ? html`<span class="members-more">+${members.length - shown.length} more</span>`
                    : null}
                </div>
              `
            : null}
        </div>
      `;
    });
  }

  _renderWorkItems(tab) {
    const items = this._itemsForTab(tab);
    if (!items.length) {
      return html`<hamie-empty tone="positive" heading="Nothing here" description="No items in this category right now."></hamie-empty>`;
    }
    return items.map((item) => {
      const busy = this._busy === item.work_item_id;
      return html`
        <div class="group-row">
          <div>
            <p class="group-title">${item.title}</p>
            <p class="group-meta">
              ${item.entity_count} entit${item.entity_count === 1 ? "y" : "ies"} — ${item.reason}
              ${item.missing_evidence?.length ? html` Not yet checked: ${item.missing_evidence.join(", ")}.` : null}
            </p>
          </div>
          <div class="group-actions">
            ${tab !== "protected"
              ? html`<hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._gatherEvidence(item)}>Gather Evidence</hamie-button>`
              : null}
            <hamie-button variant="ghost" size="xs" ?disabled=${busy} @click=${() => this._decide(item, "unsure")}>Unsure</hamie-button>
            <hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._decide(item, "keep")}>Keep</hamie-button>
          </div>
        </div>
      `;
    });
  }

  render() {
    if (!this.summary) return null;
    const buckets = this._bucketCounts();
    const readyBatches = this._readyBatches();
    const readyEntityTotal = readyBatches.reduce((sum, batch) => sum + batch.entity_count, 0);
    const heading =
      readyEntityTotal > 0
        ? `${readyEntityTotal} candidate${readyEntityTotal === 1 ? "" : "s"} ready for review`
        : buckets.protected + buckets.needs_evidence + buckets.integration_issue > 0
          ? "Investigation needed"
          : "No maintenance needed";

    return html`
      <hamie-drawer
        wide
        .open=${this.open}
        heading="Cleanup review"
        description=${heading}
        .onClose=${() => this.dispatchEvent(new CustomEvent("hamie-cleanup-review-closed", { bubbles: true, composed: true }))}
      >
        ${this._actionError
          ? html`
              <div class="action-error" role="alert">
                <span>${this._actionError}</span>
                <hamie-button variant="ghost" size="xs" aria-label="Dismiss" @click=${() => (this._actionError = null)}>
                  <ha-icon icon="mdi:close"></ha-icon>
                </hamie-button>
              </div>
            `
          : null}

        <div class="summary-row">
          <div class="stat"><strong>${readyEntityTotal}</strong><span>Safe to disable</span></div>
          <div class="stat"><strong>${buckets.protected}</strong><span>Protected</span></div>
          <div class="stat"><strong>${buckets.needs_evidence}</strong><span>Need evidence</span></div>
          ${buckets.integration_issue
            ? html`<div class="stat"><strong>${buckets.integration_issue}</strong><span>Integration issues</span></div>`
            : null}
        </div>

        <div class="tabs" role="tablist">
          ${TABS.filter((tab) => tab.id !== "integration_issue" || buckets.integration_issue > 0).map((tab) => {
            const count = tab.id === "ready" ? readyBatches.length : buckets[tab.id];
            return html`
              <button role="tab" aria-selected=${this._tab === tab.id} @click=${() => (this._tab = tab.id)}>
                ${tab.label} (${count})
              </button>
            `;
          })}
        </div>

        ${this._tab === "ready" ? this._renderReady() : this._renderWorkItems(this._tab)}
      </hamie-drawer>

      ${this._pendingDisable
        ? html`
            <hamie-dialog
              open
              heading="Disable ${this._pendingDisable.batch.entity_count} entities?"
              description="These entities will remain in Home Assistant's entity registry but will no longer load normally. This is reversible -- re-enable them any time."
              confirm-label="Disable ${this._pendingDisable.batch.entity_count} entities"
              ?busy=${this._busy === this._pendingDisable.batch.remediation_plan_id}
              .onConfirm=${() => this._confirmDisable()}
              .onCancel=${() => this._cancelDisable()}
            ></hamie-dialog>
          `
        : null}
    `;
  }
}

if (!customElements.get("hamie-cleanup-review")) {
  customElements.define("hamie-cleanup-review", HamieCleanupReview);
}
