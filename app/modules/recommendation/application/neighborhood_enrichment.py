"""Neighborhood Enrichment Adapter (Sprint 3B, isolated per
`Documents/Oficial/ArchitecturalDrivers.md`: "Enriquece un flujo de
recomendación ya funcionando; puede atrasarse sin bloquear Sprint 4").

Implements the fan-out/fan-in + partial-fallback + late-retry sequence from
Architecture.md §6.3, §7.10 and §7.12:

- §7.10: all Top-3 properties are looked up in Google Maps in parallel so the
  total recommendation response stays under the QA-01 budget (<15s) even
  though each individual Maps call may be slow.
- §7.12: any property whose Maps call does not return within `timeout_ms`
  gets `None` in the immediate result (a "Top-3 sin NeighborhoodInsight para
  esa propiedad") rather than blocking or failing the whole batch. The slow
  call keeps running in the background, *outside* the critical path, and if
  it eventually succeeds we publish `NeighborhoodEnriched` to the outbox so
  the Coordinator can send the lead a follow-up message later.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.core.database import get_session_factory
from app.modules.recommendation.domain.models import NeighborhoodEnriched, NeighborhoodInsight
from app.modules.recommendation.infrastructure.maps_client import MapsClient
from app.shared.infrastructure.event_bus import publish

logger = logging.getLogger(__name__)

_DEFAULT_RETRY_TIMEOUT_MS = 10_000
_DEFAULT_MAX_RETRIES = 1


class NeighborhoodEnrichmentAdapter:
    """`NeighborhoodEnrichmentPort` implementation backed by a `MapsClient`.

    Note on `zone`: the port contract (`domain/ports.py`, not modifiable here)
    only carries `property_id`s, not each property's zone — resolving a
    property to its zone is out of scope for this sprint, so the Maps lookup
    is keyed by the property id itself. Wiring a real zone lookup is a
    follow-up once a `Property` repository is passed in here.
    """

    def __init__(
        self,
        client: MapsClient,
        *,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_timeout_ms: int = _DEFAULT_RETRY_TIMEOUT_MS,
    ) -> None:
        self._client = client
        self._max_retries = max_retries
        self._retry_timeout_ms = retry_timeout_ms
        # Fire-and-forget background retries must be kept alive somewhere or
        # the event loop may garbage-collect them mid-flight (a well-known
        # asyncio footgun) — this set is that anchor. Tasks remove themselves
        # via `add_done_callback` once finished, success or failure.
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def enrich_top3(
        self, *, lead_id: uuid.UUID, property_ids: list[uuid.UUID], timeout_ms: int
    ) -> dict[uuid.UUID, NeighborhoodInsight | None]:
        """Fan-out to Maps for every property, fan-in with a shared budget.

        Each lookup is wrapped in its own try/except so one property's
        timeout or hard failure can never block or fail its siblings (§7.12).
        A per-property timeout also triggers a bounded, non-blocking
        background retry (see `_schedule_retry`).
        """
        timeout_s = timeout_ms / 1000

        async def fetch_one(property_id: uuid.UUID) -> tuple[uuid.UUID, NeighborhoodInsight | None]:
            try:
                nearby_places = await asyncio.wait_for(
                    self._client.nearby(zone=str(property_id), property_id=property_id),
                    timeout=timeout_s,
                )
            except Exception:  # noqa: BLE001 - timeout or Maps failure, both handled the same way
                logger.info(
                    "Neighborhood enrichment missed budget for property %s; "
                    "returning partial fallback and scheduling background retry",
                    property_id,
                )
                self._schedule_retry(lead_id=lead_id, property_id=property_id)
                return property_id, None
            return property_id, NeighborhoodInsight(property_id=property_id, nearby_places=nearby_places, partial=False)

        pairs = await asyncio.gather(*(fetch_one(property_id) for property_id in property_ids))
        return dict(pairs)

    def _schedule_retry(self, *, lead_id: uuid.UUID, property_id: uuid.UUID) -> None:
        """Kicks off the §7.12 background retry without awaiting it.

        This runs "fuera del camino crítico": the caller (and the request
        that triggered `enrich_top3`) must never wait on it. The task
        reference is stashed in `self._background_tasks` so it survives past
        the end of `enrich_top3`, and removed once it finishes either way.
        """
        task = asyncio.create_task(self._retry_and_publish(lead_id=lead_id, property_id=property_id))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _retry_and_publish(self, *, lead_id: uuid.UUID, property_id: uuid.UUID) -> None:
        """Retries the Maps lookup a bounded number of times, off the request
        path. Retries are capped (default: 1) because this is a best-effort
        enrichment, not a critical operation — an unbounded retry loop would
        risk piling up background tasks against a Maps outage for no benefit
        the lead ever sees synchronously. On success, publishes
        `NeighborhoodEnriched` in its own transaction (there is no caller
        transaction to piggy-back on, since this runs outside any request).
        """
        for attempt in range(1, self._max_retries + 1):
            try:
                nearby_places = await asyncio.wait_for(
                    self._client.nearby(zone=str(property_id), property_id=property_id),
                    timeout=self._retry_timeout_ms / 1000,
                )
            except Exception:  # noqa: BLE001 - keep retrying up to the bound, then give up
                logger.warning(
                    "Background neighborhood retry %d/%d failed for property %s",
                    attempt,
                    self._max_retries,
                    property_id,
                )
                continue

            await self._publish_late_insight(
                lead_id=lead_id, property_id=property_id, nearby_places=nearby_places
            )
            return

        logger.error(
            "Neighborhood enrichment giving up on property %s after %d retries",
            property_id,
            self._max_retries,
        )

    async def _publish_late_insight(
        self, *, lead_id: uuid.UUID, property_id: uuid.UUID, nearby_places: tuple[str, ...]
    ) -> None:
        event = NeighborhoodEnriched(
            lead_id=str(lead_id),
            property_id=str(property_id),
            nearby_places=nearby_places,
        )
        async with get_session_factory()() as session:
            await publish(session, [event])
            await session.commit()

    async def wait_for_background(self) -> None:
        """Test-only helper: await every in-flight background retry.

        Production code never calls this (that would defeat the point of
        firing the retry off the critical path) — it exists purely so tests
        can assert on the eventual outbox write deterministically instead of
        sleeping and hoping the task finished in time.
        """
        pending = list(self._background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
