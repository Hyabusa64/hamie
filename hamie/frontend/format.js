/**
 * Small shared formatting helpers used by the app shell and views.
 * No Figma source (Figma's mock data used pre-formatted strings like "2h
 * ago" directly) -- this reproduces that same relative-time convention
 * against real ISO timestamps from the backend.
 */
export function relativeTime(isoString) {
  if (!isoString) return "";
  const then = new Date(isoString).getTime();
  const diffSeconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (diffSeconds < 60) return "Just now";
  const minutes = Math.round(diffSeconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function timeOfDayGreeting(date = new Date()) {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/**
 * User-facing age formatter for evidence provenance. Invalid, implausibly
 * old, or materially future timestamps are unknown; they are never coerced
 * through epoch defaults or clamped into a believable age.
 */
export function safeRelativeTime(isoString, { maximumAgeDays = 365, futureSkewSeconds = 300 } = {}) {
  if (!isoString) return "Unknown";
  const timestamp = new Date(isoString).getTime();
  if (!Number.isFinite(timestamp)) return "Unknown";
  const ageMilliseconds = Date.now() - timestamp;
  if (ageMilliseconds < -futureSkewSeconds * 1000) return "Unknown";
  if (ageMilliseconds > maximumAgeDays * 86_400_000) return "Unknown";
  return relativeTime(isoString);
}
