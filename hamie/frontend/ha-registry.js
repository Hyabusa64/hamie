/**
 * Real Home Assistant registry name resolution -- device names, config
 * entry titles, and area names -- used to replace raw internal IDs
 * ("Config entry 01K5XRVXJRFQQA5QB0P01491P6") with the human-readable
 * names a real user actually configured, in Top Issues, Findings rows,
 * and the Finding detail drawer.
 *
 * HAMIE's own domain layer is deliberately I/O-free (see
 * domain/intelligence.py's module docstring) and never captures a
 * device's display name or a config entry's title -- only their raw
 * ids (device_id/config_entry_id), which is all Home Assistant's own
 * entity/device registries expose to a component at runtime without a
 * second, redundant capture pass. This module fetches that real,
 * already-configured Home Assistant metadata directly (never fabricated)
 * via three genuine, long-standing HA admin WebSocket commands, verified
 * present against the installed homeassistant package for both the
 * 2025.8.0 floor and the 2026.7 target:
 *   - "config/device_registry/list"  -> { id, name, name_by_user, area_id }
 *   - "config_entries/get"           -> { entry_id, title, domain }
 *   - "config/area_registry/list"    -> { area_id, name }
 *
 * Fetched once per browser session (registries change rarely relative to
 * findings/scans) and cached in module scope; call `primeHaRegistry(hass)`
 * once per view load (idempotent, coalesces concurrent callers) before
 * using the synchronous resolve*() helpers below.
 */

let cache = null; // { devices: Map, entries: Map, areas: Map }
let pending = null;

export async function primeHaRegistry(hass) {
  if (cache) return cache;
  if (pending) return pending;
  if (!hass) return null;
  pending = (async () => {
    try {
      const [devices, entries, areas] = await Promise.all([
        hass.callWS({ type: "config/device_registry/list" }),
        hass.callWS({ type: "config_entries/get" }),
        hass.callWS({ type: "config/area_registry/list" }),
      ]);
      cache = {
        devices: new Map((devices || []).map((item) => [item.id, item])),
        entries: new Map((entries || []).map((item) => [item.entry_id, item])),
        areas: new Map((areas || []).map((item) => [item.area_id, item])),
      };
    } catch {
      // Registry names are a display nicety, never a hard requirement --
      // every resolve*() helper below already falls back to the real
      // HAMIE-native title/id on a miss, so a failed fetch here (e.g. a
      // stripped-down test hass with no config component) degrades
      // gracefully rather than breaking the view.
      cache = { devices: new Map(), entries: new Map(), areas: new Map() };
    } finally {
      pending = null;
    }
    return cache;
  })();
  return pending;
}

export function resetHaRegistryCache() {
  cache = null;
  pending = null;
}

export function resolveDeviceName(deviceId) {
  const device = deviceId && cache?.devices.get(deviceId);
  return device ? device.name_by_user || device.name || null : null;
}

export function resolveConfigEntryTitle(configEntryId) {
  const entry = configEntryId && cache?.entries.get(configEntryId);
  return entry?.title || null;
}

export function resolveAreaName(areaId) {
  const area = areaId && cache?.areas.get(areaId);
  return area?.name || null;
}

export function resolveDeviceAreaName(deviceId) {
  const device = deviceId && cache?.devices.get(deviceId);
  return device?.area_id ? resolveAreaName(device.area_id) : null;
}

// Real, already-configured integration count -- the number of distinct
// config entries Home Assistant currently has set up, the same real
// entries `resolveConfigEntryTitle` reads. `null` until the registry
// has been primed at least once (never a fabricated placeholder count).
export function configEntryCount() {
  return cache ? cache.entries.size : null;
}

// Bare-array accessors for the same three real, already-cached registry
// collections above -- added for hamie-view-search.js's client-side
// device/area/integration search. Deliberately client-side: these
// registries are small (tens to low hundreds of rows on a real
// installation, confirmed against the registry snapshot this project
// already pulled), unlike the entity/finding universe (thousands), which
// is why Search still sends entity/issue queries to the real server-side
// `hamie/explorer/findings`/`hamie/explorer/groups` search params instead
// of ever fetching or filtering those client-side. Each returns `[]`
// (never `null`) before the registry has been primed, so a caller can
// render an honest empty list rather than special-casing "not primed yet".
export function listDevices() {
  return cache ? [...cache.devices.values()] : [];
}

export function listAreas() {
  return cache ? [...cache.areas.values()] : [];
}

export function listConfigEntries() {
  return cache ? [...cache.entries.values()] : [];
}

function humanizeSlug(value) {
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Resolve a group's/finding's display name from its real facets, in
 * priority order: config-entry title -> device name -> integration name
 * -> the caller's own humanized fallback (typically the backend's own
 * `title`, already human-readable when it wasn't built from a raw id).
 */
export function resolveDisplayName({ configEntryId, deviceId, integrationDomain } = {}, fallback) {
  return (
    resolveConfigEntryTitle(configEntryId) ||
    resolveDeviceName(deviceId) ||
    (integrationDomain ? humanizeSlug(integrationDomain) : null) ||
    fallback ||
    null
  );
}
