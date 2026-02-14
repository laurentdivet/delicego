from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session
from app.domaine.enums.types import TypeMagasin, TypeMouvementStock
from app.domaine.modeles import Ingredient, Magasin
from app.domaine.modeles.production import LotProduction
from app.domaine.modeles.referentiel import Menu, Recette
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock
from app.main import creer_application


def _app_avec_dependances_test(session_test: AsyncSession):
    app = creer_application()

    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

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
    return {"X-CLE-INTERNE": "cle-technique"}


@pytest.mark.asyncio
async def test_dashboard_journee_sans_production_valeurs_a_zero(session_test: AsyncSession) -> None:
    client = await _client_api(session_test)

    r = await client.get("/api/interne/dashboard/production-stock?date_cible=2025-01-01", headers=_entetes_internes())
    assert r.status_code == 200
    data = r.json()

    assert data["date_cible"] == "2025-01-01"
    assert data["production"]["nombre_lots"] == 0
    assert data["production"]["quantites_par_recette"] == []
    assert data["consommation"] == []
    assert data["stock"] == []
    assert data["alertes"]["stocks_bas"] == []
    assert data["alertes"]["dlc"] == []

    await client.aclose()


@pytest.mark.asyncio
async def test_dashboard_production_consommation_stock_alertes(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    ing = Ingredient(nom="Farine", unite_stock="kg", unite_consommation="kg", cout_unitaire=1.0, actif=True)
    session_test.add_all([magasin, ing])
    await session_test.commit()

    recette = Recette(nom="Pain")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Menu", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    date_cible = datetime(2025, 1, 1, tzinfo=timezone.utc)

    # Production du jour : 2 lots, quantités par recette = 5 + 3
    lp1 = LotProduction(magasin_id=magasin.id, plan_production_id=None, recette_id=recette.id, produit_le=date_cible.replace(hour=10), quantite_produite=5.0, unite="piece")
    lp2 = LotProduction(magasin_id=magasin.id, plan_production_id=None, recette_id=recette.id, produit_le=date_cible.replace(hour=12), quantite_produite=3.0, unite="piece")
    session_test.add_all([lp1, lp2])

    # Stock : réception 10, consommation 4 => stock 6
    lot = Lot(magasin_id=magasin.id, ingredient_id=ing.id, fournisseur_id=None, code_lot="L1", date_dlc=date(2025, 1, 1), unite="kg")
    session_test.add(lot)
    await session_test.flush()

    ms_recep = MouvementStock(
        type_mouvement=TypeMouvementStock.RECEPTION,
        magasin_id=magasin.id,
        ingredient_id=ing.id,
        lot_id=lot.id,
        quantite=10.0,
        unite="kg",
        reference_externe="REF",
        commentaire=None,
        horodatage=date_cible.replace(hour=8),
    )
    ms_conso = MouvementStock(
        type_mouvement=TypeMouvementStock.CONSOMMATION,
        magasin_id=magasin.id,
        ingredient_id=ing.id,
        lot_id=lot.id,
        quantite=4.0,
        unite="kg",
        reference_externe="REF",
        commentaire=None,
        horodatage=date_cible.replace(hour=11),
    )
    session_test.add_all([ms_recep, ms_conso])

    await session_test.commit()

    client = await _client_api(session_test)
    r = await client.get("/api/interne/dashboard/production-stock?date_cible=2025-01-01", headers=_entetes_internes())
    assert r.status_code == 200
    data = r.json()

    assert data["production"]["nombre_lots"] == 2
    assert len(data["production"]["quantites_par_recette"]) == 1
    assert data["production"]["quantites_par_recette"][0]["recette_nom"] == "Pain"
    assert data["production"]["quantites_par_recette"][0]["quantite_produite"] == pytest.approx(8.0)

    # consommation du jour : 4
    assert len(data["consommation"]) == 1
    assert data["consommation"][0]["ingredient_nom"] == "Farine"
    assert data["consommation"][0]["quantite_consommee"] == pytest.approx(4.0)

    # stock : 10 - 4 = 6
    assert len(data["stock"]) == 1
    assert data["stock"][0]["ingredient_nom"] == "Farine"
    assert data["stock"][0]["stock_total"] == pytest.approx(6.0)

    # alertes : DLC <= date_cible => déclenchée, stock bas (<=2) => non
    assert data["alertes"]["dlc"]
    assert data["alertes"]["dlc"][0]["ingredient_nom"] == "Farine"
    assert data["alertes"]["stocks_bas"] == []

    await client.aclose()


@pytest.mark.asyncio
async def test_alerte_stock_bas_declenchee(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat2", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    ing = Ingredient(nom="Sel", unite_stock="kg", unite_consommation="kg", cout_unitaire=1.0, actif=True)
    session_test.add_all([magasin, ing])
    await session_test.commit()

    date_cible = datetime(2025, 1, 1, tzinfo=timezone.utc)
    lot = Lot(magasin_id=magasin.id, ingredient_id=ing.id, fournisseur_id=None, code_lot="S1", date_dlc=None, unite="kg")
    session_test.add(lot)
    await session_test.flush()

    # stock = 2 => alerte (<= seuil)
    ms_recep = MouvementStock(
        type_mouvement=TypeMouvementStock.RECEPTION,
        magasin_id=magasin.id,
        ingredient_id=ing.id,
        lot_id=lot.id,
        quantite=2.0,
        unite="kg",
        reference_externe="REF",
        commentaire=None,
        horodatage=date_cible.replace(hour=8),
    )
    session_test.add(ms_recep)
    await session_test.commit()

    client = await _client_api(session_test)
    r = await client.get("/api/interne/dashboard/production-stock?date_cible=2025-01-01", headers=_entetes_internes())
    assert r.status_code == 200
    data = r.json()

    assert len(data["alertes"]["stocks_bas"]) == 1
    assert data["alertes"]["stocks_bas"][0]["ingredient_nom"] == "Sel"

    await client.aclose()
