"""Sprint 2.2 — US-211: adds the two affinity-profile snapshot columns
documented in `Documents/Oficial/AI_Recommendation_Domain_Model.md` §"Uso de
JSONB" (see `openspec/changes/affinity-profile-aggregation-us-211/design.md`).
Purely additive — both columns are nullable, derived data (recomputable from
`conversation_memory`), written solely by `ProfileAggregationService`:
`buyer_persona` is never mirrored from wacrm, so CON-2 is unaffected.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "buyer_profiles", sa.Column("ai_profile", postgresql.JSONB, nullable=True)
    )
    op.add_column("leads", sa.Column("buyer_persona", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "buyer_persona")
    op.drop_column("buyer_profiles", "ai_profile")
