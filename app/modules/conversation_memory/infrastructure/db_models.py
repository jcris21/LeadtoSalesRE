"""SQLAlchemy ORM model for the Conversation Memory bounded context (AI-102).

`conversation_memory` schema matches `Documents/Oficial/AI_Recommendation_Domain_Model.md`
§4 exactly (id, conversation_id, lead_id, memory_type, entity_name, value
jsonb, confidence, created_at). `value` uses the portable `JSON` type (not a
Postgres-specific `JSONB` import) for the same SQLite-test-portability reason
as `buyer_profiles.locations`/`must_haves` (see lead_qualification's
db_models.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ConversationMemoryORM(Base):
    __tablename__ = "conversation_memory"
    __table_args__ = (
        Index("ix_conversation_memory_lead_id", "lead_id"),
        Index("ix_conversation_memory_conversation_id", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
