"""Sprint 1 — Conversation & Ownership (M2): conversations (FSM + ownership
snapshot), archived_messages (raw conversation archive feeding E10) and
ownership_decisions (auditable Ownership Policy Engine record). RLS by
organization_id as defense-in-depth, same rationale as 0001.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chatwoot_conversation_id", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False, server_default="whatsapp"),
        sa.Column("state", sa.String(32), nullable=False, server_default="New"),
        sa.Column("owner_type", sa.String(16), nullable=False, server_default="unassigned"),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_reason", sa.Text, nullable=False, server_default="not evaluated"),
        sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "chatwoot_conversation_id", name="uq_org_chatwoot_conversation"
        ),
    )
    op.create_index("ix_conversations_organization_id", "conversations", ["organization_id"])
    op.create_index("ix_conversations_state", "conversations", ["state"])
    op.create_index("ix_conversations_last_contact_at", "conversations", ["last_contact_at"])

    op.create_table(
        "archived_messages",
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
        sa.Column("chatwoot_message_id", sa.String(64), nullable=False),
        sa.Column("sender", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("raw_payload", postgresql.JSONB, nullable=False),
        sa.Column("message_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "conversation_id", "chatwoot_message_id", name="uq_conversation_chatwoot_message"
        ),
    )
    op.create_index(
        "ix_archived_messages_organization_id", "archived_messages", ["organization_id"]
    )
    op.create_index(
        "ix_archived_messages_conversation_id", "archived_messages", ["conversation_id"]
    )

    op.create_table(
        "ownership_decisions",
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
        sa.Column("scenario", sa.String(64), nullable=False),
        sa.Column("inputs_snapshot", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("selected_owner", sa.String(16), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ownership_decisions_organization_id", "ownership_decisions", ["organization_id"]
    )
    op.create_index(
        "ix_ownership_decisions_conversation_id", "ownership_decisions", ["conversation_id"]
    )

    for table in ("conversations", "archived_messages", "ownership_decisions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY org_isolation_{table} ON {table}
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            """
        )


def downgrade() -> None:
    op.drop_table("ownership_decisions")
    op.drop_table("archived_messages")
    op.drop_table("conversations")
