from __future__ import annotations

"""Seed global (idempotent) pour dev/test.

Ce seed orchestre:
1) création des fournisseurs nécessaires
2) import catalogue (XLSX)
3) création de quelques ingrédients/recettes de démo (sans doublons)
4) mapping ingredient -> produit via YAML (prioritaire) puis fuzzy (fallback)
5) checks post-seed

Exécution (depuis backend/):
    python -m scripts.seed_all --dry-run --catalog-xlsx ../PRODUITS_SORAE.xlsx
    python -m scripts.seed_all --apply   --catalog-xlsx ../PRODUITS_SORAE.xlsx

Notes:
- Idempotent: rejouable sans doublons.
- --dry-run ne commit rien.
"""

import argparse
import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.enums.types import TypeMagasin
from app.domaine.modeles.catalogue import Produit, ProduitFournisseur
from app.domaine.modeles.referentiel import Fournisseur, Ingredient, LigneRecette, Magasin, Menu, Recette
from scripts import import_catalogue_foodex_xlsx
from scripts.map_ingredients_to_produits import run as run_fuzzy_mapping


@dataclass
class SeedReport:
    total_ingredients: int = 0
    mapped_ingredients: int = 0


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


async def get_or_create_fournisseur(session: AsyncSession, *, nom: str) -> Fournisseur:
    res = await session.execute(select(Fournisseur).where(Fournisseur.nom == nom))
    f = res.scalar_one_or_none()
    if f is None:
        f = Fournisseur(nom=nom, actif=True)
        session.add(f)
        await session.flush()
    else:
        f.actif = True
    return f


async def get_or_create_magasin_production(session: AsyncSession) -> Magasin:
    nom = "Escat"
    res = await session.execute(select(Magasin).where(Magasin.nom == nom))
    m = res.scalar_one_or_none()
    if m is None:
        m = Magasin(nom=nom, type_magasin=TypeMagasin.PRODUCTION, actif=True)
        session.add(m)
        await session.flush()
    else:
        m.type_magasin = TypeMagasin.PRODUCTION
        m.actif = True
    return m


async def get_or_create_ingredient(session: AsyncSession, *, nom: str, unite_stock: str) -> Ingredient:
    nom = _norm(nom)
    res = await session.execute(select(Ingredient).where(Ingredient.nom == nom))
    ing = res.scalar_one_or_none()
    if ing is None:
        # unite_consommation est NOT NULL en DB (schéma actuel). Valeur minimale cohérente.
        ing = Ingredient(nom=nom, unite_stock=unite_stock, unite_consommation=unite_stock, actif=True)
        session.add(ing)
        await session.flush()
    else:
        ing.actif = True
    return ing


async def get_or_create_ingredient_demo(
    session: AsyncSession,
    *,
    nom: str,
    unite_stock: str,
    produit_libelle_exact: str,
    unite_consommation: str | None,
    facteur_conversion: float | None,
    cout_unitaire: float | None = None,
) -> Ingredient:
    """Crée (ou réactive) un ingrédient de démo et le relie à un Produit du catalogue.

    Règles:
    - pas d'égalité stricte globale nom ingrédient / libellé produit, mais pour le seed/demo
      on pointe explicitement vers un produit via `produit_libelle_exact`.
    - idempotent: rejouable sans doublons.
    """

    nom = _norm(nom)
    res = await session.execute(select(Ingredient).where(Ingredient.nom == nom))
    ing = res.scalar_one_or_none()
    if ing is None:
        # unite_consommation est NOT NULL en DB (schéma actuel). Valeur minimale cohérente.
        ing = Ingredient(nom=nom, unite_stock=unite_stock, unite_consommation=unite_stock, actif=True)
        session.add(ing)
        await session.flush()
    else:
        ing.actif = True

    # Produit cible (exact)
    # Règle: PAS de fallback incohérent.
    # Si le produit n'existe pas dans le catalogue, on laisse produit_id à NULL.
    prod = (
        await session.execute(select(Produit).where(Produit.libelle == produit_libelle_exact))
    ).scalar_one_or_none()
    if prod is not None:
        ing.produit_id = prod.id
    else:
        # IMPORTANT: on ne force pas une valeur arbitraire.
        # Idempotence: si déjà NULL, on ne touche pas.
        ing.produit_id = None
    ing.unite_consommation = unite_consommation
    ing.facteur_conversion = facteur_conversion
    if cout_unitaire is not None:
        ing.cout_unitaire = float(cout_unitaire)
    return ing


