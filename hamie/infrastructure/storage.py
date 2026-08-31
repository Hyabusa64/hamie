"""Versioned Home Assistant Store repository adapter."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from ..application.persistence import (
    CorruptStoredStateError,
    GenerationConflictError,
    IdempotencyRecord,
    RepositoryState,
    UnsupportedStoredStateError,
)
from ..domain.ai_control import (
    decode_ai_control_acknowledgement,
    encode_ai_control_acknowledgement,
)
from ..domain.common import canonical_json, stable_digest
from ..domain.intelligence import (
    decode_ai_recommendation,
    decode_audit,
    decode_grouping_rule,
    decode_suppression_rule,
    encode_ai_recommendation,
    encode_audit,
    encode_grouping_rule,
    encode_suppression_rule,
)
from ..domain.capability import decode_capability, encode_capability
from ..domain.durable_baseline import (
    decode_analysis_baseline,
    decode_remediation_baseline,
    encode_analysis_baseline,
    encode_remediation_baseline,
)
from ..domain.incidents import decode_incident, encode_incident
from ..domain.knowledge_serialization import (
    decode_entity_successor,
    decode_implementation_group,
    encode_entity_successor,
    encode_implementation_group,
)
from ..domain.maintenance_work_record_serialization import (
    decode_maintenance_work_record,
    encode_maintenance_work_record,
)
from ..domain.recommendation_serialization import (
    decode_canonical_recommendation,
    encode_canonical_recommendation,
)
from ..domain.remediation_serialization import (
    decode_approval,
    decode_execution_lock,
    decode_execution_record,
    decode_remediation_plan,
    decode_replay_token,
    decode_rollback_record,
    encode_approval,
    encode_execution_lock,
    encode_execution_record,
    encode_remediation_plan,
    encode_replay_token,
    encode_rollback_record,
)
from ..domain.serialization import (
    decode_evaluation,
    decode_finding,
    decode_review,
    encode_evaluation,
    encode_finding,
    encode_review,
)

STORAGE_KEY = "hamie.state"


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """What was preserved when an unreadable document was set aside."""

    quarantine_key: str
    reason: str
    quarantined_at: str
    schema_version: int | None
    document_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "quarantine_key": self.quarantine_key,
            "reason": self.reason,
            "quarantined_at": self.quarantined_at,
            "schema_version": self.schema_version,
            "document_bytes": self.document_bytes,
        }
STORE_FORMAT_VERSION = 1
STORAGE_SCHEMA_VERSION = 10
STORAGE_MINOR_VERSION = 0
MAX_MIGRATION_CHECKPOINT_BYTES = 1_000_000


def _payload(state: RepositoryState) -> dict[str, Any]:
    return {
        "generation": state.generation,
        "projection_revision": state.projection_revision,
        "findings": [encode_finding(item) for item in state.findings],
        "reviews": [encode_review(item) for item in state.reviews],
        "evaluations": [encode_evaluation(item) for item in state.evaluations],
        "idempotency": [
            {
                "token": item.token,
                "command": item.command,
                "finding_id": item.finding_id,
                "resulting_revision": item.resulting_revision,
            }
            for item in state.idempotency
        ],
        "migration_history": list(state.migration_history),
        "grouping_rules": [encode_grouping_rule(item) for item in state.grouping_rules],
        "suppression_rules": [
            encode_suppression_rule(item) for item in state.suppression_rules
        ],
        "audits": [encode_audit(item) for item in state.audits],
        "recommendations": [
            encode_ai_recommendation(item) for item in state.recommendations
        ],
        "canonical_recommendations": [
            encode_canonical_recommendation(item)
            for item in state.canonical_recommendations
        ],
        "remediation_plans": [
            encode_remediation_plan(item) for item in state.remediation_plans
        ],
        "remediation_approvals": [
            encode_approval(item) for item in state.remediation_approvals
        ],
        "remediation_executions": [
            encode_execution_record(item) for item in state.remediation_executions
        ],
        "remediation_rollbacks": [
            encode_rollback_record(item) for item in state.remediation_rollbacks
        ],
        "remediation_locks": [
            encode_execution_lock(item) for item in state.remediation_locks
        ],
        "remediation_replay_tokens": [
            encode_replay_token(item) for item in state.remediation_replay_tokens
        ],
        "ai_control_acknowledgement": encode_ai_control_acknowledgement(
            state.ai_control_acknowledgement
        ),
        "maintenance_work_items": [
            encode_maintenance_work_record(item)
            for item in state.maintenance_work_items
        ],
        "last_cleanup_scan_id": state.last_cleanup_scan_id,
        "entity_successors": [
            encode_entity_successor(item) for item in state.entity_successors
        ],
        "implementation_groups": [
            encode_implementation_group(item) for item in state.implementation_groups
        ],
        "incidents": [encode_incident(item) for item in state.incidents],
        "capability": encode_capability(state.capability),
        # Additive-optional inside schema 10: a document written without these
        # keys still decodes (both default to absent), so adding durable
        # baselines needed no second migration and no second rollback hazard.
        "analysis_baseline": encode_analysis_baseline(state.analysis_baseline),
        "remediation_baselines": [
            encode_remediation_baseline(item) for item in state.remediation_baselines
        ],
    }


def encode_document(
    state: RepositoryState,
    *,
    checkpoint: dict[str, Any] | None = None,
    migration_journal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Encode a checksummed single-document commit."""
    payload = _payload(state)
    return {
        "schema_version": STORAGE_SCHEMA_VERSION,
        "schema_minor_version": STORAGE_MINOR_VERSION,
        "compatibility": {
            "minimum_reader": STORAGE_SCHEMA_VERSION,
            "maximum_reader": STORAGE_SCHEMA_VERSION,
        },
        "payload": payload,
        "checksum": stable_digest(canonical_json(payload)),
        "migration_journal": migration_journal,
        "migration_checkpoint": checkpoint,
    }


