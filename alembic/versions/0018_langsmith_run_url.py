"""Adds `ai_decision_traces.langsmith_run_url` — links each AI decision trace
row to its LangSmith run permalink (Task 8, LangSmith instrumentation), so a
human debugging from the AI Sidebar can jump straight to the full trace.

Nullable: only populated when LangSmith tracing is enabled and active for
that decision; existing rows and untraced decisions simply have it unset.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_decision_traces",
        sa.Column("langsmith_run_url", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_decision_traces", "langsmith_run_url")
