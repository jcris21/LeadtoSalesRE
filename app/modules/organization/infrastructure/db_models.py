"""SQLAlchemy ORM models for the Organization bounded context.

OrganizationORM.id doubles as the organization_id every other bounded context's
tables reference and filter by (QA-03 logical isolation). JSON columns store the
per-integration config blobs; secrets (api tokens) are stored as-is here for MVP
simplicity and are expected to sit behind Supabase's encryption-at-rest — a
dedicated secrets vault is a documented future improvement, not a Sprint 0 gap.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OrganizationORM(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="onboarding")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrganizationConfigORM(Base):
    __tablename__ = "organization_configs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    chatwoot_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    whatsapp_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    crm_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    google_workspace_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AdminUserORM(Base):
    """Human admin/broker user for the JWT-protected admin API (Sprint 0 Authentication)."""

    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
