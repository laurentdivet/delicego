from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.enums.types import TypeMagasin, TypeMouvementStock
from app.domaine.modeles.referentiel import Fournisseur, Ingredient, LigneRecette, Magasin, Menu, Recette
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock


async def seed_demo() -> None:
    """Seed de données de démonstration.

    Objectif : avoir immédiatement un parcours client fonctionnel :
    - 1 magasin
    - 3 menus
    - 1 ingrédient
    - 3 recettes (1 par menu) + BOM (LigneRecette)
    - 1 lot + réception stock suffisante

    Ainsi l'endpoint /api/client/menus renvoie `disponible=true`.
    """

    engine = create_async_engine(parametres_application.url_base_donnees, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        # Magasin
        res = await session.execute(select(Magasin).where(Magasin.nom == "Escat"))
        magasin = res.scalar_one_or_none()
        if magasin is None:
            magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
            session.add(magasin)
            await session.flush()

        # Ingrédient de base
        resi = await session.execute(select(Ingredient).where(Ingredient.nom == "Farine"))
        ingredient = resi.scalar_one_or_none()
        if ingredient is None:
            ingredient = Ingredient(nom="Farine", unite_stock="kg", unite_mesure="kg", cout_unitaire=1.2, actif=True)
            session.add(ingredient)
            await session.flush()

        # Fournisseur (minimum pour la génération achats)
        resf = await session.execute(select(Fournisseur).where(Fournisseur.nom == "Fournisseur Démo"))
        fournisseur = resf.scalar_one_or_none()
        if fournisseur is None:
            fournisseur = Fournisseur(nom="Fournisseur Démo", actif=True)
            session.add(fournisseur)
            await session.flush()

        # Stock (lot + réception)
        res_lot = await session.execute(
            select(Lot).where(
                Lot.magasin_id == magasin.id,
                Lot.ingredient_id == ingredient.id,
                Lot.code_lot == "DEMO-1",
            )
        )
        lot = res_lot.scalar_one_or_none()
        if lot is None:
            lot = Lot(
                magasin_id=magasin.id,
                ingredient_id=ingredient.id,
                fournisseur_id=None,
                code_lot="DEMO-1",
                date_dlc=date.today() + timedelta(days=30),
                unite="kg",
            )
            session.add(lot)
            await session.flush()

        # On s'assure d'avoir une réception suffisante (100 kg)
        res_ms = await session.execute(
            select(MouvementStock).where(
                MouvementStock.type_mouvement == TypeMouvementStock.RECEPTION,
                MouvementStock.magasin_id == magasin.id,
                MouvementStock.ingredient_id == ingredient.id,
                MouvementStock.lot_id == lot.id,
                MouvementStock.reference_externe == "SEED_DEMO",
            )
        )
        ms = res_ms.scalar_one_or_none()
        if ms is None:
            session.add(
                MouvementStock(
                    type_mouvement=TypeMouvementStock.RECEPTION,
                    magasin_id=magasin.id,
                    ingredient_id=ingredient.id,
                    lot_id=lot.id,
                    quantite=100.0,
                    unite="kg",
                    reference_externe="SEED_DEMO",
                    commentaire="Réception démo",
                    horodatage=datetime.now(timezone.utc),
                )
            )

        # Menus + recettes + BOM
        menus_demo = [
            ("Menu Midi", "Plat + dessert", 12.9),
            ("Menu Soir", "Plat + boisson", 14.9),
            ("Menu Végé", "Option végétarienne", 11.9),
        ]

        for nom, description, prix in menus_demo:
            resm = await session.execute(select(Menu).where(Menu.nom == nom, Menu.magasin_id == magasin.id))
            menu = resm.scalar_one_or_none()
            if menu is None:
                menu = Menu(
                    nom=nom,
                    description=description,
                    prix=prix,
                    actif=True,
                    commandable=True,
                    magasin_id=magasin.id,
                )
                session.add(menu)
                await session.flush()

            # Recette associée
            resr = await session.execute(select(Recette).where(Recette.menu_id == menu.id))
            recette = resr.scalar_one_or_none()
            if recette is None:
                recette = Recette(nom=f"Recette {nom}", menu_id=menu.id, magasin_id=magasin.id)
                session.add(recette)
                await session.flush()

            # BOM : 0.5 kg de farine par menu
            reslr = await session.execute(
                select(LigneRecette).where(LigneRecette.recette_id == recette.id, LigneRecette.ingredient_id == ingredient.id)
            )
            lr = reslr.scalar_one_or_none()
            if lr is None:
                session.add(
                    LigneRecette(
                        recette_id=recette.id,
                        ingredient_id=ingredient.id,
                        quantite=0.5,
                        unite="kg",
                    )
                )

        await session.commit()

        print("Seed OK")
        print(f"magasin_id={magasin.id}")

    await engine.dispose()


def main() -> None:
    asyncio.run(seed_demo())


if __name__ == "__main__":
    main()
