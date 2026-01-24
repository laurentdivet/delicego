from __future__ import annotations

"""Seed des données *réelles* (MENUS / INGRÉDIENTS / MAGASINS) pour DéliceGo.

🎯 Objectif
- Créer exactement 3 magasins réels (actifs)
- Créer un référentiel ingrédients unique (actifs)
- Créer les menus visibles côté client (actifs + commandables) et disponibles dans les 3 magasins
- Préparer le terrain Phase 2 : liens Menu -> Recette -> LignesRecette (ingrédients + quantités)

⚙️ Contraintes
- Idempotent : relançable sans doublons
- SQLAlchemy async uniquement
- Ne modifie pas les endpoints
- Ne touche pas au frontend
- Pas de données "demo" / "fake"

Lancement
--------
    cd backend

    # La config runtime est stricte (Step16.1) : ENV + DATABASE_URL_* requis
    export ENV=dev
    export DATABASE_URL_DEV="postgresql+asyncpg://lolo@localhost:5432/delicego_dev"
    export DATABASE_URL_TEST="$DATABASE_URL_DEV"
    export DATABASE_URL_PROD="$DATABASE_URL_DEV"

    python -m scripts.seed_real_data

"""

import asyncio
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.enums.types import TypeMagasin
from app.domaine.modeles.referentiel import Ingredient, LigneRecette, Magasin, Menu, Recette


# ------------------------------
# Normalisation / canonicalisation
# ------------------------------

def normaliser_nom(nom: str) -> str:
    # Normalisation minimale (cohérente scripts existants) : trim + espaces.
    return " ".join((nom or "").strip().split())


def canonical_key(nom: str) -> str:
    """Clé de dédoublonnage métier.

    Objectif : éviter les doublons type "Saumon cru" vs "saumon".
    On reste volontairement conservateur (pas de NLP), mais on supprime
    quelques variations triviales.
    """

    s = normaliser_nom(nom).lower()
    s = s.replace("œ", "oe")

    # Suppression de qualificatifs trop variables
    stop = [
        " cru",
        " cuit",
        " frais",
        " surgelé",
        " surgele",
    ]
    for t in stop:
        s = s.replace(t, "")

    return " ".join(s.split())


# ------------------------------
# Données réelles (MVP Phase 1 + base Phase 2)
# ------------------------------


@dataclass(frozen=True)
class MagasinSeed:
    nom: str
    type_magasin: TypeMagasin


MAGASINS_REELS: list[MagasinSeed] = [
    MagasinSeed("Carrefour Market Prigonrieux", TypeMagasin.VENTE),
    MagasinSeed("Carrefour Market Auguste-Comté", TypeMagasin.VENTE),
    MagasinSeed("Intermarché Verrouille", TypeMagasin.VENTE),
]


@dataclass(frozen=True)
class IngredientSeed:
    nom: str
    unite_stock: str
    unite_mesure: str


