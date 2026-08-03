"""Sprint 2 — Lead Sync Adapter (E7, §7.7): CDC polling with persisted cursor,
idempotent upsert by crm_lead_id, CRMStageSynced to the outbox, and the QA-08
mechanism — RBAC deny-by-default + audit row for every CRM access."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.lead_qualification.application.lead_sync import (
    CRMAccessDeniedError,
    LeadSyncAdapter,
)
from app.modules.lead_qualification.infrastructure.db_models import (
    CRMAccessAuditORM,
    LeadORM,
)
from app.modules.lead_qualification.infrastructure.repository import (
    EPOCH,
    SyncCursorRepository,
)
from app.modules.lead_qualification.infrastructure.wacrm_client import WacrmLeadSnapshot
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow
from app.shared.infrastructure.db_models import OutboxEventORM

T0 = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)


class FakeWacrmClient:
    """In-memory stand-in for the wacrm HTTP client."""

    def __init__(
        self,
        snapshots: list[WacrmLeadSnapshot] | None = None,
        organization_id=None,
    ):
        self.snapshots = snapshots or []
        self.stage_updates: list[tuple[str, str]] = []
        self.organization_id = organization_id
        self.created: list[dict] = []

    async def create_lead(self, *, contact_reference, contact_name, dni=None):
        self.created.append(
            {
                "contact_reference": contact_reference,
                "contact_name": contact_name,
                "dni": dni,
            }
        )
        snapshot = WacrmLeadSnapshot(
            crm_lead_id=f"created-{len(self.created)}",
            organization_id=self.organization_id,
            pipeline_stage="New",
            assigned_broker_id=None,
            lead_score=0.0,
            updated_at=datetime.now(UTC),
            contact_reference=contact_reference,
        )
        self.snapshots.append(snapshot)
        return snapshot

    async def list_leads_updated_since(self, organization_id, since):
        return [
            s
            for s in self.snapshots
            if s.organization_id == organization_id and s.updated_at > since
        ]

    async def get_lead(self, crm_lead_id):
        for s in self.snapshots:
            if s.crm_lead_id == crm_lead_id:
                return s
        return None

    async def update_stage(self, crm_lead_id, pipeline_stage, assigned_broker_id=None):
        self.stage_updates.append((crm_lead_id, pipeline_stage))
        for i, s in enumerate(self.snapshots):
            if s.crm_lead_id == crm_lead_id:
                updated = WacrmLeadSnapshot(
                    crm_lead_id=s.crm_lead_id,
                    organization_id=s.organization_id,
                    pipeline_stage=pipeline_stage,
                    assigned_broker_id=s.assigned_broker_id,
                    lead_score=s.lead_score,
                    updated_at=datetime.now(UTC),
                )
                self.snapshots[i] = updated
                return updated
        raise AssertionError(f"unknown lead {crm_lead_id}")


def _snapshot(org_id, crm_lead_id="lead-1", stage="New", updated_at=T0):
    return WacrmLeadSnapshot(
        crm_lead_id=crm_lead_id,
        organization_id=org_id,
        pipeline_stage=stage,
        assigned_broker_id=None,
        lead_score=0.5,
        updated_at=updated_at,
    )


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
async def seeded_org(session_factory, org_id):
    async with session_factory() as session:
        session.add(
            OrganizationORM(id=org_id, name="Org Test", status="active", created_at=utcnow())
        )
        await session.commit()
    return org_id


async def test_poll_upserts_leads_and_advances_watermark(session_factory, seeded_org):
    client = FakeWacrmClient([_snapshot(seeded_org)])
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        assert await SyncCursorRepository(session).get_watermark(seeded_org) == EPOCH

        count = await adapter.poll_once(seeded_org)
        await session.commit()
        assert count == 1

    async with session_factory() as session:
        row = (await session.execute(select(LeadORM))).scalar_one()
        assert row.crm_lead_id == "lead-1"
        assert row.pipeline_stage == "New"
        assert await SyncCursorRepository(session).get_watermark(seeded_org) == T0


async def test_poll_is_idempotent_and_resumes_from_watermark(session_factory, seeded_org):
    client = FakeWacrmClient([_snapshot(seeded_org)])
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        await adapter.poll_once(seeded_org)
        await session.commit()

    # Second poll: watermark == T0, nothing newer -> no reprocessing, still one row.
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        assert await adapter.poll_once(seeded_org) == 0
        await session.commit()

    # The same lead updated later on wacrm's side -> upsert converges to ONE row.
    client.snapshots = [
        _snapshot(seeded_org, stage="Qualified", updated_at=T0 + timedelta(minutes=5))
    ]
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        assert await adapter.poll_once(seeded_org) == 1
        await session.commit()

    async with session_factory() as session:
        rows = (await session.execute(select(LeadORM))).scalars().all()
        assert len(rows) == 1
        assert rows[0].pipeline_stage == "Qualified"


async def test_stage_change_publishes_crm_stage_synced(session_factory, seeded_org):
    client = FakeWacrmClient([_snapshot(seeded_org)])
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        await adapter.poll_once(seeded_org)
        await session.commit()

    client.snapshots = [
        _snapshot(seeded_org, stage="Qualified", updated_at=T0 + timedelta(minutes=1))
    ]
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        await adapter.poll_once(seeded_org)
        await session.commit()

    async with session_factory() as session:
        events = (
            (
                await session.execute(
                    select(OutboxEventORM).where(OutboxEventORM.event_type == "CRMStageSynced")
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].payload["fields"]["pipeline_stage"] == "Qualified"


async def test_unknown_actor_is_denied_and_audited(session_factory, seeded_org):
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=FakeWacrmClient())
        with pytest.raises(CRMAccessDeniedError):
            await adapter.get_lead(seeded_org, "lead-1", actor="rogue_module")
        await session.commit()

    async with session_factory() as session:
        audit = (await session.execute(select(CRMAccessAuditORM))).scalar_one()
        assert audit.actor == "rogue_module"
        assert audit.allowed is False


async def test_every_access_leaves_an_audit_row(session_factory, seeded_org):
    client = FakeWacrmClient([_snapshot(seeded_org)])
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        await adapter.poll_once(seeded_org)
        await adapter.get_lead(seeded_org, "lead-1", actor="coordinator")
        await session.commit()

    async with session_factory() as session:
        rows = (await session.execute(select(CRMAccessAuditORM))).scalars().all()
        assert [(r.actor, r.action, r.allowed) for r in rows] == [
            ("system.sync_worker", "poll", True),
            ("coordinator", "read", True),
        ]


async def test_push_profile_update_writes_stage_to_wacrm(session_factory, seeded_org):
    client = FakeWacrmClient([_snapshot(seeded_org)])
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        await adapter.poll_once(seeded_org)
        await session.commit()

    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        lead = await adapter.get_lead(seeded_org, "lead-1", actor="coordinator")
        updated = await adapter.push_profile_update(lead.id, actor="system.event_bus")
        await session.commit()

    assert client.stage_updates == [("lead-1", "Qualified")]
    assert updated.pipeline_stage.value == "Qualified"


async def test_create_lead_mirrors_locally_without_waiting_for_cdc(session_factory, seeded_org):
    client = FakeWacrmClient(organization_id=seeded_org)
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        lead = await adapter.create_lead(
            seeded_org,
            contact_reference="+51999888777",
            contact_name="Ana Torres",
            dni="45678912",
            actor="coordinator",
        )
        await session.commit()

    assert client.created == [
        {"contact_reference": "+51999888777", "contact_name": "Ana Torres", "dni": "45678912"}
    ]
    async with session_factory() as session:
        # Mirrored in the same call — no CDC poll happened in between.
        row = (await session.execute(select(LeadORM))).scalar_one()
        assert row.id == lead.id
        assert row.crm_lead_id == "created-1"
        assert row.contact_reference == "+51999888777"
        assert row.pipeline_stage == "New"


async def test_create_lead_by_unknown_actor_is_denied_before_touching_wacrm(
    session_factory, seeded_org
):
    client = FakeWacrmClient(organization_id=seeded_org)
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        with pytest.raises(CRMAccessDeniedError):
            await adapter.create_lead(
                seeded_org,
                contact_reference="+51999888777",
                contact_name="Ana Torres",
                actor="rogue_module",
            )
        await session.commit()

    assert client.created == []  # denied BEFORE the write reached wacrm
    async with session_factory() as session:
        audit = (await session.execute(select(CRMAccessAuditORM))).scalar_one()
        assert (audit.actor, audit.action, audit.allowed) == ("rogue_module", "create", False)


async def test_create_lead_then_poll_converges_to_one_row(session_factory, seeded_org):
    client = FakeWacrmClient(organization_id=seeded_org)
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        await adapter.create_lead(
            seeded_org,
            contact_reference="+51999888777",
            contact_name="Ana Torres",
            actor="coordinator",
        )
        await session.commit()

    # The next CDC poll re-fetches the freshly created deal: the idempotent
    # upsert must converge on the already-mirrored row, never duplicate it.
    async with session_factory() as session:
        adapter = LeadSyncAdapter(session, client=client)
        await adapter.poll_once(seeded_org)
        await session.commit()

    async with session_factory() as session:
        rows = (await session.execute(select(LeadORM))).scalars().all()
        assert len(rows) == 1
        assert rows[0].crm_lead_id == "created-1"
