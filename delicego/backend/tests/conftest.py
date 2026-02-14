from __future__ import annotations

from collections.abc import AsyncIterator
import os
from urllib.parse import urlparse

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.domaine.modeles import BaseModele


def _is_running_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def _rewrite_database_url_for_pytest(url: str) -> str:
    """Rewrite DATABASE_URL to use the dedicated test DB under pytest.

    Security rules:
    - Only runs under pytest.
    - If URL already targets a DB containing "test" => keep.
    - If URL targets exactly "delicego" => rewrite to "delicego_test".
    - Otherwise => refuse (raise).
    """

    if not _is_running_pytest():
        return url

    candidate = (url or "").strip()
    if not candidate:
        return candidate

    parsed = urlparse(
        candidate.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    dbname = (parsed.path or "").lstrip("/")
    dbname_lower = dbname.lower()

    # Already on a test DB => keep.
    if "test" in dbname_lower:
        return candidate

    # If it's the known dev/prod DB name, rewrite safely.
    if dbname == "delicego":
        rewritten = candidate[: -len(dbname)] + "delicego_test"
        os.environ["DATABASE_URL"] = rewritten
        return rewritten

    raise RuntimeError(
        "Refusing to run pytest with a non-test database URL.\n"
        f"- dbname={dbname!r} (expected a name containing 'test' or exactly 'delicego')\n"
        "If you really intend to run tests, point DATABASE_URL to a test database."
    )


def _database_url_for_tests() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if url:
        url = _rewrite_database_url_for_pytest(url)
        print("DB utilisée pour tests:", url)
        return url

    if not _is_running_pytest():
        raise RuntimeError(
            "DATABASE_URL is required outside pytest. Refusing implicit fallback."
        )

    # Fallback DEV sécurisé (base dédiée tests)
    url = "postgresql+asyncpg://delicego:delicego@127.0.0.1:5433/delicego_test"
    print("DB utilisée pour tests:", url)
    return url


@pytest_asyncio.fixture(autouse=True)
async def _forcer_env_test() -> None:
    """Marque explicitement l'environnement de tests.

    Utilisé pour des bypass STRICTEMENT en tests (ex: passlib/bcrypt instable).
    """

    os.environ.setdefault("ENV", "test")


def _assert_safe_test_database(url: str) -> None:
    parsed = urlparse(
        url.replace("postgresql+asyncpg://", "postgresql://", 1)
    )

    dbname = (parsed.path or "").lstrip("/")
    host = parsed.hostname or ""
    port = parsed.port or ""

    allow_override = (os.getenv("ALLOW_TEST_DB_RESET") or "").strip() == "1"
    looks_like_test = "test" in (dbname or "").lower()

    if not looks_like_test and not allow_override:
        raise RuntimeError(
            "Refusing to reset database because it does not look like a TEST database.\n"
            f"- dbname={dbname!r} host={host!r} port={port!r}\n"
            "Use a database containing 'test' in its name "
            "or set ALLOW_TEST_DB_RESET=1."
        )


@pytest_asyncio.fixture
async def moteur_test() -> AsyncIterator[AsyncEngine]:
    from sqlalchemy import text

    url = _database_url_for_tests()
    _assert_safe_test_database(url)

    moteur = create_async_engine(url, pool_pre_ping=True)

    async with moteur.begin() as connexion:
        await connexion.execute(text("DROP SCHEMA public CASCADE"))
        await connexion.execute(text("CREATE SCHEMA public"))
        await connexion.execute(text("GRANT ALL ON SCHEMA public TO CURRENT_USER"))
        await connexion.execute(text("GRANT ALL ON SCHEMA public TO public"))
        await connexion.run_sync(BaseModele.metadata.create_all)

    try:
        yield moteur
    finally:
        await moteur.dispose()


@pytest_asyncio.fixture
async def session_test(moteur_test: AsyncEngine) -> AsyncIterator[AsyncSession]:
    fabrique = async_sessionmaker(
        bind=moteur_test,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with fabrique() as session:
        try:
            yield session
        finally:
            await session.rollback()
