/**
 * HAMIE UI 3.0 root application shell.
 *
 * This file is the ESM source entry bundled by `npm run build:frontend`
 * (esbuild, see package.json) into dist/hamie-app.js, which is what a
 * <script type="module"> tag actually loads in the browser. Source stays
 * plain, idiomatic Lit; the bundle is the only build artifact HA ever
 * serves — see docs/DEVELOPMENT.md "Frontend build" for why Lit is
 * bundled here rather than reused from Home Assistant or vendored as a
 * standalone runtime.
 *
 * This element IS the live served panel: presentation/panel.py registers
 * `webcomponent_name="hamie-app"` and serves exactly this file's built
 * bundle (`frontend/dist/hamie-app.js`) as the panel module -- confirmed
 * by reading panel.py directly, not assumed. The unreachable legacy
 * panel and its legacy-only tests were removed in beta.15. This module
 * graph is the sole production frontend source, and browser tests load
 * its built artifact exactly as Home Assistant does.
 *
 * Layout: Figma's App() root (`dark size-full flex ... overflow-hidden`,
 * fixed 196px <aside> + flex-1 <main>) has zero responsive design at all
 * (no @media query anywhere in the extracted project, confirmed in the
 * design audit) — mobile/tablet behavior below is net-new, required
 * independently by the spec's Home Assistant Requirements section, and
 * aligned to Home Assistant's OWN most common breakpoints (600px / 870px,
 * verified by frequency across the installed hass_frontend bundle) rather
 * than an arbitrary choice, so HAMIE's panel collapses in step with HA's
 * own sidebar-narrow behavior instead of diverging from it.
 *
 * Navigation is the full reconciled set from the design audit: Figma's 8
 * screens plus the real HAMIE views Figma never designed (Groups,
 * Connectors, Audit). Views not yet migrated from the current production
 * panel render an honest "not yet migrated" placeholder — never a
 * fabricated screen — so the shell is genuinely testable end-to-end
 * without pretending unbuilt work exists (incremental migration: replace
 * one screen at a time, validate before the next).
 */
import { LitElement, css, html } from "lit";

import { designTokens } from "./design/index.js";
import { relativeTime } from "./format.js";
import "./components/hamie-sidebar.js";
import "./components/hamie-empty.js";
import "./views/hamie-view-overview.js";
import "./views/hamie-view-findings.js";
import "./views/hamie-view-incidents.js";
import "./views/hamie-view-review.js";
import "./views/hamie-view-search.js";
import "./views/hamie-view-recommendations.js";
import "./views/hamie-view-remediation.js";
import "./views/hamie-view-health.js";
import "./views/hamie-view-intelligence.js";
import "./views/hamie-view-security.js";
import "./views/hamie-view-dependencies.js";
import "./views/hamie-view-groups.js";
import "./views/hamie-view-connectors.js";
import "./views/hamie-view-audit.js";
import "./views/hamie-view-settings.js";

// IA per the approved Home/Issues/Review/Systems/Activity primary nav +
// Search/Settings secondary nav redesign. Reuses the same incremental,
// route-id-stable curation pattern this shell already established
// (House Health -> Advanced, see the prior "maintenance-console
// redesign" pass): route ids and their view components are UNCHANGED
// (findings still renders <hamie-view-findings>, health still renders
// <hamie-view-health>, etc.) -- only the sidebar's labels/icons/grouping
// changed, plus two genuinely new routes (review, search). This keeps
// every other view's internal navigation events (hamie-navigate with
// id: "findings"/"health"/"audit"/"remediation"/...), already wired
// throughout the app, working unmodified.
//
// Screens the new primary nav does not name (Recommendations, the
// Remediation/Review Queue execution engine, Dependencies, Security,
// Connectors, Groups) are demoted into Advanced rather than removed --
// they are real, working, execution-capable surfaces (Remediation is
// the only screen with genuine approve/execute authority) that the new
// Review screen deliberately does NOT duplicate or replace.
const ADVANCED_ITEMS = [
  { id: "recommendations", label: "Recommendations", icon: "mdi:lightbulb-outline" },
  { id: "remediation", label: "Remediation Queue", icon: "mdi:wrench-check-outline" },
  { id: "dependencies", label: "Dependencies", icon: "mdi:graph-outline" },
  { id: "security", label: "Security", icon: "mdi:shield-outline" },
  { id: "connectors", label: "Connectors", icon: "mdi:swap-horizontal" },
  { id: "groups", label: "Groups", icon: "mdi:folder-multiple-outline" },
  { id: "findings", label: "Raw Findings", icon: "mdi:file-search-outline" },
];

