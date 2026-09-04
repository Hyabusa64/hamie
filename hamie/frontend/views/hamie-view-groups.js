/**
 * <hamie-view-groups> — no Figma source (Groups is a real HAMIE-only
 * capability the design audit identified with no corresponding screen
 * in the extracted project). A legitimate, documented extension of the
 * reconstructed design system, built entirely from the existing
 * component library (hamie-card, hamie-status, hamie-button,
 * hamie-dialog) so it reads as part of the same visual language.
 *
 * Every field is real (domain/intelligence.py's _group_dict(), returned
 * by `hamie/explorer/groups`): title, priority, member_count,
 * warning_count, critical_count, review_state, coverage_state.
 *
 * Capability-matrix fixes (docs/CAPABILITY_MATRIX.md #13-16): added
 * search + real pagination (previously a fixed page of 25 with no way
 * to search or see more); a "Details" dialog surfacing the rest of the
 * real _group_dict() fields never shown before (open_count vs.
 * member_count, coverage_state, ai_explanation_state, common_provider,
 * common_dependency_root, representative_subjects, member_finding_ids);
 * "View Findings" (the real Groups -> Findings handoff -- matches the
 * legacy panel's "Open Group" button exactly: replaces Findings'
 * filters with `{group_id: ...}` verbatim rather than merging it with
 * whatever filters happened to be active, the same real behavior legacy
 * has) and "View dependency graph" (the real per-group impact graph,
 * reusing the same hamie-navigate-dependencies handoff Findings uses).
 *

 * Group review actions (acknowledge/dismiss/snooze/retain/suppress),
 * implemented here for the first time. Verified end-to-end against
 * presentation/api.py + application/operations_service.py before
 * writing this (not guessed -- a fabricated shape here would just
 * reproduce the same "frontend sends a shape the backend rejects" bugs
 * already found and fixed elsewhere this pass):
 *
 * - Every action is a strict two-call preview -> apply flow.
 *   `hamie/group/preview` takes only {group_id, action} and returns
 *   {group_id, action, generation, count, findings: [[finding_id,
 *   content_revision], ...]} -- nothing richer (no finding titles/
 *   severities). The whole preview object must then be echoed back
 *   verbatim as the `preview` field on `hamie/group/apply` (for
 *   acknowledge/dismiss/snooze/retain) or `hamie/group/suppress` (a
 *   separate command, requiring the same echoed preview plus a
 *   required `reason` string) -- apply never accepts a bare
 *   group_id/action pair on its own.
 * - The server generates no idempotency token; the client must
 *   generate one itself (idempotency.js, the same real algorithm the
 *   currently-shipping hamie-panel.js already uses) and pass it as
 *   `idempotency_token` on apply/suppress. Reusing a token for the same
 *   command+group is a safe replay; reusing it for a different one is
 *   a real conflict (IdempotencyConflictError).
 * - "suppress" is not a member of the ReviewAction enum and can never
 *   be sent to `group/apply` -- it only exists as its own command.
 * - Preview's `count` is the number of *eligible* member findings for
 *   that specific action (open + in an allowed prior review_state,
 *   domain/reviews.py ALLOWED_PRIOR_STATES) -- it can legitimately be
 *   0 (e.g. every member already dismissed). All 5 actions are always
 *   offered rather than guessing eligibility client-side from the
 *   group's own aggregate `review_state` (which is often "mixed"
 *   anyway) -- the real preview count is the honest signal, shown
 *   before any confirmation, and a 0-count preview is reported plainly
 *   rather than opening a pointless confirm dialog.
 * - Group-action errors (GroupPreviewConflictError, GroupNotFoundError,
 *   InvalidReviewTransitionError, IdempotencyConflictError) all carry
 *   the generic `hamie_error` wire code, never `stale_revision` --
 *   errors.js's friendlyError() matches these by exception class name
 *   instead, so they still get an honest, specific message rather than
 *   falling through to a vague generic one.
 * - No richer confirmation content exists on the wire (verified: the
 *   preview payload really has nothing beyond the count and raw
 *   finding_id/content_revision pairs) -- the confirm dialog shows the
 *   real count and the group's own title, matching what the currently
 *   shipping panel does, not a fabricated richer preview.
 */
import { LitElement, css, html } from "lit";

