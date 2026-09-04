/**
 * Turn a real HA websocket/service rejection into an honest, human-readable
 * description.
 *
 * `hass.callWS()` rejects with the raw `error` object HA's own
 * `connection.send_error(id, code, message)` sends (confirmed against
 * `homeassistant.components.websocket_api.connection.ActiveConnection
 * .send_error`) -- never a JS `Error`. HAMIE's own `_error()` helper
 * (presentation/api.py) sends `message = getattr(err, "code", None) or
 * type(err).__name__` -- the real semantic reason code (e.g.
 * "invalid_response", "unreachable") when the raised exception carries
 * one (ConnectorTestError/AIExecutorError always do, and never from raw
 * exception text or secrets -- every `.code` value is a short literal
 * hardcoded at the raise site, confirmed by reading every call site in
 * connectors/*.py), falling back to the bare exception class name (e.g.
 * "TimeoutError") only when it doesn't. `_structured_error()` sends
 * stable codes like "stale_revision"/"configuration_failed" through a
 * separate, already-handled path (KNOWN_CODES below). This is the one
 * place either kind gets turned into user-facing text, so no screen has
 * to reinvent it (or leak a raw code/class name) independently.
 *
 * Production defect fixed here: `_error()` previously always sent the
 * bare exception class name, discarding `.code` entirely -- so a real
 * Ollama request timeout surfaced to the user as the literal string
 * "TimeoutError" and a malformed/unparseable AI response surfaced as
 * "AIExecutorError", both meaningless. KNOWN_MESSAGES below now covers
 * every real `.code` raised anywhere in connectors/*.py (verified by
 * grepping every `ConnectorTestError(...)`/`AIExecutorError(...)` call
 * site, not guessed) plus the bare exception class names that can still
 * legitimately surface unwrapped (TimeoutError from asyncio.timeout,
 * ValueError from malformed transport responses, and common aiohttp
 * connection-failure class names) as a defensive fallback layer.
 *
 * The group review endpoints (hamie/group/preview|apply|suppress) all
 * route through the plain `_error()` helper, never `_structured_error()`
 * -- confirmed by reading presentation/api.py -- so `err.code` is always
 * the literal "hamie_error" there and can never match KNOWN_CODES. The
 * only real signal for those specific failures is the exception class
 * name in `err.message` (e.g. "GroupPreviewConflictError"), so those are
 * matched here too rather than silently falling through to the generic
 * fallback for a case that actually has a better honest message available.
 */
const KNOWN_CODES = {
  stale_revision: "This changed since it was loaded. Refresh and try again.",
  configuration_failed: "That configuration change could not be saved.",

  // Remediation Review Queue codes (presentation/remediation_api.py's
  // RemediationServiceError.code). Sent as `(err.code, err.message)`,
  // matching _structured_error's typed-business-error convention, not
  // the generic hamie_error + classified-text convention above -- so
  // these are matched on `code` here rather than via KNOWN_MESSAGES.
  remediation_not_found: "That recommendation or plan could not be found. Refresh the queue.",
  remediation_unsupported: "HAMIE does not support automated remediation for this recommendation yet.",
  remediation_plan_stale: "This plan has changed since it was last reviewed. Refresh and try again.",
  remediation_preview_stale: "Generate a fresh preview before approving.",
  remediation_snooze_invalid: "This proposal cannot be snoozed in its current state. Refresh the queue.",
  remediation_approval_missing: "That approval could not be found. Refresh the queue.",
  remediation_approval_invalid: "This approval is not valid for that action. Refresh and try again.",
  remediation_approval_expired: "This approval has expired. Approve again to continue.",
  remediation_approval_revoked: "This approval was revoked. Approve again to continue.",
  remediation_precondition_failed: "A safety precondition was not met, so nothing was changed.",
  remediation_backup_unavailable: "A supported backup provider is unavailable, so this proposal cannot be approved or executed.",
  remediation_lock_conflict: "Another remediation is already in progress for this target.",
  remediation_replay_conflict: "This request was already processed. Refresh to see the result.",
  remediation_execution_failed: "The remediation action failed to execute.",
  remediation_verification_failed: "HAMIE could not verify the action succeeded.",
  remediation_rolled_back: "The action failed verification and was automatically rolled back.",
  remediation_rollback_unavailable: "This verified repair can no longer be safely rolled back. Refresh its evidence.",
  remediation_rollback_failed: "The action failed and the automatic rollback also failed. Manual review is required.",
  remediation_internal_error: "The remediation request could not be completed. Try again.",
};