const NAV_ITEMS = [
  { id: "overview", label: "Home", icon: "mdi:home-outline" },
  { id: "incidents", label: "Incidents", icon: "mdi:alert-decagram-outline" },
  { id: "review", label: "Review", icon: "mdi:clipboard-check-outline" },
  { id: "health", label: "Systems", icon: "mdi:view-grid-outline" },
  { id: "audit", label: "Activity", icon: "mdi:timeline-clock-outline" },
  { id: "search", label: "Search", icon: "mdi:magnify-expand", dividerBefore: true },
  { id: "settings", label: "Settings", icon: "mdi:cog-outline" },
  { id: "advanced", label: "Advanced", icon: "mdi:tune-variant", children: ADVANCED_ITEMS },
];

const ROUTE_IDS = new Set([...NAV_ITEMS.filter((item) => !item.children).map((item) => item.id), ...ADVANCED_ITEMS.map((item) => item.id), "ai"]);

const NARROW_BREAKPOINT = 870; // HA's own sidebar-narrow threshold (verified)
const MOBILE_BREAKPOINT = 600; // HA's own phone/dialog threshold (verified)

export class HamieApp extends LitElement {
  static properties = {
    hass: { attribute: false },
    _activeId: { state: true },
    _sidebarOpen: { state: true },
    _narrow: { state: true },
    _overview: { state: true },
    _focusFindingId: { state: true },
    _focusDependencyFindingId: { state: true },
    _focusDependencyGroupId: { state: true },
    _focusDependencyLabel: { state: true },
    _focusGroupId: { state: true },
    _focusGroupTitle: { state: true },
    _focusQueueStatus: { state: true },
    _queueActionableCount: { state: true },
  };

  static styles = [
    designTokens,
    css`
      :host {
        display: flex;
        height: 100%;
        overflow: hidden;
        font-family: var(--hamie-font-body);
        font-size: var(--hamie-text-small);
        color: var(--hamie-text-primary);
        background: var(--hamie-surface-app);
        position: relative;
      }
      main {
        flex: 1;
        overflow-y: auto;
        min-width: 0;
      }
      .menu-button {
        display: none;
        position: absolute;
        top: var(--hamie-space-3);
        left: var(--hamie-space-3);
        z-index: 2;
        background: var(--hamie-surface-card);
        border: 1px solid var(--hamie-border-hairline);
        border-radius: var(--hamie-radius-md);
        width: 36px;
        height: 36px;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        color: var(--hamie-text-primary);
      }
      .scrim {
        display: none;
      }
      :host([narrow]) .menu-button {
        display: flex;
      }
      :host([narrow]) hamie-sidebar {
        position: absolute;
        inset: 0 auto 0 0;
        z-index: 3;
        transform: translateX(-100%);
        transition: transform var(--hamie-motion-normal) var(--hamie-motion-ease);
        box-shadow: var(--hamie-elevation-popover);
      }
      :host([narrow][sidebar-open]) hamie-sidebar {
        transform: translateX(0);
      }
      :host([narrow][sidebar-open]) .scrim {
        display: block;
        position: absolute;
        inset: 0;
        background: rgba(0, 0, 0, 0.5);
        z-index: 2;
      }
      :host([narrow]) main {
        padding-top: var(--hamie-space-8);
      }
    `,
  ];

  constructor() {
    super();
    this._activeId = this._routeFromLocation();
    this._sidebarOpen = false;
    this._narrow = false;
    this._mediaQuery = null;
  }

