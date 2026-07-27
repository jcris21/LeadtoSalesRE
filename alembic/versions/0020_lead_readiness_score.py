"""Adds `buyer_profiles.readiness_score` and `buyer_profiles.financing_readiness`
(US-214): the continuous weighted readiness score (0-100) and the 3-state
financing readiness classification (ready/pre_ready/discovery) produced by
LeadReadinessService.evaluate. Both are nullable -- existing profiles simply
have no readiness computed yet until evaluate() runs.

Additive only: does not touch leads.lead_score/lead_classification (US-209
Hot/Warm/Cold) or any existing buyer_profiles column.

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "buyer_profiles",
        sa.Column("readiness_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "buyer_profiles",
        sa.Column("financing_readiness", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("buyer_profiles", "financing_readiness")
    op.drop_column("buyer_profiles", "readiness_score")
