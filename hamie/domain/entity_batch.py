"""Deterministic entity-id batch parameter encoding (mission Part 8/22).

``RemediationActionStep.parameters`` bounds each value to 1000
characters (``domain/remediation.py``'s ``MAX_LIST_ITEM_LENGTH``) --
too small to hold a large batch's entity ids in one field, and
``StepExecutionResult.observed_before_state``/``observed_after_state``
are separately bounded to 4000 characters each
(``domain/remediation_execution.py``). This module is the single
shared encode/decode pair the planner/step-builder and the adapter
both use, so a batch's parameter and result shape can never silently
drift between them.
"""

from __future__ import annotations

MAX_CHUNK_CHARS = 900
MAX_CHUNKS = 60
# Chosen so a compact "entity_id=state" rollback summary (see
# application/remediation/batch_entity_adapter.py) comfortably fits
# within StepExecutionResult's 4000-character bound even for
# long entity ids -- a future chunked-rollback-storage design could
# raise this; documented here as today's real, honest limit rather
# than pretending an unbounded batch is safe.
MAX_BATCH_ENTITIES = 90


def encode_entity_id_batch(entity_ids: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """Encode a bounded, deduplicated set of entity ids into step parameters."""
    if not entity_ids:
        raise ValueError("entity id batch must not be empty")
    deduped = tuple(dict.fromkeys(entity_ids))
    if len(deduped) > MAX_BATCH_ENTITIES:
        raise ValueError(f"entity id batch exceeds {MAX_BATCH_ENTITIES} entities")
    for entity_id in deduped:
        if not entity_id or "," in entity_id or "=" in entity_id:
            raise ValueError(f"invalid entity id in batch: {entity_id!r}")
    chunks: list[str] = []
    current = ""
    for entity_id in deduped:
        candidate = f"{current},{entity_id}" if current else entity_id
        if len(candidate) > MAX_CHUNK_CHARS:
            chunks.append(current)
            current = entity_id
        else:
            current = candidate
    if current:
        chunks.append(current)
    if len(chunks) > MAX_CHUNKS:
        raise ValueError("entity id batch requires too many parameter chunks")
    return tuple((f"entity_ids_{i}", chunk) for i, chunk in enumerate(chunks))


def decode_entity_id_batch(parameters: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    """Decode the entity ids a batch step's parameters encode, in order."""
    values = dict(parameters)
    chunks: list[str] = []
    index = 0
    while f"entity_ids_{index}" in values:
        chunks.append(values[f"entity_ids_{index}"])
        index += 1
    ids: list[str] = []
    for chunk in chunks:
        ids.extend(item for item in chunk.split(",") if item)
    return tuple(dict.fromkeys(ids))
