"""Supported Home Assistant operational source adapter."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..analysis.analyzers.unavailable_entities import CAPABILITY_ID
from ..application.ports import Clock, EntityCapture, EntityRecord
from ..domain.common import stable_digest
from ..domain.evaluations import SourceCapture
from .installation_topology import InstallationTopology, async_build_installation_topology
from .source_definition_index import SourceDefinitionIndex, async_read_config_source_files

SOURCE_ID = "home_assistant"
SOURCE_MAX_AGE_SECONDS = 30
STATE_SCOPE = "entity_state"
REGISTRY_SCOPE = "entity_registry"
CAPTURE_YIELD_INTERVAL = 256
MAX_SKIPPED_ENTITY_WARNINGS = 20
# Production defect fix: the state value synthesized for a registry
# entry that has no corresponding live ``State`` object (see
# ``_records``' "registry-only" pass below). "unavailable" -- rather
# than a made-up sentinel string -- is deliberate: it is Home
# Assistant's own real vocabulary for "this entity has no working
# live value right now", already the exact string every downstream
# consumer (``UnavailableEntityAnalyzer``,
# ``domain/duplicate_classifier.py::DuplicateGroupMember.available``)
# already knows how to interpret correctly, so a registry-only entity
# is honestly conservative (available=False) rather than falling
# through as some third, unhandled value no rule anywhere accounts for.
REGISTRY_ONLY_STATE = "unavailable"

_LOGGER = logging.getLogger(__name__)


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


class HomeAssistantOperationalSource:
    """Short, read-only capture through supported Home Assistant APIs."""

    def __init__(
        self,
        hass: Any,
        *,
        clock: Clock | None = None,
        restored_detector: Callable[[Any], bool | None] | None = None,
    ) -> None:
        self._hass = hass
        self._clock = clock or _SystemClock()
        self._restored_detector = restored_detector or self._is_restored

    async def async_capture_entities(self) -> EntityCapture:
        """Capture states twice and mark changes during capture as inconsistent.

        Production defect fix: both raw snapshots are now taken back to
        back, with no ``await`` between them, before any hashing work
        happens. Previously the expensive, cooperatively-yielding
        revision hash for the *first* snapshot (``_states_revision``,
        which yields every 256 entities) ran *before* the second
        snapshot was captured -- turning what should be a
        near-instantaneous double-read into two reads separated by
        however long it takes to hash every entity in the installation.
        At real scale (6,500+ entities) that window is long enough that
        some entity updating somewhere in the house during it is close
        to certain, silently degrading *every* scan to zero coverage
        (``consistent=False`` -> the supervisor's early-return path)
        even though nothing was actually wrong -- confirmed as the root
        cause of "Health score: unknown" / findings never refreshing
        against a real ~6,500-entity installation. `hass.states.async_all()`
        and the registry snapshot are both synchronous, non-blocking
        calls; capturing both "first" and "second" pairs before the
        first `await` means nothing else can run between them in
        Python's single-threaded event loop, so the check now only ever
        fails for a genuine concurrent mutation, never for ordinary
        background house activity racing the hash computation itself.
        """
        from homeassistant.helpers import entity_registry as er

        started = self._clock.now()
        get_registry = getattr(er, "async_get", None)
        registry_supported = callable(get_registry)
        registry_get: Callable[[Any], Any] | None = (
            get_registry if registry_supported else None
        )
        first_states = tuple(self._hass.states.async_all())
        first_registry = (
            self._registry_snapshot(registry_get(self._hass))
            if registry_get is not None
            else {}
        )
        second_states = tuple(self._hass.states.async_all())
        second_registry = (
            self._registry_snapshot(registry_get(self._hass))
            if registry_get is not None
            else {}
        )
        first_revision = await self._states_revision(first_states)
        first_registry_revision = await self._registry_revision(first_registry)
        second_revision = await self._states_revision(second_states)
        second_registry_revision = await self._registry_revision(second_registry)
        states_consistent = first_revision == second_revision
        registry_consistent = (
            not registry_supported
            or first_registry_revision == second_registry_revision
        )
        consistent = states_consistent and registry_consistent
        warnings = []
        if not states_consistent:
            warnings.append("entity states changed during capture")
        if not registry_consistent:
            warnings.append("entity registry changed during capture")
        if not registry_supported:
            warnings.append("entity registry source surface is unavailable")
        revision = stable_digest(second_revision, second_registry_revision)
        # Built exactly once per capture (never per entity -- matters at
        # real scale, 8,000+ entities) and handed down into `_records`,
        # which queries it once per automation/script/scene entity. See
        # `_build_source_definition_index`'s own docstring for how a
        # read/parse failure here degrades honestly instead of aborting
        # the whole scan.
        source_index, source_definition_warnings = (
            await self._build_source_definition_index()
        )
        warnings.extend(source_definition_warnings)
        records, skip_warnings, skipped_subjects = await self._records(
            second_states, second_registry, source_index
        )
        warnings.extend(skip_warnings)
        # Additive (mission Part 2, Analyzer 2): built once per capture,
        # exactly the same defensive-degrade-to-None pattern as
        # source_index above -- a failure here never aborts the scan,
        # it only means removed-integration-orphan detection stays
        # "not evaluated" this cycle (see InstallationTopology's own
        # module docstring).
        installation_topology = await self._build_installation_topology()
        if installation_topology is None:
            warnings.append(
                "installation topology (config_entries/custom_components) "
                "could not be read this scan"
            )
        ended = self._clock.now()
        metadata = SourceCapture(
            source_id=SOURCE_ID,
            capability_id=CAPABILITY_ID,
            revision=revision,
            capture_started_at=started,
            capture_ended_at=ended,
            observed_at=ended,
            max_age_seconds=SOURCE_MAX_AGE_SECONDS,
            requested_scopes=(STATE_SCOPE, REGISTRY_SCOPE),
            captured_scopes=(
                (STATE_SCOPE, REGISTRY_SCOPE) if registry_supported else (STATE_SCOPE,)
            ),
            missing_scopes=() if registry_supported else (REGISTRY_SCOPE,),
            warnings=tuple(warnings),
            consistent=consistent,
        )
        return EntityCapture(
            metadata=metadata,
            entities=records,
            source_index=source_index,
            installation_topology=installation_topology,
            # Complete and uncapped, unlike the bounded warning prose above.
            skipped_subjects=skipped_subjects,
        )

    @staticmethod
    def _registry_created_at(registry_entry: Any | None) -> str | None:
        """Return the registry entry's creation time as an ISO 8601 string.

        Defensive against both a real ``datetime`` (the modern registry
        entry's actual type) and an already-serialized string (older
        Home Assistant versions, or a test double) -- never raises for
        either shape, and returns ``None`` rather than guessing when
        the attribute is absent entirely (pre-``created_at`` registry
        schema versions).
        """
        if registry_entry is None:
            return None
        value = getattr(registry_entry, "created_at", None)
        if value is None:
            return None
        isoformat = getattr(value, "isoformat", None)
        return _text(isoformat() if callable(isoformat) else value)

    @staticmethod
    def _registry_timestamp(value: object) -> datetime | None:
        """Return a registry field's real value as a tz-aware ``datetime``.

        Defensive against both a real ``datetime`` (the modern registry
        entry's actual type) and an already-serialized ISO 8601 string
        (older Home Assistant versions, or a test double), mirroring
        ``_registry_created_at``'s own defensiveness -- but returning the
        parsed ``datetime`` itself, since this is used for
        ``EntityRecord.last_changed``/``last_updated`` (which require a
        real tz-aware instant), not the ISO string ``_registry_created_at``
        returns for the separate ``created_at`` display field. A naive
        (tz-less) value is treated as UTC rather than rejected -- the
        registry itself is always UTC internally. Returns ``None`` for
        anything unparseable rather than guessing.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        return None

    def _record(
        self,
        state: Any | None,
        registry_entry: Any | None,
        source_index: SourceDefinitionIndex | None,
    ) -> EntityRecord:
        """Build one ``EntityRecord`` from a live state and/or a registry entry.

        ``state`` is ``None`` for a "registry-only" entity -- one that
        exists in the entity registry but has no corresponding object
        in ``hass.states.async_all()`` right now (most commonly because
        ``disabled_by`` is set, which means Home Assistant never sets
        the entity up at all; occasionally because the entity's
        platform/config entry failed to load). ``registry_entry`` must
        not also be ``None`` in that case -- ``_records`` only ever
        calls this with ``state=None`` while iterating real registry
        entries. See ``_records``' own docstring for why this path
        exists at all (production defect fix: registry-only entities
        were previously invisible to every analyzer, including
        ``DuplicateMigrationAnalyzer``, which specifically needs to see
        a disabled "migration leftover" sibling to classify its group
        correctly).
        """
        if state is None and registry_entry is None:
            raise ValueError("_record requires a live state or a registry entry")
        entity_id = state.entity_id if state is not None else registry_entry.entity_id
        domain = entity_id.partition(".")[0]
        attributes = state.attributes if state is not None else {}
        platform = (
            _text(getattr(registry_entry, "platform", None))
            if registry_entry is not None
            else None
        )
        # `unique_id` is HA's own platform-assigned identity, distinct
        # from `registry_id` below (the registry row's internal `.id`,
        # used elsewhere as this entity's durable subject identity) --
        # for automation/script/scene entities this is exactly the
        # value source_definition_index.py's SourceDefinitionIndex
        # indexes config files by (see that module's docstring).
        unique_id = (
            _text(str(registry_entry.unique_id))
            if registry_entry is not None
            and getattr(registry_entry, "unique_id", None)
            else None
        )
        source_definition_missing = (
            source_index.lookup(
                entity_id=entity_id,
                domain=domain,
                platform=platform,
                unique_id=unique_id,
            ).source_definition_missing
            if source_index is not None
            else None
        )
        # Registry-only fallbacks (state is None): no live State object
        # means no state.last_changed/last_updated to read, so the best
        # honest timestamp is the registry entry's own last-modified (or,
        # failing that, created) instant -- never a fabricated "just
        # now", except as the very last resort when the registry itself
        # carries neither (older HA schema versions, or a test double).
        if state is not None:
            state_value = state.state
            last_changed = state.last_changed
            last_updated = state.last_updated
            restored = self._restored_detector(state)
            friendly_name = _text(attributes.get("friendly_name"))
            device_class = _text(attributes.get("device_class"))
        else:
            state_value = REGISTRY_ONLY_STATE
            fallback_timestamp = (
                self._registry_timestamp(getattr(registry_entry, "modified_at", None))
                or self._registry_timestamp(getattr(registry_entry, "created_at", None))
                or self._clock.now()
            )
            last_changed = fallback_timestamp
            last_updated = fallback_timestamp
            restored = None
            friendly_name = _text(getattr(registry_entry, "name", None)) or _text(
                getattr(registry_entry, "original_name", None)
            )
            device_class = _text(getattr(registry_entry, "device_class", None)) or _text(
                getattr(registry_entry, "original_device_class", None)
            )
        return EntityRecord(
            entity_id=entity_id,
            state=state_value,
            last_changed=last_changed,
            last_updated=last_updated,
            registry_id=(
                _text(str(registry_entry.id))
                if registry_entry is not None and getattr(registry_entry, "id", None)
                else None
            ),
            unique_id=unique_id,
            source_definition_missing=source_definition_missing,
            device_id=(
                _text(str(registry_entry.device_id))
                if registry_entry is not None
                and getattr(registry_entry, "device_id", None)
                else None
            ),
            config_entry_id=(
                _text(str(registry_entry.config_entry_id))
                if registry_entry is not None
                and getattr(registry_entry, "config_entry_id", None)
                else None
            ),
            disabled=(
                getattr(registry_entry, "disabled_by", None) is not None
                if registry_entry is not None
                else None
            ),
            restored=restored,
            domain=domain,
            friendly_name=friendly_name,
            device_class=device_class,
            platform=platform,
            entity_category=(
                _text(
                    getattr(
                        getattr(registry_entry, "entity_category", None),
                        "value",
                        getattr(registry_entry, "entity_category", None),
                    )
                )
                if registry_entry is not None
                else None
            ),
            area_id=(
                _text(registry_entry.area_id)
                if registry_entry is not None
                and getattr(registry_entry, "area_id", None)
                else None
            ),
            created_at=self._registry_created_at(registry_entry),
        )

    @staticmethod
    async def _states_revision(states: tuple[Any, ...]) -> str:
        revisions = []
        for index, state in enumerate(
            sorted(states, key=lambda item: item.entity_id), start=1
        ):
            revisions.append(
                stable_digest(
                    state.entity_id,
                    state.state,
                    state.last_changed.isoformat(),
                    state.last_updated.isoformat(),
                )
            )
            if index % CAPTURE_YIELD_INTERVAL == 0:
                await asyncio.sleep(0)
        return stable_digest(*revisions)

    @staticmethod
    def _registry_snapshot(registry: Any) -> dict[str, Any]:
        entries = getattr(registry, "entities", None)
        if entries is None:
            return {}
        return {entry.entity_id: entry for entry in tuple(entries.values())}

    @staticmethod
    async def _registry_revision(entries: dict[str, Any]) -> str:
        revisions = []
        for index, entry in enumerate(
            sorted(entries.values(), key=lambda item: item.entity_id), start=1
        ):
            revisions.append(
                stable_digest(
                    entry.entity_id,
                    getattr(entry, "id", None),
                    getattr(entry, "device_id", None),
                    getattr(entry, "config_entry_id", None),
                    getattr(entry, "disabled_by", None),
                    getattr(entry, "platform", None),
                    getattr(entry, "modified_at", None),
                )
            )
            if index % CAPTURE_YIELD_INTERVAL == 0:
                await asyncio.sleep(0)
        return stable_digest(*revisions)

    async def _records(
        self,
        states: tuple[Any, ...],
        registry: dict[str, Any],
        source_index: SourceDefinitionIndex | None,
    ) -> tuple[tuple[EntityRecord, ...], tuple[str, ...], frozenset[str]]:
        """Capture every valid entity; never let one malformed entity abort the scan.

        Home Assistant's own core `validate_state()` only rejects a state
        longer than 255 characters -- it does not require non-empty or
        normalized (no surrounding whitespace) text. A real, large
        installation can contain an entity (often from a third-party
        integration Home Assistant itself has not vetted) whose live
        state genuinely violates HAMIE's own stricter internal
        `EntityRecord` invariant. That is real, surfaced evidence about
        one entity, not a reason to fail the entire scan for every other
        entity -- see docs/DEVELOPMENT.md and the reported HA 2026.7
        primary-system defect this fixes.

        `source_index` is built exactly once per capture by
        `async_capture_entities` (see `_build_source_definition_index`)
        and only ever queried here, once per entity -- never re-parsed.

        Production defect fix: previously this method only ever iterated
        `states` (`hass.states.async_all()`), so any registry entity with
        no corresponding live `State` object -- overwhelmingly entities
        with `disabled_by` set, since Home Assistant never sets up a
        disabled entity's platform at all -- was silently absent from
        every `EntityRecord` this source ever produced, for every
        analyzer, permanently. That is not a niche gap: a disabled
        sibling next to a still-active one is *exactly* the textbook
        "migration leftover" shape `domain/duplicate_classifier.py`
        exists to recognize (see its own module docstring), so this bug
        made `DuplicateMigrationAnalyzer` systematically blind to the
        single case it is most valuable for -- confirmed against a real
        production audit: every `device_tracker` and all but one `button`
        historical duplicate-suffix group involved a fully disabled
        member and was missing entirely from a live HAMIE scan's
        `hamie.duplicate_migration` findings. Domains with a high
        disabled-entity rate (`device_tracker`, `button`, but also
        `sensor`/`binary_sensor`/`switch` to a lesser degree) were simply
        the domains this silent gap hit hardest -- the bug itself was
        never domain-specific, and the fix below is not either: a second
        pass below covers every registry entry not already seen among
        `states`, regardless of domain, so a registry-only entity now
        always becomes a real (conservatively-modeled) `EntityRecord`
        instead of vanishing from HAMIE's view entirely. See `_record`'s
        own docstring for exactly how such an entity is modeled
        (`state="unavailable"`, no live timestamps to read).
        """
        records = []
        skipped: list[str] = []
        seen_entity_ids: set[str] = set()
        for index, state in enumerate(states, start=1):
            seen_entity_ids.add(state.entity_id)
            try:
                records.append(
                    self._record(state, registry.get(state.entity_id), source_index)
                )
            except (ValueError, TypeError) as err:
                skipped.append(state.entity_id)
                _LOGGER.debug(
                    "HAMIE skipped one entity with an invalid captured state: "
                    "entity_id=%s error_type=%s",
                    state.entity_id,
                    type(err).__name__,
                )
            if index % CAPTURE_YIELD_INTERVAL == 0:
                await asyncio.sleep(0)

        # Registry-only pass (the production defect fix): every registry
        # entry not already captured above via a live state -- same
        # error handling, same yield cadence, same "one bad entity never
        # aborts the scan" discipline as the loop above.
        registry_only_entries = tuple(
            entry
            for entity_id, entry in registry.items()
            if entity_id not in seen_entity_ids
        )
        for index, entry in enumerate(registry_only_entries, start=1):
            entity_id = getattr(entry, "entity_id", None) or "<unknown>"
            try:
                records.append(self._record(None, entry, source_index))
            except (ValueError, TypeError) as err:
                skipped.append(entity_id)
                _LOGGER.debug(
                    "HAMIE skipped one registry-only entity with invalid "
                    "registry data: entity_id=%s error_type=%s",
                    entity_id,
                    type(err).__name__,
                )
            if index % CAPTURE_YIELD_INTERVAL == 0:
                await asyncio.sleep(0)

        warnings = tuple(
            f"skipped invalid entity state: {entity_id}"
            for entity_id in skipped[:MAX_SKIPPED_ENTITY_WARNINGS]
        )
        if len(skipped) > MAX_SKIPPED_ENTITY_WARNINGS:
            warnings = (
                *warnings,
                f"skipped {len(skipped)} entities with an invalid captured state "
                f"in total ({MAX_SKIPPED_ENTITY_WARNINGS} listed above)",
            )
        if skipped:
            _LOGGER.warning(
                "HAMIE scan skipped %d of %d entities with an invalid captured "
                "state; every other entity was captured normally",
                len(skipped),
                len(states) + len(registry_only_entries),
            )
        return tuple(records), warnings, frozenset(skipped)

    async def _build_source_definition_index(
        self,
    ) -> tuple[SourceDefinitionIndex | None, tuple[str, ...]]:
        """Build the automation/script/scene source-definition index once per capture.

        Reuses `source_definition_index.py`'s already-validated
        `async_read_config_source_files`/`SourceDefinitionIndex.build`
        pair unchanged -- neither this method nor any caller re-derives
        or duplicates that parsing/matching logic. `async_read_config_
        source_files` already reads `hass.config.path()` (Home
        Assistant's own API for the real config directory root, not a
        hardcoded `/config`) and already offloads every blocking file
        read through `hass.async_add_executor_job`, matching
        `infrastructure/recorder_source.py`'s executor-offload idiom for
        blocking calls.

        A failure anywhere in this step (missing/unreadable config
        directory, a permission error, an installation with more
        package files than `source_definition_index.MAX_PACKAGE_FILES`)
        degrades to "no index" for this capture rather than aborting the
        whole scan: every entity's `source_definition_missing` then
        simply stays `None` ("not evaluated"), the exact same honest
        default this field always had before it was ever wired up here
        -- never a crash, and never a fabricated True/False. A parse
        failure confined to one file, in contrast, does not reach here
        at all -- `SourceDefinitionIndex` itself already degrades that
        file's domain to `SOURCE_UNAVAILABLE` per lookup (see its own
        docstring), which only ever weakens one entity's answer to
        `None`, not the whole capture's.
        """
        try:
            files = await async_read_config_source_files(self._hass)
        except Exception as err:  # noqa: BLE001 -- see docstring
            _LOGGER.warning(
                "HAMIE could not read the live config tree for source-"
                "definition evidence this scan; every automation/script/"
                "scene entity's source_definition_missing stays "
                "unevaluated: error_type=%s",
                type(err).__name__,
            )
            return None, (
                "source-definition config files could not be read this scan",
            )
        try:
            index = SourceDefinitionIndex.build(files)
        except ValueError as err:
            _LOGGER.warning(
                "HAMIE could not build the source-definition index this "
                "scan: %s",
                err,
            )
            return None, (f"source-definition index build failed: {err}",)
        return index, ()

    async def _build_installation_topology(self) -> InstallationTopology | None:
        """Build the config_entries/custom_components snapshot once per
        capture. Reuses ``installation_topology.py``'s already-defensive
        readers unchanged -- see that module's docstring for exactly how
        a read failure degrades to ``None`` (never a fabricated empty
        answer) rather than aborting the scan.
        """
        try:
            return await async_build_installation_topology(self._hass)
        except Exception as err:  # noqa: BLE001 -- see docstring
            _LOGGER.warning(
                "HAMIE could not build installation topology this scan: "
                "error_type=%s",
                type(err).__name__,
            )
            return None

    @staticmethod
    def _is_restored(state: Any) -> bool | None:
        try:
            from homeassistant.const import ATTR_RESTORED
        except ImportError:
            return None
        return state.attributes.get(ATTR_RESTORED) is True
