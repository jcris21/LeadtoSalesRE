"""Sprint 2.1 — US-208: adds `financing_type` and `decision_maker_mode` to
`buyer_profiles`, extending `PROFILE_DIMENSIONS` from 5 to 7 (see
`openspec/changes/buyer-profile-dimensions-us-208/design.md`). Both columns
are nullable — `None` means "not yet captured", identical to the existing
five dimensions before completion; no backfill required.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "buyer_profiles", sa.Column("financing_type", sa.String(32), nullable=True)
    )
    op.add_column(
        "buyer_profiles", sa.Column("decision_maker_mode", sa.String(32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("buyer_profiles", "decision_maker_mode")
    op.drop_column("buyer_profiles", "financing_type")
