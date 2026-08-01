from logging.config import fileConfig
import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from geoalchemy2 import alembic_helpers

from app.core.config import get_settings
from app.db.base import Base
import app.models

settings = get_settings()

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    """
    Ignore tables that exist in the database but are not part of our SQLAlchemy models.
    This prevents Alembic from trying to drop PostGIS system tables.
    """
    if type_ == "table" and reflected and compare_to is None:
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""

    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
        render_item=alembic_helpers.render_item,
        process_revision_directives=alembic_helpers.writer,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
        render_item=alembic_helpers.render_item,
        process_revision_directives=alembic_helpers.writer,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()