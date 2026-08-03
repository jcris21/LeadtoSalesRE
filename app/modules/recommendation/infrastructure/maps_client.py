"""Google Maps client for Neighborhood Enrichment (Sprint 3B, §6.3, §7.10-§7.12).

The real HTTP call is intentionally isolated behind a single narrow method,
`nearby`, because the fan-out/fan-in adapter needs a trivially mockable seam:
tests must be able to make one property's lookup "slow" or "fail" without
touching the network, so `enrich_top3`'s timeout and partial-fallback
behaviour (§7.12) can be exercised deterministically.

US-307: the API key is wired via `Settings.google_maps_api_key` (see
`wiring.py._get_enrichment_adapter`), and the `zone` argument is now the
property's real resolved location (`PropertyLocationPort.location_for`),
not a placeholder — `NeighborhoodEnrichmentAdapter` skips this call entirely
when either is unavailable.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol

import httpx

_NEARBY_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"


class MapsNotConfiguredError(RuntimeError):
    """Raised by `GoogleMapsClient.nearby` when no API key is configured, so
    the caller never even attempts the (guaranteed-to-fail) HTTP request.
    Distinct from a real Maps failure so callers can log/handle the two
    differently (US-307)."""


class MapsClient(Protocol):
    """Seam `NeighborhoodEnrichmentAdapter` depends on — real or fake."""

    async def nearby(self, *, zone: str, property_id: uuid.UUID) -> tuple[str, ...]: ...


class GoogleMapsClient:
    """Thin wrapper around Google Places "nearby search" over `httpx.AsyncClient`.

    `api_key` comes from `Settings.google_maps_api_key` (US-307). When empty,
    `nearby` raises `MapsNotConfiguredError` immediately instead of making a
    request that would only fail on Google's side with an auth error.
    """

    def __init__(self, http_client: httpx.AsyncClient, *, api_key: str = "") -> None:
        self._http_client = http_client
        self._api_key = api_key

    async def nearby(self, *, zone: str, property_id: uuid.UUID) -> tuple[str, ...]:
        """Returns nearby place names/descriptions for a property's zone.

        `property_id` is accepted (not sent to Maps) so callers and tests can
        correlate results/timeouts per property without a side-channel map.
        """
        if not self._api_key:
            raise MapsNotConfiguredError("google_maps_api_key is not configured")
        response = await self._http_client.get(
            _NEARBY_SEARCH_URL,
            params={"location": zone, "key": self._api_key},
        )
        response.raise_for_status()
        payload = response.json()
        return tuple(result.get("name", "") for result in payload.get("results", []))


class FakeMapsClient:
    """Test double: configurable per-property delay, canned result, or failure.

    Lets tests drive every branch of §7.12 (fast success, slow-but-eventually-
    successful, and hard failure) without any real network I/O.
    """

    def __init__(
        self,
        *,
        delays: dict[uuid.UUID, float] | None = None,
        results: dict[uuid.UUID, tuple[str, ...]] | None = None,
        failures: set[uuid.UUID] | None = None,
        default_result: tuple[str, ...] = ("Park", "School", "Cafe"),
    ) -> None:
        self._delays = delays or {}
        self._results = results or {}
        self._failures = failures or set()
        self._default_result = default_result
        self.calls: list[uuid.UUID] = []

    async def nearby(self, *, zone: str, property_id: uuid.UUID) -> tuple[str, ...]:
        self.calls.append(property_id)
        delay = self._delays.get(property_id)
        if delay:
            await asyncio.sleep(delay)
        if property_id in self._failures:
            raise RuntimeError(f"Maps lookup failed for property {property_id}")
        return self._results.get(property_id, self._default_result)