  _routeFromLocation() {
    const route = window.location.hash.replace(/^#\/?/, "");
    return ROUTE_IDS.has(route) ? route : "overview";
  }

  _syncRoute = () => {
    this._activeId = this._routeFromLocation();
    this._sidebarOpen = false;
  };

  _activate(id, { history = true } = {}) {
    if (!ROUTE_IDS.has(id)) return;
    this._activeId = id;
    this._sidebarOpen = false;
    if (history && window.location.hash !== `#${id}`) window.history.pushState({ hamieRoute: id }, "", `#${id}`);
  }

  connectedCallback() {
    super.connectedCallback();
    this._mediaQuery = window.matchMedia(`(max-width: ${NARROW_BREAKPOINT}px)`);
    this._onMediaChange = () => {
      this._narrow = this._mediaQuery.matches;
      if (!this._narrow) this._sidebarOpen = false;
    };
    window.addEventListener("popstate", this._syncRoute);
    window.addEventListener("hashchange", this._syncRoute);
    this._mediaQuery.addEventListener("change", this._onMediaChange);
    this._onMediaChange();
    this._loadOverview();
    this._subscribeLiveUpdates();
  }

  // One canonical live-state channel (mission: connector heartbeat, auto
  // scan, and other background-initiated changes must reach the UI
  // without a manual refresh, and without every view inventing its own
  // polling loop). Backend: RuntimeProjection already fans out a change
  // notification on every scan sync / connector status update / AI
  // coverage change (see runtime_projection.py's _notify call sites);
  // hamie/updates/subscribe (presentation/api.py) is a thin WS
  // subscription over that exact fan-out. This app shell is the single
  // subscriber; it refreshes its own sidebar/footer state directly and
  // rebroadcasts a `hamie-live-update` window event so any mounted view
  // can refresh itself the same way it already refreshes after its own
  // user-triggered actions -- no bespoke per-view polling.
  async _subscribeLiveUpdates() {
    if (!this.hass?.connection?.subscribeMessage) return;
    try {
      this._unsubscribeLiveUpdates = await this.hass.connection.subscribeMessage(
        () => {
          this._loadOverview();
          window.dispatchEvent(new CustomEvent("hamie-live-update"));
        },
        { type: "hamie/updates/subscribe" },
      );
    } catch {
      // No live channel (older HA WS surface, or HAMIE not loaded) --
      // views keep working, they just rely on their own manual actions
      // and the bounded 45s fallback below instead of instant push.
      this._liveUpdateFallback = window.setInterval(() => {
        this._loadOverview();
        window.dispatchEvent(new CustomEvent("hamie-live-update"));
      }, 45_000);
    }
  }

  async _loadOverview() {
    if (!this.hass) return;
    try {
      const [overview, queue] = await Promise.all([
        this.hass.callWS({ type: "hamie/explorer/overview" }),
        this.hass.callWS({ type: "hamie/remediation/queue/list", offset: 0, limit: 1 }).catch(() => null),
      ]);
      this._overview = overview;
      const counts = queue?.section_counts || {};
      this._queueActionableCount =
        (counts.ready_for_review || 0) + (counts.awaiting_approval || 0) + (counts.ready_to_execute || 0);
    } catch {
      this._overview = null;
      this._queueActionableCount = 0;
    }
  }

  // Production defect fix: this was previously only ever called once, in
  // connectedCallback -- fine for the initial sidebar badge/status render,
  // but it meant the sidebar's own "last scan" state froze at whatever it
  // was when the panel was first opened and never updated again for the
  // rest of that browser session, even after the user ran a fresh scan or
  // cleanup pass from the Overview view (which reloads its own, separate
  // `_overview` state correctly). Two UI surfaces independently deriving
  // "last scan" from the same WS command but refreshed on different
  // triggers is exactly the contradiction ("last scan completed Just now"
  // at the top vs "Scanned 3d ago" in the sidebar) seen live. The
  // `hamie-data-changed` listener on `<main>` above re-runs this any time
  // a child view finishes a scan or cleanup pass, so both surfaces read
  // the same fresh state.

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("popstate", this._syncRoute);
    window.removeEventListener("hashchange", this._syncRoute);
    this._mediaQuery?.removeEventListener("change", this._onMediaChange);
    this._unsubscribeLiveUpdates?.();
    this._unsubscribeLiveUpdates = null;
    if (this._liveUpdateFallback) {
      window.clearInterval(this._liveUpdateFallback);
      this._liveUpdateFallback = null;
    }
  }

  updated(changed) {
    if (changed.has("_narrow")) this.toggleAttribute("narrow", this._narrow);
    if (changed.has("_sidebarOpen")) this.toggleAttribute("sidebar-open", this._sidebarOpen);
  }

  _onNavigate(event) {
    this._activate(event.detail.id);
    if (event.detail.id === "remediation") {
      this._focusQueueStatus = event.detail.status || null;
    }
  }

  // Recommendations' "View finding" button dispatches this (findingId
  // in detail) -- previously unhandled anywhere, so the button did
  // nothing at all. Navigates to Findings and asks it to focus on that
  // one finding.
  _onNavigateFinding(event) {
    this._activate("findings");
    this._sidebarOpen = false;
    this._focusFindingId = event.detail.findingId;
  }

