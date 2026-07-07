"""Event-bus wiring + background CDC polling loop for Lead & Qualification (M3).

- ProfileCompleted -> Lead Sync Adapter pushes the qualified stage to wacrm
  (write direction of §7.7, via outbox/inbox: at-least-once + idempotent push).
- `crm_sync_loop` runs the read direction: one CDC poll per organization per
  interval, each in its own transaction so one org's failure never blocks the rest.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.modules.lead_qualification.application.lead_sync import (
    LeadNotFoundError,
    LeadSyncAdapter,
)
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.infrastructure.event_bus import EventBusWorker

logger = logging.getLogger(__name__)


async def handle_profile_completed(payload: dict) -> None:
    fields = payload["fields"]
    lead_id = uuid.UUID(fields["lead_id"])

    async with get_session_factory()() as session:
        adapter = LeadSyncAdapter(session)
        try:
            await adapter.push_profile_update(lead_id, actor="system.event_bus")
        except LeadNotFoundError:
            logger.error("ProfileCompleted for unknown lead %s; dropping", lead_id)
            return
        await session.commit()


def register_event_handlers(worker: EventBusWorker) -> None:
    worker.register("ProfileCompleted", "lead_qualification.crm_push", handle_profile_completed)


async def crm_sync_loop() -> None:
    """Background CDC polling (§7.7). One pass = one poll per organization."""
    settings = get_settings()
    while True:
        try:
            await sync_all_organizations_once()
        except Exception:  # noqa: BLE001 - the loop must survive transient failures
            logger.exception("CRM sync pass failed")
        await asyncio.sleep(settings.crm_sync_poll_interval_seconds)


async def sync_all_organizations_once() -> int:
    """One poll cycle across all organizations; returns total leads upserted."""
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(OrganizationORM.id))
        organization_ids = [row[0] for row in result.all()]

    total = 0
    for organization_id in organization_ids:
        try:
            async with factory() as session:
                adapter = LeadSyncAdapter(session)
                total += await adapter.poll_once(organization_id)
                await session.commit()
        except Exception:  # noqa: BLE001 - isolate per-organization failures
            logger.exception("CRM sync failed for organization %s", organization_id)
    return total
