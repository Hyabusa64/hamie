"""Corrupt HAMIE-owned derived state must recover without .storage surgery."""

from __future__ import annotations

import pytest

from hamie.application.persistence import CorruptStoredStateError, RepositoryState
from hamie.infrastructure.storage import QuarantineRecord


class _Projection:
    def __init__(self) -> None:
        self.storage_errors: list[str] = []
        self.synced: list[RepositoryState] = []

    async def async_report_storage_error(self, reason_code: str) -> None:
        self.storage_errors.append(reason_code)

    async def async_sync(self, state: RepositoryState) -> None:
        self.synced.append(state)


class _Repo:
    """Loads clean after quarantine.

    `_async_recover_corrupt_state` is invoked *after* the initial failing
    load, so failures=0 models the normal path: the reload inside recovery
    must succeed against the freshly-cleared document.
    """

    def __init__(self, *, failures: int) -> None:
        self.failures = failures
        self.quarantined: list[str] = []
        self.loads = 0

    async def async_load(self) -> RepositoryState:
        self.loads += 1
        if self.failures > 0:
            self.failures -= 1
            raise CorruptStoredStateError("payload failed validation")
        return RepositoryState()

    async def async_quarantine_corrupt_document(
        self, *, reason: str, quarantined_at: str
    ) -> QuarantineRecord:
        self.quarantined.append(quarantined_at)
        return QuarantineRecord(
            quarantine_key=f"hamie.state.corrupt.{quarantined_at}",
            reason=reason,
            quarantined_at=quarantined_at,
            schema_version=9,
            document_bytes=1234,
        )


def _runtime(repo, projection):
    from hamie.application.runtime import HamieRuntime

    rt = HamieRuntime.__new__(HamieRuntime)
    rt.repository = repo
    rt.projection = projection
    rt._storage_recovery_attempted = False
    rt.storage_recovery = None
    return rt


@pytest.mark.asyncio
async def test_corrupt_state_is_quarantined_and_rebuilt() -> None:
    repo, proj = _Repo(failures=0), _Projection()
    rt = _runtime(repo, proj)
    state = await rt._async_recover_corrupt_state("corrupt_state")

    assert isinstance(state, RepositoryState)
    assert state.generation == 0, "must restart from clean derived state"
    assert repo.quarantined, "corrupt document must be preserved, not discarded"
    assert rt.storage_recovery is not None
    assert rt.storage_recovery["reason"] == "corrupt_state"
    assert rt.storage_recovery["quarantine"]["quarantine_key"].startswith(
        "hamie.state.corrupt."
    )
    assert rt.storage_recovery["quarantine"]["document_bytes"] == 1234


@pytest.mark.asyncio
async def test_recovery_records_forensic_metadata() -> None:
    repo, proj = _Repo(failures=0), _Projection()
    rt = _runtime(repo, proj)
    await rt._async_recover_corrupt_state("corrupt_state")
    q = rt.storage_recovery["quarantine"]
    assert q["schema_version"] == 9
    assert q["reason"] == "corrupt_state"


@pytest.mark.asyncio
async def test_recovery_does_not_loop() -> None:
    """A document corrupt again right after rebuild escalates, never loops."""
    repo, proj = _Repo(failures=99), _Projection()
    rt = _runtime(repo, proj)
    rt._storage_recovery_attempted = True  # simulate one attempt already made

    with pytest.raises(CorruptStoredStateError):
        await rt._async_recover_corrupt_state("corrupt_state")
    assert proj.storage_errors == ["corrupt_state_recovery_failed"]
    assert repo.quarantined == [], "must not quarantine repeatedly"


@pytest.mark.asyncio
async def test_second_recovery_blocked_after_first_succeeds() -> None:
    repo, proj = _Repo(failures=0), _Projection()
    rt = _runtime(repo, proj)
    await rt._async_recover_corrupt_state("corrupt_state")
    with pytest.raises(CorruptStoredStateError):
        await rt._async_recover_corrupt_state("corrupt_state")
    assert proj.storage_errors == ["corrupt_state_recovery_failed"]


@pytest.mark.asyncio
async def test_quarantine_failure_still_reports_storage_error() -> None:
    class _BadRepo(_Repo):
        async def async_quarantine_corrupt_document(self, **_: object):
            raise OSError("disk full")

    repo, proj = _BadRepo(failures=0), _Projection()
    rt = _runtime(repo, proj)
    with pytest.raises(OSError):
        await rt._async_recover_corrupt_state("corrupt_state")
    assert proj.storage_errors == ["corrupt_state"]
