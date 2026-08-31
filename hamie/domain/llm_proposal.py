"""LLM-proposed remediation action: structural model (HAMIE Phase 3B).

An ``LlmProposedAction`` is the model's own structured request to have
HAMIE consider one narrow, evidence-linked mutation -- never a command
HAMIE trusts or executes directly. This module only parses and bounds
the *shape* of a proposal; it never decides whether the proposal is
actually allowed. That deterministic policy decision (resource
allowlist membership, evidence membership, action-type compatibility)
lives in ``domain/remediation_llm_proposal.py``, kept separate so this
module has no dependency on ``domain/recommendation.py`` or
``domain/remediation_resources.py`` and therefore cannot form an import
cycle with either.

Core safety invariant this module exists to support: the model may
*describe* an action, but every field is bounded, typed, and re-derived
by HAMIE before anything downstream trusts it -- never free text, never
a path, never a shell/service/automation payload (see
``connectors/schemas.py``'s ``SYSTEM_INSTRUCTIONS`` and
``validate_ai_response_semantics``, which reject executable content in
every text field including this one).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .common import require_non_empty

MAX_RESOURCE_ID_LENGTH = 128
MAX_ACTION_TYPE_LENGTH = 64
MAX_OPERATION_ENTRIES = 8
MAX_OPERATION_KEY_LENGTH = 128
MAX_OPERATION_VALUE_LENGTH = 500
MAX_EVIDENCE_IDS = 16
MAX_EVIDENCE_ID_LENGTH = 256
MAX_REASON_LENGTH = 500

# The only proposal shapes HAMIE will ever parse. Unlike the deterministic
# catalog (domain/remediation_catalog.py), this set exists purely to bound
# what a *proposal* may claim -- it is never sufficient by itself to make
# an action executable; see domain/remediation_llm_proposal.py.
SUPPORTED_PROPOSED_ACTION_TYPES = frozenset({"yaml_set"})


@dataclass(frozen=True, slots=True)
class LlmProposedAction:
    """One bounded, structurally-valid proposal the model returned.

    Never trusted as authorization to do anything -- see module
    docstring. ``operation`` is a small, closed key/value pair set (e.g.
    ``{"key": "...", "value": "..."}`` for ``yaml_set``), never free-form
    text, a path, or a command.
    """

    resource_id: str
    action_type: str
    operation: tuple[tuple[str, str], ...]
    evidence_ids: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        require_non_empty(self.resource_id, "proposed_action.resource_id")
        if len(self.resource_id) > MAX_RESOURCE_ID_LENGTH:
            raise ValueError("proposed_action.resource_id is too long")
        require_non_empty(self.action_type, "proposed_action.action_type")
        if len(self.action_type) > MAX_ACTION_TYPE_LENGTH:
            raise ValueError("proposed_action.action_type is too long")
        if self.action_type not in SUPPORTED_PROPOSED_ACTION_TYPES:
            raise ValueError(
                f"proposed_action.action_type {self.action_type!r} is not "
                "a supported proposal action type"
            )
        operation = tuple(sorted(dict(self.operation).items()))
        if not operation or len(operation) > MAX_OPERATION_ENTRIES:
            raise ValueError(
                "proposed_action.operation must be a bounded, non-empty map"
            )
        for key, value in operation:
            if not key or len(key) > MAX_OPERATION_KEY_LENGTH:
                raise ValueError("proposed_action.operation keys must be bounded")
            if len(value) > MAX_OPERATION_VALUE_LENGTH:
                raise ValueError("proposed_action.operation values must be bounded")
        object.__setattr__(self, "operation", operation)
        evidence_ids = tuple(dict.fromkeys(self.evidence_ids))
        if not evidence_ids:
            raise ValueError("proposed_action.evidence_ids must not be empty")
        if len(evidence_ids) > MAX_EVIDENCE_IDS:
            raise ValueError("proposed_action.evidence_ids is too long")
        if any(not item or len(item) > MAX_EVIDENCE_ID_LENGTH for item in evidence_ids):
            raise ValueError("proposed_action.evidence_ids items must be bounded")
        object.__setattr__(self, "evidence_ids", evidence_ids)
        require_non_empty(self.reason, "proposed_action.reason")
        if len(self.reason) > MAX_REASON_LENGTH:
            raise ValueError("proposed_action.reason is too long")


def parse_llm_proposed_action(raw: Any) -> LlmProposedAction | None:
    """Parse one optional, untrusted ``proposed_action`` payload.

    Returns ``None`` for an absent or malformed proposal -- a malformed
    proposal is dropped silently at this layer (never raised), matching
    the rule that a model's optional, invalid action attempt must never
    fail the surrounding analysis (see docs/REMEDIATION_ENGINE.md and
    connectors/schemas.py's ``repair_ai_response``/parsing tolerance
    philosophy). Callers that want to surface *why* a proposal was
    dropped should inspect the raw payload themselves before calling
    this; this function intentionally returns no diagnostic detail so
    it can be safely called from a hot parsing path with a single
    ``if result is not None`` check.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    resource_id = raw.get("resource_id")
    action_type = raw.get("action_type")
    operation = raw.get("operation")
    evidence_ids = raw.get("evidence_ids")
    reason = raw.get("reason")
    if not isinstance(resource_id, str) or not isinstance(action_type, str):
        return None
    if not isinstance(operation, dict) or not isinstance(reason, str):
        return None
    if not isinstance(evidence_ids, list):
        return None
    if not all(isinstance(item, str) for item in evidence_ids):
        return None
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in operation.items()
    ):
        return None
    try:
        return LlmProposedAction(
            resource_id=resource_id.strip(),
            action_type=action_type.strip(),
            operation=tuple((str(k), str(v)) for k, v in operation.items()),
            evidence_ids=tuple(item.strip() for item in evidence_ids if item.strip()),
            reason=reason.strip(),
        )
    except ValueError:
        return None
