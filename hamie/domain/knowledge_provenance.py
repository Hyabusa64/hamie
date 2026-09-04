"""Shared provenance vocabulary for durable HAMIE knowledge records.

Both ``domain/successors.py`` and ``domain/implementation_groups.py``
need to say *where a durable conclusion came from* -- a HAMIE analyzer's
own deterministic rule, a Claude-assisted investigation reading live
evidence by hand, an explicit human decision, or a conservative import
of a preserved remediation-evidence artifact. Kept as its own tiny
module (rather than duplicated in each) so both knowledge types use the
identical, single vocabulary -- a future consumer never has to check
"is this the successors.py or implementation_groups.py flavor of
provenance" before comparing two records.
"""

from __future__ import annotations

from enum import StrEnum


class KnowledgeProvenance(StrEnum):
    """Where a durable knowledge record's conclusion originated.

    Distinct from ``EvidenceKind`` (``domain/evidence.py``): that enum
    classifies one *observation*'s authority (observed/derived/
    asserted); this classifies the *investigation* that produced the
    whole record. A record's evidence tuple can mix multiple
    ``EvidenceKind`` values while the record itself has exactly one
    provenance.
    """

    # A HAMIE analyzer's own deterministic rule reached this conclusion
    # unattended (e.g. ``duplicate_classifier.py``'s classification).
    HAMIE_ANALYZER = "hamie_analyzer"
    # A Claude-assisted (or other AI-assisted) investigation read live
    # Home Assistant evidence by hand and recorded a conclusion --
    # never auto-trusted at a higher confidence than the evidence
    # itself supports; see ``successors.py``/``implementation_groups.py``
    # docstrings for how this provenance interacts with confidence.
    CLAUDE_ASSISTED_INVESTIGATION = "claude_assisted_investigation"
    # A human explicitly decided something (e.g. "these two entities
    # are intentionally separate") -- the highest-authority provenance,
    # but still never self-authorizing automatic remediation on its own
    # (mission Part 26/158).
    USER_DECISION = "user_decision"
    # Conservatively imported from a preserved remediation-evidence
    # artifact (e.g. a benchmark ``phase_b1_actions.json``-shaped file)
    # by ``domain/knowledge_import.py`` -- never fabricated, only
    # mapped from fields the artifact actually contains.
    IMPORTED_EVIDENCE_ARTIFACT = "imported_evidence_artifact"
