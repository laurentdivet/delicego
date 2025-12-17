from __future__ import annotations

import pytest

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMagasin, TypeMouvementStock
from app.domaine.modeles import (
    Fournisseur,
    Ingredient,
    Lot,
    Magasin,
    Utilisateur,
)
from app.domaine.modeles.stock_tracabilite import MouvementStock


@pytest.mark.asyncio
async def test_creation_objets_simples(session_test: AsyncSession) -> None:
    magasin = Magasin(
        nom="Magasin A",
        type_magasin=TypeMagasin.VENTE,
        actif=True,
    )

    ingredient = Ingredient(
        nom="Tomate",
        unite_stock="kg",
        unite_mesure="kg",
        actif=True,
    )

    fournisseur = Fournisseur(
        nom="Fournisseur A",
        actif=True,
    )

    session_test.add_all([magasin, ingredient, fournisseur])
    await session_test.commit()

    resultat = await session_test.execute(
        select(Magasin).where(Magasin.nom == "Magasin A")
    )
    assert resultat.scalar_one().nom == "Magasin A"


@pytest.mark.asyncio
async def test_contrainte_unique_email_utilisateur(
    session_test: AsyncSession,
) -> None:
    u1 = Utilisateur(
        email="a@exemple.fr",
        nom_affiche="A",
        actif=True,
    )
    u2 = Utilisateur(
        email="a@exemple.fr",
        nom_affiche="B",
        actif=True,
    )

    session_test.add(u1)
    await session_test.commit()

    session_test.add(u2)
    with pytest.raises(IntegrityError):
        await session_test.commit()


@pytest.mark.asyncio
async def test_contrainte_unique_lot(session_test: AsyncSession) -> None:
    magasin = Magasin(
        nom="Magasin B",
        type_magasin=TypeMagasin.PRODUCTION,
        actif=True,
    )

    ingredient = Ingredient(
        nom="Farine",
        unite_stock="kg",
        unite_mesure="kg",
        actif=True,
    )

    fournisseur = Fournisseur(
        nom="Fournisseur B",
        actif=True,
    )

    session_test.add_all([magasin, ingredient, fournisseur])
    await session_test.commit()

    lot1 = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=fournisseur.id,
        code_lot="LOT-001",
        unite="kg",
    )

    session_test.add(lot1)
    await session_test.commit()

    mouvement_reception = MouvementStock(
        type_mouvement=TypeMouvementStock.RECEPTION,
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        lot_id=lot1.id,
        quantite=10.0,
        unite="kg",
        commentaire="Réception initiale",
    )

    session_test.add(mouvement_reception)
    await session_test.commit()

    lot2 = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=fournisseur.id,
        code_lot="LOT-001",
        unite="kg",
    )

    session_test.add(lot2)
    with pytest.raises(IntegrityError):
        await session_test.commit()
