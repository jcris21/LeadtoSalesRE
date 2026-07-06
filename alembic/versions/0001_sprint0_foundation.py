"""Sprint 0 foundation: organizations, admin users, prompt registry, AI decision
traces, outbox/inbox event bus tables. RLS by organization_id applied as
defense-in-depth per Architecture.md Iteration 1.

Revision ID: 0001
Revises:
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="onboarding"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "organization_configs",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("chatwoot_config", postgresql.JSON, nullable=True),
        sa.Column("whatsapp_config", postgresql.JSON, nullable=True),
        sa.Column("crm_config", postgresql.JSON, nullable=True),
        sa.Column("google_workspace_config", postgresql.JSON, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "admin_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="admin"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_users_organization_id", "admin_users", ["organization_id"])

    op.create_table(
        "prompt_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.UniqueConstraint("organization_id", "agent_name", name="uq_org_agent"),
    )
    op.create_index("ix_prompt_templates_organization_id", "prompt_templates", ["organization_id"])

    op.create_table(
        "prompt_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "prompt_template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_prompt_versions_prompt_template_id", "prompt_versions", ["prompt_template_id"]
    )

    op.create_table(
        "ai_decision_traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column(
            "prompt_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id"),
            nullable=True,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tool_calls", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("context_refs", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("cost_usd", sa.Float, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("output", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ai_decision_traces_organization_id", "ai_decision_traces", ["organization_id"]
    )
    op.create_index(
        "ix_ai_decision_traces_conversation_id", "ai_decision_traces", ["conversation_id"]
    )
    op.create_index("ix_ai_decision_traces_created_at", "ai_decision_traces", ["created_at"])

    op.create_table(
        "outbox_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
    )
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_organization_id", "outbox_events", ["organization_id"])
    op.create_index("ix_outbox_events_processed_at", "outbox_events", ["processed_at"])

    op.create_table(
        "inbox_records",
        sa.Column("consumer_name", sa.String(128), nullable=False),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outbox_events.event_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("consumer_name", "event_id"),
    )

    _apply_rls()


def _apply_rls() -> None:
    """RLS by organization_id as defense-in-depth (Architecture.md §5), effective
    for any database role WITHOUT BYPASSRLS. The FastAPI backend connects with
    Supabase's `service_role` key (BYPASSRLS by design), so these policies do
    NOT gate the backend's own queries today — organization_id isolation for
    the backend is enforced at the application layer (see app/core/database.py).
    These policies matter the moment anything queries this database with a
    lesser role, e.g. Supabase PostgREST/anon or authenticated JWT access. A
    consumer relying on RLS from a non-bypass role must additionally
    `SET LOCAL app.current_organization_id` per transaction — not implemented
    here since no such consumer exists yet in Sprint 0.
    Tables without a direct organization_id column (prompt_versions,
    ai_decision_traces via prompt_version_id, inbox_records) are protected
    transitively by their parent's RLS via the FK join in the owning repository
    query, and are not given a standalone policy here.
    """
    org_scoped_tables = [
        "organizations",
        "organization_configs",
        "admin_users",
        "prompt_templates",
        "ai_decision_traces",
    ]
    for table in org_scoped_tables:
        id_column = "id" if table == "organizations" else "organization_id"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY org_isolation_{table} ON {table}
            USING ({id_column} = current_setting('app.current_organization_id', true)::uuid)
            """
        )


def downgrade() -> None:
    op.drop_table("inbox_records")
    op.drop_table("outbox_events")
    op.drop_table("ai_decision_traces")
    op.drop_table("prompt_versions")
    op.drop_table("prompt_templates")
    op.drop_table("admin_users")
    op.drop_table("organization_configs")
    op.drop_table("organizations")
