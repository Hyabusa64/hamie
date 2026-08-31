"""Local read-only scan and HAMIE-only review services."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .application.runtime import HamieRuntime
from .const import DOMAIN

SERVICE_SCAN = "scan"
SERVICE_ACKNOWLEDGE = "acknowledge"
SERVICE_SNOOZE = "snooze"
SERVICE_RETAIN = "retain"
SERVICE_DISMISS = "dismiss"
SERVICES = (
    SERVICE_SCAN,
    SERVICE_ACKNOWLEDGE,
    SERVICE_SNOOZE,
    SERVICE_RETAIN,
    SERVICE_DISMISS,
)
MAX_IDENTIFIER_LENGTH = 128
MAX_REASON_LENGTH = 500
MAX_TIMESTAMP_LENGTH = 64


class ServiceDataSchema:
    """Dependency-free strict schema callable accepted by HA's service registry."""

    def __init__(self, service: str) -> None:
        self._service = service

    def __call__(self, value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("service data must be an object")
        data = dict(value)
        if self._service == SERVICE_SCAN:
            if data:
                raise ValueError("scan accepts no fields")
            return data
        required = {"finding_id", "expected_revision", "idempotency_token"}
        allowed = set(required)
        if self._service in {SERVICE_SNOOZE, SERVICE_RETAIN, SERVICE_DISMISS}:
            allowed.add("reason")
        if self._service == SERVICE_SNOOZE:
            required.add("snooze_until")
            allowed.add("snooze_until")
        unknown = set(data) - allowed
        missing = required - set(data)
        if unknown:
            raise ValueError(f"unknown service fields: {sorted(unknown)!r}")
        if missing:
            raise ValueError(f"missing service fields: {sorted(missing)!r}")
        _bounded_text(data, "finding_id", MAX_IDENTIFIER_LENGTH)
        _bounded_text(data, "idempotency_token", MAX_IDENTIFIER_LENGTH)
        revision = data["expected_revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("expected_revision must be a positive integer")
        if "reason" in data and data["reason"] is not None:
            _bounded_text(data, "reason", MAX_REASON_LENGTH)
        if "snooze_until" in data:
            _bounded_text(data, "snooze_until", MAX_TIMESTAMP_LENGTH)
        return data


def register_services(hass: Any, runtime: HamieRuntime) -> None:
    """Register bounded local application commands for the single entry."""

    async def scan(_call: Any) -> None:
        await runtime.application.async_start_full_evaluation()

    async def review(call: Any) -> None:
        data = call.data
        finding_id = _required_text(data, "finding_id")
        token = _required_text(data, "idempotency_token")
        context = getattr(call, "context", None)
        user_id = getattr(context, "user_id", None)
        actor = (
            f"home_assistant_user:{user_id}"
            if isinstance(user_id, str) and user_id
            else "home_assistant"
        )
        revision = data.get("expected_revision")
        if not isinstance(revision, int) or revision < 1:
            raise ValueError("expected_revision must be a positive integer")
        reason = data.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("reason must be text")
        if call.service == SERVICE_ACKNOWLEDGE:
            await runtime.application.async_acknowledge(
                finding_id,
                expected_revision=revision,
                token=token,
                actor=actor,
            )
        elif call.service == SERVICE_SNOOZE:
            raw_until = _required_text(data, "snooze_until")
            try:
                until = datetime.fromisoformat(raw_until.replace("Z", "+00:00"))
            except ValueError as err:
                raise ValueError("snooze_until must be an ISO timestamp") from err
            await runtime.application.async_snooze(
                finding_id,
                expected_revision=revision,
                token=token,
                actor=actor,
                reason=reason,
                snooze_until=until,
            )
        elif call.service == SERVICE_RETAIN:
            await runtime.application.async_retain(
                finding_id,
                expected_revision=revision,
                token=token,
                actor=actor,
                reason=reason,
            )
        elif call.service == SERVICE_DISMISS:
            await runtime.application.async_dismiss(
                finding_id,
                expected_revision=revision,
                token=token,
                actor=actor,
                reason=reason,
            )

    hass.services.async_register(
        DOMAIN, SERVICE_SCAN, scan, schema=ServiceDataSchema(SERVICE_SCAN)
    )
    for service in SERVICES[1:]:
        hass.services.async_register(
            DOMAIN, service, review, schema=ServiceDataSchema(service)
        )


def unregister_services(hass: Any) -> None:
    """Remove all HAMIE services on entry unload."""
    for service in SERVICES:
        hass.services.async_remove(DOMAIN, service)


def _required_text(data: dict[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty normalized text")
    return value


def _bounded_text(data: dict[str, Any], name: str, maximum: int) -> str:
    value = data.get(name)
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > maximum
    ):
        raise ValueError(
            f"{name} must be non-empty normalized text of at most {maximum} characters"
        )
    return value
