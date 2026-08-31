"""Ports and immutable source values used by the application layer."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..domain.common import require_non_empty, require_utc, stable_digest
from ..domain.dependency_references import EntityReferenceIndex
from ..domain.evaluations import SourceCapture


@dataclass(frozen=True, slots=True)
class EntityRecord:
    """Bounded authoritative entity-state capture."""

    entity_id: str
    state: str
    last_changed: datetime
    last_updated: datetime
    registry_id: str | None
    device_id: str | None
    config_entry_id: str | None
    disabled: bool | None
    restored: bool | None
    domain: str
    friendly_name: str | None = None
    device_class: str | None = None
    platform: str | None = None
    entity_category: str | None = None
    # Additive (default None): whether this entity's backing YAML/UI
    # definition (automation/script/scene config) is known to be absent
    # from live configuration. None means "not evaluated" -- distinct
    # from False ("evaluated, definition present") -- because most
    # domains never have this checked at all (only automation/script/
    # scene ever get a real answer). Populated live by
    # infrastructure/ha_source.py::HomeAssistantOperationalSource, which
    # builds infrastructure/source_definition_index.py's
    # SourceDefinitionIndex once per capture from the real config tree
    # (hass.config.path()) and looks each entity up against it -- see
    # that source's docstring for the honest-degradation rules (a parse
    # failure anywhere in a domain's config files degrades that
    # domain's not-found answers to "not evaluated" rather than ever
    # guessing True).
    source_definition_missing: bool | None = None
    # Additive (default None): registry area assignment and creation
    # timestamp -- needed by the duplicate/migration-leftover group
    # classifier (domain/duplicate_classifier.py, mission Part 3c) to
    # tell genuinely distinct co-located entities apart from true
    # migration leftovers, and to order suffix siblings by real
    # creation time rather than trusting the suffix number itself.
    # ``created_at`` is an ISO 8601 string (comparable lexicographically)
    # matching the registry's own field type, not a datetime, to avoid
    # forcing every caller that does not need it to also satisfy this
    # dataclass's tz-aware datetime invariants.
    area_id: str | None = None
    created_at: str | None = None
    # Additive (default None): the entity registry entry's own real
    # ``unique_id`` -- Home Assistant's platform-assigned identity used
    # to cross-reference an automation/script/scene against its backing
    # config file (see infrastructure/source_definition_index.py's
    # module docstring for exactly how each domain's unique_id maps
    # onto its YAML identity). Deliberately a separate field from
    # ``registry_id`` (the registry row's own internal ``.id``, used
    # elsewhere as this entity's durable subject identity) -- the two
    # are different HA concepts and conflating them was a pre-existing
    # bug this field's introduction fixes (see
    # analysis/duplicate_group_scan.py).
    unique_id: str | None = None
    record_revision: str = ""

    def __post_init__(self) -> None:
        require_non_empty(self.entity_id, "entity_id")
        require_non_empty(self.state, "state")
        require_non_empty(self.domain, "domain")
        if self.entity_id.partition(".")[0] != self.domain:
            raise ValueError("domain must match entity_id")
        changed = require_utc(self.last_changed, "last_changed")
        updated = require_utc(self.last_updated, "last_updated")
        if changed > updated:
            raise ValueError("last_changed cannot follow last_updated")
        object.__setattr__(self, "last_changed", changed)
        object.__setattr__(self, "last_updated", updated)
        revision = self.record_revision or stable_digest(
            self.entity_id,
            self.state,
            changed.isoformat(),
            updated.isoformat(),
            self.registry_id,
            self.device_id,
            self.config_entry_id,
            self.disabled,
            self.restored,
            self.friendly_name,
            self.device_class,
            self.platform,
            self.entity_category,
            self.source_definition_missing,
            self.area_id,
            self.created_at,
            self.unique_id,
        )
        object.__setattr__(self, "record_revision", revision)


@dataclass(frozen=True, slots=True)
class EntityCapture:
    """One source capture plus its normalized entity records.

    ``source_index``/``installation_topology`` (mission Part 2) are
    additive, default-``None`` whole-capture context a small number of
    whole-collection analyzers need alongside the per-entity
    ``entities`` tuple -- built fresh once per capture by
    ``infrastructure/ha_source.py`` (mirroring how ``source_index`` was
    already built once per capture there before this pass, just not
    previously threaded onto ``EntityCapture`` itself -- see
    ``analysis/whole_collection_supervisor.py`` for why a *fresh*
    per-capture value threaded at call time is required here, unlike
    ``WholeCollectionSupervisorOptions.source_index``'s static,
    construction-time fallback). Typed as ``object`` rather than the
    concrete ``infrastructure.source_definition_index.SourceDefinitionIndex``/
    ``infrastructure.installation_topology.InstallationTopology`` types
    to avoid this application-layer module importing the infrastructure
    layer -- exactly the same layering choice
    ``analysis/whole_collection_supervisor.py``'s own
    ``WholeCollectionAnalyzer`` Protocol already made for its
    ``source_index`` parameter.
    """

    metadata: SourceCapture
    entities: tuple[EntityRecord, ...]
    source_index: object | None = None
    installation_topology: object | None = None
    #: Entity IDs the capture positively FAILED to normalize this scan, kept
    #: complete and machine-readable.
    #:
    #: `metadata.warnings` already carried these, but only as prose and only
    #: the first MAX_SKIPPED_ENTITY_WARNINGS of them -- past that cap a run
    #: reported a count and nothing else. Prose is presentation; an analyzer
    #: that wants to say "this subject is absent" needs evidence, and
    #: recovering evidence by parsing log strings is how a scanner starts
    #: lying. Absence from `entities` alone cannot distinguish "not present in
    #: the installation" from "present but unreadable this scan", which is
    #: exactly the distinction a negative conclusion depends on.
    skipped_subjects: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        entity_ids = [item.entity_id for item in self.entities]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("entity capture cannot contain duplicate entity IDs")
        object.__setattr__(
            self,
            "entities",
            tuple(sorted(self.entities, key=lambda item: item.entity_id)),
        )


class OperationalSourcePort(Protocol):
    """Authoritative, read-only Home Assistant source boundary."""

    async def async_capture_entities(self) -> EntityCapture:
        """Capture supported entity state and registry metadata."""


class Clock(Protocol):
    """Injectable UTC clock."""

    def now(self) -> datetime:
        """Return a timezone-aware UTC instant."""


class ReferenceIndexPort(Protocol):
    """Optional, additive dependency/reference evidence source (mission
    Part 1.4).

    Implemented today by
    ``infrastructure.dependency_source.HomeAssistantReferenceIndexSource``
    -- a thin adapter over the already-real, already-tested
    ``capture_all_reference_sources``/``build_reference_index`` pair
    that, before this wiring pass, was only ever reachable from the
    separate, on-demand ``application/cleanup_coordinator.py`` flow,
    never from the automatic scan pipeline
    (``application/scan_coordinator.py``). Supplying this port to
    ``ScanCoordinator`` is what actually closes that gap; omitting it
    preserves the exact prior behavior (every analyzer runs with
    ``reference_index=None``, exactly as before this pass).
    """

    async def async_capture_reference_index(self) -> EntityReferenceIndex:
        """Capture and index every reference source HAMIE can scan."""


class TemporalEvidenceSourcePort(Protocol):
    """Optional, additive recorder/statistics evidence source (mission
    Part 1.2/1.3).

    Matches ``infrastructure.recorder_source.RecorderStatisticsSource``'s
    public shape exactly (that class already satisfies this Protocol
    without modification) -- declared here, in ``application/ports.py``,
    rather than imported from ``infrastructure/`` directly, so
    ``application/scan_coordinator.py`` (an application-layer module)
    never needs to import an infrastructure-layer concrete class just to
    type-hint an optional constructor parameter.
    """

    async def async_prime(
        self, entity_ids: Sequence[str], *, now: datetime | None = None
    ) -> None:
        """Batched live fetch for every id in ``entity_ids``."""

    async def async_raw_history_available_seconds(self, entity_id: str) -> int | None:
        """Return how far back raw recorder history reaches for this entity."""

    async def async_long_term_statistics_unavailable_seconds(
        self, entity_id: str
    ) -> int | None:
        """Return the longest continuous unavailable span long-term stats confirm."""

    def raw_unavailable_seconds(self, entity_id: str) -> int | None:
        """Non-Protocol-standard convenience: seconds continuously unavailable
        within the primed raw-history window."""

    def contradicting_activity_found(self, entity_id: str) -> bool:
        """Whether any primed signal contradicts continuous unavailability."""
