from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.configuration import parametres_application
from app.domaine.modeles import BaseModele  # importe aussi tous les modèles


@pytest_asyncio.fixture
async def moteur_test() -> AsyncIterator[AsyncEngine]:
    """Moteur de base de données pour les tests.

    Scope function pour éviter les problèmes de boucle asyncio :
    un moteur async ne doit jamais être partagé entre plusieurs event loops.
    """

    moteur = create_async_engine(
        parametres_application.url_base_donnees,
        pool_pre_ping=True,
    )

    async with moteur.begin() as connexion:
        # Repartir d’un schéma propre à chaque test
        # NOTE: sous PostgreSQL, BaseModele.metadata.drop_all() peut deadlocker si des connexions
        # précédentes sont encore en cours de teardown. Pour fiabiliser, on force le reset du schéma
        # via un DROP SCHEMA ... CASCADE.
        from sqlalchemy import text

        await connexion.execute(text("DROP SCHEMA public CASCADE"))
        await connexion.execute(text("CREATE SCHEMA public"))
        # Réappliquer les droits par défaut (sinon FK/insert peuvent échouer selon le rôle)
        await connexion.execute(text("GRANT ALL ON SCHEMA public TO CURRENT_USER"))
        await connexion.execute(text("GRANT ALL ON SCHEMA public TO public"))
        # Éviter les InvalidCachedStatementError avec asyncpg quand le schéma change
        # (ne peut pas être exécuté dans un bloc transactionnel)
        await connexion.run_sync(BaseModele.metadata.create_all)

    try:
        yield moteur
    finally:
        await moteur.dispose()


@pytest_asyncio.fixture
async def session_test(moteur_test: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session SQLAlchemy async isolée par test."""

    fabrique = async_sessionmaker(
        bind=moteur_test,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with fabrique() as session:
        try:
            yield session
        finally:
            # Sécurité : rollback si le test a oublié de commit
            await session.rollback()
