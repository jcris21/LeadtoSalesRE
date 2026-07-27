"""AI-106: creates knowledge_documents (own pgvector store, separate from property_embeddings,
which indexes properties, not knowledge). Enables pgvector (idempotent - already enabled by 0011
if that migration ran) and adds an HNSW cosine index, mirroring 0011/0013.

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("embedding", postgresql.JSONB, nullable=False),
        sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_knowledge_documents_organization_id", "knowledge_documents", ["organization_id"]
    )
    op.create_index("ix_knowledge_documents_category", "knowledge_documents", ["category"])
    op.create_index("ix_knowledge_documents_approved", "knowledge_documents", ["approved"])

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        ALTER TABLE knowledge_documents
        ALTER COLUMN embedding TYPE vector(1536)
        USING embedding::text::vector(1536)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_knowledge_documents_embedding_hnsw
        ON knowledge_documents
        USING hnsw (embedding vector_cosine_ops)
        """
    )

    op.execute("ALTER TABLE knowledge_documents ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY org_isolation_knowledge_documents ON knowledge_documents
        USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.drop_table("knowledge_documents")