def encoded_document_size(state: RepositoryState) -> int:
    """Return the exact UTF-8 size of HAMIE's canonical Store document."""
    return len(canonical_json(encode_document(state)).encode("utf-8"))


def decode_document(raw: object) -> RepositoryState:
    """Preflight, recover, migrate, and validate stored state."""
    if not isinstance(raw, dict):
        raise CorruptStoredStateError("HAMIE Store document must be an object")
    version = raw.get("schema_version")
    if not isinstance(version, int):
        raise CorruptStoredStateError("HAMIE Store schema version is missing")
    if version > STORAGE_SCHEMA_VERSION:
        raise UnsupportedStoredStateError(
            f"HAMIE Store schema {version} is newer than supported "
            f"schema {STORAGE_SCHEMA_VERSION}"
        )
    if version == 0:
        return _migrate_v0(raw)
    if version == 1:
        return _migrate_v1(raw)
    if version == 2:
        return _migrate_v2(raw)
    if version == 3:
        return _migrate_v3(raw)
    if version == 4:
        return _migrate_v4(raw)
    if version == 5:
        return _migrate_v5(raw)
    if version == 6:
        return _migrate_v6(raw)
    if version == 7:
        return _migrate_v7(raw)
    if version == 8:
        return _migrate_v8(raw)
    if version == 9:
        return _migrate_v9(raw)
    journal = raw.get("migration_journal")
    if journal is not None and (
        not isinstance(journal, dict) or journal.get("phase") != "complete"
    ):
        checkpoint = raw.get("migration_checkpoint")
        if not isinstance(checkpoint, dict):
            raise CorruptStoredStateError(
                "interrupted migration has no recoverable checkpoint"
            )
        return decode_document(checkpoint)
    compatibility = raw.get("compatibility")
    if not isinstance(compatibility, dict):
        raise CorruptStoredStateError("HAMIE Store compatibility envelope is missing")
    minimum_reader = compatibility.get("minimum_reader")
    maximum_reader = compatibility.get("maximum_reader")
    if not isinstance(minimum_reader, int) or not isinstance(maximum_reader, int):
        raise CorruptStoredStateError("HAMIE Store reader envelope is invalid")
    if not minimum_reader <= STORAGE_SCHEMA_VERSION <= maximum_reader:
        raise UnsupportedStoredStateError(
            "HAMIE Store compatibility envelope excludes this reader"
        )
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise CorruptStoredStateError("HAMIE Store payload is missing")
    try:
        payload_checksum = stable_digest(canonical_json(payload))
    except ValueError as err:
        raise CorruptStoredStateError("HAMIE Store payload is not JSON-safe") from err
    if raw.get("checksum") != payload_checksum:
        raise CorruptStoredStateError("HAMIE Store checksum does not match")
    try:
        idempotency = tuple(
            IdempotencyRecord(
                token=item["token"],
                command=item["command"],
                finding_id=item["finding_id"],
                resulting_revision=item["resulting_revision"],
            )
            for item in payload.get("idempotency", [])
        )
        return RepositoryState(
            generation=payload["generation"],
            findings=tuple(
                decode_finding(item) for item in payload.get("findings", [])
            ),
            reviews=tuple(decode_review(item) for item in payload.get("reviews", [])),
            evaluations=tuple(
                decode_evaluation(item) for item in payload.get("evaluations", [])
            ),
            idempotency=idempotency,
            projection_revision=payload.get("projection_revision", 0),
            migration_history=tuple(payload.get("migration_history", [])),
            grouping_rules=tuple(
                decode_grouping_rule(item) for item in payload.get("grouping_rules", [])
            ),
            suppression_rules=tuple(
                decode_suppression_rule(item)
                for item in payload.get("suppression_rules", [])
            ),
            audits=tuple(decode_audit(item) for item in payload.get("audits", [])),
            recommendations=tuple(
                decode_ai_recommendation(item)
                for item in payload.get("recommendations", [])
            ),
            canonical_recommendations=tuple(
                decode_canonical_recommendation(item)
                for item in payload.get("canonical_recommendations", [])
            ),
            remediation_plans=tuple(
                decode_remediation_plan(item)
                for item in payload.get("remediation_plans", [])
            ),
            remediation_approvals=tuple(
                decode_approval(item)
                for item in payload.get("remediation_approvals", [])
            ),
            remediation_executions=tuple(
                decode_execution_record(item)
                for item in payload.get("remediation_executions", [])
            ),
            remediation_rollbacks=tuple(
                decode_rollback_record(item)
                for item in payload.get("remediation_rollbacks", [])
            ),
            remediation_locks=tuple(
                decode_execution_lock(item)
                for item in payload.get("remediation_locks", [])
            ),
            remediation_replay_tokens=tuple(
                decode_replay_token(item)
                for item in payload.get("remediation_replay_tokens", [])
            ),
            ai_control_acknowledgement=decode_ai_control_acknowledgement(
                payload.get("ai_control_acknowledgement")
            ),
            maintenance_work_items=tuple(
                decode_maintenance_work_record(item)
                for item in payload.get("maintenance_work_items", [])
            ),
            last_cleanup_scan_id=payload.get("last_cleanup_scan_id"),
            entity_successors=tuple(
                decode_entity_successor(item)
                for item in payload.get("entity_successors", [])
            ),
            implementation_groups=tuple(
                decode_implementation_group(item)
                for item in payload.get("implementation_groups", [])
            ),
            incidents=tuple(
                decode_incident(item) for item in payload.get("incidents", [])
            ),
            capability=decode_capability(payload.get("capability")),
            analysis_baseline=decode_analysis_baseline(
                payload.get("analysis_baseline")
            ),
            remediation_baselines=tuple(
                decode_remediation_baseline(item)
                for item in payload.get("remediation_baselines", [])
            ),
        )
    except (KeyError, TypeError, ValueError) as err:
        raise CorruptStoredStateError("HAMIE Store payload failed validation") from err


