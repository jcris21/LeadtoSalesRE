"""Staleness Guard (§7.9, QA-13): no critical business decision executes on a
`Lead` whose mirror exceeded the staleness bound (60s default) — the guard
forces a synchronous re-sync through the Lead Sync Adapter and only then lets
the caller proceed, with fresh data. Warn-and-continue is explicitly NOT an
option (Architecture.md §10 Iter. 3): a silent stale decision is the failure
mode this component exists to make impossible.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.lead_qualification.application.lead_sync import (
    LeadNotFoundError,
    LeadSyncAdapter,
)
from app.modules.lead_qualification.domain.models import Lead
from app.modules.lead_qualification.infrastructure.repository import LeadRepository

ACTOR = "staleness_guard"


class StalenessGuard:
    """`StalenessGuardPort.check_before_decision(leadId)` (§8)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        sync_adapter: LeadSyncAdapter | None = None,
        threshold_seconds: int | None = None,
    ):
        self._leads = LeadRepository(session)
        self._sync = sync_adapter or LeadSyncAdapter(session)
        self._threshold_seconds = (
            threshold_seconds
            if threshold_seconds is not None
            else get_settings().crm_staleness_threshold_seconds
        )

    async def check_before_decision(self, lead_id: uuid.UUID) -> Lead:
        """Blocks until the lead is fresh: re-syncs when stale, then returns the
        lead the decision may run on. Raises LeadNotFoundError if it vanished."""
        lead = await self._leads.get(lead_id)
        if lead is None:
            raise LeadNotFoundError(lead_id)
        if lead.is_stale(threshold_seconds=self._threshold_seconds):
            return await self._sync.force_resync(lead_id, actor=ACTOR)
        return lead
