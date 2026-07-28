"""US-219 migration (0022): `buyer_profiles.motivation` upgrade/downgrade.

Loads the migration module directly by file path (mirrors how Alembic itself
resolves `alembic/versions/*.py`, which is not a regular importable package)
and runs its `upgrade()`/`downgrade()` against a throwaway SQLite table via
`alembic.operations.Operations`, the standard way to unit-test a single
migration's column-level DDL without running the full (Postgres-only, e.g.
pgvector/HNSW) migration chain.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0022_us219_buyer_profile_motivation.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "us219_buyer_profile_motivation_migration", MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_metadata():
    migration = _load_migration()
    assert migration.revision == "0022"
    assert migration.down_revision == "0021"


def test_upgrade_adds_motivation_column():
    migration = _load_migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text("CREATE TABLE buyer_profiles (id VARCHAR PRIMARY KEY, lead_id VARCHAR)")
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

        columns = {col["name"] for col in sa.inspect(connection).get_columns("buyer_profiles")}
    assert "motivation" in columns


def test_downgrade_drops_motivation_column():
    migration = _load_migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE buyer_profiles (id VARCHAR PRIMARY KEY, lead_id VARCHAR, "
                "motivation VARCHAR)"
            )
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.downgrade()

        columns = {col["name"] for col in sa.inspect(connection).get_columns("buyer_profiles")}
    assert "motivation" not in columns
