"""SQLAlchemy ORM models for the Lead & Qualification bounded context.

leads is the local mirror of wacrm leads (wacrm stays SoR, CON-2): only the
Lead Sync Adapter writes it; `synced_at` is the QA-13 staleness reference.
buyer_profiles holds the progressive-profiling output (E3, one row per lead).
crm_sync_cursors persists the CDC watermark per organization so polling
resumes after any crash without losing or reprocessing changes (§7.7).
crm_access_audit is the QA-08 audit log: every read/write against CRM data
goes through the Lead Sync Adapter and leaves a row here — allowed or denied.
"""

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


class LeadORM(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("organization_id", "crm_lead_id", name="uq_org_crm_lead"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    crm_lead_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="New")
    lead_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: Hot/Warm/Cold, derived from lead_score by LeadScoringService (US-209).
    lead_classification: Mapped[str] = mapped_column(String(16), nullable=False, default="hot")
    assigned_broker_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    #: External contact identifier (e.g. WhatsApp phone number) shared with
    #: Chatwoot — the sole key a Conversation can use to resolve its Lead
    #: without either system inventing an id the other doesn't know (Sprint 3).
    contact_reference: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: US-211 persona snapshot (family_stage/has_pets/communication), written
    #: solely by ProfileAggregationService — never mirrored from wacrm, so
    #: CON-2 (wacrm as SoR) is unaffected, same precedent as lead_score.
    buyer_persona: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BuyerProfileORM(Base):
    __tablename__ = "buyer_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    budget_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    locations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    property_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    timeline: Mapped[str | None] = mapped_column(String(32), nullable=True)
    must_haves: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: US-208 dimensions: how the buyer plans to pay and who is involved in
    #: the purchase decision.
    financing_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision_maker_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: US-211 affinity snapshot (modern_score/family_score/confidence),
    #: derived from conversation_memory by ProfileAggregationService — never
    #: written by BuyerProfileCaptureService nor read by completeness().
    ai_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: US-214 continuous readiness score (0-100) + financing_readiness tri-state
    #: (ready/pre_ready/discovery), written solely by LeadReadinessService.evaluate --
    #: same isolated-writer precedent as ai_profile, never touched by save().
    readiness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    financing_readiness: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LeadObjectionORM(Base):
    """Append-only sales-objection log (US-209): one row per detected
    objection, never updated or deleted."""

    __tablename__ = "lead_objections"
    __table_args__ = (Index("ix_lead_objections_lead_id", "lead_id"),)

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
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_text: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class SyncCursorORM(Base):
    """One CDC watermark per organization (SyncCursorPort, §7.7)."""

    __tablename__ = "crm_sync_cursors"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    watermark: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CRMAccessAuditORM(Base):
    """QA-08: centralized audit of every CRM data access through the adapter."""

    __tablename__ = "crm_access_audit"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    crm_lead_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    allowed: Mapped[bool] = mapped_column(nullable=False, default=True)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
