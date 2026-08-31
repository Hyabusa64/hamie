"""Event-driven aggregate and bounded finding sensors for HAMIE."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory

from .application.runtime_projection import RuntimeProjectionSnapshot, ScanStatus
from .presentation.device import async_device_info

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .application.runtime import HamieRuntime


ValueFn = Callable[[RuntimeProjectionSnapshot], Any]
AttributesFn = Callable[[RuntimeProjectionSnapshot], Mapping[str, Any] | None]


@dataclass(frozen=True, kw_only=True)
class HamieSensorDescription(SensorEntityDescription):
    """Describe one projection-backed HAMIE sensor."""

    value_fn: ValueFn
    attributes_fn: AttributesFn | None = None
    enabled_default: bool = True


def _availability_attributes(snapshot: RuntimeProjectionSnapshot) -> dict[str, Any]:
    return {
        "scope": "availability_only",
        "coverage_state": snapshot.coverage_state,
        "covered_categories": list(snapshot.covered_categories),
        "uncovered_categories": list(snapshot.uncovered_categories),
        "implemented_analyzers": list(snapshot.implemented_analyzers),
        "scoring_revision": snapshot.scoring_revision,
    }


def _finding_attributes(snapshot: RuntimeProjectionSnapshot) -> dict[str, Any]:
    finding = snapshot.selected_finding
    if finding is None:
        return {"position": 0, "total": 0, "safe_to_remove": False}
    return {
        "position": snapshot.selected_index + 1,
        "total": snapshot.selectable_findings,
        "finding_id": finding.finding_id,
        "entity": finding.entity_id,
        "severity": finding.severity,
        "category": finding.category,
        "title": finding.title_key.replace("_", " ").title(),
        "recommendation": finding.recommendation,
        "confidence": finding.confidence,
        "evidence": [
            {
                "predicate": item.predicate,
                "value": item.value,
                "kind": item.kind,
                "source": item.source,
                "observed_at": item.observed_at.isoformat(),
            }
            for item in finding.evidence
        ],
        "risk": finding.risk,
        "risk_rationale": finding.risk_rationale,
        "dependency_risk": finding.dependency_risk,
        "dependency_count": finding.dependency_count,
        "referenced_by": list(finding.referenced_by),
        "safe_to_remove": finding.safe_to_remove,
        "supporting_objects": list(finding.supporting_objects),
        "dependency_coverage": finding.dependency_coverage,
        "dependency_rationale": finding.dependency_rationale,
        "lifecycle": finding.lifecycle,
        "review_state": finding.review_state,
        "occurrence_count": finding.occurrence_count,
        "first_seen": finding.first_seen.isoformat(),
        "last_seen": finding.last_seen.isoformat(),
    }


def _connector_status(snapshot: RuntimeProjectionSnapshot, connector_id: str) -> str:
    return dict(snapshot.connector_statuses).get(connector_id, "disabled")


def _connector_status_value(connector_id: str) -> ValueFn:
    """Build a typed cached-status projection function."""

    def value(snapshot: RuntimeProjectionSnapshot) -> str:
        return _connector_status(snapshot, connector_id)

    return value


def _count(
    key: str,
    value_fn: ValueFn,
    *,
    icon: str,
    enabled_default: bool = True,
) -> HamieSensorDescription:
    return HamieSensorDescription(
        key=key,
        translation_key=key,
        icon=icon,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=value_fn,
        enabled_default=enabled_default,
    )


def _scan_derived_count(
    key: str,
    value_fn: ValueFn,
    *,
    icon: str,
    enabled_default: bool = True,
) -> HamieSensorDescription:
    """Build a count sensor that is unknown until a scan has ever completed.

    `RuntimeProjectionSnapshot`'s scan-derived count fields
    (findings_open, findings_critical, etc.) default to 0 before any
    scan has run, and a failed scan never overwrites them (see
    `RuntimeProjection.async_scan_failed`, which only touches
    `scan_status`/`queue_depth`/`pending_requests`) -- so after the
    *first* scan ever attempted fails, this 0 is an uninitialized
    default, not a real computed result, and must never be shown as an
    authoritative "zero findings". `scan_completed` is set exactly once
    a scan has successfully finished and is never cleared by a later
    failure, so "no completed scan yet" is exactly `scan_completed is
    None` -- reported as HA's own native `None`/unknown sensor state,
    never a fabricated string.
    """

    def value(snapshot: RuntimeProjectionSnapshot) -> Any:
        if snapshot.scan_completed is None:
            return None
        return value_fn(snapshot)

    return HamieSensorDescription(
        key=key,
        translation_key=key,
        icon=icon,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=value,
        enabled_default=enabled_default,
    )


SENSOR_DESCRIPTIONS: tuple[HamieSensorDescription, ...] = (
    HamieSensorDescription(
        key="availability_health",
        translation_key="availability_health",
        icon="mdi:heart-pulse",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda item: item.availability_health,
        attributes_fn=_availability_attributes,
    ),
    _scan_derived_count(
        "open_findings",
        lambda item: item.findings_open,
        icon="mdi:alert-circle-outline",
    ),
    _scan_derived_count(
        "warning_findings",
        lambda item: item.findings_warning,
        icon="mdi:alert-outline",
    ),
    _scan_derived_count(
        "critical_findings",
        lambda item: item.findings_critical,
        icon="mdi:alert-octagon-outline",
    ),
    HamieSensorDescription(
        key="last_scan",
        translation_key="last_scan",
        icon="mdi:clock-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda item: item.scan_completed,
    ),
    HamieSensorDescription(
        key="scan_status",
        translation_key="scan_status",
        icon="mdi:radar",
        device_class=SensorDeviceClass.ENUM,
        options=tuple(item.value for item in ScanStatus),
        value_fn=lambda item: item.scan_status.value,
    ),
    HamieSensorDescription(
        key="scan_duration",
        translation_key="scan_duration",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda item: item.scan_duration,
        enabled_default=False,
    ),
    _scan_derived_count(
        "entities_scanned",
        lambda item: item.entities_scanned,
        icon="mdi:counter",
        enabled_default=False,
    ),
    _scan_derived_count(
        "unavailable_entities",
        lambda item: item.findings_warning,
        icon="mdi:cloud-alert-outline",
    ),
    _count(
        "generation",
        lambda item: item.generation,
        icon="mdi:source-branch",
        enabled_default=False,
    ),
    _count(
        "projection_revision",
        lambda item: item.projection_revision,
        icon="mdi:database-sync-outline",
        enabled_default=False,
    ),
    HamieSensorDescription(
        key="store_size",
        translation_key="store_size",
        icon="mdi:database-outline",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement="B",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda item: item.store_size,
        enabled_default=False,
    ),
    _scan_derived_count(
        "new_findings",
        lambda item: item.findings_new,
        icon="mdi:plus-circle-outline",
        enabled_default=False,
    ),
    _scan_derived_count(
        "resolved_findings",
        lambda item: item.findings_resolved,
        icon="mdi:check-circle-outline",
        enabled_default=False,
    ),
    HamieSensorDescription(
        key="selected_finding",
        translation_key="selected_finding",
        icon="mdi:format-list-bulleted",
        value_fn=lambda item: (
            item.selected_finding.finding_id if item.selected_finding else None
        ),
        attributes_fn=_finding_attributes,
    ),
    *(
        HamieSensorDescription(
            key=f"{connector_id}_status",
            translation_key=f"{connector_id}_status",
            icon="mdi:connection",
            device_class=SensorDeviceClass.ENUM,
            options=("disabled", "unknown", "healthy", "degraded", "error"),
            value_fn=_connector_status_value(connector_id),
            enabled_default=False,
        )
        for connector_id in ("ollama", "n8n", "mcp", "hkg")
    ),
    HamieSensorDescription(
        key="last_ai_analysis",
        translation_key="last_ai_analysis",
        icon="mdi:clock-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda item: item.last_ai_analysis,
        enabled_default=False,
    ),
    _count(
        "pending_ai_recommendations",
        lambda item: item.pending_ai_recommendations,
        icon="mdi:head-lightbulb-outline",
        enabled_default=False,
    ),
    HamieSensorDescription(
        key="last_connector_error",
        translation_key="last_connector_error",
        icon="mdi:alert-network-outline",
        value_fn=lambda item: item.last_connector_error,
        enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add projection-backed sensors without polling."""
    device_info = await async_device_info(hass, entry)
    async_add_entities(
        HamieProjectionSensor(entry, description, device_info)
        for description in SENSOR_DESCRIPTIONS
    )


class HamieProjectionSensor(SensorEntity):
    """Read one value from HAMIE's shared in-memory projection."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entry: ConfigEntry,
        description: HamieSensorDescription,
        device_info: Any,
    ) -> None:
        self.entity_description = description
        self.entity_id = f"sensor.hamie_{description.key}"
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info
        self._attr_entity_registry_enabled_default = description.enabled_default
        self._runtime: HamieRuntime = entry.runtime_data

    @property
    def native_value(self) -> Any:
        """Return the current projection value without I/O."""
        return self.entity_description.value_fn(self._runtime.projection.snapshot)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return bounded projection attributes without Store access."""
        factory = self.entity_description.attributes_fn
        return factory(self._runtime.projection.snapshot) if factory else None

    async def async_added_to_hass(self) -> None:
        """Subscribe to finite projection commits."""
        self.async_on_remove(
            self._runtime.projection.subscribe(self._handle_projection_update)
        )

    def _handle_projection_update(self) -> None:
        self.async_write_ha_state()
