"""Temporal (recorder/statistics) evidence enrichment (mission Part 1.2).

**Design decision: enrichment of ``UnavailableEntityAnalyzer`` findings,
not a standalone analyzer.** ``domain/temporal_evidence.py`` answers one
question -- "how long has this entity actually been unavailable, and
how confident can HAMIE be in a claim like '>30 days'?" -- and that
question is only ever meaningful for a subject that is *already*
established as unavailable, which is exactly what
``UnavailableEntityAnalyzer``'s findings already are. A standalone
"temporal evidence analyzer" would need to re-derive "is this entity
unavailable" from scratch just to know which entities to ask the
recorder about, duplicating ``UnavailableEntityAnalyzer``'s own grace-
period policy and risking the two silently disagreeing about which
entities qualify. Attaching temporal evidence directly onto the
finding it is evidence *for* also matches how every other analyzer in
this codebase layers evidence (see
``analysis/analyzers/unavailable_entities.py``'s own multiple
``EvidenceItem`` entries per finding) -- it is just more evidence on a
finding it already knows how to display, not a second finding about
the same entity a reviewer would have to mentally correlate.

This renders with zero new plumbing in the Issues/Findings detail view
(``hamie-view-findings.js``, ~line 833), which generically iterates
every finding's ``evidence[]`` array (`` e.kind · e.predicate = e.value
· e.source @ e.source_revision``) regardless of what an analyzer put in
it. It does **not** automatically appear on the Review screen:
``hamie-evidence-panel.js`` is a hand-fed for/against string-array
component (see its own docstring), not a generic ``evidence[]``
renderer, and ``hamie-view-review.js`` manually curates which specific
fields/strings get passed into it per category. Surfacing temporal
evidence on Review would need that curation to be extended explicitly
-- it is not automatic just because this module appends to
``evidence[]``.

Never changes ``recommendation.kind``: ``UnavailableEntityAnalyzer``'s
own ``AnalyzerDescriptor`` only ever authorizes ``MONITOR``, and that
authority check (``AnalyzerSupervisor._reduce``) already ran before
this module ever sees a finding -- this only appends evidence
describing what recorder/statistics evidence does or does not support
about a >30-day unavailability claim, with explicit provenance of which
source (raw recorder history vs. long-term statistics, or neither)
supplied it.

``source`` absent (no live recorder reachable -- the expected state for
every offline scan) degrades every finding to
``INSUFFICIENT_HISTORY_TO_PROVE_30D`` with an explicit "no recorder
source configured" provenance note, never silently omitted and never
fabricated as ``CONFIRMED``. A per-entity priming/classification
failure is captured defensively and degrades only that one finding the
same way, never the whole scan -- matching this codebase's established
"capture defensively, report honestly" pattern (see
``infrastructure/dependency_source.py``'s module docstring).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

from ..application.ports import TemporalEvidenceSourcePort
from ..domain.common import require_utc, stable_digest
from ..domain.evidence import EvidenceItem, EvidenceKind, Sensitivity
from ..domain.findings import CandidateFinding
from ..domain.temporal_evidence import TemporalEvidence, classify_temporal_evidence
from .analyzers.unavailable_entities import ANALYZER_ID as UNAVAILABLE_ANALYZER_ID
from .supervisor import SupervisionResult

_LOGGER = logging.getLogger(__name__)

ENRICHMENT_POLICY_VERSION = "1.0.0"
STATUS_PREDICATE = "hamie.entity.temporal_evidence_status@1"
PROVENANCE_PREDICATE = "hamie.entity.temporal_evidence_provenance@1"


async def async_enrich_unavailable_findings_with_temporal_evidence(
    supervision: SupervisionResult,
    *,
    source: TemporalEvidenceSourcePort | None,
    observed_at: datetime,
) -> SupervisionResult:
    """Attach honest temporal-evidence provenance to unavailable-entity findings.

    A no-op (returns ``supervision`` unchanged) for any supervision that
    is not ``UnavailableEntityAnalyzer``'s own -- safe to call
    unconditionally over every analyzer's ``SupervisionResult`` each
    scan.
    """
    at = require_utc(observed_at, "observed_at")
    targets = tuple(
        finding.subject.source_id
        for finding in supervision.findings
        if finding.analyzer_id == UNAVAILABLE_ANALYZER_ID
    )
    if not targets:
        return supervision

    active_source = source
    if active_source is not None:
        try:
            await active_source.async_prime(targets, now=at)
        except Exception:  # noqa: BLE001 -- defensive, see module docstring
            _LOGGER.exception(
                "HAMIE temporal-evidence priming failed for %d entities; "
                "every affected finding degrades to insufficient-history "
                "evidence this scan",
                len(targets),
            )
            active_source = None

    enriched: list[CandidateFinding] = []
    for finding in supervision.findings:
        if finding.analyzer_id != UNAVAILABLE_ANALYZER_ID:
            enriched.append(finding)
            continue
        enriched.append(
            await _enrich_one(finding, source=active_source, observed_at=at)
        )
    return replace(supervision, findings=tuple(enriched))


async def _enrich_one(
    finding: CandidateFinding,
    *,
    source: TemporalEvidenceSourcePort | None,
    observed_at: datetime,
) -> CandidateFinding:
    entity_id = finding.subject.source_id
    raw_available: int | None = None
    raw_unavailable: int | None = None
    lt_seconds: int | None = None
    contradicting = False
    provenance = "no_recorder_source_configured"

    if source is not None:
        try:
            raw_available = await source.async_raw_history_available_seconds(entity_id)
            lt_seconds = await source.async_long_term_statistics_unavailable_seconds(
                entity_id
            )
            raw_unavailable = source.raw_unavailable_seconds(entity_id)
            contradicting = bool(source.contradicting_activity_found(entity_id))
            if lt_seconds is not None:
                provenance = "long_term_statistics"
            elif raw_available is not None:
                provenance = "raw_recorder_history"
            else:
                provenance = "recorder_source_returned_no_evidence"
        except Exception:  # noqa: BLE001 -- defensive, see module docstring
            _LOGGER.exception(
                "HAMIE temporal-evidence lookup failed for %s; degrading to "
                "insufficient-history evidence",
                entity_id,
            )
            raw_available = raw_unavailable = lt_seconds = None
            contradicting = False
            provenance = "recorder_source_lookup_failed"

    try:
        evidence = TemporalEvidence(
            raw_history_available_seconds=raw_available,
            raw_unavailable_seconds=raw_unavailable,
            long_term_statistics_confirm_unavailable_seconds=lt_seconds,
            contradicting_activity_found=contradicting,
        )
    except ValueError:
        # A defensively-read but internally inconsistent combination
        # (e.g. unavailable_seconds > available_seconds from an
        # unexpected recorder response shape) -- degrade to no-evidence
        # rather than raise and abort the whole scan.
        _LOGGER.warning(
            "HAMIE temporal-evidence for %s was internally inconsistent; "
            "degrading to no evidence",
            entity_id,
        )
        evidence = TemporalEvidence()
        provenance = "recorder_source_returned_malformed_evidence"

    status = classify_temporal_evidence(evidence)
    revision = stable_digest(
        entity_id, provenance, status.value, observed_at.isoformat()
    )
    new_items = (
        *finding.evidence,
        EvidenceItem(
            subject=finding.subject,
            predicate=STATUS_PREDICATE,
            value=status.value,
            observed_at=observed_at,
            source_id=f"hamie.temporal_evidence.{provenance}",
            source_revision=revision,
            kind=EvidenceKind.DERIVED,
            sensitivity=Sensitivity.PUBLIC,
        ),
        EvidenceItem(
            subject=finding.subject,
            predicate=PROVENANCE_PREDICATE,
            value=provenance,
            observed_at=observed_at,
            source_id="hamie.temporal_evidence_policy",
            source_revision=ENRICHMENT_POLICY_VERSION,
            kind=EvidenceKind.DERIVED,
            sensitivity=Sensitivity.PUBLIC,
        ),
    )
    new_recommendation = replace(finding.recommendation, evidence=new_items)
    return replace(finding, evidence=new_items, recommendation=new_recommendation)