def _migrate_v1(raw: dict[str, Any]) -> RepositoryState:
    """Validate and migrate the committed RC4-RC6 Store document."""
    compatibility = raw.get("compatibility")
    if not isinstance(compatibility, dict):
        raise CorruptStoredStateError("HAMIE Store compatibility envelope is missing")
    minimum_reader = compatibility.get("minimum_reader")
    maximum_reader = compatibility.get("maximum_reader")
    if not isinstance(minimum_reader, int) or not isinstance(maximum_reader, int):
        raise CorruptStoredStateError("HAMIE Store v1 reader envelope is invalid")
    if not minimum_reader <= 1 <= maximum_reader:
        raise UnsupportedStoredStateError(
            "HAMIE Store v1 compatibility envelope excludes its migration reader"
        )
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise CorruptStoredStateError("HAMIE Store payload is missing")
    if raw.get("checksum") != stable_digest(canonical_json(payload)):
        raise CorruptStoredStateError("HAMIE Store checksum does not match")
    try:
        idempotency = tuple(
            IdempotencyRecord(
                token=item["token"],
                command=item["command"],
                finding_id=item["finding_id"],
                resulting_revision=item["resulting_revision"],
            )
            for item in payload.get("idempotency", [])
        )
        return RepositoryState(
            generation=payload["generation"],
            findings=tuple(
                decode_finding(item) for item in payload.get("findings", [])
            ),
            reviews=tuple(decode_review(item) for item in payload.get("reviews", [])),
            evaluations=tuple(
                decode_evaluation(item) for item in payload.get("evaluations", [])
            ),
            idempotency=idempotency,
            projection_revision=payload.get("projection_revision", 0),
            migration_history=(
                *tuple(payload.get("migration_history", [])),
                "1->2",
                "2->3",
                "3->4",
                "4->5",
                "5->6",
                "6->7",
                "7->8",
                "8->9",
            ),
        )
    except (KeyError, TypeError, ValueError) as err:
        raise CorruptStoredStateError("HAMIE Store v1 migration failed") from err


