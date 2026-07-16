"""Sprint 3.1 — US-310: creates `recommendations`, the audit trail of every
recommendation search (one row per ranked property: rank, score, dynamic
`signals` jsonb, explanation, neighborhood snapshot, delivery/feedback
lifecycle). Closes backlog US-301 ("store Recommendation Session"). RLS by
organization_id, same pattern as 0004.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendations",
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
        sa.Column(
            "buyer_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("buyer_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("signals", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("explanation", sa.String(2000), nullable=False),
        sa.Column("neighborhood", postgresql.JSONB, nullable=True),
        sa.Column("feedback", postgresql.JSONB, nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_recommendations_organization_id", "recommendations", ["organization_id"]
    )
    op.create_index("ix_recommendations_lead_id", "recommendations", ["lead_id"])
    op.create_index("ix_recommendations_generated_at", "recommendations", ["generated_at"])

    op.execute("ALTER TABLE recommendations ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY org_isolation_recommendations ON recommendations
        USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.drop_table("recommendations")
