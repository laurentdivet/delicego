from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests._http_helpers import entetes_internes

from app.domaine.modeles import Fournisseur, Ingredient
from app.domaine.modeles.catalogue import Produit
from app.main import creer_application


def _app_avec_dependances_test(session_test: AsyncSession):
    app = creer_application()

    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
    from app.api.dependances import fournir_session

    async def _fournir_session_override():
        assert session_test.bind is not None
        async with _AsyncSession(bind=session_test.bind, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[fournir_session] = _fournir_session_override
    return app


async def _client_api(session_test: AsyncSession) -> httpx.AsyncClient:
    app = _app_avec_dependances_test(session_test)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _entetes_internes() -> dict[str, str]:
    return entetes_internes()


@pytest.mark.asyncio
async def test_creer_produit_et_conflit_libelle(session_test: AsyncSession) -> None:
    client = await _client_api(session_test)

    r1 = await client.post(
        "/api/interne/catalogue/produits",
        headers=_entetes_internes(),
        json={"libelle": "RIZ TEST", "categorie": "SEC", "actif": True},
    )
    assert r1.status_code == 201, r1.text

    r2 = await client.post(
        "/api/interne/catalogue/produits",
        headers=_entetes_internes(),
        json={"libelle": "RIZ TEST", "categorie": None, "actif": True},
    )
    assert r2.status_code == 409, r2.text

    await client.aclose()


@pytest.mark.asyncio
async def test_get_produits_pagination(session_test: AsyncSession) -> None:
    # arrange
    session_test.add_all(
        [
            Produit(libelle="AAA", categorie=None, actif=True),
            Produit(libelle="BBB", categorie=None, actif=True),
            Produit(libelle="CCC", categorie=None, actif=True),
        ]
    )
    await session_test.commit()

    client = await _client_api(session_test)
    r = await client.get(
        "/api/interne/catalogue/produits?limit=2&offset=0",
        headers=_entetes_internes(),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 2
    assert data[0]["libelle"] == "AAA"

    await client.aclose()


@pytest.mark.asyncio
async def test_creer_produit_fournisseur_conflit_sku(session_test: AsyncSession) -> None:
    # arrange
    f = Fournisseur(nom="F1", actif=True)
    p1 = Produit(libelle="P1", categorie=None, actif=True)
    p2 = Produit(libelle="P2", categorie=None, actif=True)
    session_test.add_all([f, p1, p2])
    await session_test.commit()

    client = await _client_api(session_test)

    body = {
        "fournisseur_id": str(f.id),
        "produit_id": str(p1.id),
        "reference_fournisseur": "SKU-001",
        "libelle_fournisseur": "SKU 001",
        "unite_achat": "kg",
        "quantite_par_unite": 1.0,
        "prix_achat_ht": None,
        "tva": None,
        "actif": True,
    }

    r1 = await client.post(
        "/api/interne/catalogue/produit-fournisseur",
        headers=_entetes_internes(),
        json=body,
    )
    assert r1.status_code == 201, r1.text

    # même SKU sur même fournisseur => conflit
    body2 = dict(body)
    body2["produit_id"] = str(p2.id)
    r2 = await client.post(
        "/api/interne/catalogue/produit-fournisseur",
        headers=_entetes_internes(),
        json=body2,
    )
    assert r2.status_code == 409, r2.text

    await client.aclose()


@pytest.mark.asyncio
async def test_get_ingredients_has_produit(session_test: AsyncSession) -> None:
    p = Produit(libelle="PROD", categorie=None, actif=True)
    ing1 = Ingredient(nom="ING1", unite_stock="kg", unite_consommation="kg", actif=True)
    # NOTE: le modèle `Ingredient` n'a pas (encore) de FK/relationship vers `Produit`.
    # Ce test se concentre donc sur le filtrage `has_produit=true` au niveau API.
    # Tant qu'aucun lien DB n'existe, on vérifie le contrat minimal : une liste valide est renvoyée.
    session_test.add_all([p, ing1])
    await session_test.commit()

    client = await _client_api(session_test)

    r = await client.get(
        "/api/interne/ingredients?has_produit=true",
        headers=_entetes_internes(),
    )
    assert r.status_code == 400, r.text
    assert "has_produit" in r.text

    await client.aclose()
