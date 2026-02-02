from __future__ import annotations

"""Mapping idempotent Ingredient -> Produit.

Contexte:
- Le catalogue Foodex est importé dans les tables `produit` et `produit_fournisseur`.
- Les ingrédients existent déjà (source de vérité recettes/stock), et on souhaite les
  relier aux produits catalogue quand c'est possible, sans jamais casser l'existant.

Objectifs:
- Remplir ingredient.produit_id si on trouve un match fiable
- Remplir ingredient.unite_consommation / ingredient.facteur_conversion (achat -> conso)
- Ne jamais écraser un mapping existant, sauf si --force

Exécution (depuis backend/):
    python -m scripts.map_ingredients_to_produits --dry-run
    python -m scripts.map_ingredients_to_produits --apply
    python -m scripts.map_ingredients_to_produits --apply --force

Notes:
- Pas de dépendance "lourde" (fuzzywuzzy/rapidfuzz/etc.) : fuzzy simple maison.
- Tout est idempotent : rejouer le script ne doit pas produire de changements si rien n'a bougé.
"""

import argparse
import asyncio
import os
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.modeles.catalogue import Produit, ProduitFournisseur
from app.domaine.modeles.referentiel import Ingredient


# ---------------------------------------------------------------------------
# Normalisation & matching
# ---------------------------------------------------------------------------


def _strip_accents(s: str) -> str:
    # NFKD pour décomposer les accents, puis on enlève les marks.
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = _strip_accents(s)
    s = re.sub(r"[^a-z0-9]+", " ", s)  # punctuation -> space
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokens(s: str) -> set[str]:
    return {t for t in _norm(s).split(" ") if len(t) >= 2}


def _token_overlap_score(a: str, b: str) -> float:
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union


