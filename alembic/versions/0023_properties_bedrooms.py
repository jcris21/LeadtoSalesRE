"""Adds `properties.bedrooms` (US-222): the property inventory never modeled
bedroom count before this change. `bedrooms` becomes a Nivel 1 (blocking)
`BuyerProfile` dimension whose search-pipeline role is a hard filter in
`StructuredFilterService.filter_candidates` -- this column is what the new
`PropertyORM.bedrooms == bedrooms` `WHERE` clause reads.

Nullable, no default, no backfill: existing inventory rows have no bedroom
count until re-ingested/backfilled by a separate data task (design.md
Decision 1). A `NULL` row never matches a lead-specified bedroom constraint,
same "absent value never satisfies a present constraint" semantics
`Property.matches_hard_filters` already uses for `zone`/`property_type`.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column("bedrooms", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("properties", "bedrooms")
