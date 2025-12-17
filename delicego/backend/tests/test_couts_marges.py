from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMagasin
from app.domaine.modeles.referentiel import Ingredient, LigneRecette, Magasin, Menu, Recette
from app.domaine.services.couts_marges import MenuSansRecette, ServiceCoutsMarges


@pytest.mark.asyncio
async def test_cout_recette_simple(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    session_test.add(magasin)
    await session_test.flush()

    ing = Ingredient(
        nom="Riz",
        unite_stock="kg",
        unite_mesure="kg",
        cout_unitaire=2.0,  # 2€/kg
        actif=True,
    )
    session_test.add(ing)

    recette = Recette(nom="Recette Riz")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(
        nom="Riz simple",
        actif=True,
        commandable=True,
        prix=10.0,
        description=None,
        magasin_id=magasin.id,
        recette_id=recette.id,
    )
    session_test.add(menu)
    await session_test.flush()

    # 0.5 kg * 2 €/kg = 1 €
    lr = LigneRecette(recette_id=recette.id, ingredient_id=ing.id, quantite=0.5, unite="kg")
    session_test.add(lr)

    await session_test.commit()

    service = ServiceCoutsMarges(session_test)
    cout = await service.calculer_cout_recette(recette.id)
    assert cout == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_cout_menu_plusieurs_ingredients(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    session_test.add(magasin)
    await session_test.flush()

    ing1 = Ingredient(
        nom="Poulet",
        unite_stock="kg",
        unite_mesure="kg",
        cout_unitaire=10.0,
        actif=True,
    )
    ing2 = Ingredient(
        nom="Riz",
        unite_stock="kg",
        unite_mesure="kg",
        cout_unitaire=2.0,
        actif=True,
    )
    session_test.add_all([ing1, ing2])

    recette = Recette(nom="Recette Poulet riz")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(
        nom="Poulet riz",
        actif=True,
        commandable=True,
        prix=12.0,
        description=None,
        magasin_id=magasin.id,
        recette_id=recette.id,
    )
    session_test.add(menu)
    await session_test.flush()

    # 0.2kg poulet * 10 = 2
    # 0.3kg riz * 2 = 0.6
    session_test.add_all(
        [
            LigneRecette(recette_id=recette.id, ingredient_id=ing1.id, quantite=0.2, unite="kg"),
            LigneRecette(recette_id=recette.id, ingredient_id=ing2.id, quantite=0.3, unite="kg"),
        ]
    )

    await session_test.commit()

    service = ServiceCoutsMarges(session_test)
    cout_menu = await service.calculer_cout_menu(menu.id)
    assert cout_menu == pytest.approx(2.6)

    marge = await service.calculer_marge_menu(menu.id, prix_vente=menu.prix)
    assert marge == pytest.approx(12.0 - 2.6)


@pytest.mark.asyncio
async def test_menu_sans_recette_erreur_controlee(session_test: AsyncSession) -> None:
    # Dans le nouveau schéma, un Menu doit toujours avoir recette_id.
    # On remplace donc ce test par un cas "BOM vide" : la recette existe mais n'a pas de lignes.
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    session_test.add(magasin)
    await session_test.flush()

    recette = Recette(nom="Recette BOM vide")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(
        nom="Menu BOM vide",
        actif=True,
        commandable=True,
        prix=9.0,
        description=None,
        magasin_id=magasin.id,
        recette_id=recette.id,
    )
    session_test.add(menu)
    await session_test.commit()

    service = ServiceCoutsMarges(session_test)

    # BOM vide => coût = 0, donc pas d'exception
    cout = await service.calculer_cout_menu(menu.id)
    assert cout == pytest.approx(0.0)
