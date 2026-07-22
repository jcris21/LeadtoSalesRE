"""Sprint 4.1 — US-402: creates `brokers` (new entity, no equivalent existed
before this change) and `availability_checks` (append-only audit trail of
every AvailabilityValidatorPort.check() call — see design.md Decision 1: a
dedicated table, not a column on the future `appointments` table, so the
2-4h re-validation scenario leaves a distinguishable trace via `source`).
RLS by organization_id, same pattern as 0012.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brokers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("specialties", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("availability", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_brokers_organization_id", "brokers", ["organization_id"])

    op.execute("ALTER TABLE brokers ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY org_isolation_brokers ON brokers
        USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
        """
    )

    op.create_table(
        "availability_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "broker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brokers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("slot", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_availability_checks_organization_id", "availability_checks", ["organization_id"]
    )
    op.create_index(
        "ix_availability_checks_property_slot", "availability_checks", ["property_id", "slot"]
    )
    op.create_index(
        "ix_availability_checks_checked_at", "availability_checks", ["checked_at"]
    )

    op.execute("ALTER TABLE availability_checks ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY org_isolation_availability_checks ON availability_checks
        USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.drop_table("availability_checks")
    op.drop_table("brokers")
