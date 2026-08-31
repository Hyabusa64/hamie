/**
 * <hamie-view-dependencies> — reconstructed from App.tsx's
 * `DependenciesPage`.
 *
 * Real-data reconciliation: Figma's Dependencies page (a browsable list
 * of third-party integrations with name/version/entity count/sync time/
 * latency) has no real equivalent. The real `hamie/explorer/dependencies`
 * endpoint is conceptually different -- it returns an impact-analysis
 * graph (nodes/edges: "what breaks if this finding/group changes"),
 * scoped to one specific finding or group at a time, not a browsable
 * all-integrations list. HAMIE also doesn't track integration versions,
 * sync timestamps, or per-integration latency anywhere.
 *
 * What HAMIE does have, and this screen honestly surfaces: real
 * findings carry a real `integration` field (the HA integration domain,
 * when determinable -- domain/intelligence.py's finding_summary()).
 * Grouping open findings by that real field gives a genuine, browsable
 * "which integrations have open issues" list -- close to Figma's intent
 * (a per-integration health view) without inventing version/sync/latency
 * data. Uses the same groupFindingsBy() helper House Health uses (same
 * shape, different grouping key), per the reusable-pattern requirement.
 *
 * Capability-matrix fix (docs/CAPABILITY_MATRIX.md #17 -- the single
 * largest confirmed gap in the whole matrix): the real per-finding/
 * per-group impact graph itself had no UI anywhere to reach it. Fixed
 * by adding it here as a second mode of this same screen, entered via
 * real navigation from a Findings row's "View dependency graph" or a
 * Group's own graph action -- the integration-breakdown browse view
 * above is kept as-is, not replaced, per explicit instruction.
 *
 * Verified directly against domain/intelligence.py's dependency_graph()
 * before writing this (not guessed): the real response is
 * {nodes: [{node_id, kind, label}], edges: [{source_id, target_id,
 * relationship_type, source, source_revision, confidence, last_verified,
 * stale}], coverage, safe_to_remove, bounded}. For one selected finding,
 * an edge with relationship_type="references" and target_id equal to
 * that finding's own subject id means "source_id references (depends
 * on) this subject" -- i.e. exactly "what breaks if this is removed".
 * relationship_type="supports" with the same target means "source_id
 * supports this subject" -- i.e. "what this subject itself depends on".
 * Group-scoped graphs cover every member finding's subject at once, so
 * there's no single "the" subject to special-case -- rendered as the
 * same real node/edge listing the legacy panel always showed, without
 * the single-subject reference/depends-on breakdown.
 */
import { LitElement, css, html } from "lit";

import { friendlyError } from "../errors.js";
import { groupFindingsBy } from "../findings-status.js";
import "../components/hamie-page-header.js";
import "../components/hamie-card.js";
import "../components/hamie-metric.js";
import "../components/hamie-status.js";
import "../components/hamie-button.js";
import "../components/hamie-table.js";
import "../components/hamie-empty.js";
import "../components/hamie-loading.js";

export class HamieViewDependencies extends LitElement {
  static properties = {
    hass: { attribute: false },
    // Set by hamie-app.js when a Findings row's "View dependency graph"
    // or a Group's graph action navigates here.
    focusFindingId: { type: String },
    focusGroupId: { type: String },
    focusLabel: { type: String },
    _findings: { state: true },
    _total: { state: true },
    _error: { state: true },
    _scanning: { state: true },
    _graph: { state: true },
    _graphError: { state: true },
    // Real scan lifecycle (hamie/explorer/overview's scan_status/
    // coverage) -- distinguishes "genuinely no open findings" from "no
    // scan has ever completed" or "the latest scan failed with nothing
    // retained yet", the same real signal House Health/Findings use.
    _scanStatus: { state: true },
    _coverage: { state: true },
  };

  static styles = css`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .subtitle {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-4);
    }
    @media (max-width: 870px) {
      .metrics {
        grid-template-columns: 1fr;
      }
    }
    .row {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-3) var(--hamie-space-4);
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .row:last-child {
      border-bottom: none;
    }
    .name {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      flex: 1;
    }
    .count {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .graph-section {
      margin-bottom: var(--hamie-space-4);
    }
    .graph-section h2 {
      margin: 0 0 var(--hamie-space-2);
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .node-list {
      margin: 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      line-height: 1.7;
    }
    .decision-grid {
      display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--hamie-space-3); margin-bottom: var(--hamie-space-4);
    }
    .decision-grid p, .decision-grid li, details {
      color: var(--hamie-text-secondary); font-size: var(--hamie-text-small);
      line-height: 1.55;
    }
    .decision-grid h2 { margin-bottom: var(--hamie-space-1); }
    details > summary {
      cursor: pointer; color: var(--hamie-accent); font-weight: var(--hamie-weight-medium);
      margin-bottom: var(--hamie-space-3);
    }
    @media (max-width: 700px) {
      .decision-grid { grid-template-columns: 1fr; }
    }
    .badges {
      display: flex;
      gap: var(--hamie-space-2);
      margin-bottom: var(--hamie-space-4);
    }
  `;

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  async _load() {
    if (!this.hass) return;
    if (this.focusFindingId || this.focusGroupId) {
      await this._loadGraph();
      return;
    }
    try {
      const [result, overview] = await Promise.all([
        this.hass.callWS({
          type: "hamie/explorer/findings",
          search: "",
          filters: { lifecycle: "open" },
          sort: "priority",
          offset: 0,
          // Server hard-caps this at 100 (domain/intelligence.py
          // MAX_PAGE_SIZE) -- sending more always raises ValueError.
          limit: 100,
        }),
        this.hass.callWS({ type: "hamie/explorer/overview" }),
      ]);
      this._findings = result.items.filter((item) => item.integration);
      this._total = result.total;
      this._scanStatus = overview.scan_status;
      this._coverage = overview.coverage;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Dependency data is temporarily unavailable.");
    }
  }

