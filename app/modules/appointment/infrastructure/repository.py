"""Repositories translating between the Appointment domain objects and their
ORM rows (Sprint 4.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.appointment.domain.models import (
    Appointment,
    AppointmentStatus,
    AvailabilityCheck,
    AvailabilityCheckSource,
    AvailabilityStatus,
    Broker,
    BrokerAvailability,
)
from app.modules.appointment.infrastructure.db_models import (
    AppointmentORM,
    AvailabilityCheckORM,
    BrokerORM,
)


def _ensure_utc(value: datetime) -> datetime:
    # SQLite (tests) returns naive datetimes even for timezone=True columns;
    # values are stored as UTC, so re-attach UTC on hydration (same pattern
    # as lead_qualification/infrastructure/repository.py).
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class BrokerRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, broker: Broker) -> None:
        self._session.add(self._to_row(broker))

    async def get_by_id(self, broker_id: uuid.UUID) -> Broker | None:
        row = await self._session.get(BrokerORM, broker_id)
        return self._to_domain(row) if row is not None else None

    async def list_active_for_organization(self, organization_id: uuid.UUID) -> list[Broker]:
        result = await self._session.execute(
            select(BrokerORM).where(
                BrokerORM.organization_id == organization_id,
                BrokerORM.active.is_(True),
            )
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    @staticmethod
    def _to_row(broker: Broker) -> BrokerORM:
        return BrokerORM(
            id=broker.id,
            organization_id=broker.organization_id,
            specialties=list(broker.specialties),
            active=broker.active,
            availability={"blocks": list(broker.availability.blocks)},
        )

    @staticmethod
    def _to_domain(row: BrokerORM) -> Broker:
        return Broker(
            id=row.id,
            organization_id=row.organization_id,
            specialties=tuple(row.specialties or ()),
            active=row.active,
            availability=BrokerAvailability(
                blocks=tuple((row.availability or {}).get("blocks", ()))
            ),
        )


class AvailabilityCheckRepository:
    """Append-only: `save()` always inserts, never updates an existing row —
    the audit trail (spec.md: Auditable availability check history) requires
    every check, initial or revalidation, to remain individually queryable."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, check: AvailabilityCheck) -> None:
        self._session.add(
            AvailabilityCheckORM(
                id=check.id,
                organization_id=check.organization_id,
                property_id=check.property_id,
                broker_id=check.broker_id,
                slot=check.slot,
                status=check.status.value,
                source=check.source.value,
                checked_at=check.checked_at,
            )
        )

    async def list_for_property_and_slot(
        self, property_id: uuid.UUID, slot: datetime
    ) -> list[AvailabilityCheck]:
        result = await self._session.execute(
            select(AvailabilityCheckORM)
            .where(
                AvailabilityCheckORM.property_id == property_id,
                AvailabilityCheckORM.slot == slot,
            )
            .order_by(AvailabilityCheckORM.checked_at)
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    @staticmethod
    def _to_domain(row: AvailabilityCheckORM) -> AvailabilityCheck:
        return AvailabilityCheck(
            id=row.id,
            organization_id=row.organization_id,
            property_id=row.property_id,
            broker_id=row.broker_id,
            slot=_ensure_utc(row.slot),
            status=AvailabilityStatus(row.status),
            source=AvailabilityCheckSource(row.source),
            checked_at=_ensure_utc(row.checked_at),
        )


class AppointmentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, appointment: Appointment) -> None:
        self._session.add(
            AppointmentORM(
                id=appointment.id,
                organization_id=appointment.organization_id,
                lead_id=appointment.lead_id,
                property_id=appointment.property_id,
                broker_id=appointment.broker_id,
                scheduled_at=appointment.scheduled_at,
                status=appointment.status.value,
                calendar_event_id=appointment.calendar_event_id,
                meet_link=appointment.meet_link,
            )
        )

    async def get_by_id(self, appointment_id: uuid.UUID) -> Appointment | None:
        row = await self._session.get(AppointmentORM, appointment_id)
        return self._to_domain(row) if row is not None else None

    @staticmethod
    def _to_domain(row: AppointmentORM) -> Appointment:
        return Appointment(
            id=row.id,
            organization_id=row.organization_id,
            lead_id=row.lead_id,
            property_id=row.property_id,
            broker_id=row.broker_id,
            scheduled_at=_ensure_utc(row.scheduled_at),
            status=AppointmentStatus(row.status),
            calendar_event_id=row.calendar_event_id,
            meet_link=row.meet_link,
        )
