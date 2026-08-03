"""Adds `buyer_profiles.motivation` (US-219): purchase motivation
(relocation/investment/vacation/first_home), detected by the new
`extract_motivation` deterministic extractor and treated as a regular
progressive-profiling dimension (same capture pattern as `timeline`/
`financing_type`), not an isolated-writer snapshot like `ai_profile`/
`readiness_score`. Nullable -- existing profiles simply have no motivation
captured until a lead message expresses one.

Additive only: does not touch any existing `buyer_profiles` column, and does
not depend on US-214 (already merged as revision 0020/0021 in this chain).

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "buyer_profiles",
        sa.Column("motivation", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("buyer_profiles", "motivation")