  async _loadGraph() {
    try {
      const params = this.focusGroupId
        ? { group_id: this.focusGroupId }
        : { finding_id: this.focusFindingId };
      this._graph = await this.hass.callWS({ type: "hamie/explorer/dependencies", ...params });
      this._graphError = null;
    } catch (err) {
      this._graphError = friendlyError(err, "That dependency graph is unavailable.");
    }
  }

  _onBackToIntegrations() {
    this.focusFindingId = null;
    this.focusGroupId = null;
    this.focusLabel = null;
    this._graph = null;
    this._graphError = null;
    this._load();
  }

  async _onRefresh() {
    if (!this.hass) return;
    this._scanning = true;
    try {
      // Real hamie.scan service (services.py SERVICE_SCAN) -- takes no
      // fields, awaits full scan completion before resolving.
      await this.hass.callService("hamie", "scan", {});
      await this._load();
    } catch (err) {
      this._error = friendlyError(err, "Dependency data is temporarily unavailable.");
    } finally {
      this._scanning = false;
    }
  }

  render() {
    if (this.focusFindingId || this.focusGroupId) {
      return this._renderGraph();
    }
    if (this._error) {
      return html`<hamie-empty tone="unavailable" heading="Dependencies are unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._findings) {
      return html`<hamie-loading .lines=${4}></hamie-loading>`;
    }

    // Same real distinction Findings makes: an empty breakdown must
    // never look identical to "scanned and genuinely found nothing" when
    // no scan has actually evaluated anything yet, or the latest scan
    // failed before any results were ever retained.
    const neverScanned = this._scanStatus === "never_run";
    const failedWithNothingRetained = this._scanStatus === "failed" && this._coverage === "unknown";
    if (neverScanned || failedWithNothingRetained) {
      return html`
        <hamie-page-header heading="Dependencies" subtitle="Open findings grouped by integration">
          <div slot="actions">
            <hamie-button variant="secondary" size="sm" ?disabled=${this._scanning} @click=${this._onRefresh}>
              <ha-icon icon="mdi:refresh"></ha-icon> ${this._scanning ? "Scanning…" : "Refresh"}
            </hamie-button>
          </div>
        </hamie-page-header>
        <hamie-empty
          tone=${neverScanned ? "neutral" : "unavailable"}
          heading=${neverScanned ? "No scan has completed yet" : "The latest scan failed"}
          description=${neverScanned
            ? "Run a scan to see integration dependencies here."
            : "No previous results are available yet. Run a scan to try again."}
        ></hamie-empty>
      `;
    }

    const breakdown = groupFindingsBy(this._findings, "integration");
    const healthyCount = breakdown.filter((g) => g.status === "info").length;
    const degradedCount = breakdown.length - healthyCount;

    return html`
      <hamie-page-header
        heading="Dependencies"
        subtitle="${breakdown.length} integrations with open findings · ${degradedCount} need attention"
      >
        <div slot="actions">
          <hamie-button variant="secondary" size="sm" ?disabled=${this._scanning} @click=${this._onRefresh}>
            <ha-icon icon="mdi:refresh"></ha-icon> ${this._scanning ? "Scanning…" : "Refresh"}
          </hamie-button>
        </div>
      </hamie-page-header>

      <div class="metrics">
        <hamie-metric label="Integrations affected" value=${breakdown.length} sub="With at least one open finding" icon="mdi:puzzle-outline"></hamie-metric>
        <hamie-metric label="Needs attention" value=${degradedCount} sub="Warning or critical findings" icon="mdi:alert-outline" color="var(--hamie-status-warning)"></hamie-metric>
        <hamie-metric label="Informational only" value=${healthyCount} sub="No warning/critical findings" icon="mdi:information-outline"></hamie-metric>
      </div>

      <hamie-card padding="none">
        ${breakdown.length === 0
          ? html`<hamie-empty tone="positive" heading="No integrations have open findings" description="Findings only report an integration when Home Assistant can determine one."></hamie-empty>`
          : breakdown.map(
              (group) => html`
                <div class="row">
                  <span class="name">${group.key}</span>
                  <span class="count">${group.count} open finding${group.count === 1 ? "" : "s"}</span>
                  <hamie-status status=${group.status}></hamie-status>
                </div>
              `,
            )}
      </hamie-card>
      ${this._total > this._findings.length
        ? html`<p class="subtitle" style="margin-top: var(--hamie-space-2)">
            Showing findings for the ${this._findings.length} of ${this._total} open findings with a determinable integration.
          </p>`
        : null}
    `;
  }

  _renderGraph() {
    if (this._graphError) {
      return html`
        <hamie-page-header heading="Dependency decision">
          <div slot="actions">
            <hamie-button variant="ghost" size="sm" @click=${this._onBackToIntegrations}>
              <ha-icon icon="mdi:arrow-left"></ha-icon> Back to integrations
            </hamie-button>
          </div>
        </hamie-page-header>
        <hamie-empty tone="unavailable" heading="Dependency evidence is unavailable" description=${this._graphError}></hamie-empty>
      `;
    }
    if (!this._graph) return html`<hamie-loading .lines=${4}></hamie-loading>`;

    const decision = this._graph.decision || {};
    const edgeRows = this._graph.edges.map((edge, index) => ({
      id: `${edge.source_id}-${edge.target_id}-${index}`,
      cells: [edge.source_id, edge.relationship_type, edge.target_id, edge.confidence],
    }));

    return html`
      <hamie-page-header heading="Dependency decision" subtitle="${decision.friendly_name || decision.target || "Selected target"}">
        <div slot="actions">
          <hamie-button variant="ghost" size="sm" @click=${this._onBackToIntegrations}>
            <ha-icon icon="mdi:arrow-left"></ha-icon> Back to integrations
          </hamie-button>
        </div>
      </hamie-page-header>

      <div class="badges">
        <hamie-status status=${this._graph.coverage === "complete" ? "healthy" : "warning"} label="Coverage: ${this._graph.coverage}"></hamie-status>
        <hamie-status status=${decision.safe_to_disable ? "healthy" : "critical"} label=${decision.recommendation || "Manual review required"}></hamie-status>
      </div>

      <div class="decision-grid">
        <hamie-card padding="md">
          <h2>Summary</h2>
          <p><strong>${decision.friendly_name || decision.target}</strong><br />
            ${decision.target}<br />
            Integration: ${decision.integration || "Unknown"} ·
            Config entry: ${decision.config_entry || "Unknown"} ·
            Device: ${decision.device || "Unknown"} ·
            Area: ${decision.area || "Unknown"}
          </p>
          <p>Direct references: ${decision.direct_references?.length || 0} ·
            Indirect references: ${decision.indirect_references?.length || 0} ·
            Unresolved sources: ${decision.unresolved_sources?.length || 0}</p>
          <p>Safe to inspect: ${String(decision.safe_to_inspect)} ·
            Safe to disable: ${String(decision.safe_to_disable)} ·
            Safe to modify: ${String(decision.safe_to_modify)}</p>
        </hamie-card>

        <hamie-card padding="md">
          <h2>Recommendation</h2>
          <p><strong>${decision.recommendation || "Manual review required"}</strong></p>
          <p>${decision.reason || "Dependency evidence is incomplete."}</p>
          <p><strong>Possible impact:</strong> ${decision.possible_impact || "Unknown until coverage is complete."}</p>
        </hamie-card>

        <hamie-card padding="md">
          <h2>Referenced by</h2>
          ${Object.keys(decision.referenced_by || {}).length
            ? Object.entries(decision.referenced_by).map(([category, values]) => html`
                <p><strong>${category}</strong></p>
                <ul>${values.map((value) => html`<li>${value}</li>`)}</ul>
              `)
            : html`<p>No verified direct references were found. This does not prove modification is safe unless dependency coverage is complete.</p>`}
        </hamie-card>

        <hamie-card padding="md">
          <h2>Belongs to or supports</h2>
          ${decision.belongs_to_or_supports?.length
            ? html`<ul>${decision.belongs_to_or_supports.map((value) => html`<li>${value}</li>`)}</ul>`
            : html`<p>No supporting relationship was observed.</p>`}
        </hamie-card>
      </div>

      <details>
        <summary>View technical graph</summary>
        <div class="graph-section">
          <h2>Nodes</h2>
          ${this._graph.nodes.length
            ? html`<ul class="node-list">${this._graph.nodes.map((node) => html`<li>${node.kind}: ${node.label}</li>`)}</ul>`
            : html`<hamie-empty tone="neutral" heading="No graph nodes"></hamie-empty>`}
        </div>
        <div class="graph-section">
          <h2>Relationships</h2>
          <hamie-card padding="none">
            <hamie-table .columns=${["Source", "Relation", "Target", "Confidence"]} .rows=${edgeRows}>
              <div slot="empty" style="padding: var(--hamie-space-8) 0">
                <hamie-empty tone="neutral" heading="No relationships found"></hamie-empty>
              </div>
            </hamie-table>
          </hamie-card>
        </div>
      </details>
    `;
  }
}

if (!customElements.get("hamie-view-dependencies")) {
  customElements.define("hamie-view-dependencies", HamieViewDependencies);
}
