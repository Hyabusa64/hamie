"""Deterministic policy validation for one LLM-proposed action (Phase 3B).

This is the *only* authority that decides whether an
``LlmProposedAction`` (``domain/llm_proposal.py``) may ever become a
real ``RemediationActionStep``. It never trusts the model: every check
here is a deterministic comparison against HAMIE's own reviewed state
(the editable resource registry, the evidence ids HAMIE actually
supplied to the model) -- never the model's own claims about either.

Mirrors ``domain/remediation_planner.py``'s ``PlanningRejection``
pattern deliberately: an ordinary policy rejection is data returned to
the caller, never an exception, so a rejected proposal can be logged
and the underlying recommendation kept without any special-case
exception handling at the call site.
"""

from __future__ import annotations

from dataclasses import dataclass

from .common import require_non_empty
from .llm_proposal import LlmProposedAction
from .remediation_resources import resolve_editable_resource


@dataclass(frozen=True, slots=True)
class ProposalRejection:
    """Why one LLM-proposed action was not accepted as policy-valid."""

    reason_code: str
    message: str

    def __post_init__(self) -> None:
        require_non_empty(self.reason_code, "reason_code")
        require_non_empty(self.message, "message")


def validate_llm_proposed_action(
    proposal: LlmProposedAction,
    *,
    known_evidence_ids: frozenset[str] | None,
) -> LlmProposedAction | ProposalRejection:
    """Validate one proposal against deterministic HAMIE policy.

    ``known_evidence_ids`` is the exact set of evidence identifiers
    HAMIE actually supplied to the model for this analysis (e.g. the
    finding ids present in the evidence payload) -- every
    ``proposal.evidence_ids`` entry must be a member, or the proposal is
    rejected as unsupported/hallucinated evidence (mission Phase 13).
    Pass ``None`` only when re-validating a proposal that already passed
    this exact check once, at generation time, and the caller cannot
    reconstruct the original evidence universe (e.g. re-validating a
    persisted recommendation well after the fact) -- in that case the
    non-empty/bounded shape check still applies, but membership is not
    re-verified.

    Never raises for an ordinary policy outcome -- always returns either
    the (unchanged) validated proposal or a typed ``ProposalRejection``.
    """
    resource = resolve_editable_resource(proposal.resource_id)
    if resource is None:
        return ProposalRejection(
            reason_code="unknown_editable_resource",
            message=(
                f"{proposal.resource_id!r} is not a HAMIE-reviewed editable resource"
            ),
        )
    if not resource.supports_action_type(proposal.action_type):
        return ProposalRejection(
            reason_code="unsupported_action_for_resource",
            message=(
                f"resource {proposal.resource_id!r} does not support action "
                f"type {proposal.action_type!r}"
            ),
        )
    operation = dict(proposal.operation)
    if resource.resource_format.value == "hamie_owned_yaml_map":
        if set(operation) != {"key", "value"}:
            return ProposalRejection(
                reason_code="invalid_operation_shape",
                message="a yaml_set operation requires exactly 'key' and 'value'",
            )
        if not resource.allows_key(operation["key"]):
            return ProposalRejection(
                reason_code="key_not_allowed",
                message=(
                    f"key {operation['key']!r} is not permitted on resource "
                    f"{proposal.resource_id!r}"
                ),
            )
    if known_evidence_ids is not None:
        unknown = tuple(
            item for item in proposal.evidence_ids if item not in known_evidence_ids
        )
        if unknown:
            return ProposalRejection(
                reason_code="hallucinated_evidence",
                message=(
                    "proposed_action references evidence ids HAMIE never "
                    f"supplied: {', '.join(unknown[:5])}"
                ),
            )
    return proposal
