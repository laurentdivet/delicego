from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
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

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/api/client/menus")

    assert response.status_code == 200
    assert response.json() == []
