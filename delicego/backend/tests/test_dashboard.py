from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMagasin, TypeMouvementStock
from app.domaine.modeles import Fournisseur, Ingredient, Magasin, Menu
from app.domaine.modeles.commande_client import CommandeClient, LigneCommandeClient
from app.domaine.modeles.production import LotProduction, PlanProduction
from app.domaine.modeles.referentiel import LigneRecette, Recette
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock
from app.main import creer_application


def _client_interne() -> TestClient:
    return TestClient(creer_application())


def _entetes_internes() -> dict[str, str]:
    return {"X-CLE-INTERNE": "cle-technique"}


@pytest.mark.asyncio
async def test_dashboard_vide_retours_coherents(session_test: AsyncSession) -> None:
    client = _client_interne()

    # Vue globale
    r = client.get(
        "/api/interne/dashboard/vue-globale",
        headers=_entetes_internes(),
        params={"date_cible": "2025-01-01"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["commandes_du_jour"] == 0
    assert data["productions_du_jour"] == 0
    assert data["quantite_produite"] == 0.0
    assert data["alertes"]["stocks_bas"] == 0

    # Plans
    r = client.get("/api/interne/dashboard/plans-production", headers=_entetes_internes())
    assert r.status_code == 200
    assert r.json() == []

    # Commandes
    r = client.get("/api/interne/dashboard/commandes-clients", headers=_entetes_internes())
    assert r.status_code == 200
    assert r.json() == []

    # Alertes
    r = client.get(
        "/api/interne/dashboard/alertes",
        headers=_entetes_internes(),
        params={"date_cible": "2025-01-01"},
    )
    assert r.status_code == 200
    assert r.json()["stocks_bas"] == []
    assert r.json()["lots_proches_dlc"] == []


@pytest.mark.asyncio
async def test_dashboard_avec_donnees_agrege_correctement(session_test: AsyncSession) -> None:
    client = _client_interne()

    # --- Données : magasin + ingrédients + stock ---
    magasin = Magasin(nom="Magasin Dash", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    fournisseur = Fournisseur(nom="Fresh Dash", actif=True)

    ingredient_tomate = Ingredient(nom="Tomate Dash", unite_stock="kg", unite_consommation="kg", actif=True)
    ingredient_salade = Ingredient(nom="Salade Dash", unite_stock="kg", unite_consommation="kg", actif=True)

    session_test.add_all([magasin, fournisseur, ingredient_tomate, ingredient_salade])
    await session_test.commit()

    # Lots : un proche DLC (salade), un stock bas (tomate)
    lot_salade = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient_salade.id,
        fournisseur_id=fournisseur.id,
        code_lot="S1",
        date_dlc=date(2025, 1, 2),
        unite="kg",
    )
    lot_tomate = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient_tomate.id,
        fournisseur_id=fournisseur.id,
        code_lot="T1",
        date_dlc=None,
        unite="kg",
    )
    session_test.add_all([lot_salade, lot_tomate])
    await session_test.commit()

    # Réception : salade 5kg, tomate 1kg (stock bas < 2)
    session_test.add_all(
        [
            MouvementStock(
                type_mouvement=TypeMouvementStock.RECEPTION,
                magasin_id=magasin.id,
                ingredient_id=ingredient_salade.id,
                lot_id=lot_salade.id,
                quantite=5.0,
                unite="kg",
            ),
            MouvementStock(
                type_mouvement=TypeMouvementStock.RECEPTION,
                magasin_id=magasin.id,
                ingredient_id=ingredient_tomate.id,
                lot_id=lot_tomate.id,
                quantite=1.0,
                unite="kg",
            ),
        ]
    )
    await session_test.commit()

    # --- Plan de production avec une ligne ---
    plan = PlanProduction(magasin_id=magasin.id, date_plan=date(2025, 1, 1))
    session_test.add(plan)
    await session_test.commit()

    # --- Commande client du jour ---
    commande = CommandeClient(
        magasin_id=magasin.id,
        date_commande=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    session_test.add(commande)
    await session_test.commit()

    recette = Recette(nom="Recette Dash")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Menu Dash", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    session_test.add(
        LigneRecette(
            recette_id=recette.id,
            ingredient_id=ingredient_salade.id,
            quantite=1.0,
            unite="kg",
        )
    )
    await session_test.commit()

    lot_prod = LotProduction(
        magasin_id=magasin.id,
        plan_production_id=None,
        recette_id=recette.id,
        quantite_produite=1.0,
        unite="unite",
        produit_le=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    session_test.add(lot_prod)
    await session_test.commit()

    session_test.add(
        LigneCommandeClient(
            commande_client_id=commande.id,
            menu_id=menu.id,
            quantite=2.0,
            lot_production_id=lot_prod.id,
        )
    )
    await session_test.commit()

    # Consommation (mouvement) sur salade : 1kg
    session_test.add(
        MouvementStock(
            type_mouvement=TypeMouvementStock.CONSOMMATION,
            magasin_id=magasin.id,
            ingredient_id=ingredient_salade.id,
            lot_id=lot_salade.id,
            quantite=1.0,
            unite="kg",
            reference_externe=str(lot_prod.id),
        )
    )
    await session_test.commit()

    # --- Appels dashboard ---

    r = client.get(
        "/api/interne/dashboard/vue-globale",
        headers=_entetes_internes(),
        params={"date_cible": "2025-01-01"},
    )
    assert r.status_code == 200
    vue = r.json()
    assert vue["commandes_du_jour"] == 1
    assert vue["productions_du_jour"] == 1
    assert vue["quantite_produite"] == 1.0

    # Plans
    r = client.get("/api/interne/dashboard/plans-production", headers=_entetes_internes())
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Commandes
    r = client.get(
        "/api/interne/dashboard/commandes-clients",
        headers=_entetes_internes(),
        params={"date_cible": "2025-01-01"},
    )
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["nombre_lignes"] == 1
    assert r.json()[0]["quantite_totale"] == 2.0

    # Consommation
    r = client.get(
        "/api/interne/dashboard/consommation",
        headers=_entetes_internes(),
        params={"date_debut": "2025-01-01", "date_fin": "2025-01-01"},
    )
    assert r.status_code == 200
    conso = r.json()
    # On a 2 ingrédients en référentiel
    assert len(conso) == 2

    # Alertes
    r = client.get(
        "/api/interne/dashboard/alertes",
        headers=_entetes_internes(),
        params={"date_cible": "2025-01-01"},
    )
    assert r.status_code == 200
    alertes = r.json()

    # Tomate stock bas (<2)
    assert any(a["ingredient"] == "Tomate Dash" for a in alertes["stocks_bas"])
    # Salade DLC proche (2025-01-02 avec date_cible=2025-01-01, délai 2)
    assert any(a["ingredient"] == "Salade Dash" for a in alertes["lots_proches_dlc"])