async def get_or_create_menu(session: AsyncSession, magasin: Magasin, *, nom: str, recette_id) -> Menu:
    """Crée un menu en respectant la contrainte NOT NULL recette_id."""

    nom = _norm(nom)
    res = await session.execute(select(Menu).where(Menu.nom == nom, Menu.magasin_id == magasin.id))
    menu = res.scalar_one_or_none()
    if menu is None:
        menu = Menu(
            nom=nom,
            description=None,
            prix=0.0,
            commandable=True,
            actif=True,
            magasin_id=magasin.id,
            recette_id=recette_id,
        )
        session.add(menu)
        await session.flush()
    else:
        menu.actif = True
        menu.commandable = True
        # S'assure que recette_id est remplie
        if getattr(menu, "recette_id", None) is None:
            menu.recette_id = recette_id
    return menu


async def get_or_create_recette(session: AsyncSession, *, nom: str) -> Recette:
    """Recette globale par nom."""

    nom = _norm(nom)
    res = await session.execute(select(Recette).where(Recette.nom == nom))
    recette = res.scalar_one_or_none()
    if recette is None:
        recette = Recette(nom=nom)
        session.add(recette)
        await session.flush()
    return recette


async def upsert_ligne_recette(
    session: AsyncSession, *, recette: Recette, ingredient: Ingredient, quantite: float, unite: str
) -> None:
    res = await session.execute(
        select(LigneRecette).where(LigneRecette.recette_id == recette.id, LigneRecette.ingredient_id == ingredient.id)
    )
    lr = res.scalar_one_or_none()
    if lr is None:
        lr = LigneRecette(recette_id=recette.id, ingredient_id=ingredient.id, quantite=float(quantite), unite=unite)
        session.add(lr)
    else:
        lr.quantite = float(quantite)
        lr.unite = unite


async def checks_post_seed(session: AsyncSession) -> None:
    n_prod = (await session.execute(select(func.count()).select_from(Produit))).scalar_one()
    n_pf = (await session.execute(select(func.count()).select_from(ProduitFournisseur))).scalar_one()
    # Compat: certains schémas / versions de modèles peuvent ne pas exposer Ingredient.produit_id côté ORM.
    # Dans ce cas, on ne peut pas calculer ce check via ORM, on le saute.
    if not hasattr(Ingredient, "produit_id"):
        n_ing_mapped = 0
    else:
        n_ing_mapped = (
            await session.execute(select(func.count()).select_from(Ingredient).where(Ingredient.produit_id.is_not(None)))
        ).scalar_one()

    problems = []
    if n_prod <= 0:
        problems.append("check failed: nb produits == 0")
    if n_pf <= 0:
        problems.append("check failed: nb produit_fournisseur == 0")
    if hasattr(Ingredient, "produit_id") and n_ing_mapped <= 0:
        problems.append("check failed: nb ingredients avec produit_id == 0")

    if problems:
        for p in problems:
            print(f"[seed][ERROR] {p}")
        raise RuntimeError("; ".join(problems))

    print(f"[seed][OK] produits={n_prod} produit_fournisseur={n_pf} ingredients_mappes={n_ing_mapped}")

    # Bonus utile: afficher les ingrédients non mappés pour inciter à compléter le YAML.
    if hasattr(Ingredient, "produit_id"):
        unmapped = (
            await session.execute(
                select(Ingredient.nom)
                .where(Ingredient.actif.is_(True), Ingredient.produit_id.is_(None))
                .order_by(Ingredient.nom)
            )
        ).scalars().all()
        if unmapped:
            print("[seed][WARN] ingredients non mappés (produit_id NULL):")
            for nom in unmapped:
                print(f"  - {nom}")


