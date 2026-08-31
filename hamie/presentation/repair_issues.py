"""Quiet projection of committed findings to Home Assistant Repairs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..analysis.analyzers.unavailable_entities import ANALYZER_ID
from ..application.persistence import RepositoryState
from ..const import DOMAIN
from ..domain.common import stable_digest
from ..domain.findings import FindingLifecycle
from ..domain.reviews import ReviewState

VISIBLE_REVIEW_STATES = frozenset({ReviewState.NEW, ReviewState.ACKNOWLEDGED})
UNAVAILABLE_TRANSLATION_KEY = "unavailable_entity"
STORAGE_TRANSLATION_KEY = "storage_recovery_required"
OWNED_TRANSLATION_KEYS = frozenset(
    {UNAVAILABLE_TRANSLATION_KEY, STORAGE_TRANSLATION_KEY}
)
STORAGE_ISSUE_ID = "storage_recovery_required"


class RepairIssueProjection:
    """Synchronize stable issue IDs without repeated updates for unchanged data."""

    def __init__(
        self,
        hass: Any,
        *,
        create_issue: Callable[..., None] | None = None,
        delete_issue: Callable[[str], None] | None = None,
        existing_issues: Callable[[], Mapping[str, str | None]] | None = None,
    ) -> None:
        self._hass = hass
        self._create_issue = create_issue or self._ha_create
        self._delete_issue = delete_issue or self._ha_delete
        self._existing_issues = existing_issues or self._ha_existing
        self._published: dict[str, str] = {}

    async def async_sync(self, state: RepositoryState) -> None:
        """Project current actionable findings after canonical commit."""
        desired: dict[str, tuple[str, str, dict[str, str]]] = {}
        for finding in state.findings:
            if (
                finding.lifecycle is not FindingLifecycle.OPEN
                or finding.analyzer_id != ANALYZER_ID
                or finding.review_state not in VISIBLE_REVIEW_STATES
            ):
                continue
            placeholders = dict(finding.description_arguments)
            digest = stable_digest(
                finding.finding_id,
                finding.content_revision,
                finding.severity.value,
                finding.review_state.value,
                placeholders,
            )
            desired[finding.finding_id] = (
                digest,
                UNAVAILABLE_TRANSLATION_KEY,
                placeholders,
            )

        existing = dict(self._existing_issues())
        known = set(existing) | set(self._published)
        for issue_id in sorted(known - set(desired)):
            self._delete_issue(issue_id)
            self._published.pop(issue_id, None)
        for issue_id, (digest, translation_key, placeholders) in sorted(
            desired.items()
        ):
            if (
                self._published.get(issue_id) == digest
                or existing.get(issue_id) == digest
            ):
                self._published[issue_id] = digest
                continue
            self._create_issue(issue_id, translation_key, placeholders, digest)
            self._published[issue_id] = digest

    async def async_clear(self) -> None:
        """Remove every HAMIE-owned derived issue on unload or removal."""
        for issue_id in sorted(set(self._existing_issues()) | set(self._published)):
            self._delete_issue(issue_id)
        self._published.clear()

    async def async_report_storage_error(self, reason_code: str) -> None:
        """Publish one stable actionable issue without exposing stored content."""
        digest = stable_digest(STORAGE_TRANSLATION_KEY, reason_code)
        existing = self._existing_issues()
        if (
            self._published.get(STORAGE_ISSUE_ID) == digest
            or existing.get(STORAGE_ISSUE_ID) == digest
        ):
            self._published[STORAGE_ISSUE_ID] = digest
            return
        self._create_issue(
            STORAGE_ISSUE_ID,
            STORAGE_TRANSLATION_KEY,
            {"reason_code": reason_code},
            digest,
        )
        self._published[STORAGE_ISSUE_ID] = digest

    def _ha_create(
        self,
        issue_id: str,
        translation_key: str,
        placeholders: dict[str, str],
        digest: str,
    ) -> None:
        from homeassistant.helpers import issue_registry as ir

        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=translation_key,
            translation_placeholders=placeholders,
            data={"finding_id": issue_id, "projection_digest": digest},
        )

    def _ha_delete(self, issue_id: str) -> None:
        from homeassistant.helpers import issue_registry as ir

        ir.async_delete_issue(self._hass, DOMAIN, issue_id)

    def _ha_existing(self) -> dict[str, str | None]:
        from homeassistant.helpers import issue_registry as ir

        registry = ir.async_get(self._hass)
        return {
            issue_id: (
                issue.data.get("projection_digest")
                if isinstance(getattr(issue, "data", None), dict)
                else None
            )
            for (domain, issue_id), issue in registry.issues.items()
            if domain == DOMAIN
            and getattr(issue, "translation_key", None) in OWNED_TRANSLATION_KEYS
        }
