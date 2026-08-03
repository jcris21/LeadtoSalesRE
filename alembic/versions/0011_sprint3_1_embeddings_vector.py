"""Sprint 3.1 — US-308: enables pgvector and converts
`property_embeddings.vector` from jsonb to `vector(1536)`
(text-embedding-3-small dimensionality).

Discards `hash-v1` stand-in rows first (design.md D7): 16-dim hash vectors
cannot become 1536-dim, and they are derived data — the hash-gated ingestion
pipeline recomputes them from `properties` content once a real model is
configured. Downgrade converts back to jsonb (pgvector's text form `[...]`
is valid JSON, so real vectors survive as jsonb arrays).

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("DELETE FROM property_embeddings WHERE model_version = 'hash-v1'")
    op.execute(
        """
        ALTER TABLE property_embeddings
        ALTER COLUMN vector TYPE vector(1536)
        USING vector::text::vector(1536)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE property_embeddings
        ALTER COLUMN vector TYPE jsonb
        USING vector::text::jsonb
        """
    )
