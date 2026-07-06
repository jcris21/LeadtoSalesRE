"""Outbox/Inbox tables backing the internal Event Bus (transactional, idempotent).

Outbox rows are written in the SAME transaction as the aggregate change that
raised the event (transactional outbox pattern) — this is what makes "Coordinator
--> FSM --> DB" and "FSM -- OwnershipTransferred --> BUS" in Architecture.md §6.1
crash-safe: a commit either persists both the state change and the event, or
neither. The Inbox records (consumer_name, event_id) pairs already processed so
a re-delivered event (worker restart, retry) is a no-op for that consumer.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, PrimaryKeyConstraint, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OutboxEventORM(Base):
    __tablename__ = "outbox_events"

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)


class InboxRecordORM(Base):
    """(consumer_name, event_id) pairs already handled — the idempotency guard."""

    __tablename__ = "inbox_records"
    __table_args__ = (PrimaryKeyConstraint("consumer_name", "event_id"),)

    consumer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("outbox_events.event_id", ondelete="CASCADE"), nullable=False
    )
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
