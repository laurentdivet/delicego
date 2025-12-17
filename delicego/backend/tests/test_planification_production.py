from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import CanalVente, TypeMagasin
from app.domaine.modeles import Magasin, Menu, Recette, Vente
from app.domaine.modeles.production import LignePlanProduction, PlanProduction
from app.domaine.services.planifier_production import (
    PlanProductionDejaExistant,
    ServicePlanificationProduction,
)


async def _creer_magasin_menu_recette(
    session_test: AsyncSession,
    *,
    nom_magasin: str,
    nom_menu: str,
    nom_recette: str,
) -> tuple[Magasin, Menu, Recette]:
    magasin = Magasin(nom=nom_magasin, type_magasin=TypeMagasin.VENTE, actif=True)
    session_test.add(magasin)
    await session_test.commit()

    recette = Recette(nom=nom_recette)
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom=nom_menu, actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    return magasin, menu, recette


async def _creer_ventes(
    session_test: AsyncSession,
    *,
    magasin_id,
    menu_id,
    quantites_par_jour: dict[date, float],
) -> None:
    for jour, qte in quantites_par_jour.items():
        vente = Vente(
            magasin_id=magasin_id,
            menu_id=menu_id,
            date_vente=datetime(jour.year, jour.month, jour.day, 12, 0, 0, tzinfo=timezone.utc),
            canal=CanalVente.COMPTOIR,
            quantite=float(qte),
        )
        session_test.add(vente)

    await session_test.commit()


@pytest.mark.asyncio
async def test_plan_sans_meteo_ni_evenement_moyenne_simple(session_test: AsyncSession) -> None:
    magasin, menu, recette = await _creer_magasin_menu_recette(
        session_test,
        nom_magasin="Magasin A",
        nom_menu="Menu Salade",
        nom_recette="Salade fraiche",
    )

    # Historique sur 3 jours : total 30 -> moyenne = 10/j
    d1 = date(2025, 1, 1)
    d2 = date(2025, 1, 2)
    d3 = date(2025, 1, 3)
    await _creer_ventes(
        session_test,
        magasin_id=magasin.id,
        menu_id=menu.id,
        quantites_par_jour={d1: 10.0, d2: 10.0, d3: 10.0},
    )

    service = ServicePlanificationProduction(session_test)
    plan = await service.planifier(
        magasin_id=magasin.id,
        date_plan=date(2025, 1, 4),
        date_debut_historique=d1,
        date_fin_historique=d3,
        donnees_meteo={},
        evenements=[],
    )

    assert isinstance(plan, PlanProduction)

    res = await session_test.execute(
        select(LignePlanProduction).where(LignePlanProduction.plan_production_id == plan.id)
    )
    lignes = list(res.scalars().all())

    assert len(lignes) == 1
    assert lignes[0].recette_id == recette.id
    assert lignes[0].quantite_a_produire == 10.0


@pytest.mark.asyncio
async def test_plan_avec_meteo_chaude_augmente_recettes_froides(session_test: AsyncSession) -> None:
    magasin, menu, recette = await _creer_magasin_menu_recette(
        session_test,
        nom_magasin="Magasin B",
        nom_menu="Menu Salade",
        nom_recette="Salade du midi",
    )

    d1 = date(2025, 2, 1)
    d2 = date(2025, 2, 2)
    d3 = date(2025, 2, 3)

    # moyenne = 10
    await _creer_ventes(
        session_test,
        magasin_id=magasin.id,
        menu_id=menu.id,
        quantites_par_jour={d1: 10.0, d2: 10.0, d3: 10.0},
    )

    service = ServicePlanificationProduction(session_test)
    plan = await service.planifier(
        magasin_id=magasin.id,
        date_plan=date(2025, 2, 4),
        date_debut_historique=d1,
        date_fin_historique=d3,
        donnees_meteo={
            "temperature_max": 28.0,
            "temperature_min": 18.0,
            "precipitations_mm": 0.0,
        },
        evenements=[],
    )

    res = await session_test.execute(
        select(LignePlanProduction).where(LignePlanProduction.plan_production_id == plan.id)
    )
    lignes = list(res.scalars().all())

    assert len(lignes) == 1
    # 10 * 1.15 = 11.5 -> arrondi à l’unité : 12
    assert lignes[0].quantite_a_produire == 12.0


@pytest.mark.asyncio
async def test_plan_avec_evenement_sportif_augmente_snacking(session_test: AsyncSession) -> None:
    magasin, menu, recette = await _creer_magasin_menu_recette(
        session_test,
        nom_magasin="Magasin C",
        nom_menu="Menu Pizza",
        nom_recette="Pizza partage",
    )

    d1 = date(2025, 3, 1)
    d2 = date(2025, 3, 2)

    # total 10 sur 2 jours => moyenne = 5
    await _creer_ventes(
        session_test,
        magasin_id=magasin.id,
        menu_id=menu.id,
        quantites_par_jour={d1: 5.0, d2: 5.0},
    )

    service = ServicePlanificationProduction(session_test)
    plan = await service.planifier(
        magasin_id=magasin.id,
        date_plan=date(2025, 3, 3),
        date_debut_historique=d1,
        date_fin_historique=d2,
        donnees_meteo={},
        evenements=["LIGUE_DES_CHAMPIONS"],
    )

    res = await session_test.execute(
        select(LignePlanProduction).where(LignePlanProduction.plan_production_id == plan.id)
    )
    lignes = list(res.scalars().all())

    assert len(lignes) == 1
    # 5 * 1.20 = 6.0 -> arrondi : 6
    assert lignes[0].quantite_a_produire == 6.0


@pytest.mark.asyncio
async def test_plan_existant_declenche_exception(session_test: AsyncSession) -> None:
    magasin, menu, recette = await _creer_magasin_menu_recette(
        session_test,
        nom_magasin="Magasin D",
        nom_menu="Menu Salade",
        nom_recette="Salade",
    )

    # Créer un plan existant
    plan_existant = PlanProduction(
        magasin_id=magasin.id,
        date_plan=date(2025, 4, 1),
    )
    session_test.add(plan_existant)
    await session_test.commit()

    # Même sans ventes, on doit échouer car le plan existe déjà
    service = ServicePlanificationProduction(session_test)

    with pytest.raises(PlanProductionDejaExistant):
        await service.planifier(
            magasin_id=magasin.id,
            date_plan=date(2025, 4, 1),
            date_debut_historique=date(2025, 3, 1),
            date_fin_historique=date(2025, 3, 2),
            donnees_meteo={},
            evenements=[],
        )