const KNOWN_MESSAGES = {
  GroupPreviewConflictError: "This group changed since it was loaded. Refresh and try again.",
  GroupNotFoundError: "This group no longer exists. Refresh the list.",
  InvalidReviewTransitionError: "No eligible findings remain for that action. Refresh the list.",
  IdempotencyConflictError: "That action may already have been applied. Refresh to check.",

  // Real AIExecutorError codes (connectors/ai_executor.py). invalid_response,
  // schema_validation_failed, and semantic_validation_failed used to be one
  // generic bucket; they are now distinct so the message tells you whether
  // the text wasn't JSON at all, was JSON but missing/wrong fields even
  // after HAMIE's automatic repair and one corrective retry, or was
  // well-formed but rejected for containing unsafe content.
  invalid_response: "HAMIE could not parse the AI provider's response as JSON. Try again, or check that the model returns structured JSON.",
  // ai_response_truncated is distinct from invalid_response: HAMIE
  // structurally detected the response was cut off mid-value (an
  // unclosed JSON object/array), not merely malformed -- so the honest
  // fix is a token/output limit, never a generic parsing retry.
  ai_response_truncated: "The AI provider's response was cut off before it finished, likely due to an output length limit. Increase the model's maximum output length, or try again.",
  schema_validation_failed: "The AI provider's response was missing required information or used the wrong format, even after HAMIE tried to repair it and asked the model to correct it. Try again, or use a model that follows JSON instructions more closely.",
  semantic_validation_failed: "HAMIE rejected the AI provider's response because it tried to include an executable action. This is a safety guard, not a connection problem.",
  entity_not_found: "The selected AI Task entity is no longer available. Choose a different provider in Settings.",
  timeout: "The AI provider did not respond within the configured timeout.",
  unsupported_feature: "The selected AI Task entity does not support this kind of request.",
  execution_failed: "The AI request could not be completed.",
  ai_provider_not_ready: "No AI provider is configured yet. Set one up in Settings.",
  // Real AIRequestError code (operations_service.py): every eligible
  // root-cause group already has a current (non-stale) recommendation,
  // so there is genuinely nothing new for "Analyze All" to do this run --
  // never confused with a failure or with the prompt-budget-too-small
  // case below.
  ai_all_groups_current: "Every group already has a current AI recommendation. There's nothing new to analyze right now.",

  // Real AIRequestError codes (application/operations_service.py). Raised
  // by async_request_ai() before it ever contacts a connector -- never a
  // connector reachability problem, so these must never fall through to
  // the generic connector "unreachable" text below.
  scan_data_unavailable: "There's nothing to analyze yet. Run a scan, or wait for one to finish.",
  ai_request_selection_too_large: "Too many findings were selected. Choose 50 or fewer.",
  analysis_already_running: "An analysis is already running. Wait for it to finish before starting another.",
  ai_prompt_budget_exhausted: "The configured prompt size is too small to analyze any finding. Increase the maximum input characters in Settings.",

  // Real AIExecutorError code (connectors/ai_executor.py, ollama.py). The
  // selected findings' evidence -- even after HAMIE's own bounded,
  // deduplicated, priority-ordered selection -- was still too large for
  // the configured prompt budget. Distinct from invalid_response
  // (a provider response failing to parse): this failure happens before
  // the provider is ever called, so it must never be described as a
  // parsing problem.
  evidence_payload_too_large: "The selected findings' evidence is too large for the configured prompt size. Increase the maximum input characters in Settings, or analyze fewer findings.",

  // Real ConnectorTestError codes (connectors/base.py, ollama.py, ha_transport.py).
  invalid_url: "The configured address is not a valid URL.",
  unreachable: "Unable to reach the connector within the configured timeout.",
  host_not_allowed: "This host needs explicit approval before HAMIE can connect to it.",
  model_not_found: "The configured model was not found on the provider.",
  authentication_failed: "Authentication with the provider failed. Check the credential.",
  model_discovery_failed: "Could not retrieve the list of available models from the provider.",
  model_list_unavailable: "The provider did not return a usable model list.",
  provider_response_not_json: "The provider's response was not valid JSON. Check the configured address, port, and that nothing (like a proxy) is intercepting the request.",

  // Real n8n connector codes (connectors/n8n.py). Service health and
  // webhook readiness are deliberately separate facts -- a blank or
  // unreachable webhook must never read the same as n8n itself being
  // down, so these are their own namespaced codes rather than reusing
  // the generic connector codes above.
  n8n_service_unreachable: "The n8n host could not be reached.",
  n8n_service_timeout: "The n8n request exceeded the configured timeout.",
  n8n_dns_failure: "The n8n host's address could not be resolved. Check the configured host name.",
  n8n_service_connection_refused: "The n8n host refused the connection. Check the address and port.",
  n8n_authentication_failed: "n8n rejected the saved outbound credential.",
  n8n_forbidden: "n8n reached the request but rejected it as forbidden.",
  n8n_health_http_error: "n8n responded, but its health endpoint returned an unexpected status.",
  n8n_health_invalid_response: "n8n responded, but not with the expected health check format.",
  n8n_webhook_not_configured: "n8n is reachable, but the outbound webhook URL is not configured.",
  n8n_webhook_not_found: "n8n is reachable, but the configured webhook was not found.",
  n8n_webhook_method_not_allowed: "n8n is reachable and the webhook exists, but does not accept this readiness check's request method.",
  n8n_webhook_timeout: "The n8n webhook did not respond within the configured timeout.",
  n8n_webhook_unreachable: "The configured n8n webhook could not be reached.",
  n8n_webhook_readiness_unknown: "Webhook readiness cannot be safely confirmed without executing the workflow.",

  // Bare exception class names that can still legitimately surface
  // unwrapped (no .code attribute) -- a defensive fallback layer, not
  // the primary path now that real codes are preserved.
  TimeoutError: "Unable to reach the connector within the configured timeout.",
  ValueError: "The connector returned an unexpected response.",
  ClientConnectorError: "Unable to reach the connector. Check the address and that it is running.",
  ClientResponseError: "The connector returned an unexpected error response.",
  ClientError: "The connector returned an unexpected response.",
  ConnectionRefusedError: "The connector refused the connection. Check the address and port.",
};

/** Map a real backend code/class-name string directly to human text. */
export function humanizeCode(code, fallback) {
  return (code && KNOWN_MESSAGES[code]) || fallback;
}

export function friendlyError(err, fallback = "This data is temporarily unavailable.") {
  console.error("HAMIE request failed:", err);
  const code = err?.code;
  if (code && KNOWN_CODES[code]) return KNOWN_CODES[code];
  return humanizeCode(err?.message, fallback);
}
