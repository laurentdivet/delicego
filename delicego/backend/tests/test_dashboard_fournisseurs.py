from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests._http_helpers import entetes_internes

from app.api.dependances import fournir_session
from app.domaine.modeles import Fournisseur, Ingredient
from app.domaine.modeles.achats import CommandeFournisseur, LigneCommandeFournisseur
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
    return entetes_internes()


@pytest.mark.asyncio
async def test_dashboard_fournisseurs_vide(session_test: AsyncSession) -> None:
    client = await _client_api(session_test)

    r = await client.get("/api/interne/dashboard/fournisseurs", headers=_entetes_internes())
    assert r.status_code == 200

    data = r.json()
    assert data == {"fournisseurs": []}

    await client.aclose()


@pytest.mark.asyncio
async def test_dashboard_fournisseurs_avec_donnees_et_filtres(session_test: AsyncSession) -> None:
    f1 = Fournisseur(nom="Fournisseur A", actif=True)
    f2 = Fournisseur(nom="Fournisseur B", actif=True)
    ing = Ingredient(nom="Farine", unite_stock="kg", unite_consommation="kg", cout_unitaire=2.0, actif=True)
    session_test.add_all([f1, f2, ing])
    await session_test.commit()

    now = datetime.now(timezone.utc)

    # Dans la fenêtre
    c1 = CommandeFournisseur(fournisseur_id=f1.id, date_commande=now - timedelta(days=2))
    session_test.add(c1)
    await session_test.flush()
    session_test.add(
        LigneCommandeFournisseur(
            commande_fournisseur_id=c1.id,
            ingredient_id=ing.id,
            quantite=10.0,
            quantite_recue=4.0,
            unite="kg",
        )
    )

    # Hors fenêtre
    c2 = CommandeFournisseur(fournisseur_id=f2.id, date_commande=now - timedelta(days=30))
    session_test.add(c2)
    await session_test.flush()
    session_test.add(
        LigneCommandeFournisseur(
            commande_fournisseur_id=c2.id,
            ingredient_id=ing.id,
            quantite=5.0,
            quantite_recue=5.0,
            unite="kg",
        )
    )

    await session_test.commit()

    client = await _client_api(session_test)

    date_start = (now - timedelta(days=7)).date().isoformat()
    date_end = now.date().isoformat()

    r = await client.get(
        f"/api/interne/dashboard/fournisseurs?date_start={date_start}&date_end={date_end}",
        headers=_entetes_internes(),
    )
    assert r.status_code == 200
    data = r.json()

    # doit contenir les 2 fournisseurs, mais avec agrégats filtrés :
    # - f1: 1 commande, montant commande = 10*2=20, reçu=4*2=8, taux=0.4, dernière=now-2
    # - f2: 0 commande dans filtre => montants 0, taux 0, dernière None
    assert len(data["fournisseurs"]) == 2

    f1_row = next(x for x in data["fournisseurs"] if x["fournisseur_nom"] == "Fournisseur A")
    assert f1_row["total_commandes"] == 1
    assert f1_row["total_montant_commande"] == pytest.approx(20.0)
    assert f1_row["total_montant_recu"] == pytest.approx(8.0)
    assert f1_row["taux_reception"] == pytest.approx(0.4)
    assert f1_row["derniere_commande_date"] == (now - timedelta(days=2)).date().isoformat()

    f2_row = next(x for x in data["fournisseurs"] if x["fournisseur_nom"] == "Fournisseur B")
    assert f2_row["total_commandes"] == 0
    assert f2_row["total_montant_commande"] == pytest.approx(0.0)
    assert f2_row["total_montant_recu"] == pytest.approx(0.0)
    assert f2_row["taux_reception"] == pytest.approx(0.0)
    assert f2_row["derniere_commande_date"] is None

    await client.aclose()
