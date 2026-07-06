import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings
from app.core.database import Base
from app.modules.conversation_ownership.infrastructure import (
    db_models as conversation_db_models,  # noqa: F401
)
from app.modules.intelligence_ai_admin.infrastructure import (
    db_models as ai_admin_db_models,  # noqa: F401
)

# Import every module's ORM models so Base.metadata is complete before autogenerate.
from app.modules.organization.infrastructure import (
    db_models as organization_db_models,  # noqa: F401
)
from app.shared.infrastructure import db_models as shared_db_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()
config.set_main_option(
    "sqlalchemy.url",
    str(settings.database_url)
    .replace("postgresql://", "postgresql+asyncpg://", 1)
    # configparser treats % as interpolation syntax; escape it so
    # URL-encoded characters in the password survive.
    .replace("%", "%%"),
)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
