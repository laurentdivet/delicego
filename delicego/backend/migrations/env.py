from __future__ import annotations

import asyncio
import os
from urllib.parse import urlsplit, urlunsplit
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.domaine.modeles import BaseModele  # important : importe tous les modèles via __init__

# Configuration Alembic
config = context.config


def _mask_url_password(url: str) -> str:
    """Retourne une version loggable d'une URL (masque le password si présent)."""
    try:
        parts = urlsplit(url)
        if parts.password is None:
            return url
        # reconstruit netloc en masquant le mot de passe
        user = parts.username or ""
        host = parts.hostname or ""
        netloc = f"{user}:***@{host}"
        if parts.port:
            netloc += f":{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        # fallback best-effort
        return url.replace(":delicego@", ":***@")


def _is_valid_postgresql_url(url: str) -> bool:
    return url.startswith("postgresql://") or url.startswith("postgresql+asyncpg://")


def _resolve_migrations_url() -> str:
    """Résolution stricte de l'URL DB pour les migrations.

    Priorité:
    1) DATABASE_URL (obligatoire en CI/prod)
    2) alembic.ini sqlalchemy.url si et seulement si c'est une vraie URL postgresql*
    Sinon: erreur.
    """

    env_url = os.getenv("DATABASE_URL")
    if env_url:
        if not _is_valid_postgresql_url(env_url):
            raise RuntimeError(
                "DATABASE_URL must be a valid postgresql URL (postgresql:// or postgresql+asyncpg://). "
                f"Got: {_mask_url_password(env_url)}"
            )
        return env_url

    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url and _is_valid_postgresql_url(ini_url):
        return ini_url

    raise RuntimeError(
        "DATABASE_URL is required for migrations (or set a valid sqlalchemy.url in alembic.ini)"
    )


# Résoudre l'URL une fois (mode strict) et la pousser dans la config.
# IMPORTANT: doit être fait avant la création de l'engine.
resolved_url = _resolve_migrations_url()
print("[alembic] sqlalchemy.url =", _mask_url_password(resolved_url))
config.set_main_option("sqlalchemy.url", resolved_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Métadonnées cibles
target_metadata = BaseModele.metadata


def url_base_donnees() -> str:
    # Config est forcée par _resolve_migrations_url() au chargement de env.py
    url = config.get_main_option("sqlalchemy.url")
    assert url
    return url


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