import { relativeTime } from "../format.js";
import { friendlyError } from "../errors.js";
import { idempotencyToken } from "../idempotency.js";
import { groupingReasonLabel } from "../grouping-reason.js";
import "../components/hamie-page-header.js";
import "../components/hamie-card.js";
import "../components/hamie-status.js";
import "../components/hamie-button.js";
import "../components/hamie-dialog.js";
import "../components/hamie-input.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";
import "../components/hamie-disclosure.js";

const PAGE_SIZE = 25;

const ACTIONS = [
  { id: "acknowledge", label: "Acknowledge", icon: "mdi:check-circle-outline" },
  { id: "snooze", label: "Snooze", icon: "mdi:clock-outline" },
  { id: "retain", label: "Retain", icon: "mdi:shield-check-outline" },
  { id: "dismiss", label: "Dismiss", icon: "mdi:close-circle-outline" },
  { id: "suppress", label: "Suppress", icon: "mdi:eye-off-outline" },
];

export class HamieViewGroups extends LitElement {
  static properties = {
    hass: { attribute: false },
    _groups: { state: true },
    _total: { state: true },
    _offset: { state: true },
    _search: { state: true },
    _error: { state: true },
    _actionError: { state: true },
    _busyGroupId: { state: true },
    _pending: { state: true }, // { group, action, preview } once a preview succeeds with count > 0
    _reason: { state: true }, // suppress-only: user-entered reason text
    _detailGroup: { state: true },
  };

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
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
    .list {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-2-5);
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
    .reason {
      margin: 2px 0 0;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .stats {
      margin-top: var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .badges {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      flex-shrink: 0;
    }
    .priority-badge {
      font-size: var(--hamie-text-caption);
      font-family: var(--hamie-font-code);
      color: var(--hamie-text-secondary);
      background: var(--hamie-surface-raised);
      padding: 1px var(--hamie-space-1-5);
      border-radius: var(--hamie-radius-sm);
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1);
      margin-top: var(--hamie-space-2);
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
    .toolbar {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-3);
    }
    .search {
      width: 280px;
    }
    .pager {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--hamie-space-3) 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .detail-meta {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.8;
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
    .detail-list {
      margin: 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
  `;

  constructor() {
    super();
    this._search = "";
    this._offset = 0;
  }

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  async _load() {
    if (!this.hass) return;
    try {
      const result = await this.hass.callWS({
        type: "hamie/explorer/groups",
        search: this._search,
        offset: this._offset,
        limit: PAGE_SIZE,
      });
      this._groups = result.items;
      this._total = result.total;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Groups are temporarily unavailable.");
    }
  }

  _onSearchInput(event) {
    this._search = event.detail.value;
  }

  _onSearchApply() {
    this._offset = 0;
    this._load();
  }

  _nextPage() {
    this._offset += PAGE_SIZE;
    this._load();
  }

  _previousPage() {
    this._offset = Math.max(0, this._offset - PAGE_SIZE);
    this._load();
  }

  _onViewFindings(group) {
    this.dispatchEvent(
      new CustomEvent("hamie-navigate-findings-group", {
        detail: { groupId: group.group_id, groupTitle: group.title },
        bubbles: true,
        composed: true,
      }),
    );
  }

  _onViewDependencyGraph(group) {
    this._detailGroup = null;
    this.dispatchEvent(
      new CustomEvent("hamie-navigate-dependencies", { detail: { groupId: group.group_id }, bubbles: true, composed: true }),
    );
  }

  _statusFor(group) {
    if (group.critical_count > 0) return "critical";
    if (group.warning_count > 0) return "warning";
    return "info";
  }

  async _onAction(group, action) {
    if (!this.hass || this._busyGroupId) return;
    this._actionError = null;
    this._busyGroupId = group.group_id;
    try {
      const preview = await this.hass.callWS({
        type: "hamie/group/preview",
        group_id: group.group_id,
        action,
      });
      if (preview.count === 0) {
        this._actionError = `No eligible findings for "${ACTIONS.find((item) => item.id === action)?.label}" in "${group.title}".`;
        return;
      }
      this._reason = "";
      this._pending = { group, action, preview };
    } catch (err) {
      this._actionError = friendlyError(err, "That action could not be started.");
    } finally {
      this._busyGroupId = null;
    }
  }

  _cancelPending() {
    this._pending = null;
    this._reason = "";
  }

  async _confirmPending() {
    if (!this.hass || !this._pending) return;
    const { group, action, preview } = this._pending;
    this._busyGroupId = group.group_id;
    try {
      if (action === "suppress") {
        await this.hass.callWS({
          type: "hamie/group/suppress",
          preview,
          idempotency_token: idempotencyToken(),
          // Required by the server schema (vol.Required("reason")) --
          // the Confirm button stays disabled until this is non-empty,
          // so there is no silent default to fall back on here.
          reason: this._reason.trim(),
        });
      } else {
        await this.hass.callWS({
          type: "hamie/group/apply",
          preview,
          idempotency_token: idempotencyToken(),
        });
      }
      this._pending = null;
      this._reason = "";
      await this._load();
    } catch (err) {
      this._actionError = friendlyError(err, "That action could not be applied.");
    } finally {
      this._busyGroupId = null;
    }
  }

  render() {
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="Groups are unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._groups) {
      return html`<hamie-loading .lines=${4}></hamie-loading>`;
    }

    return html`
      <hamie-page-header
        heading="Groups"
        subtitle="${this._total ?? this._groups.length} deterministic finding group${(this._total ?? this._groups.length) === 1 ? "" : "s"}"
      ></hamie-page-header>

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

      <div class="toolbar">
        <hamie-input
          class="search"
          placeholder="Search groups…"
          icon="mdi:magnify"
          .value=${this._search}
          @hamie-input=${this._onSearchInput}
          @keydown=${(event) => event.key === "Enter" && this._onSearchApply()}
        ></hamie-input>
        <hamie-button variant="secondary" size="sm" @click=${this._onSearchApply}>Search</hamie-button>
      </div>

      ${this._groups.length === 0
        ? html`<hamie-card padding="md"><hamie-empty tone="positive" heading="No groups yet"></hamie-empty></hamie-card>`
        : html`
            <div class="list">
              ${this._groups.map(
                (group) => html`
                  <hamie-card padding="md">
                    <div class="row">
                      <div>
                        <p class="title">${group.title}</p>
                        <p class="reason">${groupingReasonLabel(group.grouping_reason)}</p>
                        <p class="stats">
                          ${group.open_count} open of ${group.member_count} finding${group.member_count === 1 ? "" : "s"} · ${group.warning_count} warning · ${group.critical_count} critical
                          · updated ${relativeTime(group.last_seen)}
                        </p>
                      </div>
                      <div class="badges">
                        <span class="priority-badge">priority ${group.priority}</span>
                        <hamie-status status=${group.coverage_state === "complete" ? "healthy" : "warning"} label="Coverage: ${group.coverage_state}"></hamie-status>
                        <hamie-status status=${this._statusFor(group)} label=${group.review_state}></hamie-status>
                      </div>
                    </div>
                    <div class="actions">
                      ${ACTIONS.map(
                        (item) => html`
                          <hamie-button
                            variant="ghost"
                            size="xs"
                            ?disabled=${this._busyGroupId === group.group_id}
                            @click=${() => this._onAction(group, item.id)}
                          >
                            <ha-icon icon=${item.icon}></ha-icon> ${item.label}
                          </hamie-button>
                        `,
                      )}
                      <hamie-button variant="secondary" size="xs" @click=${() => (this._detailGroup = group)}>Details</hamie-button>
                      <hamie-button variant="secondary" size="xs" @click=${() => this._onViewFindings(group)}>View Findings</hamie-button>
                    </div>
                  </hamie-card>
                `,
              )}
            </div>
            <div class="pager">
              <hamie-button variant="ghost" size="xs" ?disabled=${this._offset === 0} @click=${this._previousPage}>Previous</hamie-button>
              <span>${this._total === 0 ? 0 : this._offset + 1}–${Math.min(this._offset + PAGE_SIZE, this._total)} of ${this._total}</span>
              <hamie-button variant="ghost" size="xs" ?disabled=${this._offset + PAGE_SIZE >= this._total} @click=${this._nextPage}>Next</hamie-button>
            </div>
          `}

      ${this._detailGroup ? this._renderDetailDialog(this._detailGroup) : null}

      ${this._pending
        ? html`
            <hamie-dialog
              open
              heading="${ACTIONS.find((item) => item.id === this._pending.action)?.label} findings?"
              cancel-label="Cancel"
              .confirmLabel=${ACTIONS.find((item) => item.id === this._pending.action)?.label || "Confirm"}
              .destructive=${["dismiss", "suppress"].includes(this._pending.action)}
              .busy=${!!this._busyGroupId}
              .errorMessage=${this._actionError || ""}
              .confirmDisabled=${this._pending.action === "suppress" && !this._reason?.trim()}
              .onConfirm=${() => this._confirmPending()}
              .onCancel=${() => this._cancelPending()}
            >
              <p>
                ${ACTIONS.find((item) => item.id === this._pending.action)?.label} exactly ${this._pending.preview.count}
                finding${this._pending.preview.count === 1 ? "" : "s"} in "${this._pending.group.title}".
                ${this._pending.action === "snooze" ? "They will be snoozed for exactly 24 hours." : ""}
                ${this._pending.action === "suppress" ? "They will be hidden from default views, not deleted." : ""}
                Home Assistant objects will not be changed.
              </p>
              ${this._pending.action === "suppress"
                ? html`
                    <div class="dialog-reason">
                      <label for="suppress-reason">Reason (required)</label>
                      <hamie-input
                        id="suppress-reason"
                        placeholder="Why is this being suppressed?"
                        .value=${this._reason}
                        @hamie-input=${(event) => (this._reason = event.detail.value)}
                      ></hamie-input>
                    </div>
                  `
                : null}
            </hamie-dialog>
          `
        : null}
    `;
  }

  _renderDetailDialog(group) {
    return html`
      <hamie-dialog open heading="${group.title}" @hamie-dialog-closed=${() => (this._detailGroup = null)}>
        <p>${groupingReasonLabel(group.grouping_reason)}</p>
        <div class="detail-section">
          <h3>Coverage &amp; review</h3>
          <p class="detail-meta">
            Coverage: ${group.coverage_state} · Review: ${group.review_state} · Suppression: ${group.suppression_state}<br />
            AI explanation: ${group.ai_explanation_state} · Confidence: ${group.confidence}<br />
            First seen: ${relativeTime(group.first_seen)} · Last seen: ${relativeTime(group.last_seen)}
          </p>
        </div>
        ${group.common_provider || group.common_dependency_root
          ? html`
              <div class="detail-section">
                <h3>Common attribution</h3>
                <p class="detail-meta">
                  ${group.common_provider ? html`Provider: ${group.common_provider}<br />` : null}
                  ${group.common_dependency_root ? html`Dependency root: ${group.common_dependency_root}` : null}
                </p>
              </div>
            `
          : null}
        ${group.representative_subjects?.length
          ? html`
              <div class="detail-section">
                <h3>Representative subjects</h3>
                <ul class="detail-list">${group.representative_subjects.map((s) => html`<li>${s}</li>`)}</ul>
              </div>
            `
          : null}
        <div class="detail-section">
          <h3>Member findings (${group.member_count})</h3>
          <p class="detail-meta">Use "View Findings" below to inspect each one with a friendly name.</p>
          <hamie-disclosure label="Technical details">
            <ul class="detail-list">
              ${group.member_finding_ids.map((id) => html`<li>${id}</li>`)}
            </ul>
            ${group.member_list_truncated ? html`<p class="detail-meta">List truncated -- use View Findings for the full set.</p>` : null}
          </hamie-disclosure>
        </div>
        <div class="detail-section" style="display: flex; gap: var(--hamie-space-2);">
          <hamie-button variant="secondary" size="xs" @click=${() => this._onViewFindings(group)}>View Findings</hamie-button>
          <hamie-button variant="secondary" size="xs" @click=${() => this._onViewDependencyGraph(group)}>View dependency graph</hamie-button>
        </div>
        <hamie-button slot="primary-action" variant="secondary" size="sm" @click=${() => (this._detailGroup = null)}>
          Close
        </hamie-button>
      </hamie-dialog>
    `;
  }
}

if (!customElements.get("hamie-view-groups")) {
  customElements.define("hamie-view-groups", HamieViewGroups);
}
