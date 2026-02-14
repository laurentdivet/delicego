from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
import httpx
import pytest
from sqlalchemy import select
from tests._http_helpers import entetes_internes as _entetes_internes_global

from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMagasin, TypeMouvementStock
from app.domaine.modeles import Fournisseur, Ingredient, Magasin, Menu
from app.domaine.modeles.production import LigneConsommation, LignePlanProduction, LotProduction, PlanProduction
from app.domaine.modeles.referentiel import LigneRecette, Recette
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock
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
    # Ce module n'override pas ENV/INTERNAL_API_TOKEN.
    # On force donc le token attendu à la valeur dev-token (comportement dev du backend).
    os.environ["INTERNAL_API_TOKEN"] = os.getenv("INTERNAL_API_TOKEN", "dev-token")
    return _entetes_internes_global()


async def _setup_plan_production_minimal(
    session_test: AsyncSession,
    *,
    qte_planifiee: float,
    jour: date,
) -> tuple[Magasin, Recette, PlanProduction]:
    magasin = Magasin(nom="Cuisine API", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    session_test.add(magasin)
    await session_test.flush()

    recette = Recette(nom="Recette Cuisine API")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Menu Cuisine API", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.flush()

    plan = PlanProduction(magasin_id=magasin.id, date_plan=jour)
    session_test.add(plan)
    await session_test.flush()

    session_test.add(
        LignePlanProduction(
            plan_production_id=plan.id,
            recette_id=recette.id,
            quantite_a_produire=float(qte_planifiee),
        )
    )
    await session_test.commit()

    return magasin, recette, plan


async def _setup_stock_et_bom(
    session_test: AsyncSession,
    *,
    magasin: Magasin,
    recette: Recette,
) -> None:
    """Prépare une BOM + stock suffisant pour que `ServiceExecutionProduction` passe."""

    fournisseur = Fournisseur(nom="Fournisseur Cuisine API", actif=True)
    ingredient = Ingredient(nom="Ingredient Cuisine API", unite_stock="kg", unite_consommation="kg", actif=True)

    session_test.add_all([fournisseur, ingredient])
    await session_test.flush()

    # 0.2 kg par unité produite
    session_test.add(
        LigneRecette(
            recette_id=recette.id,
            ingredient_id=ingredient.id,
            quantite=0.2,
            unite="kg",
        )
    )
    await session_test.flush()

    lot_stock = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=fournisseur.id,
        code_lot="LOT-CUISINE-1",
        date_dlc=date.today() + timedelta(days=10),
        unite="kg",
    )
    session_test.add(lot_stock)
    await session_test.flush()

    session_test.add(
        MouvementStock(
            type_mouvement=TypeMouvementStock.RECEPTION,
            magasin_id=magasin.id,
            ingredient_id=ingredient.id,
            lot_id=lot_stock.id,
            quantite=10.0,
            unite="kg",
        )
    )

    await session_test.commit()


@pytest.mark.asyncio
async def test_api_lecture_ecran_cuisine(session_test: AsyncSession) -> None:
    client = await _client_api(session_test)

    jour = date(2025, 6, 3)
    magasin, recette, _plan = await _setup_plan_production_minimal(
        session_test,
        qte_planifiee=5.0,
        jour=jour,
    )

    reponse = await client.get(
        "/api/interne/production-preparation",
        headers=_entetes_internes(),
        params={"magasin_id": str(magasin.id), "date": str(jour)},
    )

    assert reponse.status_code == 200, reponse.text
    data = reponse.json()

    assert data["quantites_a_produire_aujourdhui"] == 5.0
    assert isinstance(data["quantites_par_creneau"], list)

    assert data["cuisine"][0]["recette_id"] == str(recette.id)
    assert data["cuisine"][0]["quantite_planifiee"] == 5.0
    assert data["cuisine"][0]["quantite_produite"] == 0.0
    assert data["cuisine"][0]["statut"] == "A_PRODUIRE"

    await client.aclose()


@pytest.mark.asyncio
async def test_api_bouton_produit_cree_un_lot(session_test: AsyncSession) -> None:
    client = await _client_api(session_test)

    jour = date(2025, 6, 3)
    magasin, recette, plan = await _setup_plan_production_minimal(
        session_test,
        qte_planifiee=5.0,
        jour=jour,
    )
    await _setup_stock_et_bom(session_test, magasin=magasin, recette=recette)

    reponse = await client.post(
        "/api/interne/production-preparation/produit",
        headers=_entetes_internes(),
        json={"magasin_id": str(magasin.id), "date": str(jour), "recette_id": str(recette.id)},
    )

    assert reponse.status_code == 200, reponse.text

    res = await session_test.execute(
        select(LotProduction).where(
            LotProduction.plan_production_id == plan.id,
            LotProduction.recette_id == recette.id,
        )
    )
    lots = list(res.scalars().all())
    assert len(lots) == 1
    assert float(lots[0].quantite_produite) == 5.0

    # La consommation doit avoir été déclenchée (au moins une ligne)
    res = await session_test.execute(
        select(LigneConsommation).where(LigneConsommation.lot_production_id == lots[0].id)
    )
    assert len(list(res.scalars().all())) > 0

    await client.aclose()


