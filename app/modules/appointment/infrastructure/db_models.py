"""SQLAlchemy ORM models for the Appointment bounded context (Sprint 4.1).

`brokers` is new — no equivalent table existed before this change.
`availability_checks` is an append-only audit trail (design.md Decision 1):
every `AvailabilityValidatorPort.check()` call inserts a row, distinguishing
`initial` proposal checks from the automatic `revalidation_2_4h` re-check
2-4h before a booked visit, so a status change is always traceable to when
and why it happened.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BrokerORM(Base):
    __tablename__ = "brokers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    specialties: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: MVP: simple JSON blob (design.md Decision 3) — no normalized schedule
    #: table until a broker-calendar integration is actually scoped.
    availability: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class AvailabilityCheckORM(Base):
    __tablename__ = "availability_checks"
    __table_args__ = (
        Index("ix_availability_checks_property_slot", "property_id", "slot"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    broker_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brokers.id", ondelete="SET NULL"), nullable=True
    )
    slot: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: AvailabilityStatus value (confirmed | pending | unavailable).
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    #: AvailabilityCheckSource value (initial | revalidation_2_4h).
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class AppointmentORM(Base):
    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    broker_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brokers.id", ondelete="SET NULL"), nullable=True
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: AppointmentStatus value (only "booked" in this HU's scope).
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    calendar_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    meet_link: Mapped[str] = mapped_column(String(255), nullable=False)