async def seed_all(*, apply: bool, catalog_xlsx: str | None, subset: int | None) -> int:
    url_db = os.getenv("DATABASE_URL") or parametres_application.url_base_donnees
    engine = create_async_engine(url_db, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    force = os.getenv("SEED_FORCE") == "1"

    report = SeedReport()

    async with Session() as session:
        # A) fournisseurs
        await get_or_create_fournisseur(session, nom="Foodex")

        # B) import catalogue
        # IMPORTANT: l'import est idempotent mais ouvre sa propre session.
        # Pour un seed "propre", on ne l'exécute qu'en --apply.
        if apply:
            # Important: on veut que le seed soit exécutable sans XLSX.
            # Si aucun XLSX n'est fourni, on insère un mini-catalogue de démo.
            if catalog_xlsx:
                await import_catalogue_foodex_xlsx.importer(xlsx_path=catalog_xlsx, dry_run=False, fournisseur_nom="Foodex")
            else:
                # Produit(s) minimum nécessaires au seed (référencés par produit_libelle_exact)
                for lib in ["RIZ VINAIGRE", "GINGEMBRE ROSE", "SAUCE SOJA", "WASABI"]:
                    prod = (await session.execute(select(Produit).where(Produit.libelle == lib))).scalar_one_or_none()
                    if prod is None:
                        prod = Produit(libelle=lib, categorie=None, actif=True)
                        session.add(prod)
                        await session.flush()

                # On crée un PF minimum pour satisfaire le check (pf >= 1)
                prod_ref = (await session.execute(select(Produit).where(Produit.libelle == "RIZ VINAIGRE"))).scalar_one()
                f = (await session.execute(select(Fournisseur).where(Fournisseur.nom == "Foodex"))).scalar_one()
                pf = (
                    await session.execute(
                        select(ProduitFournisseur).where(
                            ProduitFournisseur.fournisseur_id == f.id,
                            ProduitFournisseur.reference_fournisseur == "DEMO-SKU-1",
                        )
                    )
                ).scalar_one_or_none()
                if pf is None:
                    pf = ProduitFournisseur(
                        produit_id=prod_ref.id,
                        fournisseur_id=f.id,
                        reference_fournisseur="DEMO-SKU-1",
                        libelle_fournisseur="DEMO",
                        unite_achat="kg",
                        quantite_par_unite=1.0,
                        prix_achat_ht=None,
                        tva=None,
                        actif=True,
                    )
                    session.add(pf)
                    await session.flush()

        # C) données démo minimales
        magasin = await get_or_create_magasin_production(session)

        # Ingrédients métiers MINIMAUX (démo) reliés au catalogue Foodex.
        # IMPORTANT:
        # - on ne génère PAS tout le catalogue
        # - on remplace les placeholders (ING*, etc.) par désactivation
        placeholders = (
            await session.execute(select(Ingredient).where(Ingredient.nom.ilike("ING%")))
        ).scalars().all()
        for p in placeholders:
            p.actif = False

        # NB: Les libellés ci-dessous existent dans l'XLSX importé (PRODUITS_SORAE.xlsx)
        # et servent de "produit principal" pour l'ingrédient.
        await get_or_create_ingredient_demo(
            session,
            nom="Riz sushi",
            unite_stock="kg",
            produit_libelle_exact="RIZ VINAIGRE",
            unite_consommation="g",
            facteur_conversion=1000.0,
        )
        await get_or_create_ingredient_demo(
            session,
            nom="Vinaigre de riz",
            unite_stock="kg",
            produit_libelle_exact="RIZ VINAIGRE",
            unite_consommation="g",
            facteur_conversion=1000.0,
        )
        await get_or_create_ingredient_demo(
            session,
            nom="Gingembre mariné",
            unite_stock="kg",
            produit_libelle_exact="GINGEMBRE ROSE",
            unite_consommation="g",
            facteur_conversion=1000.0,
        )

        # IMPORTANT: pas de fallback incohérent.
        # Si le catalogue ne contient pas encore un produit adapté, on laisse produit_id à NULL
        # (cela incite à compléter `data/mapping_ingredients_produits.yaml` ou à enrichir le catalogue).
        ing_sauce_soja = await get_or_create_ingredient_demo(
            session,
            nom="Sauce soja",
            unite_stock="kg",
            produit_libelle_exact="SAUCE SOJA",
            unite_consommation="g",
            facteur_conversion=1000.0,
        )
        ing_wasabi = await get_or_create_ingredient_demo(
            session,
            nom="Wasabi",
            unite_stock="kg",
            produit_libelle_exact="WASABI",
            unite_consommation="g",
            facteur_conversion=1000.0,
        )

        # Nettoyage de sécurité: si une ancienne exécution a mis un fallback incohérent
        # (ex: Sauce soja / Wasabi -> "RIZ VINAIGRE"), on remet à NULL.
        # - sans --force: on ne touche qu'aux cas explicitement identifiés comme fallbacks.
        # - avec --force: on autorise le reset même si ce n'est pas le fallback connu.
        prod_riz_vinaigre = (
            await session.execute(select(Produit).where(Produit.libelle == "RIZ VINAIGRE"))
        ).scalar_one_or_none()
        if prod_riz_vinaigre is not None:
            fallback_id = prod_riz_vinaigre.id

            if ing_sauce_soja.produit_id == fallback_id or (force and ing_sauce_soja.produit_id is not None):
                ing_sauce_soja.produit_id = None
            if ing_wasabi.produit_id == fallback_id or (force and ing_wasabi.produit_id is not None):
                ing_wasabi.produit_id = None

        recette = await get_or_create_recette(session, nom="Démo Riz")
        _ = await get_or_create_menu(session, magasin, nom="Démo Riz", recette_id=recette.id)

        ing_riz = (await session.execute(select(Ingredient).where(Ingredient.nom == "Riz sushi"))).scalar_one()
        ing_vinaigre = (await session.execute(select(Ingredient).where(Ingredient.nom == "Vinaigre de riz"))).scalar_one()
        ing_gingembre = (await session.execute(select(Ingredient).where(Ingredient.nom == "Gingembre mariné"))).scalar_one()
        await upsert_ligne_recette(session, recette=recette, ingredient=ing_riz, quantite=100.0, unite="g")
        await upsert_ligne_recette(session, recette=recette, ingredient=ing_vinaigre, quantite=10.0, unite="g")
        await upsert_ligne_recette(session, recette=recette, ingredient=ing_gingembre, quantite=5.0, unite="g")

        # D) commit de la transaction seed (données démo)
        # IMPORTANT: le fuzzy mapping ouvre sa propre session ; il faut donc commit d'abord
        # pour qu'il voie les changements.
        if apply:
            await session.commit()
        else:
            await session.rollback()

    # E) mapping ingredient -> produit
    # IMPORTANT: scripts.map_ingredients_to_produits ouvre sa propre session.
    # On l'exécute donc après le commit.
    if apply:
        # Compat: certains schémas / versions de modèles peuvent ne pas exposer Ingredient.produit_id côté ORM.
        # Dans ce cas, le mapping est impossible => on saute.
        if hasattr(Ingredient, "produit_id"):
            await run_fuzzy_mapping(apply=True, force=False)

    # Petites stats post-opérations (lecture)
    async with Session() as session_ro:
        report.total_ingredients = (await session_ro.execute(select(func.count()).select_from(Ingredient))).scalar_one()
        if hasattr(Ingredient, "produit_id"):
            report.mapped_ingredients = (
                await session_ro.execute(select(func.count()).select_from(Ingredient).where(Ingredient.produit_id.is_not(None)))
            ).scalar_one()
        else:
            report.mapped_ingredients = 0

    # checks post-seed: uniquement après apply (sinon on checke un état inchangé)
    if apply:
        async with Session() as session2:
            await checks_post_seed(session2)

    await engine.dispose()

    print("[seed] rapport:")
    print(f"  ingredients_total={report.total_ingredients}")
    print(f"  ingredients_mappes={report.mapped_ingredients}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Seed global idempotent")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Ne commit rien")
    g.add_argument("--apply", action="store_true", help="Commit en base")
    p.add_argument("--catalog-xlsx", default=None, help="Chemin XLSX catalogue (optionnel)")
    p.add_argument("--subset", type=int, default=None, help="Importer seulement N lignes (optionnel, TODO)")
    p.add_argument(
        "--force",
        action="store_true",
        help=(
            "Autorise des corrections potentiellement destructrices sur les liens ingredient.produit_id "
            "(ex: reset de mappings existants). Par défaut, le seed ne modifie pas les liens existants "
            "hors cas 'fallback incohérent connu'."
        ),
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    # NOTE: --force est lu via variable d'environnement, pour éviter de refactorer toute la signature
    # (script de démo). C'est un flag seed-only.
    if args.force:
        os.environ["SEED_FORCE"] = "1"
    rc = asyncio.run(seed_all(apply=bool(args.apply), catalog_xlsx=args.catalog_xlsx, subset=args.subset))
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
