from __future__ import annotations

"""Import structuré des recettes Janvier 2025 (PDF WOK/BOOK).

⚠️ Ce script est volontairement *sans parsing PDF automatique* :
les données sont codées ici, de manière lisible et versionnée.

Objectifs :
- Créer / réutiliser : Magasin (production), Ingredient, Menu, Recette, LigneRecette
- Idempotent (re-lançable sans doublons)
- Quantités ramenées à *1 portion* (base pour prod/stock/planif)

Convention sauces & marinades (choix cohérent) :
- Les sauces/marinades sont gérées comme des *ingrédients* (techniques),
  pas comme des recettes séparées.
  Raison : le modèle actuel lie Recette à Menu (vendable) et la planif
  produit des Recettes. Pour les préparations techniques, on veut d’abord
  pouvoir consommer/planifier sans ajouter un autre modèle.

Lancement :
    cd backend
    python -m scripts.import_recettes_janvier_2025

"""

import asyncio
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.enums.types import TypeMagasin
from app.domaine.modeles.referentiel import Ingredient, LigneRecette, Magasin, Menu, Recette


# ------------------------------
# Données (extrait WOK Janvier 2025)
# ------------------------------


@dataclass(frozen=True)
class IngredientDef:
    nom: str
    unite_stock: str
    unite_mesure: str


@dataclass(frozen=True)
class LigneDef:
    ingredient: str
    quantite_par_portion: float
    unite: str


@dataclass(frozen=True)
class MenuDef:
    nom: str
    prix: float
    description: str | None
    lignes: list[LigneDef]


# Normalisation minimale (pour éviter les doublons par casse / espaces)
# NOTE: on garde les accents (ex : "Cébette") car PostgreSQL gère très bien.

def normaliser_nom(nom: str) -> str:
    return " ".join(nom.strip().split())


# Ingrédients communs (unité stock = cohérente pour stock ; unité mesure = identique)
INGREDIENTS: list[IngredientDef] = [
    IngredientDef("Riz thaï cuit", "kg", "kg"),
    IngredientDef("Riz parfumé", "kg", "kg"),
    IngredientDef("Dés de jambon", "kg", "kg"),
    IngredientDef("Petits pois", "kg", "kg"),
    IngredientDef("Œuf liquide", "kg", "kg"),
    IngredientDef("Huile de tournesol", "L", "L"),
    IngredientDef("Ail (purée)", "kg", "kg"),
    IngredientDef("Sel", "kg", "kg"),
    IngredientDef("Poivre", "kg", "kg"),
    IngredientDef("Ciboulette", "kg", "kg"),
    IngredientDef("Bœuf mariné", "kg", "kg"),
    IngredientDef("Poulet mariné", "kg", "kg"),
    IngredientDef("Oignons", "kg", "kg"),
    IngredientDef("Oignons frits", "kg", "kg"),
    IngredientDef("Cébette", "kg", "kg"),
    IngredientDef("Basilic", "kg", "kg"),
    IngredientDef("Fécule de pomme de terre", "kg", "kg"),
    IngredientDef("Nouilles udon", "kg", "kg"),
    IngredientDef("Poivrons tricolores", "kg", "kg"),
    IngredientDef("Carotte", "kg", "kg"),
    IngredientDef("Marinade de base", "kg", "kg"),
]


