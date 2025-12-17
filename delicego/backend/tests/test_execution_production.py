from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMagasin, TypeMouvementStock
from app.domaine.modeles import Fournisseur, Ingredient, Magasin, Menu
from app.domaine.modeles.production import LigneConsommation, LotProduction
from app.domaine.modeles.referentiel import LigneRecette, Recette
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock
from app.domaine.services.executer_production import (
    ErreurProduction,
    ServiceExecutionProduction,
)


@pytest.mark.asyncio
async def test_execution_production_genere_mouvements_et_consommations(
    session_test: AsyncSession,
) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    fournisseur = Fournisseur(nom="Fresh", actif=True)
    ingredient = Ingredient(nom="Tomate", unite_stock="kg", unite_mesure="kg", actif=True)

    session_test.add_all([magasin, fournisseur, ingredient])
    await session_test.commit()

    # Menu + Recette + BOM
    recette = Recette(nom="Recette Salade")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Salade", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    # 0.2 kg de tomate par unité produite
    session_test.add(
        LigneRecette(
            recette_id=recette.id,
            ingredient_id=ingredient.id,
            quantite=0.2,
            unite="kg",
        )
    )
    await session_test.commit()

    # Lots FEFO
    aujourd_hui = date.today()
    lot_proche = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=fournisseur.id,
        code_lot="L1",
        date_dlc=aujourd_hui + timedelta(days=1),
        unite="kg",
    )
    lot_lointain = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=fournisseur.id,
        code_lot="L2",
        date_dlc=aujourd_hui + timedelta(days=10),
        unite="kg",
    )
    session_test.add_all([lot_proche, lot_lointain])
    await session_test.commit()

    session_test.add_all(
        [
            MouvementStock(
                type_mouvement=TypeMouvementStock.RECEPTION,
                magasin_id=magasin.id,
                ingredient_id=ingredient.id,
                lot_id=lot_proche.id,
                quantite=0.3,
                unite="kg",
            ),
            MouvementStock(
                type_mouvement=TypeMouvementStock.RECEPTION,
                magasin_id=magasin.id,
                ingredient_id=ingredient.id,
                lot_id=lot_lointain.id,
                quantite=2.0,
                unite="kg",
            ),
        ]
    )
    await session_test.commit()

    # Production : 5 unités → besoin = 1.0 kg
    lot_production = LotProduction(
        magasin_id=magasin.id,
        plan_production_id=None,
        recette_id=recette.id,
        quantite_produite=5.0,
        unite="unite",
    )
    session_test.add(lot_production)
    await session_test.commit()

    lot_production_id = lot_production.id  # 🔒 capturé AVANT toute exécution

    service = ServiceExecutionProduction(session_test)
    resultat = await service.executer(lot_production_id=lot_production_id)

    assert resultat.nb_mouvements_stock == 2
    assert resultat.nb_lignes_consommation == 2

    # Mouvements de consommation
    res = await session_test.execute(
        select(MouvementStock).where(
            MouvementStock.reference_externe == str(lot_production_id),
            MouvementStock.type_mouvement == TypeMouvementStock.CONSOMMATION,
        )
    )
    mouvements = list(res.scalars().all())
    assert len(mouvements) == 2

    # FEFO : lot proche d’abord
    mouvements_tries = sorted(mouvements, key=lambda m: (m.lot_id != lot_proche.id, m.id))
    assert mouvements_tries[0].lot_id == lot_proche.id
    assert abs(mouvements_tries[0].quantite - 0.3) < 1e-9

    # Total consommé
    total = sum(float(m.quantite) for m in mouvements)
    assert abs(total - 1.0) < 1e-9

    # Lignes de consommation
    res = await session_test.execute(
        select(LigneConsommation).where(
            LigneConsommation.lot_production_id == lot_production_id
        )
    )
    lignes = list(res.scalars().all())
    assert len(lignes) == 2
    assert all(l.mouvement_stock_id is not None for l in lignes)


@pytest.mark.asyncio
async def test_execution_production_rollback_si_stock_insuffisant(
    session_test: AsyncSession,
) -> None:
    magasin = Magasin(nom="Magasin Z", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    ingredient = Ingredient(nom="Farine", unite_stock="kg", unite_mesure="kg", actif=True)

    session_test.add_all([magasin, ingredient])
    await session_test.commit()

    recette = Recette(nom="Recette Pizza")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Pizza", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    # 10 kg par unité (volontairement énorme)
    session_test.add(
        LigneRecette(
            recette_id=recette.id,
            ingredient_id=ingredient.id,
            quantite=10.0,
            unite="kg",
        )
    )
    await session_test.commit()

    lot = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=None,
        code_lot="F1",
        date_dlc=None,
        unite="kg",
    )
    session_test.add(lot)
    await session_test.commit()

    # Seulement 1 kg en stock
    session_test.add(
        MouvementStock(
            type_mouvement=TypeMouvementStock.RECEPTION,
            magasin_id=magasin.id,
            ingredient_id=ingredient.id,
            lot_id=lot.id,
            quantite=1.0,
            unite="kg",
        )
    )
    await session_test.commit()

    lot_production = LotProduction(
        magasin_id=magasin.id,
        plan_production_id=None,
        recette_id=recette.id,
        quantite_produite=1.0,
        unite="unite",
    )
    session_test.add(lot_production)
    await session_test.commit()

    lot_production_id = lot_production.id  # 🔒 capturé AVANT rollback

    service = ServiceExecutionProduction(session_test)

    with pytest.raises(ErreurProduction):
        await service.executer(lot_production_id=lot_production_id)

    # Vérifier qu’aucun effet de bord n’existe
    res_m = await session_test.execute(
        select(MouvementStock).where(
            MouvementStock.reference_externe == str(lot_production_id),
            MouvementStock.type_mouvement == TypeMouvementStock.CONSOMMATION,
        )
    )
    assert res_m.scalars().first() is None

    res_l = await session_test.execute(
        select(LigneConsommation).where(
            LigneConsommation.lot_production_id == lot_production_id
        )
    )
    assert res_l.scalars().first() is None
