"""Sprint 2.1 — US-209: adds the append-only `lead_objections` table and
`leads.lead_classification` (Hot/Warm/Cold), computed by `LeadScoringService`
whenever a new objection is recorded (see
`openspec/changes/lead-objections-classification-us-209/design.md`).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead_objections",
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
        ),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("raw_text", sa.String(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_lead_objections_organization_id", "lead_objections", ["organization_id"])
    op.create_index("ix_lead_objections_lead_id", "lead_objections", ["lead_id"])
    op.create_index("ix_lead_objections_created_at", "lead_objections", ["created_at"])

    op.add_column(
        "leads",
        sa.Column("lead_classification", sa.String(16), nullable=False, server_default="hot"),
    )
    op.alter_column("leads", "lead_classification", server_default=None)


def downgrade() -> None:
    op.drop_column("leads", "lead_classification")

    op.drop_index("ix_lead_objections_created_at", table_name="lead_objections")
    op.drop_index("ix_lead_objections_lead_id", table_name="lead_objections")
    op.drop_index("ix_lead_objections_organization_id", table_name="lead_objections")
    op.drop_table("lead_objections")
