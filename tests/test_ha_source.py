"""Tests for infrastructure/ha_source.py's live source-definition wiring.

Confirms the gap identified and closed in this pass:
``HomeAssistantOperationalSource`` never populated
``EntityRecord.source_definition_missing`` (zero references to that
field or to ``source_definition_index.py`` anywhere in that module
before this change -- confirmed by grep). This module exercises the
fix directly against real files on disk (via a fake ``hass`` whose
``config.path()``/``async_add_executor_job`` are the only faked
surface -- ``infrastructure/source_definition_index.py``'s own
parsing/matching functions run completely unmodified and unmocked),
covering the four scenarios named in this pass's mission:

- an automation with a real definition in ``automations.yaml``
- one defined inside a ``packages/*.yaml`` file
- one genuinely absent from all sources (``MISSING_CONFIRMED``)
- one where a package file fails to parse (degrades to
  ``SOURCE_UNAVAILABLE`` for that file's domain's not-found entities,
  never a scan crash)

``HomeAssistantOperationalSource._record``/``_build_source_definition_
index`` are exercised directly rather than the full
``async_capture_entities`` -- that top-level method does an
unconditional ``from homeassistant.helpers import entity_registry``,
and this task has no live ``homeassistant`` package installed to
import (matching every other infrastructure test in this suite, e.g.
``tests/test_recorder_source.py``'s own docstring). Both methods
exercised here are plain, homeassistant-import-free coroutines/methods
that only need duck-typed fakes for ``state``/``registry_entry``/
``hass``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hamie.infrastructure.ha_source import HomeAssistantOperationalSource

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)


@dataclass
class _FakeState:
    entity_id: str
    state: str
    last_changed: datetime = NOW
    last_updated: datetime = NOW
    attributes: dict = field(default_factory=dict)


@dataclass
class _FakeRegistryEntry:
    id: str
    entity_id: str = ""
    unique_id: str | None = None
    platform: str | None = None
    device_id: str | None = None
    config_entry_id: str | None = None
    disabled_by: str | None = None
    entity_category: str | None = None
    area_id: str | None = None
    created_at: str | None = None
    modified_at: str | None = None
    name: str | None = None
    original_name: str | None = None
    device_class: str | None = None
    original_device_class: str | None = None


class _FakeClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class _FakeConfig:
    def __init__(self, config_dir: str) -> None:
        self._config_dir = config_dir

    def path(self) -> str:
        return self._config_dir


class _FakeHass:
    """Only the two surfaces `_build_source_definition_index` touches."""

    def __init__(self, config_dir: str, *, raise_on_path: bool = False) -> None:
        self._raise_on_path = raise_on_path
        self.config = _FakeConfig(config_dir)

    async def async_add_executor_job(self, func, *args):
        if self._raise_on_path:
            raise OSError("simulated unreadable config directory")
        return func(*args)


AUTOMATIONS_YAML = """
- id: 'ui_automation_id'
  alias: A real automation
  triggers: []
  conditions: []
  actions: []
"""

PACKAGE_YAML = """
script:
  package_script:
    alias: A package-defined script
    sequence: []
