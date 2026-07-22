"""Lead Sync Adapter — bidirectional ACL to wacrm (§6.2, §7.7; E7).

The SINGLE point with read/write permission to CRM data (QA-08): every
operation authorizes the actor and writes a `crm_access_audit` row, allowed or
denied. The role model is specified in Sprint 6; until then the policy is a
deny-by-default allowlist of internal actors — the enforcement + audit
*mechanism* is what Sprint 2 delivers.

Read direction: CDC by polling with a persisted cursor (`SyncCursorPort`) —
resumable after any crash, idempotent upsert by `crm_lead_id`. Write direction:
`push_profile_update` (consumes `ProfileCompleted` via the Event Bus, at-least-
once with inbox dedup) pushes the qualified stage to wacrm.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.lead_qualification.domain.models import Lead, PipelineStage
from app.modules.lead_qualification.infrastructure.repository import (
    CRMAccessAuditRepository,
    LeadRepository,
    SyncCursorRepository,
)
from app.modules.lead_qualification.infrastructure.wacrm_client import (
    WacrmClient,
    WacrmLeadSnapshot,
)
from app.shared.infrastructure import event_bus

logger = logging.getLogger(__name__)

#: Deny-by-default allowlist. The concrete 4-role-per-organization model is a
#: Sprint 6 deliverable (QA-08 closes there); these are the internal actors
#: that legitimately reach CRM data through the adapter until then.
ALLOWED_ACTORS: frozenset[str] = frozenset(
    {
        "system.sync_worker",
        "system.event_bus",
        "coordinator",
        "staleness_guard",
        "profile_capture",
        "scheduling_service",
    }
)


class CRMAccessDeniedError(PermissionError):
    """Actor is not allowed to touch CRM data through the adapter (QA-08).
    The attempt itself is audited before this is raised."""

    def __init__(self, actor: str, action: str):
        self.actor = actor
        self.action = action
        super().__init__(f"Actor '{actor}' is not allowed to perform CRM action '{action}'")


class LeadNotFoundError(LookupError):
    def __init__(self, lead_id: uuid.UUID):
        self.lead_id = lead_id
        super().__init__(f"Lead {lead_id} not found")


class LeadSyncAdapter:
    def __init__(self, session: AsyncSession, *, client: WacrmClient | None = None):
        self._session = session
        self._client = client or WacrmClient()
        self._leads = LeadRepository(session)
        self._cursor = SyncCursorRepository(session)
        self._audit = CRMAccessAuditRepository(session)

    async def poll_once(
        self, organization_id: uuid.UUID, *, actor: str = "system.sync_worker"
    ) -> int:
        """One CDC cycle (§7.7): read watermark, fetch changed leads from wacrm,
        upsert idempotently, advance watermark, publish CRMStageSynced. Returns
        the number of leads upserted. Caller owns the transaction."""
        await self._authorize(organization_id, actor=actor, action="poll", crm_lead_id=None)

        watermark = await self._cursor.get_watermark(organization_id)
        snapshots = await self._client.list_leads_updated_since(organization_id, watermark)

        max_seen = watermark
        events = []
        earliest_skipped: datetime | None = None
        for snapshot in snapshots:
            try:
                lead = await self._upsert_from_snapshot(organization_id, snapshot)
            except ValueError:
                # Real wacrm stage names are free text set by brokers; one lead
                # whose stage doesn't match our closed PipelineStage enum must
                # not abort the whole org's poll (it used to take down CDC for
                # the entire organization).
                logger.warning(
                    "Skipping lead %s in organization %s: pipeline stage %r "
                    "does not match the required stage-naming contract",
                    snapshot.crm_lead_id,
                    organization_id,
                    snapshot.pipeline_stage,
                )
                if earliest_skipped is None or snapshot.updated_at < earliest_skipped:
                    earliest_skipped = snapshot.updated_at
                continue
            events.extend(lead.pull_domain_events())
            if snapshot.updated_at > max_seen:
                max_seen = snapshot.updated_at

        # The watermark must never pass a skipped lead: fixing a stage NAME in
        # wacrm doesn't touch the deal's updated_at, so advancing past it would
        # drop the lead forever. Advance up to just before the earliest skipped
        # lead instead — leads updated before it stop being re-fetched, the bad
        # lead (and anything after it) re-polls each cycle (idempotent upserts
        # make that harmless) and self-heals once the operator fixes the stage.
        if earliest_skipped is not None:
            max_seen = min(max_seen, earliest_skipped - timedelta(microseconds=1))
        if max_seen > watermark:
            await self._cursor.advance_watermark(organization_id, max_seen)
        if events:
            await event_bus.publish(self._session, events)
        return len(snapshots)

    async def create_lead(
        self,
        organization_id: uuid.UUID,
        *,
        contact_reference: str,
        contact_name: str,
        dni: str | None = None,
        actor: str,
    ) -> Lead:
        """G8 write direction: a lead born in the chat is created in wacrm
        (SoR) and mirrored locally in the same call — the immediate upsert
        kills the up-to-30s CDC latency, and the next poll converges on the
        same row (idempotent by crm_lead_id), so no extra state is needed."""
        await self._authorize(organization_id, actor=actor, action="create", crm_lead_id=None)
        snapshot = await self._client.create_lead(
            contact_reference=contact_reference, contact_name=contact_name, dni=dni
        )
        lead = await self._upsert_from_snapshot(organization_id, snapshot)
        events = lead.pull_domain_events()
        if events:
            await event_bus.publish(self._session, events)
        return lead

    async def get_lead(
        self, organization_id: uuid.UUID, crm_lead_id: str, *, actor: str
    ) -> Lead | None:
        """LeadSyncPort.get_lead — the only sanctioned read of CRM lead data."""
        await self._authorize(organization_id, actor=actor, action="read", crm_lead_id=crm_lead_id)
        return await self._leads.get_by_crm_id(organization_id, crm_lead_id)

    async def force_resync(self, lead_id: uuid.UUID, *, actor: str) -> Lead:
        """Direct GET outside the polling cycle (§7.9): refreshes one lead NOW.
        The Staleness Guard calls this before any critical decision on stale data."""
        lead = await self._leads.get(lead_id)
        if lead is None:
            raise LeadNotFoundError(lead_id)
        await self._authorize(
            lead.organization_id, actor=actor, action="force_resync", crm_lead_id=lead.crm_lead_id
        )
        snapshot = await self._client.get_lead(lead.crm_lead_id)
        if snapshot is None:
            # Deleted on wacrm's side: surface loudly, never decide on a ghost lead.
            raise LeadNotFoundError(lead_id)
        lead = await self._upsert_from_snapshot(lead.organization_id, snapshot)
        events = lead.pull_domain_events()
        if events:
            await event_bus.publish(self._session, events)
        return lead

    async def push_profile_update(
        self,
        lead_id: uuid.UUID,
        *,
        actor: str,
        pipeline_stage: PipelineStage = PipelineStage.QUALIFIED,
    ) -> Lead:
        """Write direction (§7.7 reverse): pushes the stage to wacrm. Idempotent —
        re-delivery pushes the same stage again, which wacrm applies as a no-op."""
        lead = await self._leads.get(lead_id)
        if lead is None:
            raise LeadNotFoundError(lead_id)
        await self._authorize(
            lead.organization_id, actor=actor, action="write", crm_lead_id=lead.crm_lead_id
        )
        snapshot = await self._client.update_stage(lead.crm_lead_id, pipeline_stage.value)
        lead = await self._upsert_from_snapshot(lead.organization_id, snapshot)
        events = lead.pull_domain_events()
        if events:
            await event_bus.publish(self._session, events)
        return lead

    async def _upsert_from_snapshot(
        self, organization_id: uuid.UUID, snapshot: WacrmLeadSnapshot
    ) -> Lead:
        """Idempotent by (organization_id, crm_lead_id): the same snapshot applied
        twice converges to the same row (CRN-6)."""
        lead = await self._leads.get_by_crm_id(organization_id, snapshot.crm_lead_id)
        if lead is None:
            lead = Lead(
                organization_id=organization_id,
                crm_lead_id=snapshot.crm_lead_id,
                pipeline_stage=PipelineStage(snapshot.pipeline_stage),
                lead_score=snapshot.lead_score,
                assigned_broker_id=snapshot.assigned_broker_id,
                contact_reference=snapshot.contact_reference,
            )
            await self._leads.add(lead)
        else:
            lead.mark_synced(
                pipeline_stage=PipelineStage(snapshot.pipeline_stage),
                lead_score=snapshot.lead_score,
                assigned_broker_id=snapshot.assigned_broker_id,
                contact_reference=snapshot.contact_reference,
            )
            await self._leads.save(lead)
        return lead

    async def _authorize(
        self,
        organization_id: uuid.UUID,
        *,
        actor: str,
        action: str,
        crm_lead_id: str | None,
    ) -> None:
        allowed = actor in ALLOWED_ACTORS
        await self._audit.record(
            organization_id=organization_id,
            actor=actor,
            action=action,
            crm_lead_id=crm_lead_id,
            allowed=allowed,
        )
        if not allowed:
            logger.warning("CRM access denied: actor=%s action=%s", actor, action)
            raise CRMAccessDeniedError(actor, action)