# Référentiel initial (obligatoire + extensible).
# NOTE: pas de prix => cout_unitaire laissé à 0.0 (défaut DB)
INGREDIENTS_REFERENTIEL: list[IngredientSeed] = [
    # Riz
    IngredientSeed("Riz vinaigré", "kg", "kg"),
    IngredientSeed("Riz thaï", "kg", "kg"),
    IngredientSeed("Riz parfumé", "kg", "kg"),

    # Légumes / fruits
    IngredientSeed("Avocat", "kg", "kg"),
    IngredientSeed("Concombre", "kg", "kg"),
    IngredientSeed("Carotte", "kg", "kg"),
    IngredientSeed("Chou blanc", "kg", "kg"),
    IngredientSeed("Chou rouge", "kg", "kg"),
    IngredientSeed("Salade iceberg", "kg", "kg"),
    IngredientSeed("Laitue", "kg", "kg"),
    IngredientSeed("Haricot mungo", "kg", "kg"),
    IngredientSeed("Mangue", "kg", "kg"),
    IngredientSeed("Oignon", "kg", "kg"),
    IngredientSeed("Poireau", "kg", "kg"),
    IngredientSeed("Cébette", "kg", "kg"),

    # Herbes
    IngredientSeed("Menthe", "kg", "kg"),
    IngredientSeed("Coriandre", "kg", "kg"),
    IngredientSeed("Basilic", "kg", "kg"),
    IngredientSeed("Ciboulette", "kg", "kg"),

    # Poissons / crustacés
    IngredientSeed("Saumon", "kg", "kg"),
    IngredientSeed("Thon", "kg", "kg"),
    IngredientSeed("Crevette", "kg", "kg"),
    IngredientSeed("Calamar", "kg", "kg"),
    IngredientSeed("Surimi", "kg", "kg"),

    # Viandes
    IngredientSeed("Poulet", "kg", "kg"),
    IngredientSeed("Bœuf", "kg", "kg"),
    IngredientSeed("Porc", "kg", "kg"),

    # Féculents / pâtes
    IngredientSeed("Vermicelle de riz", "kg", "kg"),
    IngredientSeed("Nouilles de riz", "kg", "kg"),
    IngredientSeed("Nouilles udon", "kg", "kg"),
    IngredientSeed("Nouilles ramen", "kg", "kg"),

    # Wrappers / algues
    IngredientSeed("Galette de riz", "piece", "piece"),
    IngredientSeed("Algue nori", "piece", "piece"),

    # Produits laitiers / oeufs
    IngredientSeed("Cream cheese", "kg", "kg"),
    IngredientSeed("Œuf liquide", "kg", "kg"),

    # Sauces
    IngredientSeed("Sauce soja", "L", "L"),
    IngredientSeed("Sauce unagi", "L", "L"),
    IngredientSeed("Sauce teriyaki", "L", "L"),
    IngredientSeed("Sauce ponzu", "L", "L"),
    IngredientSeed("Sauce pad thaï", "L", "L"),
    IngredientSeed("Sauce aigre-douce", "L", "L"),
    IngredientSeed("Nuoc-mâm", "L", "L"),
    IngredientSeed("Sauce huître", "L", "L"),

    # Condiments
    IngredientSeed("Gingembre", "kg", "kg"),
    IngredientSeed("Wasabi", "kg", "kg"),
    IngredientSeed("Shichimi", "kg", "kg"),
    IngredientSeed("Sésame", "kg", "kg"),
    IngredientSeed("Oignons frits", "kg", "kg"),

    # Produits transformés
    IngredientSeed("Gyoza", "piece", "piece"),
    IngredientSeed("Nems", "piece", "piece"),
    IngredientSeed("Samoussas", "piece", "piece"),
    IngredientSeed("Perle de coco", "piece", "piece"),
]


@dataclass(frozen=True)
class LigneRecetteSeed:
    ingredient_key: str  # canonical_key(ingredient.nom)
    quantite: float
    unite: str


@dataclass(frozen=True)
class MenuSeed:
    nom: str
    type_menu: str
    description: str | None
    prix: float
    lignes: list[LigneRecetteSeed]


# NOTE : le modèle actuel ne porte pas "type" sur Menu.
# On conserve le type dans le nom de recette (préparation Phase 2).

