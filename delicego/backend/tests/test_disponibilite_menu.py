from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMagasin, TypeMouvementStock
from app.domaine.modeles.referentiel import Ingredient, LigneRecette, Magasin, Menu, Recette
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock
from app.domaine.services.commander_client import ServiceCommandeClient
from app.domaine.services.disponibilite_menu import ServiceDisponibiliteMenu


@pytest.mark.asyncio
async def test_stock_suffisant_menu_disponible(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    ingredient = Ingredient(nom="Tomate", unite_stock="kg", unite_consommation="kg", actif=True)
    session_test.add_all([magasin, ingredient])
    await session_test.commit()

    recette = Recette(nom="Recette Salade")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(
        nom="Salade",
        actif=True,
        commandable=True,
        prix=10.0,
        description=None,
        magasin_id=magasin.id,
        recette_id=recette.id,
    )
    session_test.add(menu)
    await session_test.commit()

    # 0.2 kg par portion
    session_test.add(LigneRecette(recette_id=recette.id, ingredient_id=ingredient.id, quantite=0.2, unite="kg"))
    await session_test.commit()

    lot = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=None,
        code_lot="L1",
        date_dlc=date.today() + timedelta(days=2),
        unite="kg",
    )
    session_test.add(lot)
    await session_test.commit()

    # 1 kg en stock
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

    service = ServiceDisponibiliteMenu(session_test)
    assert await service.est_menu_disponible(menu_id=menu.id, quantite=1.0) is True


@pytest.mark.asyncio
async def test_stock_insuffisant_menu_indisponible(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    ingredient = Ingredient(nom="Farine", unite_stock="kg", unite_consommation="kg", actif=True)
    session_test.add_all([magasin, ingredient])
    await session_test.commit()

    recette = Recette(nom="Recette Pizza")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(
        nom="Pizza",
        actif=True,
        commandable=True,
        prix=12.0,
        description=None,
        magasin_id=magasin.id,
        recette_id=recette.id,
    )
    session_test.add(menu)
    await session_test.commit()

    # 10 kg par portion
    session_test.add(LigneRecette(recette_id=recette.id, ingredient_id=ingredient.id, quantite=10.0, unite="kg"))
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

    # seulement 1 kg en stock
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

    service = ServiceDisponibiliteMenu(session_test)
    assert await service.est_menu_disponible(menu_id=menu.id, quantite=1.0) is False


@pytest.mark.asyncio
async def test_commande_qui_vide_le_stock_rend_menu_indisponible(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    ingredient = Ingredient(nom="Tomate", unite_stock="kg", unite_consommation="kg", actif=True)
    session_test.add_all([magasin, ingredient])
    await session_test.commit()

    recette = Recette(nom="Recette Salade")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(
        nom="Salade",
        actif=True,
        commandable=True,
        prix=10.0,
        description=None,
        magasin_id=magasin.id,
        recette_id=recette.id,
    )
    session_test.add(menu)
    await session_test.commit()

    # 0.2 kg par portion
    session_test.add(LigneRecette(recette_id=recette.id, ingredient_id=ingredient.id, quantite=0.2, unite="kg"))
    await session_test.commit()

    lot = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=None,
        code_lot="L1",
        date_dlc=date.today() + timedelta(days=2),
        unite="kg",
    )
    session_test.add(lot)
    await session_test.commit()

    # Stock juste suffisant pour 1 portion
    session_test.add(
        MouvementStock(
            type_mouvement=TypeMouvementStock.RECEPTION,
            magasin_id=magasin.id,
            ingredient_id=ingredient.id,
            lot_id=lot.id,
            quantite=0.2,
            unite="kg",
        )
    )
    await session_test.commit()

    service_dispo = ServiceDisponibiliteMenu(session_test)
    assert await service_dispo.est_menu_disponible(menu_id=menu.id, quantite=1.0) is True

    # Commande de 1 menu => exécution production => consommation => stock à 0
    service_commande = ServiceCommandeClient(session_test)
    await service_commande.commander(magasin_id=magasin.id, lignes=[(menu.id, 1.0)])

    # Après commande, plus dispo
    assert await service_dispo.est_menu_disponible(menu_id=menu.id, quantite=1.0) is False
