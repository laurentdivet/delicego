from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import creer_application
from app.domaine.modeles.referentiel import Menu


@pytest.mark.asyncio
async def test_api_client_menus_vide(session_test: AsyncSession) -> None:
    """
    La base peut contenir des données créées par d'autres tests.
    On nettoie explicitement la table Menu pour garantir un test déterministe.
    """

    # Nettoyage explicite
    await session_test.execute(delete(Menu))
    await session_test.commit()

    # IMPORTANT: ne pas importer l'app globale (app.main.app) car elle utilise
    # la factory DB "réelle" (parametres_application.url_base_donnees) et peut
    # pointer vers une base non reset par la fixture session_test.
    # On construit une app de test et on override fournir_session => même engine que session_test.
    app = creer_application()
    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
    from app.api.dependances import fournir_session

    async def _fournir_session_override():
        assert session_test.bind is not None
        async with _AsyncSession(bind=session_test.bind, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[fournir_session] = _fournir_session_override

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/api/client/menus")

    assert response.status_code == 200
    assert response.json() == []