  // Findings' "View dependency graph" button (findingId + entityId in
  // detail) and Groups' per-group graph action (groupId in detail) both
  // dispatch this. Navigates to Dependencies and asks it to load the
  // real per-finding/per-group impact graph instead of its default
  // integration-breakdown view.
  _onNavigateDependencies(event) {
    this._activate("dependencies");
    this._sidebarOpen = false;
    if (event.detail.groupId) {
      this._focusDependencyGroupId = event.detail.groupId;
      this._focusDependencyFindingId = null;
      this._focusDependencyLabel = null;
    } else {
      this._focusDependencyFindingId = event.detail.findingId;
      this._focusDependencyGroupId = null;
      this._focusDependencyLabel = event.detail.entityId;
    }
  }

  // Groups' "View Findings" button dispatches this (groupId + groupTitle
  // in detail) -- the real Groups -> Findings handoff (matches the
  // legacy panel's "Open Group" button).
  _onNavigateFindingsGroup(event) {
    this._activate("findings");
    this._sidebarOpen = false;
    this._focusGroupId = event.detail.groupId;
    this._focusGroupTitle = event.detail.groupTitle;
  }

  _toggleSidebar() {
    this._sidebarOpen = !this._sidebarOpen;
  }

  // NOTE: this element is a view router, not a generic content host -- it
  // has no bare <slot>. Only known view ids render (via this method);
  // arbitrary light-DOM children passed to <hamie-app> are never
  // projected anywhere and won't inherit design tokens. Isolated
  // component-level tests need their own minimal token-applying host
  // (see tests/frontend's token-host.js pattern), not this element.
  _renderView() {
    // Views migrated from the current production panel are explicit
    // cases here; everything else falls through to the honest "not yet
    // migrated" placeholder below (incremental migration, one screen at
    // a time -- see the phased plan). Worth a real tag-name registry
    // once there are enough migrated views to justify it.
    if (this._activeId === "overview") {
      return html`<hamie-view-overview .hass=${this.hass}></hamie-view-overview>`;
    }
    if (this._activeId === "findings") {
      return html`<hamie-view-findings
        .hass=${this.hass}
        .focusFindingId=${this._focusFindingId}
        .focusGroupId=${this._focusGroupId}
        .focusGroupTitle=${this._focusGroupTitle}
      ></hamie-view-findings>`;
    }
    if (this._activeId === "incidents") {
      return html`<hamie-view-incidents .hass=${this.hass} @hamie-navigate-finding=${this._onNavigateFinding}></hamie-view-incidents>`;
    }
    if (this._activeId === "review") {
      return html`<hamie-view-review .hass=${this.hass} @hamie-navigate=${this._onNavigate} @hamie-navigate-finding=${this._onNavigateFinding}></hamie-view-review>`;
    }
    if (this._activeId === "search") {
      return html`<hamie-view-search .hass=${this.hass} @hamie-navigate-finding=${this._onNavigateFinding} @hamie-navigate-findings-group=${this._onNavigateFindingsGroup}></hamie-view-search>`;
    }
    if (this._activeId === "recommendations") {
      return html`<hamie-view-recommendations .hass=${this.hass} @hamie-navigate-finding=${this._onNavigateFinding}></hamie-view-recommendations>`;
    }
    if (this._activeId === "health") {
      return html`<hamie-view-health .hass=${this.hass}></hamie-view-health>`;
    }
    if (this._activeId === "ai") {
      return html`<hamie-view-intelligence .hass=${this.hass} @hamie-navigate=${this._onNavigate}></hamie-view-intelligence>`;
    }
    if (this._activeId === "security") {
      return html`<hamie-view-security .hass=${this.hass}></hamie-view-security>`;
    }
    if (this._activeId === "dependencies") {
      return html`<hamie-view-dependencies
        .hass=${this.hass}
        .focusFindingId=${this._focusDependencyFindingId}
        .focusGroupId=${this._focusDependencyGroupId}
        .focusLabel=${this._focusDependencyLabel}
      ></hamie-view-dependencies>`;
    }
    if (this._activeId === "remediation") {
      return html`<hamie-view-remediation .hass=${this.hass} .focusStatus=${this._focusQueueStatus}></hamie-view-remediation>`;
    }
    if (this._activeId === "groups") {
      return html`<hamie-view-groups .hass=${this.hass}></hamie-view-groups>`;
    }
    if (this._activeId === "connectors") {
      return html`<hamie-view-connectors .hass=${this.hass}></hamie-view-connectors>`;
    }
    if (this._activeId === "audit") {
      return html`<hamie-view-audit .hass=${this.hass}></hamie-view-audit>`;
    }
    if (this._activeId === "settings") {
      return html`<hamie-view-settings .hass=${this.hass}></hamie-view-settings>`;
    }
    const item = NAV_ITEMS.find((entry) => entry.id === this._activeId);
    // Phase 5 migrates one screen at a time; anything not yet migrated
    // renders an honest placeholder rather than fabricated content.
    return html`
      <hamie-empty
        tone="unavailable"
        heading="${item?.label || "This view"} is not yet migrated to UI 3.0"
        description="Still served by the current production panel until this screen is built and validated against the Figma specification."
      ></hamie-empty>
    `;
  }

