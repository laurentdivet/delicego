from __future__ import annotations

"""Seed minimal *production* (traçable, idempotent) :

- Ajoute uniquement 5 ingrédients matières premières cuisine (si absents)
- Crée 2 menus + 2 recettes associées + leurs lignes (BOM) (idempotent)

⚠️ Règles :
- Aucun renommage / modification d’ingrédients existants (on ne touche qu'aux nouveaux si création)
- Aucune création/modification d’unité autre que les valeurs fournies
- Pas de logique métier : insertion simple

Lancement :
    cd backend
    python -m scripts.seed_ingredients_et_recettes_prod

"""

import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.enums.types import TypeMagasin
from app.domaine.modeles.referentiel import Ingredient, LigneRecette, Magasin, Menu, Recette


def normaliser_nom(nom: str) -> str:
    # Normalisation minimale (cohérente avec les autres scripts) : trim + espaces.
    return " ".join(nom.strip().split())


@dataclass(frozen=True)
class IngredientSeed:
    nom: str
    unite_stock: str
    unite_mesure: str


@dataclass(frozen=True)
class LigneRecetteSeed:
    ingredient_nom: str
    quantite: float
    unite: str


@dataclass(frozen=True)
class RecetteSeed:
    menu_nom: str
    menu_prix: float
    menu_description: str | None
    recette_nom: str
    lignes: list[LigneRecetteSeed]


INGREDIENTS_A_CREER: list[IngredientSeed] = [
    IngredientSeed("RIZ POUR CUISINE JAPONAISE", "kg", "kg"),
    IngredientSeed("HUILE DE SÉSAME", "litre", "litre"),
    IngredientSeed("NOUILLES DE RIZ", "kg", "kg"),
    IngredientSeed("CACAHUÈTES CONCASSÉES", "kg", "kg"),
    IngredientSeed("CONCENTRÉ DE TAMARIN", "kg", "kg"),
]


RECETTES_A_CREER: list[RecetteSeed] = [
    RecetteSeed(
        menu_nom="Riz cantonais",
        menu_prix=0.0,
        menu_description=None,
        recette_nom="Riz cantonais",
        lignes=[
            LigneRecetteSeed("RIZ POUR CUISINE JAPONAISE", 0.100, "kg"),
            LigneRecetteSeed("Œufs entiers pasteurisés", 0.060, "kg"),
            LigneRecetteSeed("Dés de jambon cuit", 0.050, "kg"),
            LigneRecetteSeed("Edamame écossé mukimame", 0.050, "kg"),
            LigneRecetteSeed("SAUCE SOJA SHODA 1 L", 0.010, "l"),
            LigneRecetteSeed("HUILE DE SÉSAME", 0.005, "l"),
        ],
    ),
    RecetteSeed(
        menu_nom="Pad Thaï crevettes",
        menu_prix=0.0,
        menu_description=None,
        recette_nom="Pad Thaï crevettes",
        lignes=[
            LigneRecetteSeed("NOUILLES DE RIZ", 0.120, "kg"),
            LigneRecetteSeed("CREVETTES BLEUES TROPICALES CRUES ENTIERES 31/40 OBSIBLUE 1 KG", 0.120, "kg"),
            LigneRecetteSeed("Œufs entiers pasteurisés", 0.050, "kg"),
            LigneRecetteSeed("Pousses de haricot mungo en conserve", 0.050, "kg"),
            LigneRecetteSeed("SAUCE POISSON NUOC MAM SUREE 690 mL", 0.015, "l"),
            LigneRecetteSeed("CONCENTRÉ DE TAMARIN", 0.010, "kg"),
            LigneRecetteSeed("Sucre cristal", 0.010, "kg"),
            LigneRecetteSeed("HUILE DE SÉSAME", 0.005, "l"),
            LigneRecetteSeed("CACAHUÈTES CONCASSÉES", 0.015, "kg"),
        ],
    ),
]


async def get_or_create_magasin_production(session) -> Magasin:
    # On réutilise "Escat" si déjà présent (pattern existant).
    nom = "Escat"
    res = await session.execute(select(Magasin).where(Magasin.nom == nom))
    magasin = res.scalar_one_or_none()
    if magasin:
        # On s'assure juste du type (sans changer identité)
        magasin.type_magasin = TypeMagasin.PRODUCTION
        magasin.actif = True
        return magasin

    magasin = Magasin(nom=nom, type_magasin=TypeMagasin.PRODUCTION, actif=True)
    session.add(magasin)
    await session.flush()
    return magasin


