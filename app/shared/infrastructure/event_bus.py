"""Internal Event Bus: transactional Outbox on the write side, polling Inbox-guarded
dispatcher on the read side. No external broker — everything lives in the same
Postgres as the aggregates (Architecture.md §5: "Event Bus interno ... sin
infraestructura de broker externa").
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import session_scope
from app.shared.domain.base import DomainEvent
from app.shared.infrastructure.db_models import InboxRecordORM, OutboxEventORM

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict], Awaitable[None]]


async def publish(session: AsyncSession, events: list[DomainEvent]) -> None:
    """Write events to the outbox in the CALLER's transaction. Must be invoked
    before the surrounding session commits, never after — that is the whole
    point of the transactional outbox pattern."""
    for event in events:
        session.add(
            OutboxEventORM(
                event_id=event.event_id,
                event_type=event.event_type,
                organization_id=event.organization_id,
                payload=_serialize(event),
                occurred_at=event.occurred_at,
                attempts=0,
            )
        )


def _serialize(event: DomainEvent) -> dict:
    data = asdict(event)
    data.pop("event_id", None)
    data.pop("occurred_at", None)
    data.pop("organization_id", None)
    return {"event_type": event.event_type, "fields": data}


class EventBusWorker:
    """Single-writer polling worker (Architecture.md §5.1: "Outbox Worker single-writer,
    auto-restart"). Dispatches each unprocessed outbox row to every handler registered
    for its event_type, skipping handlers that already have an inbox record for that
    event_id (idempotent re-delivery)."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[str, EventHandler]]] = defaultdict(list)
        self._running = False

    def register(self, event_type: str, consumer_name: str, handler: EventHandler) -> None:
        self._handlers[event_type].append((consumer_name, handler))

    async def run_forever(self) -> None:
        settings = get_settings()
        self._running = True
        while self._running:
            processed = await self._drain_batch(settings.outbox_batch_size)
            if processed == 0:
                await asyncio.sleep(settings.outbox_poll_interval_seconds)

    def stop(self) -> None:
        self._running = False

    async def _drain_batch(self, batch_size: int) -> int:
        async with session_scope() as session:
            result = await session.execute(
                select(OutboxEventORM)
                .where(OutboxEventORM.processed_at.is_(None))
                .order_by(OutboxEventORM.occurred_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            rows = list(result.scalars().all())
            for row in rows:
                await self._dispatch_row(session, row)
            return len(rows)

    async def _dispatch_row(self, session: AsyncSession, row: OutboxEventORM) -> None:
        from datetime import datetime

        handlers = self._handlers.get(row.event_type, [])
        for consumer_name, handler in handlers:
            already_done = await session.get(InboxRecordORM, (consumer_name, row.event_id))
            if already_done is not None:
                continue
            try:
                await handler(row.payload)
                session.add(
                    InboxRecordORM(
                        consumer_name=consumer_name,
                        event_id=row.event_id,
                        processed_at=datetime.now(UTC),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - contained per-handler, not fatal to the worker
                row.attempts += 1
                row.last_error = f"{consumer_name}: {exc}"
                logger.exception(
                    "Event handler failed",
                    extra={"consumer": consumer_name, "event_id": str(row.event_id)},
                )
                return  # leave row unprocessed; retried next poll
        row.processed_at = datetime.now(UTC)


event_bus = EventBusWorker()
