"""Adds `buyer_profiles.bedrooms` — the eighth qualification dimension
(número de habitaciones), requested during the 2026-07-19 manual E2E run.

Nullable integer: existing profiles simply have the dimension pending;
`ProfilePatch` enforces the 1–15 range before anything reaches this column.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "buyer_profiles",
        sa.Column("bedrooms", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("buyer_profiles", "bedrooms")
