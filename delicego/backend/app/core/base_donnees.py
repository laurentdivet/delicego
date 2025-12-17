from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application


# IMPORTANT :
# L’engine async ne doit pas être partagé entre plusieurs boucles asyncio.
# Or, en tests (TestClient FastAPI), une autre boucle peut être créée.
# On maintient donc un cache par event loop.
_moteurs_par_boucle: dict[int, AsyncEngine] = {}
_fabriques_par_boucle: dict[int, async_sessionmaker[AsyncSession]] = {}


def _cle_boucle() -> int:
    """Identifiant stable de la boucle asyncio courante."""

    # On évite toute importation lourde (asyncio) et on s’appuie sur l’objet loop.
    try:
        import asyncio

        boucle = asyncio.get_running_loop()
    except RuntimeError:
        # Hors boucle : cas rare (imports) -> on retombe sur une clé fixe.
        return 0

    return id(boucle)


def creer_moteur_async() -> AsyncEngine:
    return create_async_engine(parametres_application.url_base_donnees, pool_pre_ping=True)


def _obtenir_fabrique_session() -> async_sessionmaker[AsyncSession]:
    cle = _cle_boucle()

    fabrique = _fabriques_par_boucle.get(cle)
    if fabrique is not None:
        return fabrique

    moteur = creer_moteur_async()
    _moteurs_par_boucle[cle] = moteur

    fabrique = async_sessionmaker(
        bind=moteur,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    _fabriques_par_boucle[cle] = fabrique

    return fabrique


async def fournir_session_async() -> AsyncIterator[AsyncSession]:
    fabrique = _obtenir_fabrique_session()
    async with fabrique() as session:
        yield session