def _migrate_v0(raw: dict[str, Any]) -> RepositoryState:
    """Migrate the only pre-v1 development fixture after bounded preflight."""
    if len(canonical_json(raw).encode()) > MAX_MIGRATION_CHECKPOINT_BYTES:
        raise CorruptStoredStateError(
            "legacy HAMIE Store document exceeds migration bound"
        )
    allowed = {"schema_version", "generation", "findings", "reviews"}
    if not set(raw) <= allowed:
        raise CorruptStoredStateError("legacy HAMIE Store document has unknown fields")
    try:
        return RepositoryState(
            generation=raw.get("generation", 0),
            findings=tuple(decode_finding(item) for item in raw.get("findings", [])),
            reviews=tuple(decode_review(item) for item in raw.get("reviews", [])),
            migration_history=(
                "0->1",
                "1->2",
                "2->3",
                "3->4",
                "4->5",
                "5->6",
                "6->7",
                "7->8",
                "8->9",
            ),
        )
    except (TypeError, ValueError) as err:
        raise CorruptStoredStateError("legacy HAMIE Store preflight failed") from err


def _cascaded_history(
    raw: dict[str, Any], state: RepositoryState, own_step: str
) -> tuple[str, ...]:
    """Insert ``own_step`` before any history a deeper recursive migration added.

    ``decode_document`` may recurse through further ``_migrate_vN`` steps
    (e.g. v2 -> v3 -> v4) before returning. Those deeper steps run, and
    append their own labels, *after* this function's caller has already
    upgraded the schema version -- so naively appending ``own_step`` last
    would record migrations out of chronological order.
    """
    original = tuple((raw.get("payload") or {}).get("migration_history", []))
    later = state.migration_history[len(original) :]
    return (*original, own_step, *later)


def _migrate_v2(raw: dict[str, Any]) -> RepositoryState:
    """Add persisted group-source bindings while preserving v2 records."""
    upgraded = deepcopy(raw)
    upgraded["schema_version"] = 3
    upgraded["schema_minor_version"] = 0
    upgraded["compatibility"] = {"minimum_reader": 3, "maximum_reader": 3}
    state = decode_document(upgraded)
    return replace(state, migration_history=_cascaded_history(raw, state, "2->3"))


def _migrate_v3(raw: dict[str, Any]) -> RepositoryState:
    """Add canonical recommendation records while preserving v3 records."""
    upgraded = deepcopy(raw)
    upgraded["schema_version"] = 4
    upgraded["schema_minor_version"] = 0
    upgraded["compatibility"] = {"minimum_reader": 4, "maximum_reader": 4}
    state = decode_document(upgraded)
    return replace(state, migration_history=_cascaded_history(raw, state, "3->4"))


def _migrate_v4(raw: dict[str, Any]) -> RepositoryState:
    """Add remediation plan/approval/execution records while preserving v4 records."""
    upgraded = deepcopy(raw)
    upgraded["schema_version"] = 5
    upgraded["schema_minor_version"] = 0
    upgraded["compatibility"] = {"minimum_reader": 5, "maximum_reader": 5}
    state = decode_document(upgraded)
    return replace(state, migration_history=_cascaded_history(raw, state, "4->5"))


def _migrate_v5(raw: dict[str, Any]) -> RepositoryState:
    """Add the AI Control acknowledgement record while preserving v5 records.

    Existing users default safely: an absent ``ai_control_acknowledgement``
    decodes to ``None`` (see ``decode_ai_control_acknowledgement``), and
    ``effective_ai_mode`` (``domain/ai_control.py``) treats a missing
    acknowledgement as "AI Control not yet unlocked" regardless of what
    ``ai_operating_mode`` a stored config entry might already have set --
    no migrated installation can silently gain AI-Control-tier automatic
    execution power (mission Part 30).
    """
    upgraded = deepcopy(raw)
    upgraded["schema_version"] = 6
    upgraded["schema_minor_version"] = 0
    upgraded["compatibility"] = {"minimum_reader": 6, "maximum_reader": 6}
    state = decode_document(upgraded)
    return replace(state, migration_history=_cascaded_history(raw, state, "5->6"))


