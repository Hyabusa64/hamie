/**
 * <hamie-view-recommendations> — reconstructed from App.tsx's
 * `RecommendationsPage`.
 *
 * Real-data reconciliation (recommendations_page() / operations_service.py):
 * - No `priority` field exists on real recommendations at all. Figma's
 *   high/medium/low badge has nothing to bind to -- omitted entirely
 *   (hamie-problem-card's priority is optional precisely for this).
 * - `confidence` is a real field but a *different concept* (how sure the
 *   AI is, not how urgent the issue is) -- shown as plain labeled text,
 *   never as a priority-shaped badge, so it can't be misread as urgency.
 * - No `category` field -- omitted.
 * - No discrete per-item "action" (Figma's "View entity"/"Create
 *   automation"/etc.) -- real recommendations are strictly advisory, not
 *   executable (the backend's own AI executor explicitly never takes
 *   actions). The one real, safe action available is viewing the related
 *   finding(s) via `finding_ids`, shown only when that data exists.
 * - Real structured content Figma never anticipated (`probable_causes`,
 *   `recommended_checks`) is shown via hamie-problem-card's `details`
 *   slot rather than dropped.
 * - "Dismiss" maps to the real `hamie/ai/review` command with
 *   state="rejected" (the closest real semantic equivalent -- there is
 *   no literal "dismissed" state, but "rejected" removes it from the
 *   active/new set the same way Figma's dismiss does).
 * - Empty state: Figma's positive "All clear" empty state is a genuine
 *   match for zero active recommendations -- reused directly via
 *   <hamie-empty tone="positive">, but only when zero actually means
 *   "nothing to report". Confirmed live on the RockPi beta device (audit
 *   log: repeated real ai_response_rejected/invalid_response entries,
 *   zero persisted recommendations ever) that a fully failing AI
 *   connector produces the exact same empty `hamie/recommendations/list`
 *   result as a healthy house with nothing wrong -- the list endpoint
 *   alone cannot tell those apart. Real production defect: every failed
 *   analysis rendered as a fresh, positive "All clear", the opposite of
 *   what happened. Fixed by also reading the real `hamie/connectors/status`
 *   ollama entry (the same data Connectors already displays) when the
 *   list is empty: an errored/degraded connector renders the existing
 *   "unavailable" tone with its real classified error instead of "All
 *   clear". A merely disabled or healthy-but-never-run connector still
 *   renders "All clear" -- zero recommendations because AI was never
 *   asked is not a failure.
 *
 * Capability-matrix fixes (docs/CAPABILITY_MATRIX.md #18-21): the legacy
 * panel shows every recommendation regardless of review_state (with the
 * state visible per item), the full `proposed_repair_plan` list,
 * provider/model/created_at metadata, and two real actions ("Analyze
 * Highest Priority" -- previews the top-priority group then requests an
 * advisory explanation for it; "Analyze Scan Summary" -- requests one
 * over the whole current scan). This view previously hid every
 * recommendation that wasn't review_state="new" and non-stale (with no
 * way to see them), never showed proposed_repair_plan or the provider/
 * model/created_at fields at all, and had no way to trigger new
 * analysis from this screen. All of these are real, already-defined
 * backend fields/commands (verified earlier this pass); fixed to match.
 * Dismiss (a real UI 3.0 addition with no legacy equivalent -- see the
 * matrix) is now only offered for the review_state="new"/non-stale
 * subset it actually applies to, since dismissing an already-resolved
 * recommendation has no real meaning, but every recommendation is shown.
 *
 * Pagination (matrix #67): the legacy panel pages recommendations via
 * the real offset/limit params on `hamie/recommendations/list` (server-
 * capped at 100 per operations_service.py's recommendations_page()).
 * This view previously discarded `total`/`offset` from the response and
 * always fetched a single fixed page with no way to see older
 * recommendations. Fixed with the same offset-tracking prev/next pager
 * used by Findings/Groups.
 */
