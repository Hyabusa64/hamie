/**
 * Generate a real client-supplied idempotency token for HAMIE's group
 * review/suppress write actions (hamie/group/apply, hamie/group/suppress).
 * The server never generates or returns one -- confirmed in
 * presentation/api.py/operations_service.py: the caller must generate it,
 * and the server only remembers the last 128 tokens per store to detect
 * safe replays vs conflicting reuse. Must be non-empty, untrimmed-equal
 * to itself, and at most 128 characters (operations_service.py's
 * `_idempotency` validation).
 *
 * Reproduced from the exact algorithm already proven in the currently
 * shipping hamie-panel.js (`_idempotencyToken()`), not reinvented, so
 * both frontends generate tokens the same real backend already accepts.
 */
let sequence = 0;

export function idempotencyToken() {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  sequence += 1;
  const time = Date.now().toString(36);
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    const bytes = new Uint8Array(12);
    globalThis.crypto.getRandomValues(bytes);
    const random = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    return `hamie-${time}-${sequence.toString(36)}-${random}`;
  }
  return `hamie-${time}-${sequence.toString(36)}-local`;
}
