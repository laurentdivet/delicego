from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.enums.types import TypeMagasin, TypeMouvementStock
from app.domaine.modeles.referentiel import Fournisseur, Ingredient, LigneRecette, Magasin, Menu, Recette
from app.domaine.modeles.achats import ReceptionMarchandise
from app.domaine.modeles.impact import FacteurCO2, IngredientImpact, PerteCasse
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

    # DATABASE_URL est la source de vérité.
    url_db = os.getenv("DATABASE_URL") or parametres_application.url_base_donnees
    engine = create_async_engine(url_db, pool_pre_ping=True)
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
            ingredient = Ingredient(
                nom="Farine",
                unite_stock="kg",
                unite_consommation="kg",
                cout_unitaire=1.2,
                actif=True,
            )
            session.add(ingredient)
            await session.flush()

        # Fournisseur (minimum pour la génération achats)
        resf_local = await session.execute(select(Fournisseur).where(Fournisseur.nom == "Fournisseur Local Démo"))
        fournisseur_local = resf_local.scalar_one_or_none()
        if fournisseur_local is None:
            fournisseur_local = Fournisseur(nom="Fournisseur Local Démo", actif=True, region="Occitanie", distance_km=30.0)
            session.add(fournisseur_local)
            await session.flush()

        resf_nonlocal = await session.execute(select(Fournisseur).where(Fournisseur.nom == "Fournisseur Non-Local Démo"))
        fournisseur_nonlocal = resf_nonlocal.scalar_one_or_none()
        if fournisseur_nonlocal is None:
            fournisseur_nonlocal = Fournisseur(nom="Fournisseur Non-Local Démo", actif=True, region="Ailleurs", distance_km=800.0)
            session.add(fournisseur_nonlocal)
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

        # Réceptions "achats" pour KPI local (2 réceptions sur 2 fournisseurs)
        now = datetime.now(timezone.utc)
        res_rm = await session.execute(
            select(ReceptionMarchandise).where(ReceptionMarchandise.magasin_id == magasin.id)
        )
        existing_rm = res_rm.scalars().all()
        if len(existing_rm) == 0:
            session.add(
                ReceptionMarchandise(
                    magasin_id=magasin.id,
                    fournisseur_id=fournisseur_local.id,
                    commande_achat_id=None,
                    recu_le=now - timedelta(days=2),
                )
            )
            session.add(
                ReceptionMarchandise(
                    magasin_id=magasin.id,
                    fournisseur_id=fournisseur_nonlocal.id,
                    commande_achat_id=None,
                    recu_le=now - timedelta(days=1),
                )
            )

        # Mouvement PERTE pour KPI waste
        res_perte = await session.execute(
            select(MouvementStock).where(
                MouvementStock.type_mouvement == TypeMouvementStock.PERTE,
                MouvementStock.magasin_id == magasin.id,
                MouvementStock.ingredient_id == ingredient.id,
                MouvementStock.reference_externe == "SEED_IMPACT",
            )
        )
        ms_perte = res_perte.scalar_one_or_none()
        if ms_perte is None:
            session.add(
                MouvementStock(
                    type_mouvement=TypeMouvementStock.PERTE,
                    magasin_id=magasin.id,
                    ingredient_id=ingredient.id,
                    lot_id=lot.id,
                    quantite=5.0,
                    unite="kg",
                    reference_externe="SEED_IMPACT",
                    commentaire="Perte démo",
                    horodatage=now - timedelta(days=1),
                )
            )

        # PerteCasse (optionnel) pour tester la table dédiée
        res_pc = await session.execute(select(PerteCasse).where(PerteCasse.magasin_id == magasin.id))
        if res_pc.first() is None:
            session.add(
                PerteCasse(
                    magasin_id=magasin.id,
                    ingredient_id=ingredient.id,
                    jour=(date.today() - timedelta(days=1)),
                    quantite=1.0,
                    unite="kg",
                    cause="casse",
                )
            )

        # Facteurs CO2 + mapping ingredient -> catégorie
        res_fc = await session.execute(select(FacteurCO2).where(FacteurCO2.categorie.in_(["viande", "legumes"])))
        existing_fc = {f.categorie for f in res_fc.scalars().all()}
        # Valeurs indicatives (documentées), remplaçables
        if "viande" not in existing_fc:
            session.add(FacteurCO2(categorie="viande", facteur_kgco2e_par_kg=20.0, source="indicatif"))
        if "legumes" not in existing_fc:
            session.add(FacteurCO2(categorie="legumes", facteur_kgco2e_par_kg=2.0, source="indicatif"))

        res_map = await session.execute(select(IngredientImpact).where(IngredientImpact.ingredient_id == ingredient.id))
        if res_map.scalar_one_or_none() is None:
            session.add(IngredientImpact(ingredient_id=ingredient.id, categorie_co2="legumes"))

        # Menus + recettes + BOM
        menus_demo = [
            ("Menu Midi", "Plat + dessert", 12.9),
            ("Menu Soir", "Plat + boisson", 14.9),
            ("Menu Végé", "Option végétarienne", 11.9),
        ]

        for nom, description, prix in menus_demo:
            # Recette associée (modèle actuel: Menu.recette_id obligatoire)
            resr = await session.execute(select(Recette).where(Recette.nom == f"Recette {nom}"))
            recette = resr.scalar_one_or_none()
            if recette is None:
                recette = Recette(nom=f"Recette {nom}")
                session.add(recette)
                await session.flush()

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
                    recette_id=recette.id,
                )
                session.add(menu)
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
