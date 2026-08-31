"""Native event-driven controls for HAMIE."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory

from .presentation.device import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    async_device_info,
)

__all__ = (
    "DEVICE_MANUFACTURER",
    "DEVICE_MODEL",
    "DEVICE_NAME",
    "HamieRunScanButton",
)
if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .application.runtime import HamieRuntime


BUTTON_ENTITY_ID = "button.hamie_run_scan"
BUTTON_TRANSLATION_KEY = "run_scan"
SNOOZE_DURATION = timedelta(hours=24)


@dataclass(frozen=True, kw_only=True)
class HamieButtonDescription(ButtonEntityDescription):
    """Describe a bounded projection or review action."""

    action: str


ACTION_BUTTONS = (
    HamieButtonDescription(
        key="previous_finding",
        translation_key="previous_finding",
        icon="mdi:chevron-left",
        action="previous",
    ),
    HamieButtonDescription(
        key="next_finding",
        translation_key="next_finding",
        icon="mdi:chevron-right",
        action="next",
    ),
    HamieButtonDescription(
        key="acknowledge_finding",
        translation_key="acknowledge_finding",
        icon="mdi:check-circle-outline",
        action="acknowledge",
    ),
    HamieButtonDescription(
        key="dismiss_finding",
        translation_key="dismiss_finding",
        icon="mdi:close-circle-outline",
        action="dismiss",
    ),
    HamieButtonDescription(
        key="snooze_finding",
        translation_key="snooze_finding",
        icon="mdi:clock-outline",
        action="snooze",
    ),
    HamieButtonDescription(
        key="retain_finding",
        translation_key="retain_finding",
        icon="mdi:shield-check-outline",
        action="retain",
    ),
    HamieButtonDescription(
        key="analyze_selected_finding",
        translation_key="analyze_selected_finding",
        icon="mdi:head-lightbulb-outline",
        action="analyze_selected_finding",
    ),
    HamieButtonDescription(
        key="analyze_selected_group",
        translation_key="analyze_selected_group",
        icon="mdi:account-group-outline",
        action="analyze_selected_group",
    ),
    HamieButtonDescription(
        key="analyze_highest_priority",
        translation_key="analyze_highest_priority",
        icon="mdi:priority-high",
        action="analyze_highest_priority",
    ),
    HamieButtonDescription(
        key="refresh_ai_explanation",
        translation_key="refresh_ai_explanation",
        icon="mdi:refresh",
        action="refresh_ai_explanation",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add HAMIE controls to its single device."""
    device_info = await async_device_info(hass, entry)
    async_add_entities(
        [
            HamieRunScanButton(entry, device_info),
            *(
                HamieFindingActionButton(entry, description, device_info)
                for description in ACTION_BUTTONS
            ),
        ]
    )


