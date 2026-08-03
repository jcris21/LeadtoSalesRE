"""Sprint 4.2 — US-404: creates `appointments`, the materialized outcome of
`SchedulingService.book_visit` once `AvailabilityValidatorPort` (US-402)
confirms a slot and `GoogleCalendarPort` (US-403) creates the event. RLS by
organization_id, same pattern as 0016.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "broker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brokers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("calendar_event_id", sa.String(255), nullable=False),
        sa.Column("meet_link", sa.String(255), nullable=False),
    )
    op.create_index("ix_appointments_organization_id", "appointments", ["organization_id"])
    op.create_index("ix_appointments_lead_id", "appointments", ["lead_id"])
    op.create_index("ix_appointments_scheduled_at", "appointments", ["scheduled_at"])

    op.execute("ALTER TABLE appointments ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY org_isolation_appointments ON appointments
        USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.drop_table("appointments")