import { LitElement, css, html } from "lit";

import { safeRelativeTime } from "../format.js";
import { friendlyError, humanizeCode } from "../errors.js";
import "../components/hamie-page-header.js";
import "../components/hamie-card.js";
import "../components/hamie-button.js";
import "../components/hamie-problem-card.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";
import "../components/hamie-disclosure.js";

const PAGE_SIZE = 25;

export class HamieViewRecommendations extends LitElement {
  static properties = {
    hass: { attribute: false },
    _items: { state: true },
    _total: { state: true },
    _offset: { state: true },
    _error: { state: true },
    _analyzing: { state: true },
    _analysisError: { state: true }, // Analyze-only failure; keeps existing recommendations visible
    _ollamaStatus: { state: true },
    _analysis: { state: true },
    _capability: { state: true },
    _probing: { state: true },
  };

  static styles = css`
    .capability {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      align-items: baseline;
      font-size: 0.85rem;
      color: var(--secondary-text-color, #666);
    }
    .capability strong {
      font-weight: 600;
      color: var(--primary-text-color, #212121);
    }
    .capability-failed {
      flex-basis: 100%;
      margin-top: 0.25rem;
      color: var(--error-color, #c62828);
    }
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-medium);
      box-sizing: border-box;
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      flex-shrink: 0;
    }
    .meta {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .list {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-2-5);
    }
    .confidence {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .details-list {
      margin: 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
    .pager {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--hamie-space-3) 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .analysis-error {
      margin-bottom: var(--hamie-space-4);
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

  constructor() {
    super();
    this._offset = 0;
  }

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  async _load() {
    if (!this.hass) return;
    try {
      const [result, connectors, overview] = await Promise.all([
        this.hass.callWS({
          type: "hamie/recommendations/list",
          offset: this._offset,
          limit: PAGE_SIZE,
        }),
        // Only needed to tell a genuine "nothing to report" empty result
        // apart from "every analysis attempt has been failing" -- both
        // produce an identical empty recommendations list on their own.
        this.hass.callWS({ type: "hamie/connectors/status" }).catch(() => []),
        // The authoritative analysis state. Deriving it here from an empty
        // list plus a healthy connector is exactly how this page came to
        // show "412 incidents", "evidence is too large" and "All clear"
        // together: the provider was healthy, the payload was too large,
        // and the list endpoint cannot tell "nothing is wrong" apart from
        // "nothing was looked at".
        this.hass.callWS({ type: "hamie/explorer/overview" }).catch(() => null),
      ]);
      this._items = result.items;
      this._total = result.total;
      this._ollamaStatus = connectors.find((item) => item.connector_id === "ollama") ?? null;
      this._analysis = overview?.analysis ?? null;
      this._capability = overview?.capability ?? null;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Recommendations are temporarily unavailable.");
    }
  }

  // Zero recommendations is only genuinely "All clear" when it does not
  // also mean "the AI connector has been failing". Only an actual
  // error/degraded connector status counts -- "disabled" or "healthy"
  // (AI simply hasn't run, or last ran fine) both still mean "All clear".
  // The backend decides whether "All clear" is honest. This method only
  // renders that decision -- it must never re-derive it.
  _allClearPermitted() {
    if (!this._analysis) return false;
    return this._analysis.all_clear_permitted === true;
  }

  _analysisIncompleteDescription() {
    const a = this._analysis;
    if (!a) {
      return "HAMIE could not determine whether analysis has covered this scan.";
    }
    const parts = [];
    if (a.eligible_total) {
      parts.push(`${a.analyzed_total} of ${a.eligible_total} findings analyzed`);
    }
    if (a.groups_total) {
      parts.push(`${a.groups_analyzed} of ${a.groups_total} root-cause groups`);
    }
    if (a.high_priority_unanalyzed) {
      parts.push(`${a.high_priority_unanalyzed} high-priority incident(s) not analyzed`);
    }
    if (a.failed_groups) parts.push(`${a.failed_groups} group(s) failed`);
    const counts = parts.length ? ` (${parts.join(", ")})` : "";
    return `${a.reason}${counts}. Zero recommendations here does not mean nothing is wrong.`;
  }

  _analysisHeading() {
    switch (this._analysis?.state) {
      case "not_analyzed":
        return "Not analyzed yet";
      case "analyzing":
        return "Analysis running";
      case "failed":
        return "Analysis failed";
      case "stale":
        return "Analysis out of date";
      case "provider_unavailable":
        return "AI provider unavailable";
      default:
        return "Analysis incomplete";
    }
  }

  _ollamaFailureDescription() {
    const status = this._ollamaStatus;
    if (!status || (status.status !== "error" && status.status !== "degraded")) {
      return null;
    }
    return humanizeCode(
      status.error_code,
      "HAMIE's AI provider has been failing to return a usable analysis. Review Connectors for details.",
    );
  }

  _nextPage() {
    this._offset += PAGE_SIZE;
    this._load();
  }

  _previousPage() {
    this._offset = Math.max(0, this._offset - PAGE_SIZE);
    this._load();
  }

  // A failed analysis (parse/schema/provider/duplicate-request rejection,
  // or genuinely nothing eligible to analyze) must never make already-
  // loaded, still-valid recommendations disappear -- only the page's own
  // initial load failing does that. This mirrors the exact banner pattern
  // House Health/Intelligence already use for the same reason.
  _reportAnalysisFailure(err, fallback) {
    const message = friendlyError(err, fallback);
    if (this._items) {
      this._analysisError = message;
    } else {
      this._error = message;
    }
  }

  async _onAnalyzeHighestPriority() {
    if (!this.hass) return;
    this._analyzing = true;
    this._analysisError = null;
    try {
      const groups = await this.hass.callWS({ type: "hamie/explorer/groups", search: "", offset: 0, limit: 1 });
      if (groups.items?.length) {
        await this.hass.callWS({ type: "hamie/ai/analyze", group_ids: [groups.items[0].group_id] });
        await this._load();
      }
    } catch (err) {
      this._reportAnalysisFailure(err, "That analysis could not be started.");
    } finally {
      this._analyzing = false;
    }
  }

  // Capability is measured by the backend. This renders the measurement --
  // it never infers "probably fine" from the connector being reachable,
  // which is the mistake that produced a healthy connector alongside zero
  // usable recommendations.
  _capabilitySummary() {
    const c = this._capability;
    if (!c) return null;
    const verdict = c.result?.verdict ?? c.gate?.verdict ?? "unknown";
    const model = c.model || "no model configured";
    const permitted = c.analysis_permitted === true;
    const failed = c.gate?.failed_dimensions ?? [];
    const probed = c.result?.probed_at ? new Date(c.result.probed_at).toLocaleString() : "never";
    return { verdict, model, permitted, failed, probed, reason: c.gate?.reason ?? "" };
  }

  async _onProbeCapability() {
    if (!this.hass) return;
    this._probing = true;
    this._analysisError = null;
    try {
      await this.hass.callWS({ type: "hamie/ai/capability/probe" });
      await this._load();
    } catch (err) {
      this._reportAnalysisFailure(err, "The capability probe could not be completed.");
    } finally {
      this._probing = false;
    }
  }

  async _onAnalyzeScanSummary() {
    if (!this.hass) return;
    this._analyzing = true;
    this._analysisError = null;
    try {
      await this.hass.callWS({ type: "hamie/ai/analyze" });
      await this._load();
    } catch (err) {
      this._reportAnalysisFailure(err, "There's nothing for HAMIE to analyze right now.");
    } finally {
      this._analyzing = false;
    }
  }

  async _onDismiss(recommendationId) {
    if (!this.hass) return;
    try {
      await this.hass.callWS({ type: "hamie/ai/review", recommendation_id: recommendationId, state: "rejected" });
      this._items = this._items.filter((item) => item.recommendation_id !== recommendationId);
    } catch (err) {
      this._error = friendlyError(err, "That recommendation could not be dismissed.");
    }
  }

  _onViewFinding(findingId) {
    this.dispatchEvent(
      new CustomEvent("hamie-navigate-finding", { detail: { findingId }, bubbles: true, composed: true }),
    );
  }

  _onReviewQueue() {
    this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "remediation" }, bubbles: true, composed: true }));
  }

  render() {
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="Recommendations are unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._items) {
      return html`<hamie-loading .lines=${3}></hamie-loading>`;
    }

    return html`
      <hamie-page-header
        heading="Recommendations"
        subtitle="${this._total > 0 ? `${this._total} recommendation${this._total === 1 ? "" : "s"} from HAMIE` : "No recommendations at this time"}"
      >
        <div slot="actions" class="header-actions">
          <hamie-button variant="secondary" size="sm" ?disabled=${this._analyzing} @click=${this._onAnalyzeHighestPriority}>
            Analyze Highest Priority
          </hamie-button>
          <hamie-button variant="secondary" size="sm" ?disabled=${this._analyzing} @click=${this._onAnalyzeScanSummary}>
            ${this._analyzing ? "Analyzing…" : "Analyze Scan Summary"}
          </hamie-button>
          <hamie-button variant="ghost" size="sm" ?disabled=${this._probing} @click=${this._onProbeCapability}>
            ${this._probing ? "Probing…" : "Probe model"}
          </hamie-button>
        </div>
      </hamie-page-header>

