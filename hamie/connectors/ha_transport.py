"""Home Assistant shared-session JSON transport adapter."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from .base import ConnectorTestError, HttpResult

_LOGGER = logging.getLogger(__name__)


class HomeAssistantHttpTransport:
    """Use Home Assistant's owned async session without blocking the event loop."""

    def __init__(self, session: Any) -> None:
        self._session = session

    async def async_request_json(
        self,
        *,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
        headers: dict[str, str],
        timeout: float,
        verify_tls: bool,
        maximum_response_bytes: int = 128_000,
    ) -> HttpResult:
        """Perform one bounded explicit request."""
        await _async_validate_resolved_host(url)
        started = monotonic()
        async with asyncio.timeout(timeout):
            async with self._session.request(
                method,
                url,
                json=payload,
                headers=headers,
                ssl=verify_tls,
                allow_redirects=False,
            ) as response:
                raw = await _read_bounded_body(response, maximum_response_bytes)
                try:
                    data = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as err:
                    _LOGGER.debug(
                        "HAMIE connector response was not valid JSON: "
                        "url=%s status=%s body_bytes=%d",
                        url,
                        response.status,
                        len(raw),
                    )
                    raise ConnectorTestError("provider_response_not_json") from err
                return HttpResult(
                    status=response.status,
                    data=data,
                    latency_ms=max(0, int((monotonic() - started) * 1_000)),
                )


_READ_CHUNK_BYTES = 65_536


async def _read_bounded_body(response: Any, maximum_response_bytes: int) -> bytes:
    """Drain the full response body up to a byte cap, never a single short read.

    ``response.content.read(n)`` (``aiohttp.StreamReader.read``) only
    waits for the buffer to become non-empty, then returns whatever is
    *currently* buffered -- up to ``n`` bytes, but frequently far fewer
    for any response that arrives across more than one chunk (routine
    for a real LLM completion body, never an issue for the tiny
    single-chunk ``/api/tags`` health-check response). A single
    ``read(maximum_response_bytes + 1)`` call therefore silently
    truncates larger real responses mid-JSON, which every caller then
    (wrongly) reports as "not valid JSON... check the proxy" even
    though the connector and the full response were both fine. Looping
    ``read(chunk_size)`` until EOF (``b""``) reads the complete body
    while still enforcing the byte cap incrementally.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await response.content.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > maximum_response_bytes:
            raise ValueError("connector response exceeds configured limit")
        chunks.append(chunk)
    return b"".join(chunks)


async def _async_validate_resolved_host(url: str) -> None:
    """Reject unsafe DNS results before opening the explicit finite request."""
    parsed = urlsplit(url)
    host = parsed.hostname
    if host is None:
        raise ConnectorTestError("invalid_url")
    addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]
    try:
        addresses = (ipaddress.ip_address(host),)
    except ValueError:
        try:
            resolved = await asyncio.get_running_loop().getaddrinfo(
                host,
                parsed.port,
                type=socket.SOCK_STREAM,
            )
        except OSError as err:
            raise ConnectorTestError("unreachable") from err
        addresses = tuple(
            dict.fromkeys(ipaddress.ip_address(item[4][0]) for item in resolved)
        )
    if not addresses:
        raise ConnectorTestError("unreachable")
    if any(
        address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        for address in addresses
    ):
        raise ConnectorTestError("host_not_allowed")
