"""SQLAlchemy ORM models for the Recommendation bounded context (M4, Sprint 3A).

properties is the local mirror of the inventory source (Architecture.md §6.3):
Structured Filter runs plain SQL against it instead of round-tripping to
inventory on every request. property_embeddings holds the precalculated
vector per property plus the `source_hash` of the content it was computed
from, so the Ingestion Pipeline can tell "unchanged" from "needs recompute"
without ever re-embedding on the request path.

Generic sqlalchemy.JSON/Uuid types (not `pgvector.sqlalchemy.Vector`) keep
these models portable across SQLite (tests) and Postgres (prod), same
convention as `lead_qualification/infrastructure/db_models.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PropertyORM(Base):
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_id", name="uq_org_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    zone: Mapped[str] = mapped_column(String(120), nullable=False)
    property_type: Mapped[str] = mapped_column(String(32), nullable=False)
    features: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PropertyEmbeddingORM(Base):
    """One precalculated vector per property. `source_hash` is the content
    fingerprint (features/description/price/zone/type) the vector was
    computed from — the Ingestion Pipeline recomputes only when it changes,
    never on a timestamp guess."""

    __tablename__ = "property_embeddings"

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        primary_key=True,
    )
    vector: Mapped[list] = mapped_column(JSON, nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