async def get_or_create_menu(session, magasin: Magasin, *, nom: str, prix: float, description: str | None) -> Menu:
    nom = normaliser_nom(nom)
    res = await session.execute(select(Menu).where(Menu.nom == nom).where(Menu.magasin_id == magasin.id))
    menu = res.scalar_one_or_none()
    if menu:
        # Mise à niveau minimale (pas de logique métier)
        menu.actif = True
        menu.commandable = True
        menu.prix = float(prix)
        menu.description = description
        return menu

    menu = Menu(
        nom=nom,
        description=description,
        prix=float(prix),
        commandable=True,
        actif=True,
        magasin_id=magasin.id,
    )
    session.add(menu)
    await session.flush()
    return menu


async def get_or_create_recette(session, magasin: Magasin, *, menu: Menu, nom: str) -> Recette:
    nom = normaliser_nom(nom)
    res = await session.execute(
        select(Recette).where(Recette.menu_id == menu.id).where(Recette.magasin_id == magasin.id)
    )
    recette = res.scalar_one_or_none()
    if recette:
        recette.nom = nom
        return recette

    recette = Recette(nom=nom, menu_id=menu.id, magasin_id=magasin.id)
    session.add(recette)
    await session.flush()
    return recette


async def get_or_create_ingredient(session, seed: IngredientSeed) -> Ingredient:
    nom = normaliser_nom(seed.nom)
    res = await session.execute(select(Ingredient).where(Ingredient.nom == nom))
    ing = res.scalar_one_or_none()

    if ing:
        # Règle : aucun renommage d'ingrédient existant.
        # Ici on ne modifie pas les champs d'unité pour éviter toute altération.
        return ing

    ing = Ingredient(
        nom=nom,
        unite_stock=seed.unite_stock,
        unite_mesure=seed.unite_mesure,
        actif=True,
    )
    session.add(ing)
    await session.flush()
    return ing


async def upsert_ligne_recette(session, *, recette: Recette, ingredient: Ingredient, quantite: float, unite: str) -> None:
    res = await session.execute(
        select(LigneRecette).where(
            LigneRecette.recette_id == recette.id,
            LigneRecette.ingredient_id == ingredient.id,
        )
    )
    lr = res.scalar_one_or_none()

    if lr:
        lr.quantite = float(quantite)
        lr.unite = unite
        return

    lr = LigneRecette(
        recette_id=recette.id,
        ingredient_id=ingredient.id,
        quantite=float(quantite),
        unite=unite,
    )
    session.add(lr)


async def seed() -> None:
    engine = create_async_engine(parametres_application.url_base_donnees, pool_pre_ping=True)
    sessionmaker_ = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with sessionmaker_() as session:
        magasin = await get_or_create_magasin_production(session)

        # 1) Ingrédients (uniquement les 5)
        ingredients_map: dict[str, Ingredient] = {}
        for ing_seed in INGREDIENTS_A_CREER:
            ing = await get_or_create_ingredient(session, ing_seed)
            ingredients_map[normaliser_nom(ing_seed.nom)] = ing

        # 2) Recettes + lignes
        for recette_seed in RECETTES_A_CREER:
            menu = await get_or_create_menu(
                session,
                magasin,
                nom=recette_seed.menu_nom,
                prix=recette_seed.menu_prix,
                description=recette_seed.menu_description,
            )
            recette = await get_or_create_recette(session, magasin, menu=menu, nom=recette_seed.recette_nom)

            for ligne in recette_seed.lignes:
                ing_nom = normaliser_nom(ligne.ingredient_nom)
                res_ing = await session.execute(select(Ingredient).where(Ingredient.nom == ing_nom))
                ingredient = res_ing.scalar_one_or_none()
                if ingredient is None:
                    raise RuntimeError(f"Ingrédient introuvable en base: {ligne.ingredient_nom}")

                await upsert_ligne_recette(
                    session,
                    recette=recette,
                    ingredient=ingredient,
                    quantite=ligne.quantite,
                    unite=ligne.unite,
                )

        await session.commit()

    await engine.dispose()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