@pytest.mark.asyncio
async def test_api_bouton_ajuste_cree_un_lot_avec_quantite_diff(session_test: AsyncSession) -> None:
    client = await _client_api(session_test)

    jour = date(2025, 6, 3)
    magasin, recette, plan = await _setup_plan_production_minimal(
        session_test,
        qte_planifiee=5.0,
        jour=jour,
    )
    await _setup_stock_et_bom(session_test, magasin=magasin, recette=recette)

    reponse = await client.post(
        "/api/interne/production-preparation/ajuste",
        headers=_entetes_internes(),
        json={
            "magasin_id": str(magasin.id),
            "date": str(jour),
            "recette_id": str(recette.id),
            "quantite": 3.0,
        },
    )

    assert reponse.status_code == 200, reponse.text

    res = await session_test.execute(
        select(LotProduction).where(
            LotProduction.plan_production_id == plan.id,
            LotProduction.recette_id == recette.id,
        )
    )
    lots = list(res.scalars().all())
    assert len(lots) == 1
    assert float(lots[0].quantite_produite) == 3.0

    await client.aclose()


@pytest.mark.asyncio
async def test_api_bouton_non_produit_cree_trace_sans_consommation(session_test: AsyncSession) -> None:
    client = await _client_api(session_test)

    jour = date(2025, 6, 3)
    magasin, recette, plan = await _setup_plan_production_minimal(
        session_test,
        qte_planifiee=5.0,
        jour=jour,
    )
    await _setup_stock_et_bom(session_test, magasin=magasin, recette=recette)

    reponse = await client.post(
        "/api/interne/production-preparation/non-produit",
        headers=_entetes_internes(),
        json={"magasin_id": str(magasin.id), "date": str(jour), "recette_id": str(recette.id)},
    )

    assert reponse.status_code == 200, reponse.text

    res = await session_test.execute(
        select(LotProduction).where(
            LotProduction.plan_production_id == plan.id,
            LotProduction.recette_id == recette.id,
        )
    )
    lots = list(res.scalars().all())
    assert len(lots) == 1
    assert float(lots[0].quantite_produite) == 0.0

    # Aucune conso
    res = await session_test.execute(
        select(LigneConsommation).where(LigneConsommation.lot_production_id == lots[0].id)
    )
    assert len(list(res.scalars().all())) == 0

    res = await session_test.execute(
        select(MouvementStock).where(
            MouvementStock.reference_externe == str(lots[0].id),
            MouvementStock.type_mouvement == TypeMouvementStock.CONSOMMATION,
        )
    )
    assert len(list(res.scalars().all())) == 0

    await client.aclose()


@pytest.mark.asyncio
async def test_api_traceabilite_lisible_apres_service(session_test: AsyncSession) -> None:
    client = await _client_api(session_test)

    jour = date(2025, 6, 3)
    magasin, recette, plan = await _setup_plan_production_minimal(
        session_test,
        qte_planifiee=5.0,
        jour=jour,
    )
    await _setup_stock_et_bom(session_test, magasin=magasin, recette=recette)

    # 1) PRODUIT (quantité plan)
    reponse = await client.post(
        "/api/interne/production-preparation/produit",
        headers=_entetes_internes(),
        json={"magasin_id": str(magasin.id), "date": str(jour), "recette_id": str(recette.id)},
    )
    assert reponse.status_code == 200, reponse.text

    # 2) AJUSTE (quantité différente)
    reponse = await client.post(
        "/api/interne/production-preparation/ajuste",
        headers=_entetes_internes(),
        json={
            "magasin_id": str(magasin.id),
            "date": str(jour),
            "recette_id": str(recette.id),
            "quantite": 3.0,
        },
    )
    assert reponse.status_code == 200, reponse.text

    # 3) NON_PRODUIT
    reponse = await client.post(
        "/api/interne/production-preparation/non-produit",
        headers=_entetes_internes(),
        json={"magasin_id": str(magasin.id), "date": str(jour), "recette_id": str(recette.id)},
    )
    assert reponse.status_code == 200, reponse.text

    # Forcer un ordre déterministe pour la lecture (produit_le)
    res = await session_test.execute(
        select(LotProduction)
        .where(
            LotProduction.plan_production_id == plan.id,
            LotProduction.recette_id == recette.id,
        )
        .order_by(LotProduction.cree_le.asc())
    )
    lots = list(res.scalars().all())
    assert len(lots) == 3

    lots[0].produit_le = datetime(2025, 6, 3, 8, 0, tzinfo=timezone.utc)  # produit
    lots[1].produit_le = datetime(2025, 6, 3, 9, 0, tzinfo=timezone.utc)  # ajuste
    lots[2].produit_le = datetime(2025, 6, 3, 10, 0, tzinfo=timezone.utc)  # non_produit
    await session_test.commit()

    reponse = await client.get(
        "/api/interne/production-preparation/traceabilite",
        headers=_entetes_internes(),
        params={
            "magasin_id": str(magasin.id),
            "date": str(jour),
            "recette_id": str(recette.id),
        },
    )

    assert reponse.status_code == 200, reponse.text
    data = reponse.json()
    types = [e["type"] for e in data["evenements"]]

    assert "PRODUIT" in types
    assert "AJUSTE" in types
    assert "NON_PRODUIT" in types

    await client.aclose()
