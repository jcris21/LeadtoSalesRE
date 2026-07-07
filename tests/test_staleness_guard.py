"""Sprint 2 — Staleness Guard (QA-13, §7.9) + the sprint's acceptance test:
no business decision executes on `Lead.is_stale() == True` without forcing a
re-sync first — the guard blocks and refreshes, never warns-and-continues."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.lead_qualification.application.lead_sync import (
    LeadNotFoundError,
    LeadSyncAdapter,
)
from app.modules.lead_qualification.application.staleness_guard import StalenessGuard
from app.modules.lead_qualification.domain.models import Lead
from app.modules.lead_qualification.infrastructure.repository import LeadRepository
from app.modules.lead_qualification.infrastructure.wacrm_client import WacrmLeadSnapshot
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow

THRESHOLD = 60  # QA-13 bound, seconds


class FakeWacrmClient:
    def __init__(self, snapshot: WacrmLeadSnapshot | None = None):
        self.snapshot = snapshot
        self.resync_calls = 0

    async def get_lead(self, crm_lead_id):
        self.resync_calls += 1
        return self.snapshot

    async def list_leads_updated_since(self, organization_id, since):
        return []

    async def update_stage(self, crm_lead_id, pipeline_stage, assigned_broker_id=None):
        raise AssertionError("not used here")


def test_is_stale_boundary():
    lead = Lead(organization_id=new_id(), crm_lead_id="l", synced_at=datetime.now(UTC))
    now = lead.synced_at
    assert lead.is_stale(threshold_seconds=THRESHOLD, now=now + timedelta(seconds=59)) is False
    assert lead.is_stale(threshold_seconds=THRESHOLD, now=now + timedelta(seconds=61)) is True


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
async def seeded(session_factory, org_id):
    """One org + one lead whose mirror is 10 minutes old (stale)."""
    async with session_factory() as session:
        session.add(
            OrganizationORM(id=org_id, name="Org Test", status="active", created_at=utcnow())
        )
        lead = Lead(
            organization_id=org_id,
            crm_lead_id="lead-1",
            synced_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        await LeadRepository(session).add(lead)
        await session.commit()
    return org_id, lead.id


async def test_stale_lead_forces_resync_before_decision(session_factory, seeded):
    org_id, lead_id = seeded
    client = FakeWacrmClient(
        WacrmLeadSnapshot(
            crm_lead_id="lead-1",
            organization_id=org_id,
            pipeline_stage="Qualified",
            assigned_broker_id=None,
            lead_score=0.9,
            updated_at=datetime.now(UTC),
        )
    )
    async with session_factory() as session:
        guard = StalenessGuard(
            session,
            sync_adapter=LeadSyncAdapter(session, client=client),
            threshold_seconds=THRESHOLD,
        )
        lead = await guard.check_before_decision(lead_id)
        await session.commit()

    assert client.resync_calls == 1  # decision proceeded ONLY after re-sync
    assert lead.is_stale(threshold_seconds=THRESHOLD) is False
    assert lead.pipeline_stage.value == "Qualified"  # decision sees fresh data


async def test_fresh_lead_passes_without_resync(session_factory, seeded):
    org_id, lead_id = seeded
    client = FakeWacrmClient()
    async with session_factory() as session:
        repo = LeadRepository(session)
        lead = await repo.get(lead_id)
        lead.mark_synced(
            pipeline_stage=lead.pipeline_stage,
            lead_score=lead.lead_score,
            assigned_broker_id=None,
        )
        await repo.save(lead)
        await session.commit()

    async with session_factory() as session:
        guard = StalenessGuard(
            session,
            sync_adapter=LeadSyncAdapter(session, client=client),
            threshold_seconds=THRESHOLD,
        )
        await guard.check_before_decision(lead_id)

    assert client.resync_calls == 0


async def test_lead_deleted_on_crm_side_surfaces_not_silently_passes(session_factory, seeded):
    _, lead_id = seeded
    client = FakeWacrmClient(snapshot=None)  # wacrm no longer knows the lead
    async with session_factory() as session:
        guard = StalenessGuard(
            session,
            sync_adapter=LeadSyncAdapter(session, client=client),
            threshold_seconds=THRESHOLD,
        )
        with pytest.raises(LeadNotFoundError):
            await guard.check_before_decision(lead_id)
