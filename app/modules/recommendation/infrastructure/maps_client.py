"""Google Maps client for Neighborhood Enrichment (Sprint 3B, §6.3, §7.10-§7.12).

The real HTTP call is intentionally isolated behind a single narrow method,
`nearby`, because this codebase has no Google Maps API key/config wiring yet
(out of scope for this sprint) and because the fan-out/fan-in adapter needs a
trivially mockable seam: tests must be able to make one property's lookup
"slow" or "fail" without touching the network, so `enrich_top3`'s timeout and
partial-fallback behaviour (§7.12) can be exercised deterministically.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol

import httpx

_NEARBY_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"


class MapsClient(Protocol):
    """Seam `NeighborhoodEnrichmentAdapter` depends on — real or fake."""

    async def nearby(self, *, zone: str, property_id: uuid.UUID) -> tuple[str, ...]: ...


class GoogleMapsClient:
    """Thin wrapper around Google Places "nearby search" over `httpx.AsyncClient`.

    No API key/config is wired here (that is explicitly out of scope for this
    task) — this class only defines the shape of the real call so it can be
    completed later without touching the application layer above it.
    """

    def __init__(self, http_client: httpx.AsyncClient, *, api_key: str = "") -> None:
        self._http_client = http_client
        self._api_key = api_key

    async def nearby(self, *, zone: str, property_id: uuid.UUID) -> tuple[str, ...]:
        """Returns nearby place names/descriptions for a property's zone.

        `property_id` is accepted (not sent to Maps) so callers and tests can
        correlate results/timeouts per property without a side-channel map.
        """
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
