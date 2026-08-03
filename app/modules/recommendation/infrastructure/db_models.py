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

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
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
    #: US-309: the Python attribute stays `zone` (every consumer reads it) but
    #: the physical column is the reconciled snake_case `district` — see
    #: migration 0010 and the drift analysis in AI_Recommendation_Domain_Model.md.
    zone: Mapped[str] = mapped_column("district", String(120), nullable=False)
    property_type: Mapped[str] = mapped_column(String(32), nullable=False)
    features: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    #: US-309: columns that existed only in the hand-edited Supabase schema,
    #: formalized here. `link_references` is a list of media URLs (photos,
    #: video, PDF).
    name_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(32), nullable=True)
    link_references: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: US-222: hard-filter dimension for `StructuredFilterService`. Nullable,
    #: no backfill — see migration 0023.
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecommendationORM(Base):
    """US-310: one row per ranked property per search — the audit trail of
    what was recommended, why (`signals`), and its delivery/feedback
    lifecycle. `signals` stores `RankingSignal[]` as
    `[{"name", "weight", "value"}]` (dynamic, no fixed score columns)."""

    __tablename__ = "recommendations"
    __table_args__ = (
        Index("ix_recommendations_lead_id", "lead_id"),
        Index("ix_recommendations_generated_at", "generated_at"),
    )

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
    buyer_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("buyer_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    signals: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(String(2000), nullable=False)
    neighborhood: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: Reserved for future feedback events (learning loop) — no writer yet.
    feedback: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
