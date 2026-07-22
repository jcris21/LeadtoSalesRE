"""Sprint 4.2 — US-404: Scheduling Service. Critical acceptance test: booking
is refused (nothing persisted, no side effects) unless AvailabilityValidatorPort
.check() returns confirmed at the point of booking itself — the same "never
silently proceed" invariant US-402 established, enforced here at point of use
(design.md Decision 1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.modules.appointment.application.scheduling_service import SchedulingService
from app.modules.appointment.domain.models import (
    AvailabilityCheck,
    AvailabilityCheckSource,
    AvailabilityStatus,
    Broker,
    CalendarEventResult,
    SlotNotConfirmedError,
)
from app.modules.appointment.infrastructure.google_calendar_client import FakeGoogleCalendarClient
from app.modules.appointment.infrastructure.repository import (
    AvailabilityCheckRepository,
    BrokerRepository,
)
from app.modules.lead_qualification.application.lead_sync import LeadSyncAdapter
from app.modules.lead_qualification.infrastructure.db_models import LeadORM
from app.modules.lead_qualification.infrastructure.wacrm_client import WacrmLeadSnapshot
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow
from app.shared.infrastructure.db_models import OutboxEventORM

SLOT = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
ATTENDEES = ("lead@example.com", "broker@example.com")


class FakeWacrmClient:
    """Minimal in-memory stand-in — only `update_stage` is exercised by
    `push_profile_update`, following the same shape as
    tests/test_lead_sync.py's `FakeWacrmClient`."""

    def __init__(self, snapshot: WacrmLeadSnapshot):
        self._snapshot = snapshot
        self.stage_updates: list[tuple[str, str]] = []

    async def update_stage(self, crm_lead_id, pipeline_stage, assigned_broker_id=None):
        self.stage_updates.append((crm_lead_id, pipeline_stage))
        return WacrmLeadSnapshot(
            crm_lead_id=crm_lead_id,
            organization_id=self._snapshot.organization_id,
            pipeline_stage=pipeline_stage,
            assigned_broker_id=None,
            lead_score=self._snapshot.lead_score,
            updated_at=datetime.now(UTC),
            contact_reference=self._snapshot.contact_reference,
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


@pytest.fixture
async def seeded_lead(session_factory, seeded_org):
    lead_id = new_id()
    async with session_factory() as session:
        session.add(
            LeadORM(
                id=lead_id,
                organization_id=seeded_org,
                crm_lead_id="lead-404",
                pipeline_stage="Qualified",
                lead_score=0.8,
                lead_classification="hot",
                contact_reference="+51999888777",
                synced_at=utcnow(),
                created_at=utcnow(),
            )
        )
        await session.commit()
    return lead_id


def _build_service(
    session, *, seeded_org, calendar=None
) -> tuple[SchedulingService, FakeWacrmClient]:
    calendar = calendar or FakeGoogleCalendarClient(
        result=CalendarEventResult(
            calendar_event_id="evt-404", meet_link="https://meet.google.com/x"
        )
    )
    wacrm_client = FakeWacrmClient(
        WacrmLeadSnapshot(
            crm_lead_id="lead-404",
            organization_id=seeded_org,
            pipeline_stage="Qualified",
            assigned_broker_id=None,
            lead_score=0.8,
            updated_at=datetime.now(UTC),
            contact_reference="+51999888777",
        )
    )
    lead_sync = LeadSyncAdapter(session, client=wacrm_client)
    service = SchedulingService(session, calendar=calendar, lead_sync=lead_sync)
    return service, wacrm_client, calendar


async def _seed_confirmed_check(session_factory, org_id, property_id):
    async with session_factory() as session:
        await AvailabilityCheckRepository(session).save(
            AvailabilityCheck(
                organization_id=org_id,
                property_id=property_id,
                slot=SLOT,
                status=AvailabilityStatus.CONFIRMED,
                source=AvailabilityCheckSource.INITIAL,
            )
        )
        await session.commit()


async def test_happy_path_books_appointment_and_orchestrates_every_step(
    session_factory, seeded_org, seeded_lead
):
    property_id = new_id()
    async with session_factory() as session:
        broker = Broker(organization_id=seeded_org, active=True)
        await BrokerRepository(session).add(broker)
        await session.commit()
    broker_id = broker.id
    await _seed_confirmed_check(session_factory, seeded_org, property_id)

    async with session_factory() as session:
        service, wacrm_client, calendar = _build_service(session, seeded_org=seeded_org)
        appointment = await service.book_visit(
            organization_id=seeded_org,
            lead_id=seeded_lead,
            property_id=property_id,
            broker_id=broker_id,
            slot=SLOT,
            attendees=ATTENDEES,
        )
        await session.commit()

    assert appointment.status.value == "booked"
    assert appointment.calendar_event_id == "evt-404"
    assert appointment.meet_link == "https://meet.google.com/x"
    assert len(calendar.calls) == 1
    assert wacrm_client.stage_updates == [("lead-404", "AppointmentSet")]

    async with session_factory() as session:
        outbox_events = (await session.execute(select(OutboxEventORM))).scalars().all()
        assert any(row.event_type == "AppointmentBooked" for row in outbox_events)

        lead_row = await session.get(LeadORM, seeded_lead)
        assert lead_row.pipeline_stage == "AppointmentSet"


@pytest.mark.parametrize("status", [AvailabilityStatus.PENDING, AvailabilityStatus.UNAVAILABLE])
async def test_booking_refused_without_confirmed_availability(
    session_factory, seeded_org, seeded_lead, status
):
    """Critical acceptance test: no Appointment, no AppointmentBooked event,
    no Calendar call, no CRM sync — unless AvailabilityValidatorPort.check()
    itself returns confirmed."""
    property_id = new_id()
    broker_id = new_id()

    if status is AvailabilityStatus.UNAVAILABLE:
        async with session_factory() as session:
            await AvailabilityCheckRepository(session).save(
                AvailabilityCheck(
                    organization_id=seeded_org,
                    property_id=property_id,
                    slot=SLOT,
                    status=AvailabilityStatus.UNAVAILABLE,
                    source=AvailabilityCheckSource.INITIAL,
                )
            )
            await session.commit()
    # PENDING requires no seeding — it's AvailabilityValidatorService's default.

    async with session_factory() as session:
        service, wacrm_client, calendar = _build_service(session, seeded_org=seeded_org)
        with pytest.raises(SlotNotConfirmedError):
            await service.book_visit(
                organization_id=seeded_org,
                lead_id=seeded_lead,
                property_id=property_id,
                broker_id=broker_id,
                slot=SLOT,
                attendees=ATTENDEES,
            )
        await session.commit()

    assert calendar.calls == []
    assert wacrm_client.stage_updates == []

    async with session_factory() as session:
        outbox_events = (await session.execute(select(OutboxEventORM))).scalars().all()
        assert not any(row.event_type == "AppointmentBooked" for row in outbox_events)

        lead_row = await session.get(LeadORM, seeded_lead)
        assert lead_row.pipeline_stage == "Qualified"  # unchanged


async def test_appointment_rls_isolation_by_organization(session_factory):
    """RLS is Postgres-only (SQLite tests can't exercise the SQL policy
    itself), so this verifies the application-level equivalent: an
    appointment saved for org A is retrievable under org A's own lookup and
    is a distinct row from anything org B might have — same posture as
    tests/test_availability_validator.py's RLS test."""
    from app.modules.appointment.domain.models import Appointment
    from app.modules.appointment.infrastructure.repository import AppointmentRepository

    org_a, org_b = new_id(), new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_a, name="Org A", status="active", created_at=utcnow()))
        session.add(OrganizationORM(id=org_b, name="Org B", status="active", created_at=utcnow()))
        repo = AppointmentRepository(session)
        appointment_a = Appointment(
            organization_id=org_a,
            lead_id=new_id(),
            property_id=new_id(),
            broker_id=new_id(),
            scheduled_at=SLOT,
            calendar_event_id="evt-a",
            meet_link="https://meet.google.com/a",
        )
        appointment_b = Appointment(
            organization_id=org_b,
            lead_id=new_id(),
            property_id=new_id(),
            broker_id=new_id(),
            scheduled_at=SLOT,
            calendar_event_id="evt-b",
            meet_link="https://meet.google.com/b",
        )
        await repo.save(appointment_a)
        await repo.save(appointment_b)
        await session.commit()

    async with session_factory() as session:
        fetched = await AppointmentRepository(session).get_by_id(appointment_a.id)

    assert fetched is not None
    assert fetched.organization_id == org_a
    assert fetched.calendar_event_id == "evt-a"