def _migrate_v6(raw: dict[str, Any]) -> RepositoryState:
    """Add durable maintenance work item records while preserving v6 records.

    Existing users default safely: an absent ``maintenance_work_items``
    list decodes to an empty tuple -- exactly what a real installation
    that has never run Clean Up under this release has anyway.
    """
    upgraded = deepcopy(raw)
    upgraded["schema_version"] = 7
    upgraded["schema_minor_version"] = 0
    upgraded["compatibility"] = {"minimum_reader": 7, "maximum_reader": 7}
    state = decode_document(upgraded)
    return replace(state, migration_history=_cascaded_history(raw, state, "6->7"))


def _migrate_v7(raw: dict[str, Any]) -> RepositoryState:
    """Add durable entity-successor/implementation-group records while
    preserving v7 records.

    Existing users default safely: absent ``entity_successors``/
    ``implementation_groups`` lists decode to empty tuples -- exactly
    what a real installation that has never had a successor or
    implementation-group relationship recorded under this release has
    anyway. No prior conclusion is invented; the knowledge layer starts
    empty and is only ever populated by an explicit importer or
    analyzer (mission Parts 8/9/44/45).
    """
    upgraded = deepcopy(raw)
    upgraded["schema_version"] = 8
    upgraded["schema_minor_version"] = 0
    upgraded["compatibility"] = {"minimum_reader": 8, "maximum_reader": 8}
    state = decode_document(upgraded)
    return replace(state, migration_history=_cascaded_history(raw, state, "7->8"))


def _migrate_v8(raw: dict[str, Any]) -> RepositoryState:
    """Add durable incidents while preserving every v8 record.

    Existing installations start with no incident records.  The next
    successful read-only scan derives them from current findings; migration
    never invents conclusions from historical data.
    """
    upgraded = deepcopy(raw)
    upgraded["schema_version"] = 9
    upgraded["schema_minor_version"] = 0
    upgraded["compatibility"] = {"minimum_reader": 9, "maximum_reader": 9}
    state = decode_document(upgraded)
    return replace(state, migration_history=_cascaded_history(raw, state, "8->9"))


def _migrate_v9(raw: dict[str, Any]) -> RepositoryState:
    """Add the durable provider-capability record, preserving every v9 record.

    An existing installation starts with no capability evidence, which is the
    honest state: nothing has been probed against this configuration yet, and
    migration must never manufacture a verdict for a model it never tested.
    The gate reads that absence as "not permitted until probed", so the first
    bulk analysis after upgrading asks for a probe rather than assuming the
    previous behaviour was fine.
    """
    upgraded = deepcopy(raw)
    upgraded["schema_version"] = 10
    upgraded["schema_minor_version"] = 0
    upgraded["compatibility"] = {"minimum_reader": 10, "maximum_reader": 10}
    upgraded.setdefault("payload", {}).setdefault("capability", None)
    checksum_payload = upgraded["payload"]
    upgraded["checksum"] = stable_digest(canonical_json(checksum_payload))
    state = decode_document(upgraded)
    return replace(state, migration_history=_cascaded_history(raw, state, "9->10"))


class InMemoryRepository:
    """Dependency-free repository adapter for tests and deterministic composition."""

    def __init__(self, state: RepositoryState | None = None) -> None:
        self.state = state or RepositoryState()
        self.commits = 0

    async def async_load(self) -> RepositoryState:
        """Return immutable current state."""
        return self.state

    async def async_commit(
        self, state: RepositoryState, *, expected_generation: int
    ) -> None:
        """Commit with optimistic generation validation."""
        if self.state.generation != expected_generation:
            raise GenerationConflictError("repository generation changed")
        if state.generation != expected_generation + 1:
            raise ValueError("committed state must advance generation exactly once")
        self.state = state
        self.commits += 1

    async def async_remove(self) -> None:
        """Reset the in-memory adapter to empty state."""
        self.state = RepositoryState()

    async def async_quarantine_corrupt_document(
        self, *, reason: str, quarantined_at: str
    ) -> QuarantineRecord | None:
        """Interface parity with the Store adapter; resets to empty state."""
        self.state = RepositoryState()
        return QuarantineRecord(
            quarantine_key=f"{STORAGE_KEY}.corrupt.{quarantined_at}",
            reason=reason,
            quarantined_at=quarantined_at,
            schema_version=None,
            document_bytes=0,
        )


