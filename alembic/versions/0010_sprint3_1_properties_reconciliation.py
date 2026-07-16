"""Sprint 3.1 — US-309: reconciles the `properties` schema drift between the
0004 migration (`zone`) and the hand-edited Supabase database (`District`,
`name_address`, `Link_references` text, `estado` — added outside Alembic).

State-conditional (design.md D2): inspects the live columns and converges
BOTH documented starting states to the reconciled snake_case schema —
`district`, `name_address` (text), `estado` (text), `link_references`
(jsonb list of media URLs). Logs which branch ran. Downgrade restores the
0004 shape.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-15
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")


def _column_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("properties")}


def _fresh_state_upgrade() -> None:
    """The fresh-0004 branch, also emitted verbatim in offline `--sql` mode
    (the inspector needs a live connection; the drifted-Supabase branch can
    only run online)."""
    op.alter_column("properties", "zone", new_column_name="district")
    op.add_column("properties", sa.Column("name_address", sa.String(255), nullable=True))
    op.add_column("properties", sa.Column("estado", sa.String(32), nullable=True))
    op.add_column(
        "properties",
        sa.Column(
            "link_references",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def upgrade() -> None:
    if context.is_offline_mode():
        logger.info("properties: offline --sql mode — emitting the fresh-0004 branch")
        _fresh_state_upgrade()
        return

    columns = _column_names()

    if "district" not in columns:
        if "District" in columns:
            logger.info("properties: drifted state detected — renaming District -> district")
            op.alter_column("properties", "District", new_column_name="district")
        elif "zone" in columns:
            logger.info("properties: fresh 0004 state detected — renaming zone -> district")
            op.alter_column("properties", "zone", new_column_name="district")
        else:
            raise RuntimeError(
                "properties has neither 'district', 'District' nor 'zone' — "
                "unexpected schema state, refusing to guess"
            )

    if "name_address" not in columns:
        op.add_column("properties", sa.Column("name_address", sa.String(255), nullable=True))

    if "estado" not in columns:
        op.add_column("properties", sa.Column("estado", sa.String(32), nullable=True))

    if "link_references" not in columns:
        if "Link_references" in columns:
            # Drifted state: text column holding a bare URL — wrap non-null
            # values into a one-element jsonb array, null/empty becomes [].
            logger.info(
                "properties: converting Link_references (text) -> link_references (jsonb)"
            )
            op.alter_column("properties", "Link_references", new_column_name="link_references")
            op.execute(
                """
                ALTER TABLE properties
                ALTER COLUMN link_references TYPE jsonb
                USING CASE
                    WHEN link_references IS NULL OR link_references = '' THEN '[]'::jsonb
                    ELSE jsonb_build_array(link_references)
                END
                """
            )
            op.alter_column(
                "properties",
                "link_references",
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            )
        else:
            op.add_column(
                "properties",
                sa.Column(
                    "link_references",
                    postgresql.JSONB,
                    nullable=False,
                    server_default=sa.text("'[]'::jsonb"),
                ),
            )


def downgrade() -> None:
    # Restores the 0004 shape (`zone`, none of the reconciled columns). The
    # drifted pre-0010 Supabase state is not restored — it was never a
    # migration-defined state to begin with.
    op.drop_column("properties", "link_references")
    op.drop_column("properties", "estado")
    op.drop_column("properties", "name_address")
    op.alter_column("properties", "district", new_column_name="zone")
