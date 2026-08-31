"""HAMIE integration composition root."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Compose one local read-only HAMIE runtime."""
    from homeassistant.const import Platform

    from .analysis.analyzers.abandoned_bugfix_fork import AbandonedBugfixForkAnalyzer
    from .analysis.analyzers.automation_migration_residue import (
        AutomationMigrationResidueAnalyzer,
    )
    from .analysis.analyzers.duplicate_migration import DuplicateMigrationAnalyzer
    from .analysis.analyzers.functional_self_reference import (
        FunctionalSelfReferenceAnalyzer,
    )
    from .analysis.analyzers.orphaned_definitions import OrphanedDefinitionAnalyzer
    from .analysis.analyzers.removed_integration_orphan import (
        RemovedIntegrationOrphanAnalyzer,
    )
    from .analysis.analyzers.unavailable_entities import (
        UnavailableEntityAnalyzer,
        UnavailableEntityPolicy,
    )
    from .analysis.analyzers.wrong_domain_action import WrongDomainActionAnalyzer
    from .analysis.supervisor import AnalyzerSupervisor, PerformanceProfile
    from .analysis.whole_collection_supervisor import WholeCollectionSupervisor
    from .application.application_service import HamieApplicationService
    from .application.operations_service import MaintenanceOperationsService
    from .application.runtime import HamieRuntime
    from .application.runtime_projection import RuntimeProjection
    from .application.scan_coordinator import ScanCoordinator
    from .application.scan_scheduler import ScanScheduler
    from .connectors.heartbeat import ConnectorHeartbeat
    from .connectors.manager import ConnectorManager
    from .infrastructure.dependency_source import HomeAssistantReferenceIndexSource
    from .infrastructure.ha_source import HomeAssistantOperationalSource
    from .infrastructure.recorder_source import RecorderStatisticsSource
    from .infrastructure.storage import HomeAssistantStoreRepository
    from .presentation.repair_issues import RepairIssueProjection
    from .services import register_services

    entry_options = dict(getattr(entry, "options", {}))
    repository = HomeAssistantStoreRepository(hass)
    source = HomeAssistantOperationalSource(hass)
    projection = RuntimeProjection(
        RepairIssueProjection(hass),
        store_size=repository.document_size,
        options=entry_options,
    )
    installation_id = entry.data.get("installation_id", entry.entry_id)
    coordinator = ScanCoordinator(
        source,
        repository,
        projection,
        # Three supervisors, one analyzer each -- see
        # application/scan_coordinator.py's ScanCoordinator docstring:
        # every registered supervisor runs over the same capture and
        # its findings are reconciled independently by analyzer_id, so
        # adding a new supervisor here cannot affect any other
        # analyzer's existing findings/coverage.
        #
        # OrphanedDefinitionAnalyzer's source-definition evidence is now
        # live: infrastructure/ha_source.py's HomeAssistantOperationalSource
        # builds infrastructure/source_definition_index.py's
        # SourceDefinitionIndex once per capture from the real config
        # tree (hass.config.path()) and populates
        # EntityRecord.source_definition_missing for every automation/
        # script/scene entity from it. DuplicateMigrationAnalyzer (via
        # analysis/duplicate_group_scan.py) reads that same populated
        # field rather than re-parsing the config tree a second time --
        # see that module's _member_for_record for the exact
        # precedence. A subject still lands in "uncovered"/stays
        # unevaluated only when the live read/parse itself genuinely
        # fails (missing config dir, permission error, a malformed
        # config file) -- an honest degradation, never a fabricated
        # answer; see HomeAssistantOperationalSource._build_source_
        # definition_index's own docstring.
        #
        # DuplicateMigrationAnalyzer is registered through
        # WholeCollectionSupervisor, not AnalyzerSupervisor: suffix-
        # duplicate grouping is a whole-collection operation, not a
        # per-partition one -- see analysis/whole_collection_supervisor.py's
        # module docstring for the full reasoning behind this second,
        # small supervisor type rather than distorting
        # AnalyzerSupervisor's per-partition contract to fit.
        supervisors=(
            AnalyzerSupervisor(
                UnavailableEntityAnalyzer(
                    UnavailableEntityPolicy(
                        grace_seconds=max(
                            int(
                                entry_options.get(
                                    "minimum_finding_age_seconds", 300
                                )
                            ),
                            int(
                                entry_options.get(
                                    "transient_unavailable_grace_seconds", 300
                                )
                            ),
                        ),
                        include_disabled_entities=bool(
                            entry_options.get("include_disabled_entities", False)
                        ),
                        include_diagnostic_entities=bool(
                            entry_options.get("include_diagnostic_entities", False)
                        ),
                    ),
                    source_instance=installation_id,
                )
            ),
            AnalyzerSupervisor(
                OrphanedDefinitionAnalyzer(source_instance=installation_id)
            ),
            WholeCollectionSupervisor(
                DuplicateMigrationAnalyzer(source_instance=installation_id)
            ),
            # The six new analyzers this pass adds (mission Part 2), all
            # registered as independent WholeCollectionSupervisor
            # entries -- each one's findings are reconciled by its own
            # distinct analyzer_id (application/reconciliation.py),
            # never mixed with DuplicateMigrationAnalyzer's own
            # findings for the same group/entity. Every one of these
            # receives the same fresh-per-capture source_index/
            # installation_topology WholeCollectionSupervisor now
            # threads through automatically (see
            # analysis/whole_collection_supervisor.py).
            WholeCollectionSupervisor(
                FunctionalSelfReferenceAnalyzer(source_instance=installation_id)
            ),
            WholeCollectionSupervisor(
                RemovedIntegrationOrphanAnalyzer(source_instance=installation_id)
            ),
            WholeCollectionSupervisor(
                WrongDomainActionAnalyzer(source_instance=installation_id)
            ),
            WholeCollectionSupervisor(
                AutomationMigrationResidueAnalyzer(source_instance=installation_id)
            ),
            WholeCollectionSupervisor(
                AbandonedBugfixForkAnalyzer(source_instance=installation_id)
            ),
        ),
        profile=PerformanceProfile.CONSERVATIVE,
        # Both optional and purely additive (mission Part 1.2/1.4): a
        # failure inside either adapter degrades that one evidence
        # source gracefully (see ScanCoordinator._execute and
        # analysis/temporal_enrichment.py) and never aborts a scan.
        reference_source=HomeAssistantReferenceIndexSource(hass),
        temporal_evidence_source=RecorderStatisticsSource(hass),
    )
    application = HamieApplicationService(coordinator, repository, projection)
    connectors = ConnectorManager(
        options=dict(getattr(entry, "options", {})),
        hass=hass,
        status_listener=projection.update_connector_status,
        installation_id=installation_id,
    )
    operations = MaintenanceOperationsService(
        repository,
        projection,
        connectors,
        options=entry_options,
        # Lets the Gate H failure hook LOOK for its marker file. The hook
        # still refuses unless that file exists and names a group.
        fixture_config_dir=hass.config.config_dir,
    )
    coordinator.set_lifecycle_port(operations)
    application.set_transition_listener(operations)
    runtime_options: dict[str, Any] = {
        "initial_scan_enabled": bool(entry_options.get("initial_scan_enabled", True))
    }
    if "initial_scan_delay" in entry_options:
        runtime_options["initial_scan_delay"] = float(
            entry_options["initial_scan_delay"]
        )
    heartbeat = ConnectorHeartbeat(
        hass,
        connectors,
        interval_seconds=float(
            entry_options.get("connector_heartbeat_interval_seconds", 60)
        ),
    )
    scan_scheduler = None
    if bool(entry_options.get("auto_scan_enabled", True)):
        scan_scheduler = ScanScheduler(
            hass,
            coordinator,
            projection,
            interval_seconds=float(entry_options.get("auto_scan_interval_minutes", 60))
            * 60.0,
        )
    runtime = HamieRuntime(
        hass,
        repository,
        projection,
        coordinator,
        application,
        connectors,
        operations,
        heartbeat=heartbeat,
        scan_scheduler=scan_scheduler,
        **runtime_options,
    )
    await runtime.async_initialize()
    entry.runtime_data = runtime
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    from .llm import async_setup_api

    await async_setup_api(hass, entry)
    register_services(hass, runtime)
    if hasattr(entry, "async_on_unload"):
        entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    if hasattr(hass, "http"):
        from .presentation.n8n_http import async_register_n8n_view
        from .presentation.panel import async_register_panel, async_remove_panel

        # Production defect fix: this setup runs on *every* config-entry
        # reload (any real settings save from either the inline HAMIE
        # editors or native Options Flow triggers one), not just the
        # first install. async_register_panel is idempotent (see its own
        # docstring) so it is always safe to call here when the panel
        # should be visible; the panel is only ever actively *removed*
        # here, in the one case that legitimately means it should
        # disappear -- the user just disabled it in this exact save.
        # True integration removal is handled by async_remove_entry
        # below, never by a routine reload.
        if bool(entry_options.get("sidebar_panel_enabled", True)):
            await async_register_panel(hass)
        else:
            await async_remove_panel(hass)
        async_register_n8n_view(hass)
    await hass.config_entries.async_forward_entry_setups(
        entry, (Platform.BUTTON, Platform.SENSOR)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload HAMIE and cancel only its finite owned work.

    Production defect fix: this used to always remove the sidebar panel
    here (HA calls this before every reload, not only before a real
    removal). Home Assistant's config-entry reload is unload -> setup;
    a user actively viewing the HAMIE panel while saving any setting
    would see it vanish here and Home Assistant's frontend router,
    detecting the currently-open panel no longer exists, redirected to
    the default Overview dashboard -- confirmed live against the
    deployed RockPi instance. The panel must now persist across a
    routine reload; real removal only ever happens in async_setup_entry
    (when sidebar_panel_enabled is explicitly turned off in that exact
    save) or async_remove_entry below (true integration deletion).
    """
    from homeassistant.const import Platform

    from .services import unregister_services

    if not await hass.config_entries.async_unload_platforms(
        entry, (Platform.BUTTON, Platform.SENSOR)
    ):
        return False
    unregister_services(hass)
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None:
        await runtime.async_shutdown()
    entries = hass.data.get(DOMAIN, {})
    entries.pop(entry.entry_id, None)
    if not entries:
        hass.data.pop(DOMAIN, None)
    model_cache = hass.data.get("hamie.configuration_model_cache", {})
    if isinstance(model_cache, dict):
        model_cache.pop(entry.entry_id, None)
        if not model_cache:
            hass.data.pop("hamie.configuration_model_cache", None)
    entry.runtime_data = None
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Audit an explicit options change, then reload finite resources."""
    guards = hass.data.get("hamie.configuration_update_guards", {})
    future = guards.get(entry.entry_id) if isinstance(guards, dict) else None
    if future is not None:
        if not future.done():
            future.set_result(None)
        return
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None and runtime.operations is not None:
        await runtime.operations.async_record_audit(
            "configuration_changed",
            actor="home_assistant_options_flow",
            target_ids=(entry.entry_id,),
        )
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config-entry metadata without changing identity or options."""
    if entry.version > 5:
        return False
    options = dict(entry.options)
    if entry.version < 3:
        options["n8n_authentication_type"] = {
            "bearer": "bearer_token",
            "hmac": "shared_secret",
        }.get(
            str(options.get("n8n_authentication_type", "bearer_token")),
            options.get("n8n_authentication_type", "bearer_token"),
        )
        options["hamie_options_revision"] = 2
        hass.config_entries.async_update_entry(
            entry,
            version=3,
            minor_version=0,
            options=options,
        )
    if entry.version < 4:
        _migrate_n8n_credential_split(options)
        options["hamie_options_revision"] = 3
        hass.config_entries.async_update_entry(
            entry,
            version=4,
            minor_version=0,
            options=options,
        )
    if entry.version < 5:
        _migrate_conversation_analysis_removed(options)
        options["hamie_options_revision"] = 4
        hass.config_entries.async_update_entry(
            entry,
            version=5,
            minor_version=0,
            options=options,
        )
    return True


def _migrate_n8n_credential_split(options: dict[str, Any]) -> None:
    """Separate n8n's single outbound/inbound auth pair into two directions.

    beta.3 stopped conflating HAMIE's outbound call to n8n's webhook with
    n8n's inbound call back to HAMIE. Existing stored credentials are
    preserved -- never deleted -- and routed to whichever direction(s)
    they actually served under the prior combined design.
    """
    old_outbound_type = str(options.get("n8n_authentication_type", "bearer_token"))
    old_inbound_mode = str(
        options.get("n8n_inbound_authentication_mode", old_outbound_type)
    )
    old_bearer = options.pop("n8n_bearer_token", None)
    new_outbound_type = {"bearer_token": "api_key", "shared_secret": "none"}.get(
        old_outbound_type, old_outbound_type
    )
    options["n8n_authentication_type"] = new_outbound_type
    if new_outbound_type == "api_key" and old_bearer:
        options["n8n_outbound_api_key"] = old_bearer
    if old_inbound_mode == "bearer_token" and old_bearer:
        options["n8n_inbound_bearer_token"] = old_bearer


def _migrate_conversation_analysis_removed(options: dict[str, Any]) -> None:
    """Retire the Conversation background-analysis provider.

    beta.3 reserves Home Assistant Conversation entities for a possible
    future interactive assistant -- they must never drive background
    analysis. Existing users who had selected the Conversation connection
    method are moved to the deprecated-but-safe "direct" fallback rather
    than left on a mode that no longer exists; nothing is deleted, and the
    provider status card will honestly show "Not tested" until the user
    reviews the change, instead of silently pretending it still works.
    """
    options.pop("conversation_entity_id", None)
    if str(options.get("ai_connection_method", "direct")) == "ha_conversation":
        options["ai_connection_method"] = "direct"


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove HAMIE canonical state and any remaining derived issues.

    Home Assistant calls this optional hook only when a config entry is
    actually being deleted (confirmed against homeassistant.config_
    entries.ConfigEntries.async_remove) -- unlike async_unload_entry,
    which also runs before every routine reload. The sidebar panel is
    real removal work that belongs exactly here, not on every settings
    save (see async_unload_entry's docstring for the production defect
    this fixed: removing it there caused Home Assistant's frontend to
    redirect a currently-viewing user to the default Overview dashboard
    on every save).
    """
    from .infrastructure.storage import HomeAssistantStoreRepository
    from .presentation.repair_issues import RepairIssueProjection

    await RepairIssueProjection(hass).async_clear()
    await HomeAssistantStoreRepository(hass).async_remove()
    if hasattr(hass, "http"):
        from .presentation.panel import async_remove_panel

        await async_remove_panel(hass)