class HamieRunScanButton(ButtonEntity):
    """Run one read-only HAMIE scan through the application service."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:radar"
    _attr_should_poll = False
    _attr_translation_key = BUTTON_TRANSLATION_KEY

    def __init__(self, entry: ConfigEntry, device_info: Any) -> None:
        """Bind the button to one stable HAMIE config-entry identity."""
        self.entity_id = BUTTON_ENTITY_ID
        self._attr_unique_id = f"{entry.entry_id}_run_scan"
        self._attr_device_info = device_info
        self._runtime: HamieRuntime = entry.runtime_data

    async def async_press(self) -> None:
        """Request the same coalesced scan used by the hamie.scan service."""
        await self._runtime.application.async_start_full_evaluation()


class HamieFindingActionButton(ButtonEntity):
    """Navigate or review the one bounded finding projection."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: ConfigEntry,
        description: HamieButtonDescription,
        device_info: Any,
    ) -> None:
        self.entity_description = description
        self.entity_id = f"button.hamie_{description.key}"
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info
        self._runtime: HamieRuntime = entry.runtime_data

    @property
    def available(self) -> bool:
        """Disable controls that have no legitimate runtime target.

        Availability here must depend only on runtime requirements (a
        selected finding/group, AI provider readiness, an in-flight
        analysis) -- never on whether an unrelated diagnostic entity
        exists or is enabled.
        """
        return self._unavailable_reason() is None

    @property
    def capability_attributes(self) -> dict[str, Any] | None:
        """Explain why a control is unavailable; never ghost silently.

        Home Assistant's entity state writer only merges
        extra_state_attributes when available is True (it deliberately
        drops them for unavailable entities), so an unavailable_reason
        placed there would never actually reach the state machine on the
        one control that needs it: an unavailable button. capability_attr
        is the one attribute channel HA always includes regardless of
        availability, so it is used here instead.
        """
        reason = self._unavailable_reason()
        return None if reason is None else {"unavailable_reason": reason}

    def _unavailable_reason(self) -> str | None:
        snapshot = self._runtime.projection.snapshot
        action = self.entity_description.action
        if action.startswith("analyze_") or action == "refresh_ai_explanation":
            connectors = self._runtime.connectors
            if connectors is not None and connectors.pending > 0:
                return "analysis_running"
            if connectors is None or not connectors.ai_provider_ready(
                self._runtime.hass
            ):
                return "ai_provider_not_ready"
            if not self._runtime.projection.explorer.groups:
                return "no_findings"
            if action in {"analyze_selected_finding", "refresh_ai_explanation"}:
                if snapshot.selected_finding is None:
                    return "no_selected_finding"
                return None
            if action == "analyze_selected_group":
                if snapshot.selected_finding is None:
                    return "no_selected_finding"
                group_id = self._runtime.projection.explorer.group_for_finding.get(
                    snapshot.selected_finding.finding_id
                )
                return None if group_id else "no_selected_group"
            return None  # analyze_highest_priority needs no selection.
        if action in {"previous", "next"}:
            if snapshot.selectable_findings == 0:
                return "no_findings"
            if snapshot.selectable_findings == 1:
                return "single_finding_only"
            return None
        if snapshot.selected_finding is None:
            return "no_selected_finding"
        return None

    async def async_added_to_hass(self) -> None:
        """Subscribe only to finite projection changes."""
        self.async_on_remove(
            self._runtime.projection.subscribe(self._handle_projection_update)
        )

    async def async_press(self) -> None:
        """Execute a local projection or HAMIE review command."""
        action = self.entity_description.action
        if action == "previous":
            self._runtime.projection.select_previous()
            return
        if action == "next":
            self._runtime.projection.select_next()
            return

        finding = self._runtime.projection.snapshot.selected_finding
        if action.startswith("analyze_") or action == "refresh_ai_explanation":
            if self._unavailable_reason() is not None:
                return
            operations = self._runtime.operations
            explorer = self._runtime.projection.explorer
            if operations is None:
                return
            if action in {"analyze_selected_finding", "refresh_ai_explanation"}:
                if finding is None:
                    return
                await operations.async_request_ai(
                    finding_ids=(finding.finding_id,), actor="home_assistant_button"
                )
            elif action == "analyze_selected_group":
                if finding is None:
                    return
                group_id = explorer.group_for_finding[finding.finding_id]
                await operations.async_request_ai(
                    group_ids=(group_id,), actor="home_assistant_button"
                )
            else:
                await operations.async_request_ai(
                    group_ids=(explorer.groups[0].group_id,),
                    actor="home_assistant_button",
                )
            return
        if finding is None:
            return
        common = {
            "expected_revision": finding.content_revision,
            "token": uuid4().hex,
            "actor": "home_assistant_button",
        }
        application = self._runtime.application
        if action == "acknowledge":
            await application.async_acknowledge(finding.finding_id, **common)
        elif action == "dismiss":
            await application.async_dismiss(finding.finding_id, **common)
        elif action == "retain":
            await application.async_retain(finding.finding_id, **common)
        elif action == "snooze":
            await application.async_snooze(
                finding.finding_id,
                snooze_until=datetime.now(UTC) + SNOOZE_DURATION,
                **common,
            )

    def _handle_projection_update(self) -> None:
        self.async_write_ha_state()