class HomeAssistantStoreRepository:
    """One-document HA Store adapter; no multi-document atomicity is claimed."""

    def __init__(self, hass: Any) -> None:
        from homeassistant.helpers.storage import Store

        self._hass = hass
        self._store = Store(
            hass,
            STORE_FORMAT_VERSION,
            STORAGE_KEY,
            atomic_writes=True,
        )
        self._checkpoint: dict[str, Any] | None = None
        self._commit_lock = asyncio.Lock()
        self._document_generation = 0
        self._document_size = encoded_document_size(RepositoryState())

    async def async_load(self) -> RepositoryState:
        """Load, preflight, recover, and migrate the Store document."""
        raw = await self._store.async_load()
        if raw is None:
            return RepositoryState()
        state = decode_document(raw)
        self._document_generation = state.generation
        self._document_size = len(canonical_json(raw).encode("utf-8"))
        if (
            isinstance(raw, dict)
            and isinstance(raw.get("schema_version"), int)
            and raw["schema_version"] < STORAGE_SCHEMA_VERSION
        ):
            self._checkpoint = deepcopy(raw)
        return state

    def document_size(self, state: RepositoryState) -> int:
        """Return the cached serialized size from the normal Store I/O path."""
        if state.generation == self._document_generation:
            return self._document_size
        return encoded_document_size(state)

    async def async_commit(
        self, state: RepositoryState, *, expected_generation: int
    ) -> None:
        """Atomically replace the individual Store document."""
        async with self._commit_lock:
            current = await self.async_load()
            if current.generation != expected_generation:
                raise GenerationConflictError("repository generation changed")
            if state.generation != expected_generation + 1:
                raise ValueError("committed state must advance generation exactly once")
            checkpoint = self._checkpoint
            self._checkpoint = None
            journal = (
                {
                    "from_schema": checkpoint["schema_version"],
                    "to_schema": STORAGE_SCHEMA_VERSION,
                    "phase": "complete",
                }
                if checkpoint is not None
                else None
            )
            document = encode_document(
                state,
                checkpoint=checkpoint,
                migration_journal=journal,
            )
            await self._store.async_save(document)
            self._document_generation = state.generation
            self._document_size = len(canonical_json(document).encode("utf-8"))

    async def async_remove(self) -> None:
        """Remove HAMIE's single Store document during config-entry removal."""
        async with self._commit_lock:
            await self._store.async_remove()
            self._checkpoint = None
            self._document_generation = 0
            self._document_size = encoded_document_size(RepositoryState())

    async def async_quarantine_corrupt_document(
        self, *, reason: str, quarantined_at: str
    ) -> QuarantineRecord | None:
        """Preserve an unreadable document, then clear it so HAMIE can rebuild.

        HAMIE's persisted state is *derived* data: every finding is
        regenerated by the next scan from Home Assistant itself. When the
        document cannot be decoded there is nothing to migrate and nothing
        irreplaceable to lose, but the corrupt bytes are still the only
        forensic record of how it broke -- so they are copied to their own
        Store key rather than discarded. Recovery therefore never requires
        hand-editing .storage.
        """
        from homeassistant.helpers.storage import Store

        async with self._commit_lock:
            raw = await self._store.async_load()
            if raw is None:
                return None
            quarantine_key = f"{STORAGE_KEY}.corrupt.{quarantined_at}"
            schema_version = (
                raw.get("schema_version") if isinstance(raw, dict) else None
            )
            await Store(
                self._hass,
                STORE_FORMAT_VERSION,
                quarantine_key,
                atomic_writes=True,
            ).async_save(
                {
                    "quarantined_at": quarantined_at,
                    "reason": reason,
                    "schema_version": schema_version,
                    "document": raw,
                }
            )
            await self._store.async_remove()
            self._checkpoint = None
            self._document_generation = 0
            self._document_size = encoded_document_size(RepositoryState())
            return QuarantineRecord(
                quarantine_key=quarantine_key,
                reason=reason,
                quarantined_at=quarantined_at,
                schema_version=(
                    schema_version if isinstance(schema_version, int) else None
                ),
                document_bytes=len(canonical_json(raw).encode("utf-8")),
            )
