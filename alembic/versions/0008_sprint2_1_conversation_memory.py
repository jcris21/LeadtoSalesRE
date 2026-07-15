"""Sprint 2.1 — AI-102: adds `conversation_memory`, the free-text
conversational-signal table already documented in
`Documents/Oficial/AI_Recommendation_Domain_Model.md` §4 (see
`openspec/changes/conversation-memory-extraction-ai-102/design.md`). Purely
additive — no existing table is touched.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("memory_type", sa.String(32), nullable=False),
        sa.Column("entity_name", sa.String(128), nullable=False),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_conversation_memory_organization_id", "conversation_memory", ["organization_id"]
    )
    op.create_index("ix_conversation_memory_lead_id", "conversation_memory", ["lead_id"])
    op.create_index(
        "ix_conversation_memory_conversation_id", "conversation_memory", ["conversation_id"]
    )
    op.create_index("ix_conversation_memory_created_at", "conversation_memory", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_conversation_memory_created_at", table_name="conversation_memory")
    op.drop_index("ix_conversation_memory_conversation_id", table_name="conversation_memory")
    op.drop_index("ix_conversation_memory_lead_id", table_name="conversation_memory")
    op.drop_index("ix_conversation_memory_organization_id", table_name="conversation_memory")
    op.drop_table("conversation_memory")
