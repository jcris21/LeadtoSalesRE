"""Tests for the Neighborhood Enrichment Adapter (Sprint 3B, §7.10/§7.12).

Covers the fan-out/fan-in contract: all-fast success, one-slow partial
fallback, background retry publishing `NeighborhoodEnriched` to the outbox
after a late success, a hard-failing property not blocking its siblings, and
the overall call being bounded by `timeout_ms` rather than by the slowest
property.
"""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import select

from app.modules.recommendation.application.neighborhood_enrichment import (
    NeighborhoodEnrichmentAdapter,
)
from app.modules.recommendation.infrastructure.maps_client import (
    FakeMapsClient,
    GoogleMapsClient,
    MapsNotConfiguredError,
)
from app.shared.infrastructure.db_models import OutboxEventORM

LEAD_ID = uuid.uuid4()


def _three_property_ids() -> list[uuid.UUID]:
    return [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]


class _FakeLocationLookup:
    """Test double for `PropertyLocationPort` (US-307): a plain dict of
    `property_id -> location | None`, so tests can assert exactly what
    `MapsClient.nearby` was called with."""

    def __init__(self, locations: dict[uuid.UUID, str | None]) -> None:
        self._locations = locations
        self.calls: list[uuid.UUID] = []

    async def location_for(self, property_id: uuid.UUID) -> str | None:
        self.calls.append(property_id)
        return self._locations.get(property_id)


class _RecordingMapsClient:
    """Test double that just records the `zone` it was called with, so tests
    can assert the adapter passed a real resolved location, not `property_id`."""

    def __init__(self) -> None:
        self.zones_called: list[str] = []

    async def nearby(self, *, zone: str, property_id: uuid.UUID) -> tuple[str, ...]:
        self.zones_called.append(zone)
        return ("Park",)


@pytest.mark.asyncio
async def test_all_fast_returns_full_insights_for_every_property():
    property_ids = _three_property_ids()
    client = FakeMapsClient()
    adapter = NeighborhoodEnrichmentAdapter(client)

    result = await adapter.enrich_top3(lead_id=LEAD_ID, property_ids=property_ids, timeout_ms=200)

    assert set(result.keys()) == set(property_ids)
    for property_id in property_ids:
        insight = result[property_id]
        assert insight is not None
        assert insight.partial is False
        assert insight.nearby_places == ("Park", "School", "Cafe")


@pytest.mark.asyncio
async def test_one_slow_property_returns_none_for_it_and_populates_the_rest(session_factory):
    # `session_factory` swaps in the in-memory SQLite engine (see conftest.py)
    # so the background retry's late `publish` (it succeeds after 0.3s here)
    # has somewhere real to write instead of reaching for the unconfigured
    # production Postgres connection.
    fast_a, fast_b, slow = _three_property_ids()
    client = FakeMapsClient(delays={slow: 0.3})
    adapter = NeighborhoodEnrichmentAdapter(client, retry_timeout_ms=1_000)

    result = await adapter.enrich_top3(
        lead_id=LEAD_ID, property_ids=[fast_a, fast_b, slow], timeout_ms=50
    )

    assert result[fast_a] is not None
    assert result[fast_b] is not None
    assert result[slow] is None

    # Don't leave the background retry task dangling past the test.
    await adapter.wait_for_background()


@pytest.mark.asyncio
async def test_failing_property_does_not_crash_or_block_siblings():
    fast_a, fast_b, failing = _three_property_ids()
    client = FakeMapsClient(failures={failing})
    adapter = NeighborhoodEnrichmentAdapter(client, max_retries=1, retry_timeout_ms=50)

    result = await adapter.enrich_top3(
        lead_id=LEAD_ID, property_ids=[fast_a, fast_b, failing], timeout_ms=200
    )

    assert result[fast_a] is not None
    assert result[fast_b] is not None
    assert result[failing] is None

    # The background retry will also fail (client always raises for this id)
    # and must give up quietly rather than raising out of the task.
    await adapter.wait_for_background()


@pytest.mark.asyncio
async def test_enrich_top3_wall_clock_is_bounded_by_timeout_not_slowest_property(session_factory):
    # session_factory: the background retry here still misses its own
    # (shorter) timeout since the property sleeps 5s, so no publish happens,
    # but wiring the in-memory engine keeps this test independent of ordering
    # relative to the other tests that do publish.
    fast_a, fast_b, slow = _three_property_ids()
    client = FakeMapsClient(delays={slow: 5.0})
    adapter = NeighborhoodEnrichmentAdapter(client, retry_timeout_ms=1_000)

    started = time.monotonic()
    await adapter.enrich_top3(lead_id=LEAD_ID, property_ids=[fast_a, fast_b, slow], timeout_ms=50)
    elapsed = time.monotonic() - started

    # Generous margin to avoid flakiness: bounded by the 50ms timeout, nowhere
    # near the property's 5s delay.
    assert elapsed < 0.5

    await adapter.wait_for_background()