"""

BROKEN_PACKAGE_YAML = """
script:
  broken: [this is not, valid yaml: :::
"""


def _write_config_tree(config_dir: Path, *, include_broken_package: bool) -> None:
    (config_dir / "automations.yaml").write_text(AUTOMATIONS_YAML, encoding="utf-8")
    packages_dir = config_dir / "packages"
    packages_dir.mkdir()
    (packages_dir / "demo.yaml").write_text(PACKAGE_YAML, encoding="utf-8")
    if include_broken_package:
        (packages_dir / "broken.yaml").write_text(
            BROKEN_PACKAGE_YAML, encoding="utf-8"
        )


# --------------------------------------------------------------------------
# 1/2/3: PRESENT (top-level file), PRESENT (package), MISSING_CONFIRMED.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_automation_present_in_top_level_automations_yaml(tmp_path: Path) -> None:
    _write_config_tree(tmp_path, include_broken_package=False)
    source = HomeAssistantOperationalSource(_FakeHass(str(tmp_path)))
    index, warnings = await source._build_source_definition_index()
    assert warnings == ()
    assert index is not None

    state = _FakeState(entity_id="automation.ui_created", state="on")
    registry_entry = _FakeRegistryEntry(
        id="internal-row-id-1", unique_id="ui_automation_id", platform="automation"
    )
    record = source._record(state, registry_entry, index)

    assert record.source_definition_missing is False
    # unique_id (the real HA registry identity used for the config
    # cross-reference) must be captured distinctly from registry_id
    # (the row's own internal .id).
    assert record.unique_id == "ui_automation_id"
    assert record.registry_id == "internal-row-id-1"


@pytest.mark.asyncio
async def test_script_present_inside_a_package_file(tmp_path: Path) -> None:
    _write_config_tree(tmp_path, include_broken_package=False)
    source = HomeAssistantOperationalSource(_FakeHass(str(tmp_path)))
    index, warnings = await source._build_source_definition_index()
    assert warnings == ()

    state = _FakeState(entity_id="script.package_script", state="off")
    registry_entry = _FakeRegistryEntry(
        id="internal-row-id-2", unique_id="package_script", platform="script"
    )
    record = source._record(state, registry_entry, index)

    assert record.source_definition_missing is False


@pytest.mark.asyncio
async def test_automation_genuinely_absent_is_missing_confirmed(tmp_path: Path) -> None:
    _write_config_tree(tmp_path, include_broken_package=False)
    source = HomeAssistantOperationalSource(_FakeHass(str(tmp_path)))
    index, warnings = await source._build_source_definition_index()
    assert warnings == ()

    state = _FakeState(entity_id="automation.deleted_long_ago", state="unavailable")
    registry_entry = _FakeRegistryEntry(
        id="internal-row-id-3", unique_id="no_longer_in_any_file", platform="automation"
    )
    record = source._record(state, registry_entry, index)

    assert record.source_definition_missing is True


# --------------------------------------------------------------------------
# 4: a malformed package file degrades that domain's coverage only --
#    never a scan crash, and never a false MISSING_CONFIRMED for the
#    entity that could legitimately be defined in the broken file.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_package_file_degrades_to_unavailable_not_a_crash(
    tmp_path: Path,
) -> None:
    _write_config_tree(tmp_path, include_broken_package=True)
    source = HomeAssistantOperationalSource(_FakeHass(str(tmp_path)))
    # Building the index must not raise despite the malformed package file.
    index, warnings = await source._build_source_definition_index()
    assert warnings == ()
    assert index is not None
    assert index.script.failed_files == ("packages/broken.yaml",)

    # An entity that would have to be found (if anywhere) in the very
    # file that failed to parse must degrade to "not evaluated" (None),
    # never a false MISSING_CONFIRMED positive.
    mystery_state = _FakeState(entity_id="script.mystery", state="unknown")
    mystery_registry_entry = _FakeRegistryEntry(
        id="internal-row-id-4", unique_id="mystery_script", platform="script"
    )
    mystery_record = source._record(mystery_state, mystery_registry_entry, index)
    assert mystery_record.source_definition_missing is None

    # A DIFFERENT domain's already-successfully-parsed file is entirely
    # unaffected by the broken package -- the degradation is scoped to
    # the domain that actually shares the failed file, not global.
    automation_state = _FakeState(entity_id="automation.ui_created", state="on")
    automation_registry_entry = _FakeRegistryEntry(
        id="internal-row-id-5", unique_id="ui_automation_id", platform="automation"
    )
    automation_record = source._record(
        automation_state, automation_registry_entry, index
    )
    assert automation_record.source_definition_missing is False

    # The already-successfully-parsed package script is also unaffected
    # -- a PRESENT answer already found in a good file is never
    # retroactively invalidated by a different file failing.
    present_state = _FakeState(entity_id="script.package_script", state="off")
    present_registry_entry = _FakeRegistryEntry(
        id="internal-row-id-6", unique_id="package_script", platform="script"
    )
    present_record = source._record(present_state, present_registry_entry, index)
    assert present_record.source_definition_missing is False


# --------------------------------------------------------------------------
# Honest degradation when the live read itself fails outright (missing/
# unreadable config directory) -- never a scan crash, never a guess.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unreadable_config_directory_degrades_to_no_index(tmp_path: Path) -> None:
    _write_config_tree(tmp_path, include_broken_package=False)
    source = HomeAssistantOperationalSource(
        _FakeHass(str(tmp_path), raise_on_path=True)
    )
    index, warnings = await source._build_source_definition_index()
    assert index is None
    assert warnings
    assert "could not be read" in warnings[0]

    state = _FakeState(entity_id="automation.ui_created", state="on")
    registry_entry = _FakeRegistryEntry(
        id="internal-row-id-7", unique_id="ui_automation_id", platform="automation"
    )
    # `_record` must never raise just because no index was available --
    # it simply leaves source_definition_missing unevaluated.
    record = source._record(state, registry_entry, index)
    assert record.source_definition_missing is None


@pytest.mark.asyncio
async def test_non_definition_domain_is_never_evaluated(tmp_path: Path) -> None:
    """A light entity is outside automation/script/scene entirely --
    source_definition_missing must stay None regardless of the index.
    """
    _write_config_tree(tmp_path, include_broken_package=False)
    source = HomeAssistantOperationalSource(_FakeHass(str(tmp_path)))
    index, _warnings = await source._build_source_definition_index()

    state = _FakeState(entity_id="light.kitchen", state="on")
    registry_entry = _FakeRegistryEntry(
        id="internal-row-id-8", unique_id="kitchen_light", platform="hue"
    )
    record = source._record(state, registry_entry, index)
    assert record.source_definition_missing is None


# --------------------------------------------------------------------------
# Production defect fix: registry-only entities (no corresponding live
# ``State`` object, overwhelmingly because ``disabled_by`` is set) must now
# become real ``EntityRecord``s instead of vanishing from the capture
# entirely. Confirmed root cause of every device_tracker and all but one
# button historical duplicate-suffix group being invisible to
# ``hamie.duplicate_migration`` in a real production scan (see
# ``hamie/infrastructure/ha_source.py::HomeAssistantOperationalSource.
# _records``'s own docstring for the full production evidence).
# --------------------------------------------------------------------------


def test_record_for_disabled_device_tracker_with_no_live_state() -> None:
    """A disabled device_tracker (the exact production shape: a migration-
    leftover sibling Home Assistant never sets up, so it has no State
    object at all) must still become a conservative, honest EntityRecord.
    """
    source = HomeAssistantOperationalSource(_FakeHass("/config"), clock=_FakeClock(NOW))
    registry_entry = _FakeRegistryEntry(
        id="row-dt-1",
        entity_id="device_tracker.example_phone_15_2",
        disabled_by="integration",
        unique_id="example_phone_15_old",
        platform="mobile_app",
    )
    record = source._record(None, registry_entry, None)

    assert record.entity_id == "device_tracker.example_phone_15_2"
    assert record.domain == "device_tracker"
    assert record.state == "unavailable"
    assert record.disabled is True
    assert record.restored is None
    assert record.registry_id == "row-dt-1"


def test_record_for_disabled_button_with_no_live_state() -> None:
    """Same shape, button domain -- the other domain confirmed 87.5%
    excluded in the real production audit before this fix.
    """
    source = HomeAssistantOperationalSource(_FakeHass("/config"), clock=_FakeClock(NOW))
    registry_entry = _FakeRegistryEntry(
        id="row-btn-1",
        entity_id="button.garage_trigger_alarm_2",
        disabled_by="integration",
        unique_id="eufy_security_station_trigger_alarm",
        platform="eufy_security",
    )
    record = source._record(None, registry_entry, None)

    assert record.entity_id == "button.garage_trigger_alarm_2"
    assert record.domain == "button"
    assert record.state == "unavailable"
    assert record.disabled is True


def test_record_for_registry_only_entity_uses_modified_at_timestamp() -> None:
    """Prefer the registry's own ``modified_at`` over ``created_at`` and
    over the clock -- the most accurate honest timestamp available when
    there is no live state to read one from.
    """
    source = HomeAssistantOperationalSource(_FakeHass("/config"), clock=_FakeClock(NOW))
    registry_entry = _FakeRegistryEntry(
        id="row-2",
        entity_id="button.foo_2",
        disabled_by="integration",
        created_at="2020-01-01T00:00:00+00:00",
        modified_at="2024-06-15T08:30:00+00:00",
    )
    record = source._record(None, registry_entry, None)
    assert record.last_changed == datetime(2024, 6, 15, 8, 30, 0, tzinfo=UTC)
    assert record.last_updated == datetime(2024, 6, 15, 8, 30, 0, tzinfo=UTC)


def test_record_for_registry_only_entity_falls_back_to_clock_when_no_timestamps() -> None:
    """Neither ``modified_at`` nor ``created_at`` present (older HA schema,
    or a test double) -- the clock is the honest last resort, never a
    crash and never a fabricated arbitrary date.
    """
    source = HomeAssistantOperationalSource(_FakeHass("/config"), clock=_FakeClock(NOW))
    registry_entry = _FakeRegistryEntry(
        id="row-3",
        entity_id="button.foo_3",
        disabled_by="integration",
    )
    record = source._record(None, registry_entry, None)
    assert record.last_changed == NOW
    assert record.last_updated == NOW


def test_record_for_registry_only_entity_uses_registry_name_for_friendly_name() -> None:
    """No live ``attributes.friendly_name`` to read -- fall back to the
    registry's own ``name``/``original_name`` instead of leaving it blank.
    """
    source = HomeAssistantOperationalSource(_FakeHass("/config"), clock=_FakeClock(NOW))
    registry_entry = _FakeRegistryEntry(
        id="row-4",
        entity_id="button.foo_2",
        disabled_by="integration",
        original_name="Foo Button (old)",
    )
    record = source._record(None, registry_entry, None)
    assert record.friendly_name == "Foo Button (old)"


def test_record_requires_state_or_registry_entry() -> None:
    """Never silently fabricate a record from nothing."""
    source = HomeAssistantOperationalSource(_FakeHass("/config"), clock=_FakeClock(NOW))
    with pytest.raises(ValueError, match="requires a live state or a registry entry"):
        source._record(None, None, None)


@pytest.mark.asyncio
async def test_records_captures_both_live_and_registry_only_entities() -> None:
    """End-to-end ``_records``: a live sibling and its disabled, state-less
    sibling must BOTH appear in the resulting record set -- the exact
    pair ``group_suffix_siblings``/``scan_duplicate_groups`` need to see
    together to ever classify a migration-leftover duplicate group.
    """
    source = HomeAssistantOperationalSource(_FakeHass("/config"), clock=_FakeClock(NOW))
    live_state = _FakeState(entity_id="device_tracker.example_phone_15", state="home")
    live_registry_entry = _FakeRegistryEntry(
        id="row-live", entity_id="device_tracker.example_phone_15"
    )
    disabled_registry_entry = _FakeRegistryEntry(
        id="row-disabled",
        entity_id="device_tracker.example_phone_15_2",
        disabled_by="integration",
    )
    registry = {
        "device_tracker.example_phone_15": live_registry_entry,
        "device_tracker.example_phone_15_2": disabled_registry_entry,
    }
    records, warnings, _skipped = await source._records((live_state,), registry, None)

    assert warnings == ()
    entity_ids = {record.entity_id for record in records}
    assert entity_ids == {
        "device_tracker.example_phone_15",
        "device_tracker.example_phone_15_2",
    }
    by_id = {record.entity_id: record for record in records}
    assert by_id["device_tracker.example_phone_15"].state == "home"
    assert by_id["device_tracker.example_phone_15"].disabled is False
    assert by_id["device_tracker.example_phone_15_2"].state == "unavailable"
    assert by_id["device_tracker.example_phone_15_2"].disabled is True


@pytest.mark.asyncio
async def test_records_registry_only_pass_never_duplicates_live_entities() -> None:
    """A registry entry that DOES have a live state must be captured
    exactly once (via the live-state pass), never a second time via the
    registry-only pass -- ``EntityCapture`` rejects duplicate entity IDs.
    """
    source = HomeAssistantOperationalSource(_FakeHass("/config"), clock=_FakeClock(NOW))
    live_state = _FakeState(entity_id="light.kitchen", state="on")
    registry_entry = _FakeRegistryEntry(id="row-1", entity_id="light.kitchen")
    registry = {"light.kitchen": registry_entry}

    records, _warnings, _skipped = await source._records((live_state,), registry, None)

    assert len(records) == 1
    assert records[0].entity_id == "light.kitchen"
    assert records[0].state == "on"