MENUS: list[MenuDef] = [
    # WOK (fabriqué sur place)
    MenuDef(
        nom="Riz Cantonais",
        prix=9.90,
        description="Wok riz cantonais, ciboulette.",
        # PDF : pour 8 bols: 1600g riz thaï cuit, 500g jambon, 300g petits pois,
        # 440g œuf liquide, 80g huile, 25g ail purée, sel 10g, poivre 10g.
        # => par portion = / 8.
        lignes=[
            LigneDef("Riz thaï cuit", 200.0, "g"),
            LigneDef("Dés de jambon", 62.5, "g"),
            LigneDef("Petits pois", 37.5, "g"),
            LigneDef("Œuf liquide", 55.0, "g"),
            LigneDef("Huile de tournesol", 10.0, "g"),
            LigneDef("Ail (purée)", 3.125, "g"),
            LigneDef("Sel", 1.25, "g"),
            LigneDef("Poivre", 1.25, "g"),
            LigneDef("Ciboulette", 1.0, "g"),
        ],
    ),
    MenuDef(
        nom="Bœuf aux oignons",
        prix=11.90,
        description="Wok bœuf aux oignons, oignons frits et cébette.",
        # PDF composition 1 barquette : bœuf aux oignons 150g, riz parfumé 200g, cébette 2g, oignons frits 5g
        # Ici on stocke la BOM "portion" directement.
        lignes=[
            LigneDef("Bœuf mariné", 150.0, "g"),
            LigneDef("Riz parfumé", 200.0, "g"),
            LigneDef("Cébette", 2.0, "g"),
            LigneDef("Oignons frits", 5.0, "g"),
            # La recette pas-à-pas indique aussi des oignons crus + huile + fécule.
            # On les inclut pour la prod : 320g oignons pour 4 bols => 80g/portion.
            LigneDef("Oignons", 80.0, "g"),
            LigneDef("Huile de tournesol", 10.0, "g"),
            LigneDef("Fécule de pomme de terre", 1.0, "c.à.s"),
            LigneDef("Poivre", 1.25, "g"),
        ],
    ),
    MenuDef(
        nom="Bœuf au basilic",
        prix=11.90,
        description="Wok bœuf au basilic.",
        lignes=[
            LigneDef("Bœuf mariné", 150.0, "g"),
            LigneDef("Riz parfumé", 200.0, "g"),
            LigneDef("Basilic", 1.0, "g"),
            LigneDef("Oignons", 80.0, "g"),
            LigneDef("Huile de tournesol", 10.0, "g"),
            LigneDef("Fécule de pomme de terre", 1.0, "c.à.s"),
        ],
    ),
    MenuDef(
        nom="Poulet aux oignons",
        prix=10.90,
        description="Wok poulet aux oignons, oignons frits et cébette.",
        lignes=[
            LigneDef("Poulet mariné", 150.0, "g"),
            LigneDef("Riz parfumé", 200.0, "g"),
            LigneDef("Cébette", 2.0, "g"),
            LigneDef("Oignons frits", 5.0, "g"),
            LigneDef("Oignons", 80.0, "g"),
            LigneDef("Huile de tournesol", 10.0, "g"),
            LigneDef("Poivre", 1.25, "g"),
        ],
    ),
    MenuDef(
        nom="Poulet au basilic",
        prix=10.90,
        description="Wok poulet au basilic.",
        lignes=[
            LigneDef("Poulet mariné", 150.0, "g"),
            LigneDef("Riz parfumé", 200.0, "g"),
            LigneDef("Basilic", 1.0, "g"),
            LigneDef("Oignons", 80.0, "g"),
            LigneDef("Huile de tournesol", 10.0, "g"),
        ],
    ),
    MenuDef(
        nom="Nouilles Udon Veggie",
        prix=10.90,
        description="Wok udon légumes, marinade de base.",
        # PDF : 1 bol : 1 sachet udon 200g, oignons 40g, poivrons 40g, carotte 40g,
        # huile 20g, sel 5g, poivre 5g, ail 1 c.à.c, marinade de base 80g, topping cébette 2g
        lignes=[
            LigneDef("Nouilles udon", 200.0, "g"),
            LigneDef("Oignons", 40.0, "g"),
            LigneDef("Poivrons tricolores", 40.0, "g"),
            LigneDef("Carotte", 40.0, "g"),
            LigneDef("Huile de tournesol", 20.0, "g"),
            LigneDef("Sel", 5.0, "g"),
            LigneDef("Poivre", 5.0, "g"),
            LigneDef("Ail (purée)", 1.0, "c.à.c"),
            LigneDef("Marinade de base", 80.0, "g"),
            LigneDef("Cébette", 2.0, "g"),
        ],
    ),
]


# ------------------------------
# Helpers DB (idempotence)
# ------------------------------