@pytest.mark.asyncio
async def test_background_retry_publishes_neighborhood_enriched_after_late_success(
    session_factory, db_session
):
    property_id = uuid.uuid4()
    # First call (inside enrich_top3's timeout window) is slow enough to miss
    # the budget; the retry call for the same property_id succeeds fast.
    client = FakeMapsClient(delays={property_id: 0.2})
    adapter = NeighborhoodEnrichmentAdapter(client, max_retries=1, retry_timeout_ms=5_000)

    result = await adapter.enrich_top3(
        lead_id=LEAD_ID, property_ids=[property_id], timeout_ms=20
    )
    assert result[property_id] is None

    # Let the background retry run to completion (it re-calls the same fake
    # client method, which no longer needs to wait out a fresh delay budget
    # since `retry_timeout_ms` is generous).
    await adapter.wait_for_background()

    result_rows = await db_session.execute(
        select(OutboxEventORM).where(OutboxEventORM.event_type == "NeighborhoodEnriched")
    )
    rows = result_rows.scalars().all()
    assert len(rows) == 1
    fields = rows[0].payload["fields"]
    assert fields["lead_id"] == str(LEAD_ID)
    assert fields["property_id"] == str(property_id)
    assert fields["nearby_places"] == ["Park", "School", "Cafe"]


@pytest.mark.asyncio
async def test_background_retry_gives_up_after_bounded_attempts_without_raising():
    property_id = uuid.uuid4()
    client = FakeMapsClient(failures={property_id})
    adapter = NeighborhoodEnrichmentAdapter(client, max_retries=2, retry_timeout_ms=50)

    result = await adapter.enrich_top3(lead_id=LEAD_ID, property_ids=[property_id], timeout_ms=10)
    assert result[property_id] is None

    # Should not raise, and should stop after max_retries attempts (1 initial
    # fan-out call + 2 retry attempts = 3 total calls recorded by the fake).
    await adapter.wait_for_background()
    assert len(client.calls) == 1 + adapter._max_retries


@pytest.mark.asyncio
async def test_no_api_key_configured_skips_http_call_for_every_property():
    """US-307: `GoogleMapsClient` with an empty key must never attempt the
    HTTP request — the adapter resolves every property to `None` instead."""
    property_ids = _three_property_ids()
    client = GoogleMapsClient(http_client=None, api_key="")  # http_client unused: never called
    adapter = NeighborhoodEnrichmentAdapter(client)

    result = await adapter.enrich_top3(lead_id=LEAD_ID, property_ids=property_ids, timeout_ms=200)

    assert result == {property_id: None for property_id in property_ids}


@pytest.mark.asyncio
async def test_maps_not_configured_error_raised_without_a_real_request():
    with pytest.raises(MapsNotConfiguredError):
        await GoogleMapsClient(http_client=None, api_key="").nearby(
            zone="Palermo", property_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_enrich_top3_resolves_real_location_instead_of_property_id():
    """US-307: when a `location_lookup` is wired, the Maps call must use the
    property's real resolved location, not the `property_id` placeholder."""
    property_id = uuid.uuid4()
    client = _RecordingMapsClient()
    lookup = _FakeLocationLookup({property_id: "Palermo, Buenos Aires"})
    adapter = NeighborhoodEnrichmentAdapter(client, location_lookup=lookup)

    result = await adapter.enrich_top3(
        lead_id=LEAD_ID, property_ids=[property_id], timeout_ms=200
    )

    assert client.zones_called == ["Palermo, Buenos Aires"]
    assert result[property_id] is not None
    assert result[property_id].nearby_places == ("Park",)


@pytest.mark.asyncio
async def test_property_with_no_resolvable_location_is_skipped_without_blocking_siblings():
    """US-307: a property with nothing in `PropertyLocationPort` resolves to
    `None` without a Maps call, and does not affect its siblings' results."""
    has_location, no_location = uuid.uuid4(), uuid.uuid4()
    client = _RecordingMapsClient()
    lookup = _FakeLocationLookup({has_location: "Palermo, Buenos Aires", no_location: None})
    adapter = NeighborhoodEnrichmentAdapter(client, location_lookup=lookup)

    result = await adapter.enrich_top3(
        lead_id=LEAD_ID, property_ids=[has_location, no_location], timeout_ms=200
    )

    assert client.zones_called == ["Palermo, Buenos Aires"]
    assert result[has_location] is not None
    assert result[no_location] is None
