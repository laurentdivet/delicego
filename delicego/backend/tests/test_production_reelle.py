from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import CanalVente, TypeMagasin
from app.domaine.modeles import Ingredient, LigneRecette, Magasin, Menu, Recette, Vente
from app.domaine.modeles.production import LignePlanProduction, PlanProduction
from app.domaine.services.production_reelle import ServiceProductionReelle


async def _creer_magasin_menu_recette_et_bom(
    session_test: AsyncSession,
    *,
    nom_magasin: str,
    nom_menu: str,
    nom_recette: str,
    ingredient: Ingredient,
    quantite_par_unite: float,
    unite: str,
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

    session_test.add(
        LigneRecette(
            recette_id=recette.id,
            ingredient_id=ingredient.id,
            quantite=float(quantite_par_unite),
            unite=unite,
        )
    )
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
            canal=CanalVente.INTERNE,
            quantite=float(qte),
        )
        session_test.add(vente)

    await session_test.commit()


@pytest.mark.asyncio
async def test_jour_sans_ventes_plan_vide(session_test: AsyncSession) -> None:
    ingredient = Ingredient(nom="Tomate", unite_stock="kg", unite_mesure="kg", actif=True)
    session_test.add(ingredient)
    await session_test.commit()

    # Magasin/menu/recette existent, mais aucune vente
    magasin, menu, recette = await _creer_magasin_menu_recette_et_bom(
        session_test,
        nom_magasin="Magasin A",
        nom_menu="Menu Salade",
        nom_recette="Salade",
        ingredient=ingredient,
        quantite_par_unite=0.2,
        unite="kg",
    )

    service = ServiceProductionReelle(session_test)
    # Fenêtre 3 jours : historique = 1,2,3 janv.
    plan = await service.generer_plan_production(
        magasin_id=magasin.id,
        date_plan=date(2025, 1, 4),
        fenetre_jours=3,
        donnees_meteo={},
        evenements=[],
    )

    assert isinstance(plan, PlanProduction)

    res = await session_test.execute(
        select(LignePlanProduction).where(LignePlanProduction.plan_production_id == plan.id)
    )
    lignes = list(res.scalars().all())

    # Pas de ventes => pas de lignes
    assert lignes == []


@pytest.mark.asyncio
async def test_jour_avec_ventes_plan_non_vide(session_test: AsyncSession) -> None:
    ingredient = Ingredient(nom="Tomate", unite_stock="kg", unite_mesure="kg", actif=True)
    session_test.add(ingredient)
    await session_test.commit()

    magasin, menu, recette = await _creer_magasin_menu_recette_et_bom(
        session_test,
        nom_magasin="Magasin B",
        nom_menu="Menu Salade",
        nom_recette="Salade",
        ingredient=ingredient,
        quantite_par_unite=0.2,
        unite="kg",
    )

    # 3 jours de ventes : 10/j => moyenne 10
    d1 = date(2025, 1, 1)
    d2 = date(2025, 1, 2)
    d3 = date(2025, 1, 3)
    await _creer_ventes(
        session_test,
        magasin_id=magasin.id,
        menu_id=menu.id,
        quantites_par_jour={d1: 10.0, d2: 10.0, d3: 10.0},
    )

    service = ServiceProductionReelle(session_test)
    # Fenêtre 3 jours : historique = 1,2,3 janv.
    plan = await service.generer_plan_production(
        magasin_id=magasin.id,
        date_plan=date(2025, 1, 4),
        fenetre_jours=3,
        donnees_meteo={},
        evenements=[],
    )

    res = await session_test.execute(
        select(LignePlanProduction).where(LignePlanProduction.plan_production_id == plan.id)
    )
    lignes = list(res.scalars().all())

    assert len(lignes) == 1
    assert lignes[0].recette_id == recette.id


@pytest.mark.asyncio
async def test_coherence_besoins_ingredients(session_test: AsyncSession) -> None:
    # 2 ingrédients
    tomate = Ingredient(nom="Tomate", unite_stock="kg", unite_mesure="kg", actif=True)
    sauce = Ingredient(nom="Sauce", unite_stock="kg", unite_mesure="kg", actif=True)
    session_test.add_all([tomate, sauce])
    await session_test.commit()

    magasin = Magasin(nom="Magasin C", type_magasin=TypeMagasin.VENTE, actif=True)
    session_test.add(magasin)
    await session_test.commit()

    recette = Recette(nom="Recette Mix")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Menu Mix", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    # BOM : 0.2 kg tomate + 0.1 kg sauce
    session_test.add_all(
        [
            LigneRecette(recette_id=recette.id, ingredient_id=tomate.id, quantite=0.2, unite="kg"),
            LigneRecette(recette_id=recette.id, ingredient_id=sauce.id, quantite=0.1, unite="kg"),
        ]
    )
    await session_test.commit()

    # ventes historiques : 10 / jour sur 3 jours => moyenne 10
    d1 = date(2025, 1, 1)
    d2 = date(2025, 1, 2)
    d3 = date(2025, 1, 3)
    await _creer_ventes(
        session_test,
        magasin_id=magasin.id,
        menu_id=menu.id,
        quantites_par_jour={d1: 10.0, d2: 10.0, d3: 10.0},
    )

    service = ServiceProductionReelle(session_test)

    # Fenêtre 3 jours : historique = 1,2,3 janv. => moyenne = 10
    plan = await service.generer_plan_production(
        magasin_id=magasin.id,
        date_plan=date(2025, 1, 4),
        fenetre_jours=3,
        donnees_meteo={},
        evenements=[],
    )

    besoins = await service.calculer_besoins_ingredients(plan_id=plan.id)
    besoins_par_nom = {b.ingredient_nom: b for b in besoins}

    # quantité planifiée ~ 10 => besoins: tomate 2.0 kg, sauce 1.0 kg
    assert besoins_par_nom["Tomate"].quantite == pytest.approx(2.0)
    assert besoins_par_nom["Sauce"].quantite == pytest.approx(1.0)