MENUS_PHASE_1: list[MenuSeed] = [
    MenuSeed(
        nom="Riz Cantonais",
        type_menu="wok",
        description="Wok riz cantonais.",
        prix=9.90,
        lignes=[
            LigneRecetteSeed(canonical_key("Riz thaï"), 0.200, "kg"),
            LigneRecetteSeed(canonical_key("Œuf liquide"), 0.055, "kg"),
            LigneRecetteSeed(canonical_key("Oignon"), 0.030, "kg"),
            LigneRecetteSeed(canonical_key("Ciboulette"), 0.001, "kg"),
            LigneRecetteSeed(canonical_key("Sauce soja"), 0.010, "L"),
        ],
    ),
    MenuSeed(
        nom="Nouilles Udon Veggie",
        type_menu="wok",
        description="Wok udon légumes.",
        prix=10.90,
        lignes=[
            LigneRecetteSeed(canonical_key("Nouilles udon"), 0.200, "kg"),
            LigneRecetteSeed(canonical_key("Oignon"), 0.040, "kg"),
            LigneRecetteSeed(canonical_key("Carotte"), 0.040, "kg"),
            LigneRecetteSeed(canonical_key("Cébette"), 0.002, "kg"),
            LigneRecetteSeed(canonical_key("Sauce soja"), 0.010, "L"),
        ],
    ),
    MenuSeed(
        nom="California Saumon Avocat",
        type_menu="sushi",
        description="Roll saumon avocat.",
        prix=8.90,
        lignes=[
            LigneRecetteSeed(canonical_key("Riz vinaigré"), 0.150, "kg"),
            LigneRecetteSeed(canonical_key("Saumon"), 0.060, "kg"),
            LigneRecetteSeed(canonical_key("Avocat"), 0.040, "kg"),
            LigneRecetteSeed(canonical_key("Algue nori"), 1.0, "piece"),
        ],
    ),
    MenuSeed(
        nom="Ramen Poulet",
        type_menu="ramen",
        description="Ramen poulet.",
        prix=12.90,
        lignes=[
            LigneRecetteSeed(canonical_key("Nouilles ramen"), 0.180, "kg"),
            LigneRecetteSeed(canonical_key("Poulet"), 0.120, "kg"),
            LigneRecetteSeed(canonical_key("Cébette"), 0.005, "kg"),
            LigneRecetteSeed(canonical_key("Sauce soja"), 0.010, "L"),
        ],
    ),
    MenuSeed(
        nom="Perle de coco (x1)",
        type_menu="dessert",
        description="Dessert perle de coco.",
        prix=3.50,
        lignes=[
            LigneRecetteSeed(canonical_key("Perle de coco"), 1.0, "piece"),
        ],
    ),
]


# ------------------------------
# DB helpers (idempotents)
# ------------------------------


async def get_or_create_magasin(session: AsyncSession, seed: MagasinSeed) -> tuple[Magasin, bool]:
    nom = normaliser_nom(seed.nom)
    res = await session.execute(select(Magasin).where(Magasin.nom == nom))
    m = res.scalar_one_or_none()

    if m is not None:
        m.type_magasin = seed.type_magasin
        m.actif = True
        return m, False

    m = Magasin(nom=nom, type_magasin=seed.type_magasin, actif=True)
    session.add(m)
    await session.flush()
    return m, True


async def get_or_create_ingredient(session: AsyncSession, seed: IngredientSeed) -> tuple[Ingredient, bool]:
    nom = normaliser_nom(seed.nom)

    # On lit l'id uniquement pour rester robuste si le schéma diverge.
    res = await session.execute(select(Ingredient.id).where(Ingredient.nom == nom))
    ing_id = res.scalar_one_or_none()
    ing = await session.get(Ingredient, ing_id) if ing_id else None

    if ing is not None:
        ing.unite_stock = seed.unite_stock
        ing.unite_mesure = seed.unite_mesure
        ing.actif = True
        return ing, False

    ing = Ingredient(
        nom=nom,
        unite_stock=seed.unite_stock,
        unite_mesure=seed.unite_mesure,
        actif=True,
    )
    session.add(ing)
    await session.flush()
    return ing, True


async def get_or_create_recette_globale(session: AsyncSession, *, nom: str) -> tuple[Recette, bool]:
    nom = normaliser_nom(nom)
    res = await session.execute(select(Recette).where(Recette.nom == nom))
    r = res.scalar_one_or_none()
    if r is not None:
        return r, False

    r = Recette(nom=nom)
    session.add(r)
    await session.flush()
    return r, True


async def get_or_create_menu(
    session: AsyncSession,
    *,
    magasin: Magasin,
    nom: str,
    description: str | None,
    prix: float,
    recette: Recette,
) -> tuple[Menu, bool]:
    nom = normaliser_nom(nom)
    res = await session.execute(select(Menu).where(Menu.magasin_id == magasin.id, Menu.nom == nom))
    m = res.scalar_one_or_none()

    if m is not None:
        m.description = description
        m.prix = float(prix)
        m.actif = True
        m.commandable = True
        m.recette_id = recette.id
        return m, False

    m = Menu(
        nom=nom,
        description=description,
        prix=float(prix),
        actif=True,
        commandable=True,
        magasin_id=magasin.id,
        recette_id=recette.id,
    )
    session.add(m)
    await session.flush()
    return m, True


