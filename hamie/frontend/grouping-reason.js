/**
 * Human-readable label for a root-cause group's real `grouping_reason`
 * field (domain/intelligence.py's `_primary_key`) -- a code-facing
 * internal description ("common config entry", "common device",
 * "common providing integration", or a dynamically-built
 * `"common {dimension}"` for any configured grouping dimension) that
 * used to leak to the UI completely verbatim (a confirmed real
 * production defect: Overview's Top Issues panel showing the literal
 * string "common config entry" as if it were user-facing copy).
 *
 * The backend reason is always exactly "common " + a dimension name, so
 * this is a real translation, not a guess: named reasons get a specific
 * label; any other "common X" dimension not explicitly named here still
 * gets an honest generic "Same X" rather than the raw internal string.
 */
const GROUPING_REASON_LABELS = {
  "common config entry": "Same integration instance",
  "common device": "Same device",
  "common providing integration": "Same integration",
  "common integration domain": "Same integration",
  "common config entry id": "Same integration instance",
  "common device id": "Same device",
  "common entity domain": "Same entity type",
  "common area id": "Same area",
  "common source provider": "Same source",
  "common name prefix": "Similar naming",
  "common failure condition": "Same failure pattern",
  "common dependency root": "Same dependency",
  "common analyzer id": "Same analyzer",
  "common category": "Same category",
  "common severity": "Same severity",
};

export function groupingReasonLabel(reason) {
  if (!reason) return "";
  if (GROUPING_REASON_LABELS[reason]) return GROUPING_REASON_LABELS[reason];
  if (reason.startsWith("common ")) return `Same ${reason.slice("common ".length)}`;
  return reason;
}
