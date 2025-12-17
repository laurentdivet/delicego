from __future__ import annotations

"""Initialisation stock réel PROD pour 3 magasins (idempotent).

Objectif:
- Créer des Lots + MouvementsStock de type RECEPTION pour constituer un stock initial
- 10 unités par ingrédient, par magasin
- DLC = NULL
- Import idempotent via `reference_externe = "INIT-STOCK-2025-<magasin_uuid>"`

Lancement:
    cd backend
    python -m scripts.init_stock_prod_3_magasins

⚠️ Règles strictes:
- Ne crée aucun nouvel ingrédient
- Ne modifie aucun ingrédient existant

"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.enums.types import TypeMouvementStock
from app.domaine.modeles.referentiel import Ingredient, Magasin
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock


def normaliser_nom(nom: str) -> str:
    # Normalisation minimale (cohérente avec les scripts existants)
    return " ".join(nom.strip().split())


@dataclass(frozen=True)
class MagasinCible:
    id: UUID
    nom: str


MAGASINS: list[MagasinCible] = [
    MagasinCible(UUID("0be7d9d5-8883-41b0-aff3-2dc6a77e76df"), "Carrefour Prigonrieux"),
    MagasinCible(UUID("3994db1d-af25-4141-a64f-27e74b411e0d"), "Carrefour Auguste Comte"),
    MagasinCible(UUID("60a4b99e-e2e3-4909-8b88-74acac5ca4a2"), "Intermarché Bergerac"),
]

# Ingrédients à stocker (noms EXACTS existants)
INGREDIENTS_NOMS: list[str] = [
    "RIZ POUR CUISINE JAPONAISE",
    "Œufs entiers pasteurisés",
    "Dés de jambon cuit",
    "Edamame écossé mukimame",
    "SAUCE SOJA SHODA 1 L",
    "HUILE DE SÉSAME",
    "NOUILLES DE RIZ",
    "CREVETTES BLEUES TROPICALES CRUES ENTIERES 31/40 OBSIBLUE 1 KG",
    "Pousses de haricot mungo en conserve",
    "SAUCE POISSON NUOC MAM SUREE 690 mL",
    "CONCENTRÉ DE TAMARIN",
    "Sucre cristal",
    "CACAHUÈTES CONCASSÉES",
]

QTE_INIT = 10.0
CODE_LOT = "INIT-STOCK-2025"


async def get_magasin(session, magasin_id: UUID) -> Magasin:
    res = await session.execute(select(Magasin).where(Magasin.id == magasin_id))
    magasin = res.scalar_one_or_none()
    if magasin is None:
        raise RuntimeError(f"Magasin introuvable: {magasin_id}")
    return magasin


async def get_ingredient_strict(session, ingredient_nom: str) -> Ingredient:
    # Le user demande les noms EXACTS existants.
    # On normalise tout de même les espaces pour être robuste, mais on vérifie ensuite.
    nom_norm = normaliser_nom(ingredient_nom)

    res = await session.execute(select(Ingredient).where(Ingredient.nom == nom_norm))
    ing = res.scalar_one_or_none()
    if ing is None:
        raise RuntimeError(f"Ingrédient introuvable en base (nom exact requis): {ingredient_nom}")

    # Sécurité : si la base contient une variante d'espaces, on refuse (pour éviter un match ambigu)
    if ing.nom != nom_norm:
        raise RuntimeError(
            f"Ingrédient trouvé mais nom différent après normalisation: demandé={ingredient_nom!r} base={ing.nom!r}"
        )

    return ing


async def get_or_create_lot_init(session, *, magasin: Magasin, ingredient: Ingredient) -> Lot:
    # Lot unique par (magasin, ingredient, fournisseur_id=NULL, code_lot=CODE_LOT)
    res = await session.execute(
        select(Lot).where(
            Lot.magasin_id == magasin.id,
            Lot.ingredient_id == ingredient.id,
            Lot.fournisseur_id.is_(None),
            Lot.code_lot == CODE_LOT,
        )
    )
    lot = res.scalar_one_or_none()
    if lot is not None:
        return lot

    lot = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=None,
        code_lot=CODE_LOT,
        date_dlc=None,
        unite=ingredient.unite_stock,
    )
    session.add(lot)
    await session.flush()
    return lot


async def ensure_reception_mouvement(
    session,
    *,
    magasin: Magasin,
    ingredient: Ingredient,
    lot: Lot,
    reference_externe: str,
) -> bool:
    """Crée le mouvement RECEPTION si absent.

    Returns:
        True si créé, False si déjà existant.
    """

    res = await session.execute(
        select(MouvementStock).where(
            MouvementStock.type_mouvement == TypeMouvementStock.RECEPTION,
            MouvementStock.magasin_id == magasin.id,
            MouvementStock.ingredient_id == ingredient.id,
            MouvementStock.lot_id == lot.id,
            MouvementStock.reference_externe == reference_externe,
        )
    )
    ms = res.scalar_one_or_none()
    if ms is not None:
        return False

    session.add(
        MouvementStock(
            type_mouvement=TypeMouvementStock.RECEPTION,
            magasin_id=magasin.id,
            ingredient_id=ingredient.id,
            lot_id=lot.id,
            quantite=QTE_INIT,
            unite=ingredient.unite_stock,
            reference_externe=reference_externe,
            commentaire=f"Initialisation stock réel {QTE_INIT:g} {ingredient.unite_stock} par ingrédient",
            horodatage=datetime.now(timezone.utc),
        )
    )
    return True


async def run() -> None:
    engine = create_async_engine(parametres_application.url_base_donnees, pool_pre_ping=True)
    sessionmaker_ = async_sessionmaker(bind=engine, expire_on_commit=False)

    # Résumé
    lots_crees: dict[UUID, int] = {m.id: 0 for m in MAGASINS}
    mouvements_crees: dict[UUID, int] = {m.id: 0 for m in MAGASINS}

    async with sessionmaker_() as session:
        # Vérification stricte des ingrédients en amont (fail fast)
        ingredients: list[Ingredient] = []
        for nom in INGREDIENTS_NOMS:
            ingredients.append(await get_ingredient_strict(session, nom))

        # Traitement magasin par magasin
        for magasin_cible in MAGASINS:
            magasin = await get_magasin(session, magasin_cible.id)
            ref_ext = f"INIT-STOCK-2025-{magasin.id}"

            for ing in ingredients:
                # Lot
                lot_avant = await session.execute(
                    select(Lot.id).where(
                        Lot.magasin_id == magasin.id,
                        Lot.ingredient_id == ing.id,
                        Lot.fournisseur_id.is_(None),
                        Lot.code_lot == CODE_LOT,
                    )
                )
                lot_existait = lot_avant.scalar_one_or_none() is not None

                lot = await get_or_create_lot_init(session, magasin=magasin, ingredient=ing)
                if not lot_existait:
                    lots_crees[magasin.id] += 1

                # Mouvement RECEPTION
                created = await ensure_reception_mouvement(
                    session,
                    magasin=magasin,
                    ingredient=ing,
                    lot=lot,
                    reference_externe=ref_ext,
                )
                if created:
                    mouvements_crees[magasin.id] += 1

        await session.commit()

    await engine.dispose()

    print("\n=== INIT STOCK PROD: RÉSUMÉ ===")
    for m in MAGASINS:
        print(f"- {m.nom} ({m.id}) : lots créés={lots_crees[m.id]}, mouvements RECEPTION créés={mouvements_crees[m.id]}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
