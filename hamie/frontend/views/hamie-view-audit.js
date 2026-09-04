/**
 * <hamie-view-audit> — renders the "Activity" screen (spec: "chronological
 * operational timeline -- findings opened/resolved, scans, analyzer
 * failures, review decisions -- not a raw log dump"). Originally built
 * as Audit (no Figma source; a real HAMIE-only capability), on the
 * existing component library (hamie-card, hamie-table, hamie-button,
 * hamie-dialog). This pass changes only the primary list's presentation
 * from a <hamie-table> to the new <hamie-activity-timeline> primitive --
 * every field, the filters, and the Export/Clear actions below are the
 * exact same real `hamie/audit/list` data and commands, unchanged.
 *
 * Every field is real (operations_service.py's audit_page(),
 * `hamie/audit/list`): audit_id, event, at, actor, target_ids, details.
 * `event`/`actor` are free-form strings written by many different call
 * sites across the backend (e.g. "connector_test_succeeded",
 * "group_acknowledge", "ai_request_started") -- not a closed enum, so
 * no icon/type taxonomy is invented for them, just plain text.
 *
 * Actions, both real and verified against presentation/api.py before
 * writing this:
 * - "Export": the real `hamie/configuration/audit/export` command
 *   (requires `schema_version`) returns the full bounded secret-free
 *   history as one JSON object -- downloaded as a real file via a Blob,
 *   not a fabricated feature.
 * - "Clear history": the real `hamie/configuration/audit/clear` command
 *   -- requires `schema_version`, `expected_revision` (the page's own
 *   `revision` field, so a stale click after other changes correctly
 *   fails with the real "stale_revision" structured error code), a
 *   16-128 char `idempotency_token`, and a literal `confirmed: true`.
 *   Destructive, so gated behind a confirm dialog.
 * - Row "Details": the raw `details`/`target_ids` fields are shown
 *   verbatim in a dialog rather than summarized, since they're
 *   genuinely free-form per event type -- no fixed layout could
 *   honestly represent all of them.
 *
 * Pagination (matrix #67): audit_page() is a real offset/limit page
 * (server-capped at 100, hamie/audit/list). This view previously
 * always fetched a single fixed 100-record page and showed a static
 * "showing N of total" notice with no way to reach older events.
 * Fixed with the same offset-tracking prev/next pager used by
 * Findings/Groups/Recommendations.
 */
import { LitElement, css, html } from "lit";
import { createRef, ref } from "lit/directives/ref.js";

import { relativeTime } from "../format.js";
import { friendlyError } from "../errors.js";
import { idempotencyToken } from "../idempotency.js";
import "../components/hamie-page-header.js";
import "../components/hamie-card.js";
import "../components/hamie-activity-timeline.js";
import "../components/hamie-button.js";
import "../components/hamie-dialog.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";

const PAGE_SIZE = 25;

const EVENT_LABELS = {
  scan_completed: "Scan completed",
  connector_test_succeeded: "Connector test succeeded",
  connector_test_failed: "Connector test failed",
  ai_recommendation_created: "Recommendation generated",
  evidence_refreshed: "Evidence refreshed",
  remediation_plan_created: "Proposal created",
  remediation_proposal_snoozed: "Proposal snoozed",
  remediation_proposal_resumed: "Proposal resumed",
  remediation_proposal_snooze_expired: "Proposal snooze expired",
  backup_started: "Backup started",
  backup_verified: "Backup verified",
  remediation_approval_granted: "Proposal approved",
  remediation_approval_rejected: "Proposal rejected",
  remediation_execution_started: "Execution started",
  remediation_execution_succeeded: "Execution succeeded",
  remediation_execution_failed: "Execution failed",
  remediation_verification_passed: "Verification passed",
  remediation_verification_failed: "Verification failed",
  remediation_rollback_started: "Rollback started",
  remediation_rollback_succeeded: "Rollback completed",
  group_snooze: "Findings snoozed",
  group_dismiss: "Findings dismissed",
  audit_history_cleared: "Audit history cleared",
};

function eventLabel(event) {
  return EVENT_LABELS[event] || event.replaceAll("_", " ").replace(/^./, (value) => value.toUpperCase());
}

// target_ids is free-form per event type (this file's own docstring) --
// a real Home Assistant entity_id ("sensor.xyz") is a recognizable,
// user-meaningful identifier and safe to show as-is; anything else
// (a raw internal finding_id/group_id/plan_id hash) is not something an
// ordinary user should have to read in the primary table -- the full
// list remains available in "Details" (see _detail rendering below).
const ENTITY_ID_PATTERN = /^[a-z_]+\.[a-z0-9_]+$/;

function targetSummary(targetIds) {
  if (!targetIds.length) return "—";
  if (targetIds.length === 1 && ENTITY_ID_PATTERN.test(targetIds[0])) return targetIds[0];
  return `${targetIds.length} object${targetIds.length === 1 ? "" : "s"}`;
}

