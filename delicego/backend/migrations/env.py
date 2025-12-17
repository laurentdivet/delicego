from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.configuration import parametres_application
from app.domaine.modeles import BaseModele  # important : importe tous les modèles via __init__

# Configuration Alembic
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Métadonnées cibles
target_metadata = BaseModele.metadata


def url_base_donnees() -> str:
    return parametres_application.url_base_donnees


def run_migrations_offline() -> None:
    """Exécute les migrations en mode 'offline'."""

    context.configure(
        url=url_base_donnees(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Exécute les migrations en mode 'online' avec SQLAlchemy async."""

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url_base_donnees()

    connectable = async_engine_from_config(
        configuration,
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
