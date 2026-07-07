"""Sprint 2 — Lead & Qualification (M3): leads (local mirror of wacrm, QA-13
`synced_at`), buyer_profiles (progressive profiling, E3), crm_sync_cursors
(CDC watermark per organization, §7.7) and crm_access_audit (QA-08 centralized
audit). RLS by organization_id as defense-in-depth, same rationale as 0001.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("crm_lead_id", sa.String(64), nullable=False),
        sa.Column("pipeline_stage", sa.String(32), nullable=False, server_default="New"),
        sa.Column("lead_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("assigned_broker_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "crm_lead_id", name="uq_org_crm_lead"),
    )
    op.create_index("ix_leads_organization_id", "leads", ["organization_id"])
    op.create_index("ix_leads_synced_at", "leads", ["synced_at"])

    op.create_table(
        "buyer_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("budget_min", sa.Float, nullable=True),
        sa.Column("budget_max", sa.Float, nullable=True),
        sa.Column("locations", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("property_type", sa.String(32), nullable=True),
        sa.Column("timeline", sa.String(32), nullable=True),
        sa.Column("must_haves", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_buyer_profiles_organization_id", "buyer_profiles", ["organization_id"])

    op.create_table(
        "crm_sync_cursors",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("watermark", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "crm_access_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("crm_lead_id", sa.String(64), nullable=True),
        sa.Column("allowed", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("detail", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_access_audit_organization_id", "crm_access_audit", ["organization_id"])
    op.create_index("ix_crm_access_audit_occurred_at", "crm_access_audit", ["occurred_at"])

    for table in ("leads", "buyer_profiles", "crm_sync_cursors", "crm_access_audit"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY org_isolation_{table} ON {table}
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            """
        )


def downgrade() -> None:
    op.drop_table("crm_access_audit")
    op.drop_table("crm_sync_cursors")
    op.drop_table("buyer_profiles")
    op.drop_table("leads")