// details.outcome is a raw domain enum value (ExecutionOutcome/
// RollbackOutcome in remediation_execution.py, e.g. "partially_succeeded",
// "rolled_back") -- always lowercase snake_case, unlike the humanized
// event-name fallback below, so it needs the same title-case treatment.
function eventOutcome(item) {
  if (item.details?.outcome) return item.details.outcome.replaceAll("_", " ").replace(/^./, (value) => value.toUpperCase());
  if (item.event.endsWith("_failed") || item.event.endsWith("_rejected")) return "Failed";
  if (item.event.endsWith("_succeeded") || item.event.endsWith("_completed") || item.event.endsWith("_passed")) return "Succeeded";
  return "Recorded";
}

// Timeline dot tone/icon -- derived from the exact same real outcome
// signal `eventOutcome` above already computes, never a second
// independent classification of the same event.
function eventTone(item) {
  const outcome = eventOutcome(item);
  if (outcome === "Failed") return "critical";
  if (outcome === "Succeeded") return "healthy";
  return "info";
}

const EVENT_ICON_PREFIX = [
  [/^scan/, "mdi:magnify"],
  [/^connector/, "mdi:swap-horizontal"],
  [/^ai_/, "mdi:brain"],
  [/^remediation_execution/, "mdi:play-circle-outline"],
  [/^remediation_rollback/, "mdi:undo-variant"],
  [/^remediation_approval/, "mdi:check-decagram-outline"],
  [/^remediation/, "mdi:wrench-check-outline"],
  [/^group_/, "mdi:folder-alert-outline"],
  [/^maintenance_work/, "mdi:broom"],
  [/^configuration/, "mdi:cog-outline"],
  [/^audit_history/, "mdi:clipboard-text-clock-outline"],
];

function eventIcon(event) {
  return EVENT_ICON_PREFIX.find(([pattern]) => pattern.test(event))?.[1] || "mdi:circle-small";
}

export class HamieViewAudit extends LitElement {
  static properties = {
    hass: { attribute: false },
    _page: { state: true },
    _offset: { state: true },
    _error: { state: true },
    _actionError: { state: true },
    _detail: { state: true }, // the one audit record currently shown in the details dialog
    _clearing: { state: true },
    _confirmingClear: { state: true },
    _filters: { state: true },
  };

  _clearHistoryTriggerRef = createRef();