async def upsert_lignes_recette(
    session: AsyncSession,
    *,
    recette: Recette,
    lignes: Iterable[LigneRecetteSeed],
    ingredients_by_key: dict[str, Ingredient],
) -> None:
    for l in lignes:
        ing = ingredients_by_key.get(l.ingredient_key)
        if ing is None:
            raise RuntimeError(f"Ingrédient manquant pour recette '{recette.nom}': key={l.ingredient_key}")

        res = await session.execute(
            select(LigneRecette).where(
                LigneRecette.recette_id == recette.id,
                LigneRecette.ingredient_id == ing.id,
            )
        )
        lr = res.scalar_one_or_none()

        if lr is not None:
            lr.quantite = float(l.quantite)
            lr.unite = l.unite
            continue

        session.add(
            LigneRecette(
                recette_id=recette.id,
                ingredient_id=ing.id,
                quantite=float(l.quantite),
                unite=l.unite,
            )
        )


# ------------------------------
# Main
# ------------------------------


async def seed_real_data() -> None:
    # NB: la configuration expose `url_base_donnees` (et non `url_base_donnees_effective`)
    engine = create_async_engine(parametres_application.url_base_donnees, pool_pre_ping=True)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    created_mag = 0
    created_ing = 0
    created_menu = 0
    created_rec = 0

    async with sm() as session:
        # 1) Magasins
        magasins: list[Magasin] = []
        for mseed in MAGASINS_REELS:
            mag, created = await get_or_create_magasin(session, mseed)
            magasins.append(mag)
            if created:
                created_mag += 1

        # 2) Ingrédients (référentiel)
        dedup: dict[str, IngredientSeed] = {}
        for s in INGREDIENTS_REFERENTIEL:
            key = canonical_key(s.nom)
            if key in dedup:
                raise RuntimeError(f"Doublon dans INGREDIENTS_REFERENTIEL: '{s.nom}' conflict key='{key}'")
            dedup[key] = s

        ingredients_by_key: dict[str, Ingredient] = {}
        for key, seed in dedup.items():
            ing, created = await get_or_create_ingredient(session, seed)
            ingredients_by_key[key] = ing
            if created:
                created_ing += 1

        # 3) Menus + recettes + BOM
        for menuseed in MENUS_PHASE_1:
            recette_nom = f"{menuseed.type_menu.upper()} - {menuseed.nom}"  # stable, explicite
            recette, created_r = await get_or_create_recette_globale(session, nom=recette_nom)
            if created_r:
                created_rec += 1

            await upsert_lignes_recette(
                session,
                recette=recette,
                lignes=menuseed.lignes,
                ingredients_by_key=ingredients_by_key,
            )

            # Menus dans les 3 magasins (même catalogue)
            for mag in magasins:
                _, created_m = await get_or_create_menu(
                    session,
                    magasin=mag,
                    nom=menuseed.nom,
                    description=menuseed.description,
                    prix=menuseed.prix,
                    recette=recette,
                )
                if created_m:
                    created_menu += 1

        await session.commit()

        nb_mag = (await session.execute(select(func.count()).select_from(Magasin))).scalar_one()
        nb_ing = (await session.execute(select(func.count()).select_from(Ingredient))).scalar_one()
        nb_menu = (await session.execute(select(func.count()).select_from(Menu))).scalar_one()

    await engine.dispose()

    print("\n=== SEED REAL DATA: RÉSUMÉ ===")
    print(f"magasins: +{created_mag} (total={nb_mag})")
    print(f"ingredients: +{created_ing} (total={nb_ing})")
    print(f"menus: +{created_menu} (total={nb_menu})")
    print(f"recettes: +{created_rec} (total créations run)")


def main() -> None:
    asyncio.run(seed_real_data())


if __name__ == "__main__":
    main()
