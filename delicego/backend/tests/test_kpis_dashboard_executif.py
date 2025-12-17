from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMagasin, TypeMouvementStock
from app.domaine.modeles import Fournisseur, Ingredient, Magasin, Menu, Recette
from app.domaine.modeles.commande_client import CommandeClient, LigneCommandeClient
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock
from app.domaine.modeles.ventes_prevision import ExecutionPrevision, LignePrevision
from app.main import creer_application


def _client_interne() -> TestClient:
    return TestClient(creer_application())


def _entetes_internes() -> dict[str, str]:
    return {"X-CLE-INTERNE": "cle-technique"}


@pytest.mark.asyncio
async def test_kpis_dashboard_executif_retourne_kpis_et_statuts(session_test: AsyncSession) -> None:
    client = _client_interne()

    magasin = Magasin(nom="M1", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    fournisseur = Fournisseur(nom="F1", actif=True)
    ingredient = Ingredient(nom="Ing1", unite_stock="kg", unite_mesure="kg", actif=True)
    session_test.add_all([magasin, fournisseur, ingredient])
    await session_test.commit()

    # Stock + consommation pour food cost
    lot = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=fournisseur.id,
        code_lot="L1",
        date_dlc=date(2025, 1, 2),
        unite="kg",
    )
    session_test.add(lot)
    await session_test.commit()

    session_test.add(
        MouvementStock(
            type_mouvement=TypeMouvementStock.CONSOMMATION,
            magasin_id=magasin.id,
            ingredient_id=ingredient.id,
            lot_id=lot.id,
            quantite=2.0,
            unite="kg",
            horodatage=datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
        )
    )
    await session_test.commit()

    recette = Recette(nom="Recette Menu1")
    session_test.add(recette)
    await session_test.flush()

    # Menu + commande => CA
    menu = Menu(
        nom="Menu1",
        actif=True,
        magasin_id=magasin.id,
        recette_id=recette.id,
        prix=10.0,
        commandable=True,
    )
    session_test.add(menu)
    await session_test.commit()

    commande = CommandeClient(
        magasin_id=magasin.id,
        date_commande=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    session_test.add(commande)
    await session_test.commit()

    session_test.add(
        LigneCommandeClient(
            commande_client_id=commande.id,
            menu_id=menu.id,
            quantite=3.0,
            lot_production_id=None,
        )
    )
    await session_test.commit()

    # Prévision => écart vs prévision
    exec_prev = ExecutionPrevision(magasin_id=magasin.id)
    session_test.add(exec_prev)
    await session_test.commit()

    session_test.add(
        LignePrevision(
            execution_prevision_id=exec_prev.id,
            date_prevue=date(2025, 1, 1),
            menu_id=menu.id,
            quantite_prevue=2.0,
        )
    )
    await session_test.commit()

    r = client.get(
        "/api/interne/kpis/dashboard-executif",
        headers=_entetes_internes(),
        params={"date_cible": "2025-01-01", "magasin_id": str(magasin.id)},
    )
    assert r.status_code == 200
    data = r.json()

    assert data["magasin_id"] == str(magasin.id)
    assert data["kpis"]["ca_jour"]["valeur"] == 30.0
    assert data["kpis"]["ecart_vs_prevision_pct"] is not None

    # statuts présents
    assert "ecart_vs_prevision_pct" in data["statuts"]
    assert "food_cost_reel_pct" in data["statuts"]
    assert "marge_brute_pct" in data["statuts"]

    # alertes visibles
    assert isinstance(data["alertes"], list)
