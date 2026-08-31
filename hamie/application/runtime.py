"""Owned services and finite startup work for one config entry."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from ..connectors.heartbeat import ConnectorHeartbeat
from ..connectors.manager import ConnectorManager
from .application_service import HamieApplicationService
from .operations_service import MaintenanceOperationsService
from .persistence import (
    CorruptStoredStateError,
    PersistenceUnitOfWorkPort,
    UnsupportedStoredStateError,
)
from .runtime_projection import RuntimeProjection
from .scan_coordinator import ScanCoordinator
from .scan_scheduler import ScanScheduler

_LOGGER = logging.getLogger(__name__)
INITIAL_SCAN_SETTLE_SECONDS = 30


class HamieRuntime:
    """Own HAMIE entry resources and the one-shot initial evaluation."""

    def __init__(
        self,
        hass: Any,
        repository: PersistenceUnitOfWorkPort,
        projection: RuntimeProjection,
        coordinator: ScanCoordinator,
        application: HamieApplicationService,
        connectors: ConnectorManager | None = None,
        operations: MaintenanceOperationsService | None = None,
        *,
        initial_scan_enabled: bool = True,
        initial_scan_delay: float | None = None,
        heartbeat: ConnectorHeartbeat | None = None,
        scan_scheduler: ScanScheduler | None = None,
    ) -> None:
        self.hass = hass
        self.repository = repository
        self.projection = projection
        self.coordinator = coordinator
        self.application = application
        self.connectors = connectors
        self.operations = operations
        self.heartbeat = heartbeat
        self.scan_scheduler = scan_scheduler
        self._initial_scan_enabled = initial_scan_enabled
        self._initial_scan_delay = (
            INITIAL_SCAN_SETTLE_SECONDS
            if initial_scan_delay is None
            else initial_scan_delay
        )
        self._startup_unsubscribe: Callable[[], None] | None = None
        self._initial_task: asyncio.Task[None] | None = None
        # Recovery is attempted at most once per runtime instance so a
        # document that is corrupt *again* immediately after rebuilding
        # escalates instead of looping.
        self._remediation_executor: Any = None
        self._incident_remediation: Any = None
        self._remediation_lifecycle: Any = None
        self._storage_recovery_attempted = False
        self.storage_recovery: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Remediation workflow accessors (used by presentation/api.py).
    # Constructed lazily so importing the runtime never requires Ollama.
    # ------------------------------------------------------------------

    @property
    def investigation_model(self) -> Any:
        """Async (system, user) -> text, routed through the canonical provider.

        Root cause of the previous failure recorded here: this accessor used
        `self.connectors.ollama()`, which does not exist on ConnectorManager,
        behind a hasattr() guard -- so it silently degraded to "no local
        inference provider configured" on every call. It now uses the same
        ConnectorManager routing every other AI path uses.
        """

        async def _call(system: str, user: str) -> str:
            return await self.connectors.async_investigate(system, user)

        return _call

    @property
    def incident_remediation(self) -> Any:
        """Closed-loop triage bound to this Home Assistant instance."""
        if getattr(self, "_incident_remediation", None) is None:
            import re

            from .incident_remediation import (
                IncidentRemediationPipeline,
                WorldGateway,
            )
            from .investigator import Investigator

            hass = self.hass
            # Home Assistant disambiguates a colliding entity id by appending
            # a single digit (_2, _3, ...). Only that exact suffix may be
            # stripped: a normalizer that removed any trailing _<digits> turned
            # "device_tracker_15" into "device_tracker" and lost the real
            # successor -- found live on incident inc_54f6249... which had 10
            # genuine config references and no candidate.
            _DUP_SUFFIX = re.compile(r"^(.*)_([2-9])$")

            async def _entity_state(entity_id: str) -> str | None:
                state = hass.states.get(entity_id)
                return None if state is None else state.state

            def _enumerate_config_targets() -> list[str]:
                """Active configuration files, newest-safe and bounded.

                BLOCKING: os.path.isdir/os.listdir touch the filesystem and
                must only ever run inside asyncio.to_thread. An earlier
                revision enumerated here on the event loop and Home Assistant
                logged "Detected blocking call to listdir ... inside the event
                loop by custom integration 'hamie'"; a stalled loop is a
                house-wide problem, so every filesystem call below is now
                reached exclusively from a worker thread.

                Backups, .storage and unrelated trees are excluded on purpose:
                a grep hit in an old backup is not a production problem.
                """
                import os

                root = hass.config.config_dir
                targets = [
                    os.path.join(root, name)
                    for name in ("automations.yaml", "scripts.yaml", "scenes.yaml")
                ]
                pkg = os.path.join(root, "packages")
                if os.path.isdir(pkg):
                    for entry in sorted(os.listdir(pkg)):
                        if entry.endswith((".yaml", ".yml")) and ".bak" not in entry:
                            targets.append(os.path.join(pkg, entry))
                return targets

            async def _search_config(needle: str):
                """Occurrences of a reference in ACTIVE configuration only."""

                def _scan():
                    found = []
                    for path in _enumerate_config_targets():
                        try:
                            with open(path, encoding="utf-8") as fh:
                                count = fh.read().count(needle)
                        except OSError:
                            continue
                        if count:
                            found.append((path, count))
                    return tuple(found)

                return await asyncio.to_thread(_scan)

            async def _get_incident(incident_id: str):
                # NOTE: the projection accessor is _incident_projection();
                # there is no public alias on MaintenanceOperationsService.
                for item in self.operations._incident_projection():
                    if item.incident_id != incident_id:
                        continue
                    data = item.public_dict()
                    # public_dict() is the bounded API view and deliberately
                    # omits internal digests; the remediation lifecycle needs
                    # the material digest to report (not enforce) incident
                    # drift between approval and execution.
                    data["material_digest"] = item.material_digest
                    data["root_key"] = item.root_key
                    return data
                return None

            async def _similar_entities(entity_id: str):
                """Conservative successor candidates.

                Only the exact base of a Home Assistant duplicate suffix, and
                only when that base actually exists. Deliberately narrow:
                anything looser lets string similarity pick a production
                target, which is the failure mode this pipeline exists to
                prevent. No candidate -> operator decision, never a guess.
                """
                domain, _, obj = entity_id.partition(".")
                match = _DUP_SUFFIX.match(obj)
                if match is None:
                    return ()
                base = f"{domain}.{match.group(1)}"
                return (base,) if hass.states.get(base) is not None else ()

            self._incident_remediation = IncidentRemediationPipeline(
                WorldGateway(
                    _entity_state, _search_config, _get_incident, _similar_entities
                ),
                Investigator(self.investigation_model),
                self.remediation_executor,
                # Lets the advisory-failure hook LOOK for its marker file.
                fixture_config_dir=self.hass.config.config_dir,
            )
        return self._incident_remediation

    @property
    def remediation_executor(self) -> Any:
        """Controlled mutation tools bound to this Home Assistant instance."""
        if getattr(self, "_remediation_executor", None) is None:
            from ..application.remediation_tools import (
                FileGateway,
                HaGateway,
                PathPolicy,
                RemediationExecutor,
            )

            hass = self.hass

            async def _check_config() -> dict[str, Any]:
                from homeassistant.helpers.check_config import (
                    async_check_ha_config_file,
                )

                res = await async_check_ha_config_file(hass)
                return {
                    "result": "invalid" if res.errors else "valid",
                    "errors": [str(e) for e in res.errors] or None,
                }

            async def _reload_domain(domain: str) -> bool:
                try:
                    await hass.services.async_call(domain, "reload", blocking=True)
                    return True
                except Exception:  # noqa: BLE001 - reported as a failed check
                    return False

            async def _entity_state(entity_id: str) -> str | None:
                state = hass.states.get(entity_id)
                return None if state is None else state.state

            async def _recent_errors() -> int:
                # Counted from HA's own system_log ring buffer when present.
                try:
                    from homeassistant.components.system_log import DOMAIN as SL

                    handler = hass.data.get(SL)
                    records = getattr(handler, "records", None)
                    if records is None:
                        return 0
                    import time

                    cutoff = time.time() - 60
                    return sum(
                        1
                        for r in list(records)
                        if getattr(r, "level", "") == "ERROR"
                        and float(getattr(r, "timestamp", 0)) >= cutoff
                    )
                except Exception:  # noqa: BLE001 - absence is not a failure
                    return 0

            async def _error_signatures() -> tuple[str, ...]:
                """Stable identities of current ERROR records.

                Counting errors cannot separate an error this repair caused
                from one that was already there; comparing the set before and
                after can, and only signatures naming something the repair
                actually touched are ever attributed to it.
                """
                try:
                    from homeassistant.components.system_log import DOMAIN as SL

                    handler = hass.data.get(SL)
                    records = getattr(handler, "records", None)
                    if records is None:
                        return ()
                    signatures: list[str] = []
                    for record in list(records)[:200]:
                        if getattr(record, "level", "") != "ERROR":
                            continue
                        message = getattr(record, "message", "")
                        if isinstance(message, (list, tuple)):
                            message = " ".join(str(part) for part in message)
                        signatures.append(
                            f"{getattr(record, 'name', '')}:{str(message)[:200]}"
                        )
                    return tuple(signatures)
                except Exception:  # noqa: BLE001 - absence degrades, never passes
                    return ()

            async def _domain_state_counts(domain: str) -> dict[str, int]:
                counts: dict[str, int] = {}
                for state in hass.states.async_all(domain):
                    counts[state.state] = counts.get(state.state, 0) + 1
                return counts

            async def _config_scope_entities(paths: tuple[str, ...]) -> tuple[str, ...]:
                """The automation/script entities the given files define.

                Reuses HAMIE's own SourceDefinitionIndex rather than a second
                YAML parser, then maps each definition id onto the registry's
                unique_id convention. This is the scope regression checks are
                correlated against, so that "unavailable automations went up"
                can be narrowed to "one of the automations we just touched".
                """
                import os

                from ..infrastructure.source_definition_index import (
                    ConfigSourceFile,
                    SourceDefinitionIndex,
                )

                root = hass.config.config_dir
                wanted = {os.path.relpath(path, root): path for path in paths}

                def _read() -> tuple[ConfigSourceFile, ...]:
                    files: list[ConfigSourceFile] = []
                    for label, full in sorted(wanted.items()):
                        try:
                            with open(full, encoding="utf-8") as handle:
                                files.append(
                                    ConfigSourceFile(path=label, content=handle.read())
                                )
                        except OSError:
                            continue
                    return tuple(files)

                files = await asyncio.to_thread(_read)
                if not files:
                    return ()
                index = SourceDefinitionIndex.build(files)
                by_domain = {
                    "automation": set(index.automation.ids_to_files),
                    "script": set(index.script.ids_to_files),
                }
                from homeassistant.helpers import entity_registry as er

                registry = er.async_get(hass)
                found = {
                    entry.entity_id
                    for entry in registry.entities.values()
                    if entry.entity_id.split(".", 1)[0] in by_domain
                    and entry.unique_id in by_domain[entry.entity_id.split(".", 1)[0]]
                }
                return tuple(sorted(found))

            self._remediation_executor = RemediationExecutor(
                FileGateway(PathPolicy(allowed_roots=(hass.config.config_dir,))),
                HaGateway(
                    _check_config,
                    _reload_domain,
                    _entity_state,
                    _recent_errors,
                    _error_signatures,
                    _domain_state_counts,
                    _config_scope_entities,
                ),
            )
        return self._remediation_executor

    @property
    def remediation_lifecycle(self) -> Any:
        """Post-approval proof: mutation, validation, rescan, resolution.

        Deliberately built on the same WorldGateway the triage pipeline uses,
        so the targets re-derived at execution time come from exactly one
        implementation. No investigator is wired in at all: the model has no
        vote after approval.
        """
        if getattr(self, "_remediation_lifecycle", None) is None:
            from ..domain.incidents import IncidentLifecycle
            from .remediation_lifecycle import LifecycleGateway, RemediationLifecycle

            async def _request_scan() -> dict[str, Any]:
                result = await self.coordinator.async_request_scan(
                    trigger="post_remediation"
                )
                evaluation = result.evaluation
                return {
                    "scan_id": evaluation.identity.scan_id,
                    "state": evaluation.state.value,
                    "finding_count": len(result.state.findings),
                    # Coverage is reported, not assumed: this installation
                    # scans PARTIAL as its normal state, so a repair must be
                    # able to reconcile against a partial scan while still
                    # recording which analyzers did not fully cover it.
                    "incomplete_analyzers": [
                        item.analyzer_id
                        for item in evaluation.coverage
                        if item.state.value != "complete"
                    ],
                }

            async def _current_scan_id() -> str | None:
                # The committed scan id lives on the projection snapshot.
                # An earlier revision read operations.overview(), which does
                # not carry it -- the panel's `last_scan_id` is merged in from
                # runtime.projection.snapshot by presentation/api.py's
                # ws_overview. That silently produced None, which weakened the
                # "is this scan genuinely new?" guard.
                snapshot = getattr(self.projection, "snapshot", None)
                return getattr(snapshot, "last_scan_id", None)

            async def _incidents() -> tuple[dict[str, Any], ...]:
                values = []
                for item in self.operations._incident_projection():
                    data = item.public_dict()
                    data["material_digest"] = item.material_digest
                    values.append(data)
                return tuple(values)

            async def _record_audit(event, *, actor, target_ids, details) -> None:
                await self.operations.async_record_audit(
                    event, actor=actor, target_ids=tuple(target_ids), details=tuple(details)
                )

            async def _set_lifecycle(
                *, incident_id, lifecycle, expected_revision, actor, token
            ) -> None:
                await self.operations.async_set_incident_lifecycle(
                    incident_id,
                    IncidentLifecycle(lifecycle),
                    expected_revision=expected_revision,
                    actor=actor,
                    token=token,
                )

            async def _save_remediation_baseline(baseline) -> None:
                """Durably record an in-flight repair, bounded by retention.

                Without this the lifecycle held everything in memory and a
                restart between mutation and reconciliation lost the entire
                truth of the repair -- which is why remediation_baselines
                stayed at 0.
                """
                from dataclasses import replace as _replace

                from ..domain.durable_baseline import prune_remediation_baselines

                state = await self.repository.async_load()
                others = tuple(
                    item
                    for item in state.remediation_baselines
                    if not (
                        item.plan_identity == baseline.plan_identity
                        and item.incident_id == baseline.incident_id
                    )
                )
                next_state = _replace(
                    state,
                    generation=state.generation + 1,
                    projection_revision=state.projection_revision + 1,
                    remediation_baselines=prune_remediation_baselines(
                        (*others, baseline)
                    ),
                )
                await self.repository.async_commit(
                    next_state, expected_generation=state.generation
                )
                await self.projection.async_sync(next_state)

            self._remediation_lifecycle = RemediationLifecycle(
                self.incident_remediation.world,
                LifecycleGateway(
                    _request_scan,
                    _current_scan_id,
                    _incidents,
                    _record_audit,
                    _set_lifecycle,
                    _save_remediation_baseline,
                ),
                self.remediation_executor,
                # Enables the fixture interruption hook to *look* for its
                # marker file. The hook still refuses unless the marker
                # exists and every planned location is a fixture file.
                fixture_config_dir=self.hass.config.config_dir,
            )
        return self._remediation_lifecycle

    async def async_initialize(self) -> None:
        """Validate persisted state, repair projection, then arm background work."""
        try:
            state = await self.repository.async_load()
        except CorruptStoredStateError:
            state = await self._async_recover_corrupt_state("corrupt_state")
        except UnsupportedStoredStateError:
            await self.projection.async_report_storage_error("incompatible_schema")
            raise
        await self.projection.async_sync(state)
        # Bind the deterministic readers incident reconciliation needs BEFORE
        # anything can ask for a verdict. Binding them lazily inside the
        # remediation pipeline property meant a fresh restart left them unset,
        # and reconciliation then read "no reader" as "entity absent".
        if self.operations is not None:
            self.operations.bind_world_readers(
                self._reconciliation_entity_state, self._reconciliation_config_search
            )
        if self.heartbeat is not None:
            self.heartbeat.async_start()
        if self.scan_scheduler is not None:
            self.scan_scheduler.async_start()
        from homeassistant.helpers.start import async_at_started

        if self._initial_scan_enabled:
            unsubscribe = async_at_started(self.hass, self._schedule_initial_scan)
            if self._initial_task is None:
                self._startup_unsubscribe = unsubscribe
        if state.remediation_baselines:
            # Read the durable record back. Checkpoints were being written and
            # reloaded but never reconciled, so an interrupted repair stayed
            # interrupted silently -- truth nobody reads proves nothing.
            async_at_started(self.hass, self._async_recover_interrupted_repairs)

    async def _async_recover_interrupted_repairs(self, _event: Any = None) -> None:
        """Classify interrupted repairs once Home Assistant is fully up.

        Deferred to `started` on purpose: classification re-derives the plan
        from live entity state, which is not trustworthy mid-setup. Never
        raises -- a recovery that fails must not stop Home Assistant from
        finishing startup, and the baseline stays on disk for the next try.
        """
        try:
            state = await self.repository.async_load()
            incomplete = tuple(
                item for item in state.remediation_baselines if not item.complete
            )
            if not incomplete:
                return
            await self.remediation_lifecycle.async_recover_interrupted(incomplete)
        except Exception:  # noqa: BLE001 - startup must survive this
            _LOGGER.exception(
                "HAMIE could not classify interrupted repairs; the durable "
                "baselines remain on disk for the next attempt"
            )

    async def _reconciliation_entity_state(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        return None if state is None else state.state

    async def _reconciliation_config_search(self, needle: str):
        """Occurrences in ACTIVE configuration. Shares the repair pipeline's
        gateway so validity and repairability answer from one implementation."""
        return await self.incident_remediation.world.search_config(needle)

    async def _async_recover_corrupt_state(self, reason: str) -> Any:
        """Rebuild HAMIE's own derived state instead of failing setup forever.

        Persisted findings are derived data: the next scan regenerates them
        from Home Assistant. Previously a corrupt document raised, HAMIE never
        finished setup, and the `storage_recovery_required` repair offered the
        operator no way to act on it -- the only fix was hand-editing
        .storage. Now the unreadable bytes are quarantined (preserved for
        forensics), the live document is cleared, and HAMIE starts from empty
        state and rescans.

        Recovery runs at most once per runtime: if the freshly written
        document is unreadable again, that is a code defect rather than data
        rot, so it escalates instead of looping.
        """
        from datetime import UTC, datetime

        if self._storage_recovery_attempted:
            await self.projection.async_report_storage_error(
                "corrupt_state_recovery_failed"
            )
            raise CorruptStoredStateError(
                "stored state was unreadable again immediately after recovery"
            )
        self._storage_recovery_attempted = True

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        quarantine = None
        try:
            quarantine = await self.repository.async_quarantine_corrupt_document(
                reason=reason, quarantined_at=stamp
            )
        except Exception:  # noqa: BLE001 - recovery must not mask the original fault
            _LOGGER.exception("HAMIE could not quarantine unreadable stored state")
            await self.projection.async_report_storage_error(reason)
            raise

        # Validate the rebuilt state actually loads before continuing.
        state = await self.repository.async_load()

        self.storage_recovery = {
            "reason": reason,
            "recovered_at": stamp,
            "quarantine": quarantine.as_dict() if quarantine is not None else None,
        }
        _LOGGER.warning(
            "HAMIE recovered from unreadable stored state (%s); previous document "
            "preserved as %s. Findings will be rebuilt by the next scan.",
            reason,
            quarantine.quarantine_key if quarantine is not None else "<nothing to preserve>",
        )
        return state

    async def async_shutdown(self) -> None:
        """Cancel finite owned work and release startup listener."""
        if self._startup_unsubscribe is not None:
            self._startup_unsubscribe()
            self._startup_unsubscribe = None
        task = self._initial_task
        self._initial_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self.heartbeat is not None:
            await self.heartbeat.async_stop()
        if self.scan_scheduler is not None:
            await self.scan_scheduler.async_stop()
        await self.coordinator.async_cancel()
        if self.connectors is not None:
            await self.connectors.async_close()
        await self.projection.async_clear()

    async def _schedule_initial_scan(self, _hass: Any) -> None:
        self._startup_unsubscribe = None
        if self._initial_task is not None:
            return
        self._initial_task = self.hass.async_create_task(
            self._async_initial_scan(), "hamie_initial_scan"
        )

    async def _async_initial_scan(self) -> None:
        try:
            await asyncio.sleep(self._initial_scan_delay)
            await self.coordinator.async_request_scan(trigger="initial")
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.warning("HAMIE initial read-only evaluation failed", exc_info=True)