async def get_or_create_magasin_production(session: AsyncSession, nom: str = "Escat") -> Magasin:
    nom = normaliser_nom(nom)

    q = await session.execute(select(Magasin).where(Magasin.nom == nom))
    magasin = q.scalar_one_or_none()
    if magasin:
        # S'assure que le type est cohérent.
        magasin.type_magasin = TypeMagasin.PRODUCTION
        magasin.actif = True
        return magasin

    magasin = Magasin(nom=nom, type_magasin=TypeMagasin.PRODUCTION, actif=True)
    session.add(magasin)
    await session.flush()
    return magasin


async def get_or_create_ingredient(session: AsyncSession, definition: IngredientDef) -> Ingredient:
    nom = normaliser_nom(definition.nom)

    q = await session.execute(select(Ingredient).where(Ingredient.nom == nom))
    ingredient = q.scalar_one_or_none()

    if ingredient:
        # On remet à niveau sans changer l'identité.
        ingredient.unite_stock = definition.unite_stock
        ingredient.unite_mesure = definition.unite_mesure
        ingredient.actif = True
        return ingredient

    ingredient = Ingredient(
        nom=nom,
        unite_stock=definition.unite_stock,
        unite_mesure=definition.unite_mesure,
        actif=True,
    )
    session.add(ingredient)
    await session.flush()
    return ingredient


async def get_or_create_menu(session: AsyncSession, magasin: Magasin, definition: MenuDef) -> Menu:
    nom = normaliser_nom(definition.nom)

    q = await session.execute(
        select(Menu).where(Menu.nom == nom).where(Menu.magasin_id == magasin.id)
    )
    menu = q.scalar_one_or_none()

    if menu:
        menu.actif = True
        menu.commandable = True
        menu.prix = definition.prix
        menu.description = definition.description
        return menu

    menu = Menu(
        nom=nom,
        actif=True,
        commandable=True,
        prix=definition.prix,
        description=definition.description,
        magasin_id=magasin.id,
    )
    session.add(menu)
    await session.flush()
    return menu


async def get_or_create_recette(session: AsyncSession, magasin: Magasin, menu: Menu) -> Recette:
    nom = f"Recette {menu.nom}"

    q = await session.execute(
        select(Recette)
        .where(Recette.menu_id == menu.id)
        .where(Recette.magasin_id == magasin.id)
    )
    recette = q.scalar_one_or_none()

    if recette:
        recette.nom = nom
        return recette

    recette = Recette(
        nom=nom,
        menu_id=menu.id,
        magasin_id=magasin.id,
    )
    session.add(recette)
    await session.flush()
    return recette


async def upsert_lignes_recette(session: AsyncSession, recette: Recette, lignes: Iterable[LigneDef]) -> None:
    # On fait simple : pour chaque ligne, on upsert via unique(recette_id, ingredient_id)
    for ligne in lignes:
        nom_ingredient = normaliser_nom(ligne.ingredient)

        q = await session.execute(select(Ingredient).where(Ingredient.nom == nom_ingredient))
        ingredient = q.scalar_one()

        ql = await session.execute(
            select(LigneRecette)
            .where(LigneRecette.recette_id == recette.id)
            .where(LigneRecette.ingredient_id == ingredient.id)
        )
        lr = ql.scalar_one_or_none()

        if lr:
            lr.quantite = float(ligne.quantite_par_portion)
            lr.unite = ligne.unite
        else:
            lr = LigneRecette(
                recette_id=recette.id,
                ingredient_id=ingredient.id,
                quantite=float(ligne.quantite_par_portion),
                unite=ligne.unite,
            )
            session.add(lr)


async def importer() -> None:
    moteur = create_async_engine(parametres_application.url_base_donnees, pool_pre_ping=True)
    sessionmaker_ = async_sessionmaker(bind=moteur, expire_on_commit=False)

    async with sessionmaker_() as session:
        magasin = await get_or_create_magasin_production(session, nom="Escat")

        # Ingrédients
        for ing in INGREDIENTS:
            await get_or_create_ingredient(session, ing)

        # Menus + recettes + lignes
        for menu_def in MENUS:
            menu = await get_or_create_menu(session, magasin, menu_def)
            recette = await get_or_create_recette(session, magasin, menu)
            await upsert_lignes_recette(session, recette, menu_def.lignes)

        await session.commit()

    await moteur.dispose()


def main() -> None:
    asyncio.run(importer())


if __name__ == "__main__":
    main()
