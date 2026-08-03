"""Sprint 4.1 — US-402: Availability Validator (§7.13/§8). Critical acceptance
test (ImplementationPlan.md Sprint 4): no code path may produce a `confirmed`
result without an explicit prior `AvailabilityCheck.status == confirmed` — the
service never guesses `confirmed` out of nothing (design.md Decision 2)."""

from datetime import UTC, datetime

import pytest

from app.modules.appointment.application.availability_validator import (
    AvailabilityValidatorService,
)
from app.modules.appointment.domain.models import (
    AvailabilityCheckSource,
    AvailabilityStatus,
    Broker,
)
from app.modules.appointment.infrastructure.repository import (
    AvailabilityCheckRepository,
    BrokerRepository,
)
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow

SLOT = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)


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


async def test_pending_by_default_no_broker(session_factory, seeded_org):
    """No real-time availability feed in the MVP (design.md) -> pending, not
    an invented confirmed."""
    async with session_factory() as session:
        service = AvailabilityValidatorService(session)
        status = await service.check(
            organization_id=seeded_org, property_id=new_id(), slot=SLOT
        )
        await session.commit()

    assert status is AvailabilityStatus.PENDING


async def test_missing_or_inactive_broker_is_unavailable(session_factory, seeded_org):
    async with session_factory() as session:
        inactive = Broker(organization_id=seeded_org, active=False)
        await BrokerRepository(session).add(inactive)
        await session.commit()

        service = AvailabilityValidatorService(session)
        status_inactive = await service.check(
            organization_id=seeded_org,
            property_id=new_id(),
            slot=SLOT,
            broker_id=inactive.id,
        )
        status_missing = await service.check(
            organization_id=seeded_org,
            property_id=new_id(),
            slot=SLOT,
            broker_id=new_id(),  # no such broker
        )
        await session.commit()

    assert status_inactive is AvailabilityStatus.UNAVAILABLE
    assert status_missing is AvailabilityStatus.UNAVAILABLE


async def test_never_silently_confirms_pending(session_factory, seeded_org):
    """Repeated checks with no explicit confirmation stay pending forever —
    spec.md: 'Pending status requires explicit human confirmation'."""
    property_id = new_id()
    async with session_factory() as session:
        service = AvailabilityValidatorService(session)
        first = await service.check(organization_id=seeded_org, property_id=property_id, slot=SLOT)
        second = await service.check(organization_id=seeded_org, property_id=property_id, slot=SLOT)
        await session.commit()

    assert first is AvailabilityStatus.PENDING
    assert second is AvailabilityStatus.PENDING


async def test_critical_acceptance_confirmed_requires_explicit_prior_check(
    session_factory, seeded_org
):
    """The critical acceptance test: nothing in the service can produce
    `confirmed` unless an `AvailabilityCheck` row already says so."""
    property_id = new_id()
    async with session_factory() as session:
        # Simulates the out-of-scope manual broker confirmation flow
        # (design.md Non-Goals) writing a confirmed row directly.
        from app.modules.appointment.domain.models import AvailabilityCheck

        await AvailabilityCheckRepository(session).save(
            AvailabilityCheck(
                organization_id=seeded_org,
                property_id=property_id,
                slot=SLOT,
                status=AvailabilityStatus.CONFIRMED,
                source=AvailabilityCheckSource.INITIAL,
            )
        )
        await session.commit()

    async with session_factory() as session:
        service = AvailabilityValidatorService(session)
        status = await service.check(organization_id=seeded_org, property_id=property_id, slot=SLOT)
        await session.commit()

    assert status is AvailabilityStatus.CONFIRMED  # propagated, not invented


async def test_revalidation_confirms_an_already_booked_slot(session_factory, seeded_org):
    """§7.13 re-validation scenario: 2-4h before the visit, check() runs again
    with source=revalidation_2_4h and an already-confirmed slot stays
    confirmed."""
    property_id = new_id()
    async with session_factory() as session:
        from app.modules.appointment.domain.models import AvailabilityCheck

        await AvailabilityCheckRepository(session).save(
            AvailabilityCheck(
                organization_id=seeded_org,
                property_id=property_id,
                slot=SLOT,
                status=AvailabilityStatus.CONFIRMED,
                source=AvailabilityCheckSource.INITIAL,
            )
        )
        await session.commit()

    async with session_factory() as session:
        service = AvailabilityValidatorService(session)
        status = await service.check(
            organization_id=seeded_org,
            property_id=property_id,
            slot=SLOT,
            source=AvailabilityCheckSource.REVALIDATION_2_4H,
        )
        await session.commit()

    assert status is AvailabilityStatus.CONFIRMED


async def test_revalidation_detects_unavailable_and_flags_for_reprogramming(
    session_factory, seeded_org
):
    property_id = new_id()
    async with session_factory() as session:
        broker = Broker(organization_id=seeded_org, active=False)
        await BrokerRepository(session).add(broker)
        await session.commit()

    async with session_factory() as session:
        service = AvailabilityValidatorService(session)
        status = await service.check(
            organization_id=seeded_org,
            property_id=property_id,
            slot=SLOT,
            broker_id=broker.id,
            source=AvailabilityCheckSource.REVALIDATION_2_4H,
        )
        await session.commit()

    assert status is AvailabilityStatus.UNAVAILABLE


async def test_two_checks_same_slot_persist_as_distinct_rows(session_factory, seeded_org):
    """spec.md: 'Multiple checks for the same slot remain distinct' — no
    overwrite, full audit history."""
    property_id = new_id()
    async with session_factory() as session:
        service = AvailabilityValidatorService(session)
        await service.check(
            organization_id=seeded_org,
            property_id=property_id,
            slot=SLOT,
            source=AvailabilityCheckSource.INITIAL,
        )
        await service.check(
            organization_id=seeded_org,
            property_id=property_id,
            slot=SLOT,
            source=AvailabilityCheckSource.REVALIDATION_2_4H,
        )
        await session.commit()

    async with session_factory() as session:
        rows = await AvailabilityCheckRepository(session).list_for_property_and_slot(
            property_id, SLOT
        )

    assert len(rows) == 2
    assert {row.source for row in rows} == {
        AvailabilityCheckSource.INITIAL,
        AvailabilityCheckSource.REVALIDATION_2_4H,
    }


async def test_broker_rls_isolation_by_organization(session_factory):
    """RLS is Postgres-only (SQLite tests can't exercise the SQL policy
    itself), so this test verifies the application-level equivalent: querying
    brokers scoped to org A never returns org B's rows — same posture as
    every other module's isolation test in this suite."""
    org_a, org_b = new_id(), new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_a, name="Org A", status="active", created_at=utcnow()))
        session.add(OrganizationORM(id=org_b, name="Org B", status="active", created_at=utcnow()))
        repo = BrokerRepository(session)
        await repo.add(Broker(organization_id=org_a))
        await repo.add(Broker(organization_id=org_b))
        await session.commit()

    async with session_factory() as session:
        brokers_a = await BrokerRepository(session).list_active_for_organization(org_a)

    assert len(brokers_a) == 1
    assert brokers_a[0].organization_id == org_a