def _fuzzy_candidates(ingredient_nom: str, produits: list[Produit]) -> list[tuple[Produit, float]]:
    """Retourne des candidats (produit, score) triés desc.

    Heuristiques simples:
    - exact normalisé => score 1.0
    - startswith / contains => score 0.80 / 0.75
    - overlap tokens (Jaccard) => score dans [0..1]
    """

    ni = _norm(ingredient_nom)
    out: list[tuple[Produit, float]] = []

    for p in produits:
        np = _norm(p.libelle)
        if not np:
            continue

        if np == ni:
            out.append((p, 1.0))
            continue

        # contains/startswith : on favorise les matches assez longs
        if len(ni) >= 5 and np.startswith(ni):
            out.append((p, 0.80))
            continue
        if len(ni) >= 5 and (ni in np):
            out.append((p, 0.75))
            continue

        # token overlap
        score = _token_overlap_score(ingredient_nom, p.libelle)
        if score >= 0.50:
            out.append((p, score))

    out.sort(key=lambda x: x[1], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Unités & conversions
# ---------------------------------------------------------------------------


def _is_viande_charcut(ingredient_nom: str) -> bool:
    n = _norm(ingredient_nom)
    keywords = [
        "viande",
        "boeuf",
        "b uf",  # sécurité si accents/bizarre
        "porc",
        "poulet",
        "dinde",
        "agneau",
        "jambon",
        "lardon",
        "saucisse",
        "charcut",
        "steak",
        "escalope",
        "bacon",
        "canard",
        "veau",
    ]
    return any(k in n for k in keywords)


@dataclass(frozen=True)
class Conversion:
    unite_consommation: str
    facteur_conversion: float


def _conversion_depuis_unite_achat(unite_achat: str | None) -> Conversion | None:
    """Conversion achat -> consommation (base).

    Règle: on se contente des conversions sûres.
    - kg -> g (1000)
    - g -> g (1)
    - l -> ml (1000)
    - litre -> ml (1000)
    - ml -> ml (1)
    - pce/pièce/pcs -> pièce (1)
    """

    if not unite_achat:
        return None

    u = _norm(unite_achat)

    # poids
    if u in {"kg", "kilo", "kilogramme"}:
        return Conversion("g", 1000.0)
    if u in {"g", "gramme"}:
        return Conversion("g", 1.0)

    # volume
    if u in {"l", "litre", "litres"}:
        return Conversion("ml", 1000.0)
    if u in {"ml"}:
        return Conversion("ml", 1.0)

    # pièces
    if u in {"pce", "piece", "pieces", "pcs"}:
        return Conversion("piece", 1.0)

    return None


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


@dataclass
class MappingStats:
    total: int = 0
    mapped: int = 0
    ambiguous: int = 0
    not_found: int = 0
    skipped_existing: int = 0


async def _load_reference_unite_achat_par_produit(session) -> dict[str, str]:
    """Choisit une unité d'achat "référence" par produit.

    Comme Produit n'a pas d'unité d'achat, on la récupère depuis ProduitFournisseur.
    Heuristique: on prend la première entrée (stable, mais déterminisme acceptable).
    """

    res = await session.execute(select(ProduitFournisseur))
    rows = res.scalars().all()
    out: dict[str, str] = {}
    for pf in rows:
        pid = str(pf.produit_id)
        if pid not in out and pf.unite_achat:
            out[pid] = pf.unite_achat
    return out


async def run(*, apply: bool, force: bool) -> int:
    url_db = os.getenv("DATABASE_URL") or parametres_application.url_base_donnees
    engine = create_async_engine(url_db, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    stats = MappingStats()
    ambiguous_logs: list[str] = []
    not_found_logs: list[str] = []
    suggestions: dict[str, list[str]] = {}

    async with session_maker() as session:
        ingredients = (await session.execute(select(Ingredient).order_by(Ingredient.nom))).scalars().all()
        produits = (await session.execute(select(Produit).order_by(Produit.libelle))).scalars().all()
        unite_achat_par_produit = await _load_reference_unite_achat_par_produit(session)

        stats.total = len(ingredients)
        produits_par_norm: dict[str, Produit] = {}
        # attention: Produit.libelle est unique => on peut indexer
        for p in produits:
            produits_par_norm[_norm(p.libelle)] = p

        for ing in ingredients:
            # ne jamais écraser un mapping déjà rempli (sauf --force)
            # Compat: certains schémas peuvent ne pas avoir (encore) le champ ingredient.produit_id.
            # Dans ce cas, on ne peut pas faire le mapping.
            if not hasattr(ing, "produit_id"):
                continue

            if ing.produit_id is not None and not force:
                stats.skipped_existing += 1
                continue

            ing_nom = ing.nom
            ni = _norm(ing_nom)
            if not ni:
                stats.not_found += 1
                not_found_logs.append(f"[not_found] ingredient_id={ing.id} nom={ing_nom!r} (nom vide après normalisation)")
                continue

            # a) exact match normalisé
            exact = produits_par_norm.get(ni)
            if exact is not None:
                chosen = exact
                score = 1.0
                candidates = [(exact, 1.0)]
            else:
                # b) fuzzy simple
                candidates = _fuzzy_candidates(ing_nom, produits)
                if not candidates:
                    stats.not_found += 1
                    not_found_logs.append(f"[not_found] ingredient_id={ing.id} nom={ing_nom!r}")
                    # suggestions: top 3 avec token overlap même faible
                    sug = []
                    # On récupère des scores plus faibles pour aider au debug
                    weak = []
                    for p in produits:
                        sc = _token_overlap_score(ing_nom, p.libelle)
                        if sc > 0:
                            weak.append((p, sc))
                    weak.sort(key=lambda x: x[1], reverse=True)
                    for p, sc in weak[:3]:
                        sug.append(f"{p.libelle} (score={sc:.2f})")
                    if sug:
                        suggestions[ing_nom] = sug
                    continue

                chosen, score = candidates[0]

                # c) ambiguïté : si plusieurs candidats avec score similaire et suffisamment haut
                # On considère ambigu si:
                # - top score >= 0.75
                # - et au moins 2 candidats dans un delta de 0.05
                top = score
                close = [c for c in candidates[:5] if (top - c[1]) <= 0.05 and c[1] >= 0.75]
                if len(close) >= 2:
                    stats.ambiguous += 1
                    libs = ", ".join([f"{p.libelle}({s:.2f})" for p, s in close])
                    ambiguous_logs.append(f"[ambiguous] ingredient_id={ing.id} nom={ing_nom!r} candidates={libs}")
                    continue

            # mise à jour champs (idempotent)
            ing.produit_id = chosen.id

            # unite_consommation / facteur_conversion
            # On dérive depuis l'unité d'achat (via produit_fournisseur) quand possible.
            unite_achat = unite_achat_par_produit.get(str(chosen.id))
            conv = _conversion_depuis_unite_achat(unite_achat)

            # règle: viande/charcut => unité conso par défaut "g" si pas connu
            if getattr(ing, "unite_consommation", None) is None:
                if conv is not None:
                    ing.unite_consommation = conv.unite_consommation
                elif _is_viande_charcut(ing_nom):
                    ing.unite_consommation = "g"

            if getattr(ing, "facteur_conversion", None) is None and conv is not None and hasattr(ing, "facteur_conversion"):
                ing.facteur_conversion = float(conv.facteur_conversion)

            stats.mapped += 1

        if apply:
            await session.commit()
        else:
            await session.rollback()

    await engine.dispose()

    # Rapport
    print("\n=================== RAPPORT MAPPING INGREDIENT -> PRODUIT ===================")
    print(f"total_ingredients     = {stats.total}")
    print(f"mapped                = {stats.mapped}")
    print(f"skipped_existing       = {stats.skipped_existing}")
    print(f"ambiguous             = {stats.ambiguous}")
    print(f"not_found             = {stats.not_found}")
    print(f"mode                  = {'APPLY' if apply else 'DRY-RUN'}")
    print("=============================================================================\n")

    if ambiguous_logs:
        print("-- AMBIGUS (top 50) --")
        for line in ambiguous_logs[:50]:
            print(line)
        print()

    if not_found_logs:
        print("-- NON TROUVÉS (top 20) --")
        for line in not_found_logs[:20]:
            print(line)
        print()

    if suggestions:
        print("-- SUGGESTIONS (top 20 non trouvés) --")
        for ing_nom in list(suggestions.keys())[:20]:
            print(f"[suggest] {ing_nom!r} -> {suggestions[ing_nom]}")
        print()

    # code retour utile en CI
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Map ingredients to produits (catalogue)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Ne commit rien en base")
    g.add_argument("--apply", action="store_true", help="Commit les modifications en base")
    p.add_argument("--force", action="store_true", help="Autorise l'écrasement d'un mapping existant")
    return p


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(run(apply=bool(args.apply), force=bool(args.force)))


if __name__ == "__main__":
    main()
