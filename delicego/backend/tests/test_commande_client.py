from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMagasin, TypeMouvementStock
from app.domaine.modeles import Fournisseur, Ingredient, Magasin, Menu
from app.domaine.modeles.commande_client import CommandeClient, LigneCommandeClient
from app.domaine.modeles.production import LigneConsommation, LotProduction
from app.domaine.modeles.referentiel import LigneRecette, Recette
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock
from app.domaine.services.commander_client import (
    ServiceCommandeClient,
    StockInsuffisantCommandeClient,
)


@pytest.mark.asyncio
async def test_commande_valide_declenche_production_et_consommation_fefo(
    session_test: AsyncSession,
) -> None:
    magasin = Magasin(nom="Escat Cmd", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    fournisseur = Fournisseur(nom="Fresh Cmd", actif=True)
    ingredient = Ingredient(nom="Tomate Cmd", unite_stock="kg", unite_mesure="kg", actif=True)

    session_test.add_all([magasin, fournisseur, ingredient])
    await session_test.commit()

    recette = Recette(nom="Recette Salade Cmd")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Menu Salade Cmd", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    # 0.2 kg par unité
    session_test.add(
        LigneRecette(
            recette_id=recette.id,
            ingredient_id=ingredient.id,
            quantite=0.2,
            unite="kg",
        )
    )
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

    # Stock total 2.3 kg
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

    # Commande : 5 unités -> besoin 1.0 kg
    service = ServiceCommandeClient(session_test)
    commande_id = await service.commander(
        magasin_id=magasin.id,
        lignes=[(menu.id, 5.0)],
        commentaire="Sans oignons",
    )

    # Commande + ligne existent
    res_c = await session_test.execute(select(CommandeClient).where(CommandeClient.id == commande_id))
    commande = res_c.scalar_one()
    assert commande.commentaire == "Sans oignons"

    res_l = await session_test.execute(
        select(LigneCommandeClient).where(LigneCommandeClient.commande_client_id == commande_id)
    )
    ligne = res_l.scalar_one()
    assert ligne.menu_id == menu.id
    assert ligne.lot_production_id is not None

    # LotProduction créé
    res_lp = await session_test.execute(select(LotProduction).where(LotProduction.id == ligne.lot_production_id))
    lot_prod = res_lp.scalar_one()
    assert lot_prod.quantite_produite == 5.0

    # Consommations créées (via ServiceExecutionProduction)
    res_cons = await session_test.execute(
        select(LigneConsommation).where(LigneConsommation.lot_production_id == lot_prod.id)
    )
    conso = list(res_cons.scalars().all())
    assert len(conso) == 2  # FEFO : 0.3 + 0.7

    # Mouvements stock de consommation : uniquement via production (reference_externe == lot_production.id)
    res_m = await session_test.execute(
        select(MouvementStock).where(
            MouvementStock.type_mouvement == TypeMouvementStock.CONSOMMATION,
            MouvementStock.reference_externe == str(lot_prod.id),
        )
    )
    mouvements = list(res_m.scalars().all())
    assert len(mouvements) == 2


@pytest.mark.asyncio
async def test_commande_stock_insuffisant_rollback_total(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat Cmd KO", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    fournisseur = Fournisseur(nom="Fresh Cmd KO", actif=True)
    ingredient = Ingredient(nom="Farine Cmd KO", unite_stock="kg", unite_mesure="kg", actif=True)

    session_test.add_all([magasin, fournisseur, ingredient])
    await session_test.commit()

    recette = Recette(nom="Recette Pizza Cmd KO")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Menu Pizza Cmd KO", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    # 10 kg par unité -> énorme
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
        fournisseur_id=fournisseur.id,
        code_lot="F1",
        date_dlc=None,
        unite="kg",
    )
    session_test.add(lot)
    await session_test.commit()

    # Stock : 1 kg
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

    service = ServiceCommandeClient(session_test)

    with pytest.raises(StockInsuffisantCommandeClient):
        await service.commander(
            magasin_id=magasin.id,
            lignes=[(menu.id, 1.0)],
        )

    # Vérifier rollback : aucune commande, aucune ligne, aucun lot_production
    res_c = await session_test.execute(select(CommandeClient))
    assert res_c.scalars().first() is None

    res_l = await session_test.execute(select(LigneCommandeClient))
    assert res_l.scalars().first() is None

    res_lp = await session_test.execute(select(LotProduction))
    assert res_lp.scalars().first() is None

    # Et surtout : aucun mouvement de consommation n’a été créé
    res_m = await session_test.execute(
        select(MouvementStock).where(MouvementStock.type_mouvement == TypeMouvementStock.CONSOMMATION)
    )
    assert res_m.scalars().first() is None
