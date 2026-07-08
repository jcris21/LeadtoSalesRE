"""SQLAlchemy ORM models for the Conversation & Ownership bounded context.

conversations persists the FSM + ownership snapshot (Conversation aggregate).
archived_messages is the raw conversation archive that starts accumulating in
Sprint 1 so the E10 conversation-mining corpus exists when that epic ships
(ArchitecturalDrivers §7 note on E10) — full raw webhook payload, not just the
MessageRef, because mining needs the original content and Chatwoot data can be
purged/rotated on their side.
ownership_decisions is the persistent, auditable record of every Ownership
Policy Engine evaluation (QA-11: explanation is a first-class field).
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ConversationORM(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "chatwoot_conversation_id", name="uq_org_chatwoot_conversation"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chatwoot_conversation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="whatsapp")
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="New", index=True)
    #: External contact identifier (e.g. WhatsApp phone number) from the
    #: Chatwoot payload; shared with wacrm's Lead.contact_reference so a
    #: Conversation can be resolved to its Lead (Sprint 3 identity matching).
    contact_reference: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_type: Mapped[str] = mapped_column(String(16), nullable=False, default="unassigned")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    owner_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    owner_reason: Mapped[str] = mapped_column(Text, nullable=False, default="not evaluated")
    last_contact_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArchivedMessageORM(Base):
    """Raw conversation archive (Sprint 1 deliverable, feeds E10 later)."""

    __tablename__ = "archived_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "chatwoot_message_id", name="uq_conversation_chatwoot_message"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chatwoot_message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sender: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    message_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OwnershipDecisionORM(Base):
    """Persistent record of each Ownership Policy Engine evaluation: input
    snapshot, selected owner and human-readable explanation. Auditable and
    replayable; OwnershipOutcome attaches to it from Sprint 4."""

    __tablename__ = "ownership_decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scenario: Mapped[str] = mapped_column(String(64), nullable=False)
    inputs_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    selected_owner: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