  // Only counts with real decision significance are badged (spec
  // section 4): open findings and actionable Review Queue work. Never
  // Recommendations merely because historical AI recommendations exist
  // -- most are already reviewed/stale, so that count doesn't mean
  // "action needed" the way the other two genuinely do. Badges are
  // simply absent when data hasn't loaded yet or a count is zero, never
  // a placeholder number.
  _navItemsWithBadges() {
    const overview = this._overview;
    return NAV_ITEMS.map((item) => {
      if (item.id === "incidents" && overview?.active_incidents) {
        return { ...item, badge: overview.active_incidents };
      }
      // Remediation Queue moved under Advanced this pass (see
      // ADVANCED_ITEMS' docstring) -- its own actionable-work count
      // still needs a real, visible signal, now surfaced on the
      // "Advanced" parent button itself rather than lost entirely, since
      // hamie-sidebar.js's `_renderItem` only renders a badge on a
      // top-level button, not on a collapsed child row.
      if (item.id === "advanced" && this._queueActionableCount) {
        return { ...item, badge: this._queueActionableCount };
      }
      return item;
    });
  }

  _footerStatus() {
    if (!this._overview) return { text: "Loading…", ok: true };
    // Bottom status communicates operational state, not maintenance debt --
    // operational_health already excludes diagnostic/optional entity
    // clutter (see runtime_projection.py), so a house with hundreds of
    // stale diagnostic sensors but healthy primary entities/automations
    // never reads as "needs attention" here. availability_health (the
    // whole-house figure) belongs in the Maintenance health dimension, not
    // this summary line.
    const { operational_health: health, coverage, last_scan: lastScan } = this._overview;
    const ok =
      health == null || (typeof health === "number" && health >= 90 && coverage === "complete");
    const scanText = lastScan ? `Scanned ${relativeTime(lastScan)}` : "No scan yet";
    return { text: `${ok ? "All systems operational" : "Needs attention"} · ${scanText}`, ok };
  }

  render() {
    const status = this._footerStatus();
    return html`
      <button class="menu-button" @click=${this._toggleSidebar} aria-label="Toggle navigation">
        <ha-icon icon="mdi:menu"></ha-icon>
      </button>
      <div class="scrim" @click=${this._toggleSidebar}></div>
      <hamie-sidebar
        .items=${this._navItemsWithBadges()}
        .activeId=${this._activeId}
        .statusText=${status.text}
        .statusOk=${status.ok}
        @hamie-navigate=${this._onNavigate}
      >
        <span slot="version">UI 3.1</span>
      </hamie-sidebar>
      <!--
        hamie-navigate is bound here too, not just on hamie-sidebar:
        Lit's @event binding attaches directly to that one element, and
        <main> (a sibling of hamie-sidebar, not an ancestor of it) never
        passes bubbled events through it. Any view rendered inside main
        that dispatches hamie-navigate (e.g. Overview's "View in
        Groups") would otherwise silently do nothing -- the same class
        of dead-navigation bug already found and fixed for
        hamie-navigate-finding earlier this pass. hamie-navigate-finding,
        hamie-navigate-dependencies, and hamie-navigate-findings-group
        are bound here for the same reason, delegated once at this level
        rather than per-view.
      -->
      <main
        @hamie-navigate=${this._onNavigate}
        @hamie-navigate-finding=${this._onNavigateFinding}
        @hamie-navigate-dependencies=${this._onNavigateDependencies}
        @hamie-navigate-findings-group=${this._onNavigateFindingsGroup}
        @hamie-data-changed=${this._loadOverview}
      >
        ${this._renderView()}
      </main>
    `;
  }
}

if (!customElements.get("hamie-app")) {
  customElements.define("hamie-app", HamieApp);
}
