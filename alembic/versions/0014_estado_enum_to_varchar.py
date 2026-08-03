"""Sprint 3.2 follow-up: converges the drifted `properties.estado` type.

The hand-edited Supabase database created `estado` as a Postgres enum
(`estado_propiedad`), so migration 0010's "add if missing" branch left it
untouched and every ORM write fails with DatatypeMismatchError (varchar
into enum). The reconciled schema (PropertyORM, 0010's fresh branch)
defines `estado` as varchar(32) — this migration converts the drifted
enum column to that shape with `USING estado::text` (values preserved)
and drops the now-unused enum type.

State-conditional like 0010: a database whose `estado` is already
varchar (fresh-0010 path) is left untouched.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-17
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")


def _estado_is_enum() -> bool:
    bind = op.get_bind()
    udt_name = bind.execute(
        sa.text(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_name = 'properties' AND column_name = 'estado'"
        )
    ).scalar()
    return udt_name == "estado_propiedad"


def upgrade() -> None:
    if context.is_offline_mode():
        logger.info("properties.estado: offline --sql mode — fresh state, nothing to do")
        return

    if not _estado_is_enum():
        logger.info("properties.estado: already varchar — nothing to do")
        return

    logger.info("properties.estado: drifted enum detected — converting to varchar(32)")
    # The drifted column carries an enum-typed DEFAULT that would keep a
    # dependency on the type; the reconciled schema has no server default.
    op.execute("ALTER TABLE properties ALTER COLUMN estado DROP DEFAULT")
    op.execute(
        "ALTER TABLE properties "
        "ALTER COLUMN estado TYPE varchar(32) USING estado::text"
    )
    op.execute("DROP TYPE IF EXISTS estado_propiedad")


def downgrade() -> None:
    # The enum was drift (never a migration-defined state); the reconciled
    # varchar(32) shape is already what 0010 defines, so there is nothing
    # to restore.
    pass
