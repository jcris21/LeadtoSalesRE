"""Sprint 3.2 — US-304: HNSW index for pgvector semantic retrieval.

`vector_cosine_ops` matches the `<->` cosine-distance ordering used by
`PropertyRepository.semantic_search`; ascending cosine distance is the same
ranking the previous in-memory path produced with descending cosine
similarity (design.md D5). The column itself became `vector(1536)` in 0011.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_property_embeddings_vector_hnsw
        ON property_embeddings
        USING hnsw (vector vector_cosine_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_property_embeddings_vector_hnsw")