      ${(() => {
        const c = this._capabilitySummary();
        if (!c) return null;
        return html`
          <hamie-card padding="sm">
            <div class="capability" role="status">
              <strong>Model</strong> ${c.model}
              &middot; <strong>Capability</strong> ${c.verdict}
              &middot; <strong>Analysis</strong> ${c.permitted ? "permitted" : "blocked"}
              &middot; <strong>Last probed</strong> ${c.probed}
              ${c.failed.length
                ? html`<div class="capability-failed">Failing: ${c.failed.join(", ")}</div>`
                : null}
              ${!c.permitted && c.reason
                ? html`<div class="capability-failed">${c.reason}</div>`
                : null}
            </div>
          </hamie-card>
        `;
      })()}

      ${this._analysisError
        ? html`
            <div class="analysis-error" role="alert">
              <span>${this._analysisError}</span>
              <hamie-button variant="ghost" size="xs" aria-label="Dismiss" @click=${() => (this._analysisError = null)}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          `
        : null}

      ${this._items.length === 0
        ? this._ollamaFailureDescription()
          ? html`
              <hamie-card padding="md">
                <hamie-empty
                  tone="unavailable"
                  heading="Recent analysis failed"
                  description=${this._ollamaFailureDescription()}
                ></hamie-empty>
              </hamie-card>
            `
          : !this._allClearPermitted()
          ? html`
              <hamie-card padding="md">
                <hamie-empty
                  tone="unavailable"
                  heading=${this._analysisHeading()}
                  description=${this._analysisIncompleteDescription()}
                ></hamie-empty>
              </hamie-card>
            `
          : html`
              <hamie-card padding="md">
                <hamie-empty
                  tone="positive"
                  heading="All clear"
                  description="Your home is running optimally. HAMIE has no recommendations."
                ></hamie-empty>
              </hamie-card>
            `
        : html`
            <div class="list">
              ${this._items.map((item) => {
                const findingId = item.finding_ids?.[0];
                const dismissible = item.review_state === "new" && !item.stale;
                const stateLabel = item.status || item.review_state;
                const coverage = item.coverage || {};
                return html`
                  <hamie-problem-card
                    heading=${item.summary}
                    body=${item.probable_causes?.[0] || ""}
                    actionLabel=${findingId ? "View evidence" : ""}
                    ?dismissible=${dismissible}
                    @hamie-action=${() => findingId && this._onViewFinding(findingId)}
                    @hamie-dismiss=${() => this._onDismiss(item.recommendation_id)}
                  >
                    <div slot="details">
                      <p class="meta">
                        <strong>Evidence:</strong> ${item.finding_ids?.length || 0} affected finding${item.finding_ids?.length === 1 ? "" : "s"} ·
                        last observed ${safeRelativeTime(item.evidence_last_observed_at)}
                      </p>
                      <p class="meta">
                        <strong>Recommended action:</strong>
                        ${item.proposed_repair_plan?.[0] || item.recommended_checks?.[0] || "Gather more evidence"}
                      </p>
                      <span class="confidence">
                        Confidence: ${item.confidence} · Risk: ${item.risk || "Unknown"} · Status: ${stateLabel}
                      </span>

                      <hamie-disclosure label="Details">
                        <p class="meta">
                          <strong>Why it matters:</strong>
                          ${item.risk_notes?.[0] || "Impact is not yet confirmed; inspect the current evidence before deciding."}
                        </p>
                        <p class="meta">
                          <strong>Root cause:</strong>
                          ${item.confidence === "high" ? "Likely" : "Unknown"} — ${item.probable_causes?.[0] || "More evidence is required"}
                        </p>
                        <p class="meta">
                          <strong>Dependencies checked:</strong> AI advisories do not determine dependency completeness.
                          Inspect the deterministic dependency decision before any proposal.
                        </p>
                        <p class="meta">
                          <strong>Execution capability:</strong> Advisory only. Executable proposals, when eligible, appear separately in Review Queue.
                        </p>
                        <p class="meta">
                          Generated: ${safeRelativeTime(item.generated_at)} ·
                          Evidence observed: ${safeRelativeTime(item.evidence_last_observed_at)}
                        </p>
                        <p class="meta">
                          Coverage: ${coverage.coverage || "unknown"} ·
                          ${coverage.selected_findings ?? item.finding_ids?.length ?? 0} selected ·
                          ${coverage.groups_analyzed ?? item.group_ids?.length ?? 0} root-cause groups analyzed ·
                          ${coverage.skipped_findings ?? 0} deferred
                        </p>
                        <p class="meta">
                          Why selected: ${coverage.selection_reason || "Selected from the highest-impact current evidence"} ·
                          Repairability: ${item.repairability || "Advisory only"}
                        </p>
                        ${item.recommended_checks?.length
                          ? html`<ul class="details-list">${item.recommended_checks.map((check) => html`<li>${check}</li>`)}</ul>`
                          : null}
                        ${item.proposed_repair_plan?.length
                          ? html`
                              <p class="meta"><strong>Non-executing plan:</strong></p>
                              <ul class="details-list">${item.proposed_repair_plan.map((step) => html`<li>${step}</li>`)}</ul>
                            `
                          : null}
                        <p class="meta">
                          <strong>Affected findings:</strong> ${item.finding_ids?.join(", ") || "Unknown"}
                        </p>
                      </hamie-disclosure>

                      <hamie-button variant="secondary" size="xs" @click=${this._onReviewQueue}>
                        Review proposals
                      </hamie-button>
                    </div>
                  </hamie-problem-card>
                `;
              })}
            </div>
            ${this._total > PAGE_SIZE
              ? html`
                  <div class="pager">
                    <hamie-button variant="ghost" size="xs" ?disabled=${this._offset === 0} @click=${this._previousPage}>Previous</hamie-button>
                    <span>${this._offset + 1}–${Math.min(this._offset + PAGE_SIZE, this._total)} of ${this._total}</span>
                    <hamie-button variant="ghost" size="xs" ?disabled=${this._offset + PAGE_SIZE >= this._total} @click=${this._nextPage}>Next</hamie-button>
                  </div>
                `
              : null}
          `}
    `;
  }
}

if (!customElements.get("hamie-view-recommendations")) {
  customElements.define("hamie-view-recommendations", HamieViewRecommendations);
}