  // Focus must return to the control that opened the dialog once it
  // closes (Cancel, X, Escape, or a successful clear all route through
  // this same dialog-closed handler) -- not left stranded on whatever
  // the browser's default post-removal focus target happens to be.
  _onConfirmClearDialogClosed() {
    this._confirmingClear = false;
    this._clearHistoryTriggerRef.value?.focus();
  }

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
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
    .audit-filters {
      display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: var(--hamie-space-2); margin-bottom: var(--hamie-space-3);
    }
    .audit-filters input {
      min-height: 38px; box-sizing: border-box; width: 100%;
      color: var(--hamie-text-primary); background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-md); padding: 8px;
    }
    @media (max-width: 870px) {
      .audit-filters { grid-template-columns: 1fr; }
    }
    .pager {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--hamie-space-3) var(--hamie-space-4);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      border-top: 1px solid var(--hamie-border-hairline);
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      font-size: var(--hamie-text-micro);
      font-family: var(--hamie-font-code);
      color: var(--hamie-text-secondary);
      margin: 0;
    }
  `;

  constructor() {
    super();
    this._offset = 0;
    this._filters = {};
  }

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  async _load() {
    if (!this.hass) return;
    try {
      this._page = await this.hass.callWS({
        type: "hamie/audit/list",
        offset: this._offset,
        limit: PAGE_SIZE,
        ...this._filters,
      });
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Audit history is temporarily unavailable.");
    }
  }

  _nextPage() {
    this._offset += PAGE_SIZE;
    this._load();
  }

  _previousPage() {
    this._offset = Math.max(0, this._offset - PAGE_SIZE);
    this._load();
  }

  async _onExport() {
    if (!this.hass) return;
    this._actionError = null;
    try {
      const data = await this.hass.callWS({
        type: "hamie/configuration/audit/export",
        schema_version: 2,
      });
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `hamie-audit-export-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      this._actionError = friendlyError(err, "The audit history could not be exported.");
    }
  }

  async _onConfirmClear() {
    if (!this.hass || !this._page) return;
    this._clearing = true;
    try {
      await this.hass.callWS({
        type: "hamie/configuration/audit/clear",
        schema_version: 2,
        expected_revision: this._page.revision,
        idempotency_token: idempotencyToken(),
        confirmed: true,
      });
      this._onConfirmClearDialogClosed();
      this._offset = 0;
      await this._load();
    } catch (err) {
      this._actionError = friendlyError(err, "Audit history could not be cleared.");
    } finally {
      this._clearing = false;
    }
  }

  render() {
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="Audit history is unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._page) {
      return html`<hamie-loading .lines=${4}></hamie-loading>`;
    }

    const items = this._page.items;
    const timelineItems = items.map((item) => ({
      id: item.audit_id,
      icon: eventIcon(item.event),
      tone: eventTone(item),
      heading: eventLabel(item.event),
      meta: `${item.actor} · ${targetSummary(item.target_ids)} · ${eventOutcome(item)}`,
      timeLabel: relativeTime(item.at),
      raw: item,
    }));

    return html`
      <hamie-page-header
        heading="Activity"
        subtitle="${this._page.total} recorded event${this._page.total === 1 ? "" : "s"}"
      >
        <div slot="actions" class="header-actions">
          <hamie-button variant="secondary" size="sm" @click=${this._onExport}>
            <ha-icon icon="mdi:download-outline"></ha-icon> Export
          </hamie-button>
          <hamie-button
            ${ref(this._clearHistoryTriggerRef)}
            variant="danger"
            size="sm"
            ?disabled=${items.length === 0}
            @click=${() => (this._confirmingClear = true)}
          >
            <ha-icon icon="mdi:trash-can-outline"></ha-icon> Clear history
          </hamie-button>
        </div>
      </hamie-page-header>

      <div class="audit-filters" aria-label="Audit filters">
        ${[
          ["event_type", "Event type"],
          ["actor", "Actor"],
          ["target", "Target"],
          ["outcome", "Outcome"],
          ["date_from", "Date from (aware ISO)"],
          ["date_to", "Date to (aware ISO)"],
          ["proposal", "Proposal ID"],
          ["finding", "Finding ID"],
        ].map(([key, placeholder]) => html`
          <input
            aria-label=${placeholder}
            placeholder=${placeholder}
            .value=${this._filters[key] || ""}
            @input=${(event) => (this._filters = { ...this._filters, [key]: event.target.value })}
          />
        `)}
        <hamie-button variant="secondary" size="sm" @click=${() => { this._offset = 0; this._load(); }}>Apply filters</hamie-button>
        <hamie-button variant="ghost" size="sm" @click=${() => { this._filters = {}; this._offset = 0; this._load(); }}>Clear filters</hamie-button>
      </div>

      ${this._actionError
        ? html`
            <div class="action-error">
              <span>${this._actionError}</span>
              <hamie-button variant="ghost" size="xs" @click=${() => (this._actionError = null)}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          `
        : null}

      <hamie-card padding="md">
        ${timelineItems.length === 0
          ? html`<hamie-empty tone="neutral" heading="No activity yet"></hamie-empty>`
          : html`<hamie-activity-timeline interactive .items=${timelineItems} @hamie-timeline-click=${(event) => (this._detail = items.find((item) => item.audit_id === event.detail.id))}></hamie-activity-timeline>`}
        ${this._page.total > 0
          ? html`
              <div class="pager">
                <hamie-button variant="ghost" size="xs" ?disabled=${this._offset === 0} @click=${this._previousPage}>Previous</hamie-button>
                <span>${this._offset + 1}–${Math.min(this._offset + PAGE_SIZE, this._page.total)} of ${this._page.total}</span>
                <hamie-button variant="ghost" size="xs" ?disabled=${this._offset + PAGE_SIZE >= this._page.total} @click=${this._nextPage}>Next</hamie-button>
              </div>
            `
          : null}
      </hamie-card>

      ${this._detail
        ? html`
            <hamie-dialog open heading="${eventLabel(this._detail.event)}" @hamie-dialog-closed=${() => (this._detail = null)}>
              <p><strong>Actor:</strong> ${this._detail.actor}</p>
              <p><strong>When:</strong> ${relativeTime(this._detail.at)}</p>
              <p><strong>Targets:</strong> ${this._detail.target_ids.length ? this._detail.target_ids.join(", ") : "none"}</p>
              <p><strong>Details:</strong></p>
              <pre>${JSON.stringify(this._detail.details, null, 2)}</pre>
              <hamie-button slot="primary-action" variant="secondary" size="sm" @click=${() => (this._detail = null)}>
                Close
              </hamie-button>
            </hamie-dialog>
          `
        : null}

      ${this._confirmingClear
        ? html`
            <hamie-dialog
              open
              heading="Clear all audit history?"
              cancel-label="Cancel"
              confirm-label="Clear history"
              destructive
              .busy=${this._clearing}
              .errorMessage=${this._actionError || ""}
              .onConfirm=${() => this._onConfirmClear()}
              .onCancel=${() => this._onConfirmClearDialogClosed()}
              .focusReturnTarget=${this._clearHistoryTriggerRef.value}
            >
              <p>
                This permanently clears all ${this._page.total} recorded audit event${this._page.total === 1 ? "" : "s"}.
                Home Assistant objects and HAMIE findings are not affected.
              </p>
            </hamie-dialog>
          `
        : null}
    `;
  }
}

if (!customElements.get("hamie-view-audit")) {
  customElements.define("hamie-view-audit", HamieViewAudit);
}
