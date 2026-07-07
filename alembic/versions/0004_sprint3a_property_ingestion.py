"""Sprint 3A — Recommendation (M4): properties (local mirror of the
inventory source, Architecture.md §6.3) and property_embeddings
(precalculated vectors keyed by a content hash so the pipeline never
re-embeds on the request path). RLS by organization_id as defense-in-depth,
same rationale as 0001/0003.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "properties",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("price", sa.Float, nullable=False),
        sa.Column("zone", sa.String(120), nullable=False),
        sa.Column("property_type", sa.String(32), nullable=False),
        sa.Column("features", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("description", sa.String(2000), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "external_id", name="uq_org_external_id"),
    )
    op.create_index("ix_properties_organization_id", "properties", ["organization_id"])

    op.create_table(
        "property_embeddings",
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("vector", postgresql.JSONB, nullable=False),
        sa.Column("model_version", sa.String(32), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.execute("ALTER TABLE properties ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY org_isolation_properties ON properties
        USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.drop_table("property_embeddings")
    op.drop_table("properties")
