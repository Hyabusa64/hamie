/**
 * Shared finding-status derivation, used by every screen that renders a
 * findings table (Findings, House Health, and any future one). Extracted
 * because House Health duplicated this logic independently and got it
 * wrong (hardcoded "warning" for every open row instead of following
 * severity) -- exactly the kind of repeated reconciliation that should
 * be solved once, not per screen.
 *
 * Real HAMIE separates `lifecycle` (open/resolved -- only two values)
 * from `review_state` (new/acknowledged/snoozed/retained/dismissed).
 * Figma conflates both into one 3-value status (open/snoozed/resolved).
 */

export function realFindingStatus(item) {
  if (item.lifecycle === "resolved") return "resolved";
  if (item.review_state === "snoozed") return "snoozed";
  return "open";
}

// Figma colors the "open" status chip by the row's own severity
// (warning/critical severity -> matching chip color; anything else ->
// info/blue) rather than one fixed color for every open row.
export function findingStatusToken(item) {
  const status = realFindingStatus(item);
  if (status === "resolved") return { status: "healthy", label: "resolved" };
  if (status === "snoozed") return { status: "idle", label: "snoozed" };
  const openColor = item.severity === "warning" || item.severity === "critical" ? item.severity : "info";
  return { status: openColor, label: "open" };
}

/**
 * Group findings by an arbitrary real field (e.g. `category` for House
 * Health, `integration` for Dependencies) and derive a severity-based
 * status for each group. Extracted because House Health and Dependencies
 * both need this exact shape -- grouping key differs, the aggregation
 * logic doesn't.
 */
export function groupFindingsBy(items, field, { fallbackLabel = "Unknown" } = {}) {
  const groups = new Map();
  for (const item of items) {
    const key = item[field] || fallbackLabel;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  return [...groups.entries()].map(([key, groupItems]) => {
    const hasCritical = groupItems.some((i) => i.severity === "critical");
    const hasWarning = groupItems.some((i) => i.severity === "warning");
    const status = hasCritical ? "critical" : hasWarning ? "warning" : "info";
    return { key, count: groupItems.length, status };
  });
}
