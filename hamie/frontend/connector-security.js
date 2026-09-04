/**
 * Shared "Enabled" -> "Allow connection to this local-network host"
 * auto-approve semantics, used identically by every connector editor
 * (hamie-ai-provider-editor.js for Ollama, hamie-connector-editor.js for
 * n8n/MCP/HKG) so this one deterministic rule lives in exactly one
 * place instead of being hand-copied per connector.
 *
 * Production defect this fixes: every connector already had its own
 * real `{section}_approve_host` field (configuration.py), but every
 * frontend editor only ever rendered it once a `host_not_allowed` error
 * from a failed Test Connection/Save was already present -- so enabling
 * a connector pointed at a private-network address (the overwhelmingly
 * common real case: Ollama or n8n on the local LAN) silently
 * left the user needing to fail a test first before the control needed
 * to fix it ever appeared. The control itself is now always rendered
 * (see each editor's render()); this module owns only the *auto-enable*
 * behavior triggered by the Enabled toggle itself.
 *
 * Rule: the first time a connector transitions from disabled to enabled
 * in one editing session, if local-network-host approval was previously
 * unset/false AND has not itself been explicitly touched yet this
 * session, turn it on automatically. Once the user has explicitly
 * changed the approval toggle themselves (in either direction) during
 * this session, their choice is preserved -- even across a later
 * disable/re-enable of the connector in the same session.
 */
export function applyEnabledTransition({
  draft,
  enabledKey,
  approveHostKey,
  nextEnabled,
  approveHostManuallyChanged,
}) {
  const wasEnabled = Boolean(draft[enabledKey]);
  const next = { ...draft, [enabledKey]: nextEnabled };
  if (
    !wasEnabled &&
    nextEnabled &&
    !approveHostManuallyChanged &&
    !draft[approveHostKey]
  ) {
    next[approveHostKey] = true;
  }
  return next;
}
