"""Adds `outbox_events.next_attempt_at` and `dead_lettered_at` — closes G12
(docs/e2e-manual-chat-checklist.md): the outbox worker previously retried a
failing row every poll interval forever, with no backoff and no ceiling. A
handler that fails on every delivery (e.g. a downstream outage, or the
schema-mismatch incident that burned the Gemini quota on 2026-07-23) could
retry hundreds of times per minute.

`next_attempt_at` gates when a failed row becomes eligible again (exponential
backoff computed from `attempts`); `dead_lettered_at` stops retries entirely
once `attempts` reaches the configured ceiling, leaving the row (and
`last_error`) in place for manual inspection instead of processing it forever.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_outbox_events_next_attempt_at",
        "outbox_events",
        ["next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_next_attempt_at", table_name="outbox_events")
    op.drop_column("outbox_events", "dead_lettered_at")
    op.drop_column("outbox_events", "next_attempt_at")
