"""SQLAlchemy ORM model for the Knowledge/RAG bounded context (AI-106).

Generic `sqlalchemy.JSON` for `embedding` (not `pgvector.sqlalchemy.Vector`) keeps this model
portable across SQLite (tests) and Postgres (prod) - same convention as
`recommendation.infrastructure.db_models.PropertyEmbeddingORM`. The real Postgres column is
`vector(1536)` (migration `0020`); `KnowledgeRepository` binds it via raw SQL with an explicit
`::vector` cast, mirroring `PropertyRepository.save_embedding`/`semantic_search`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KnowledgeDocumentORM(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    embedding: Mapped[list] = mapped_column(JSON, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
