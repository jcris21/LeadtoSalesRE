from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.shared.domain.base import DomainEvent, new_id
from app.shared.infrastructure.db_models import OutboxEventORM
from app.shared.infrastructure.event_bus import EventBusWorker, publish


@dataclass(frozen=True)
class SampleEvent(DomainEvent):
    note: str = ""


@pytest.mark.asyncio
async def test_publish_writes_outbox_row(db_session):
    event = SampleEvent(organization_id=new_id(), note="hello")
    await publish(db_session, [event])
    await db_session.commit()

    result = await db_session.execute(
        select(OutboxEventORM).where(OutboxEventORM.event_id == event.event_id)
    )
    row = result.scalar_one()
    assert row.event_type == "SampleEvent"
    assert row.processed_at is None


@pytest.mark.asyncio
async def test_dispatch_is_idempotent_across_redelivery(db_session):
    event = SampleEvent(organization_id=new_id(), note="hello")
    await publish(db_session, [event])
    await db_session.commit()

    calls: list[dict] = []

    async def handler(payload: dict) -> None:
        calls.append(payload)

    worker = EventBusWorker()
    worker.register("SampleEvent", "test-consumer", handler)

    result = await db_session.execute(
        select(OutboxEventORM).where(OutboxEventORM.event_id == event.event_id)
    )
    row = result.scalar_one()

    # First delivery: handler runs, inbox record + processed_at get set.
    await worker._dispatch_row(db_session, row)
    await db_session.commit()
    assert len(calls) == 1
    assert row.processed_at is not None

    # Re-delivery of the SAME event to the SAME consumer must be a no-op.
    row.processed_at = None  # simulate a worker restart re-scanning the row
    await worker._dispatch_row(db_session, row)
    await db_session.commit()
    assert len(calls) == 1  # handler NOT invoked again


@pytest.mark.asyncio
async def test_handler_failure_leaves_row_unprocessed(db_session):
    event = SampleEvent(organization_id=new_id(), note="boom")
    await publish(db_session, [event])
    await db_session.commit()

    async def failing_handler(payload: dict) -> None:
        raise RuntimeError("downstream unavailable")

    worker = EventBusWorker()
    worker.register("SampleEvent", "failing-consumer", failing_handler)

    result = await db_session.execute(
        select(OutboxEventORM).where(OutboxEventORM.event_id == event.event_id)
    )
    row = result.scalar_one()

    await worker._dispatch_row(db_session, row)
    await db_session.commit()

    assert row.processed_at is None
    assert row.attempts == 1
    assert "failing-consumer" in row.last_error


@pytest.mark.asyncio
async def test_handler_failure_schedules_backoff(db_session):
    event = SampleEvent(organization_id=new_id(), note="boom")
    await publish(db_session, [event])
    await db_session.commit()

    async def failing_handler(payload: dict) -> None:
        raise RuntimeError("downstream unavailable")

    worker = EventBusWorker()
    worker.register("SampleEvent", "failing-consumer", failing_handler)

    result = await db_session.execute(
        select(OutboxEventORM).where(OutboxEventORM.event_id == event.event_id)
    )
    row = result.scalar_one()

    before = datetime.now(UTC)
    await worker._dispatch_row(db_session, row)
    await db_session.commit()

    settings = get_settings()
    assert row.dead_lettered_at is None
    assert row.next_attempt_at is not None
    expected_delay = settings.outbox_retry_backoff_base_seconds  # 2**(1-1) == 1
    assert (row.next_attempt_at - before).total_seconds() >= expected_delay - 0.5


@pytest.mark.asyncio
async def test_repeated_failures_dead_letter_after_max_attempts(db_session):
    event = SampleEvent(organization_id=new_id(), note="boom")
    await publish(db_session, [event])
    await db_session.commit()

    async def failing_handler(payload: dict) -> None:
        raise RuntimeError("downstream unavailable")

    worker = EventBusWorker()
    worker.register("SampleEvent", "failing-consumer", failing_handler)

    result = await db_session.execute(
        select(OutboxEventORM).where(OutboxEventORM.event_id == event.event_id)
    )
    row = result.scalar_one()

    settings = get_settings()
    for _ in range(settings.outbox_max_attempts):
        row.next_attempt_at = None  # simulate backoff having elapsed each round
        await worker._dispatch_row(db_session, row)
        await db_session.commit()

    assert row.attempts == settings.outbox_max_attempts
    assert row.dead_lettered_at is not None
    assert row.processed_at is None


@pytest.mark.asyncio
async def test_drain_batch_skips_rows_before_next_attempt_at(db_session):
    from datetime import timedelta

    event = SampleEvent(organization_id=new_id(), note="not yet")
    await publish(db_session, [event])
    await db_session.commit()

    result = await db_session.execute(
        select(OutboxEventORM).where(OutboxEventORM.event_id == event.event_id)
    )
    row = result.scalar_one()
    row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=5)
    await db_session.commit()

    calls: list[dict] = []

    async def handler(payload: dict) -> None:
        calls.append(payload)

    worker = EventBusWorker()
    worker.register("SampleEvent", "test-consumer", handler)

    processed = await worker._drain_batch(50)

    assert processed == 0
    assert calls == []
