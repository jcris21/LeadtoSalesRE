"""Sprint 3 — Conversation<->Lead identity matching: adds `contact_reference`
to leads (the identifier wacrm shares with Chatwoot) and `contact_reference`
+ `lead_id` to conversations, so the Coordinator can resolve a Lead from a
Conversation without either external system inventing an id the other
doesn't know (see `LeadLinker`).

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("contact_reference", sa.String(64), nullable=True))
    op.create_index("ix_leads_contact_reference", "leads", ["contact_reference"])

    op.add_column(
        "conversations", sa.Column("contact_reference", sa.String(64), nullable=True)
    )
    op.create_index(
        "ix_conversations_contact_reference", "conversations", ["contact_reference"]
    )
    op.add_column(
        "conversations",
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_conversations_lead_id", "conversations", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_conversations_lead_id", table_name="conversations")
    op.drop_column("conversations", "lead_id")
    op.drop_index("ix_conversations_contact_reference", table_name="conversations")
    op.drop_column("conversations", "contact_reference")
    op.drop_index("ix_leads_contact_reference", table_name="leads")
    op.drop_column("leads", "contact_reference")
