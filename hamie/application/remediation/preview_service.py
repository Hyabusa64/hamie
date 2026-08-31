"""No-mutation preview orchestration (HAMIE Phase 2B).

Calls each step's adapter ``preview()`` method -- never ``execute()`` --
to render human-facing before/after text for review. The plan's own
``preview_digest`` (``domain.remediation.compute_structural_preview_digest``,
already baked into the immutable ``RemediationPlan`` by the planner) is
the tamper-evident value an ``ApprovalRecord`` actually binds to; the
richer adapter-rendered text this module produces is display-only and
never part of any fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ...domain.remediation import RemediationPlan, compute_structural_preview_digest
from .adapters import (
    AdapterPreviewResult,
    RemediationActionAdapter,
    RemediationAdapterContext,
)


class PreviewMismatchError(RuntimeError):
    """The plan's stored preview_digest no longer matches its own actions.

    Should be unreachable in practice -- ``RemediationPlan.__post_init__``
    already cross-checks this at construction -- but this module
    re-verifies independently rather than trusting an in-memory object
    that could have been tampered with between construction and use.
    """


@dataclass(frozen=True, slots=True)
class StepPreview:
    """One step's rendered preview, paired with its structural definition."""

    step_index: int
    action_type: str
    adapter_id: str
    rendered_before: str | None
    rendered_after: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreviewRunResult:
    """The complete, reproducible preview for one plan."""

    remediation_plan_id: str
    plan_fingerprint: str
    preview_digest: str
    steps: tuple[StepPreview, ...]


async def async_run_preview(
    plan: RemediationPlan,
    *,
    adapters: dict[str, RemediationActionAdapter],
    now: datetime,
    execution_id: str = "preview",
) -> PreviewRunResult:
    """Render a plan's preview. Never mutates anything.

    Raises ``PreviewMismatchError`` if the plan's ``preview_digest`` no
    longer matches its own structural actions, and ``KeyError`` (via the
    adapter lookup) if a step's adapter is not registered -- both are
    real defects a caller must not silently ignore, never soft-failed
    into a partial preview.
    """
    expected_digest = compute_structural_preview_digest(plan.actions)
    if plan.preview_digest != expected_digest:
        raise PreviewMismatchError(
            "plan.preview_digest does not match its current actions"
        )

    context = RemediationAdapterContext(
        installation_id=plan.installation_id, now=now, execution_id=execution_id
    )
    steps: list[StepPreview] = []
    for step in plan.actions:
        adapter = adapters[step.adapter_id]
        result: AdapterPreviewResult = await adapter.preview(step, context)
        steps.append(
            StepPreview(
                step_index=step.step_index,
                action_type=step.action_type,
                adapter_id=step.adapter_id,
                rendered_before=result.rendered_before,
                rendered_after=result.rendered_after,
                warnings=result.warnings,
            )
        )
    return PreviewRunResult(
        remediation_plan_id=plan.remediation_plan_id,
        plan_fingerprint=plan.plan_fingerprint,
        preview_digest=plan.preview_digest or expected_digest,
        steps=tuple(steps),
    )
