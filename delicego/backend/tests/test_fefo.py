from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMagasin, TypeMouvementStock
from app.domaine.modeles import Fournisseur, Ingredient, Magasin
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock
from app.domaine.services.allocateur_fefo import (
    AllocateurFEFO,
    DemandeConsommationIngredient,
    StockInsuffisant,
)


@pytest.mark.asyncio
async def test_allocation_fefo_ordre_et_repartition(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    ingredient = Ingredient(nom="Salade", unite_stock="kg", unite_mesure="kg", actif=True)
    fournisseur = Fournisseur(nom="Fresh", actif=True)

    session_test.add_all([magasin, ingredient, fournisseur])
    await session_test.commit()

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

    # Réceptions : lot proche = 3kg, lot lointain = 10kg
    session_test.add_all(
        [
            MouvementStock(
                type_mouvement=TypeMouvementStock.RECEPTION,
                magasin_id=magasin.id,
                ingredient_id=ingredient.id,
                lot_id=lot_proche.id,
                quantite=3.0,
                unite="kg",
            ),
            MouvementStock(
                type_mouvement=TypeMouvementStock.RECEPTION,
                magasin_id=magasin.id,
                ingredient_id=ingredient.id,
                lot_id=lot_lointain.id,
                quantite=10.0,
                unite="kg",
            ),
        ]
    )
    await session_test.commit()

    allocateur = AllocateurFEFO(session_test)
    demande = DemandeConsommationIngredient(ingredient_id=ingredient.id, quantite=5.0, unite="kg")

    allocations = await allocateur.allouer(magasin_id=magasin.id, demande=demande)

    # FEFO : on consomme d’abord le lot le plus proche (3), puis lointain (2)
    assert len(allocations) == 2
    assert allocations[0].lot_id == lot_proche.id
    assert allocations[0].quantite_allouee == 3.0
    assert allocations[1].lot_id == lot_lointain.id
    assert allocations[1].quantite_allouee == 2.0


@pytest.mark.asyncio
async def test_allocation_fefo_stock_insuffisant(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Magasin X", type_magasin=TypeMagasin.VENTE, actif=True)
    ingredient = Ingredient(nom="Oignon", unite_stock="kg", unite_mesure="kg", actif=True)

    session_test.add_all([magasin, ingredient])
    await session_test.commit()

    lot = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=None,
        code_lot="OX",
        date_dlc=None,
        unite="kg",
    )
    session_test.add(lot)
    await session_test.commit()

    # Seulement 1kg en réception
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

    allocateur = AllocateurFEFO(session_test)
    demande = DemandeConsommationIngredient(ingredient_id=ingredient.id, quantite=2.0, unite="kg")

    with pytest.raises(StockInsuffisant):
        await allocateur.allouer(magasin_id=magasin.id, demande=demande)
