from __future__ import annotations

"""Import recettes depuis PDF (Janvier 2025).

OBJECTIF UNIQUE:
- Parser des PDF fournis (ex: "1_BOOK Janvier 2025.pdf", "3_WOK Janvier 2025.pdf")
- Détecter les recettes (titre en MAJUSCULES + section "COMPOSITION")
- Importer en base:
  - Recette (clé logique = nom + source)
  - Lignes de recette (ingrédient, quantité, unite='g')

Contraintes:
- Idempotent: si recette existe déjà (même nom+source), on supprime ses lignes puis on recrée.
- Ne jamais supprimer un ingrédient.
- Mapping ingredient -> produit: exact normalisé, sinon fuzzy simple non ambigu, sinon NULL.

CLI:
    python -m scripts.import_recettes_from_pdfs --pdf "../1_BOOK Janvier 2025.pdf" --pdf "../3_WOK Janvier 2025.pdf" --dry-run
    python -m scripts.import_recettes_from_pdfs --pdf "../1_BOOK Janvier 2025.pdf" --pdf "../3_WOK Janvier 2025.pdf" --apply
"""

import argparse
import logging
import asyncio
import os
import re
import unicodedata
import json
import csv
from dataclasses import dataclass
from pathlib import Path
from collections import Counter

logger = logging.getLogger(__name__)

import pdfplumber
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.dialects.postgresql import insert

from app.core.configuration import parametres_application
from app.domaine.modeles.referentiel import Ingredient, LigneRecette, LigneRecetteImportee, Recette
from app.domaine.services.ingredient_matching import (
    build_ingredient_normalized_index,
    match_ingredient_id_with_index,
    normalize_ingredient_label,
)


SOURCE = "janvier_2025"

RAPPORT_CSV_PATH = Path(__file__).with_name("rapport_mapping_ingredients.csv")
NON_MAPPES_CSV_PATH = Path(__file__).with_name("ingredients_non_mappes.csv")


def _norm(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _norm_key(s: str) -> str:
    """Normalisation agressive pour matching (sans accents, upper, espaces)."""

    s = _norm(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_title(line: str) -> bool:
    """Titre = ligne en MAJUSCULES, plutôt courte, pas un label type DLC/POIDS."""

    s = _norm(line)
    if not s:
        return False
    if len(s) < 4 or len(s) > 80:
        return False
    up = _norm_key(s)
    # exclure ces marqueurs
    banned = ["COMPOSITION", "POIDS NET", "POIDS BRUT", "EMBALLAGE", "DLC", "INGREDIENTS", "COMPO"]
    if any(b in up for b in banned):
        return False
    # au moins 70% de lettres (évite "POIDS NET1311")
    letters = sum(ch.isalpha() for ch in s)
    ratio = letters / max(1, len(s))
    if ratio < 0.55:
        return False
    # doit être "uppercase" (tolère accents)
    return s == s.upper()


STOP_MARKERS = [
    "POIDS NET",
    "EMBALLAGE",
    "DLC",
]


def _is_stop(line: str) -> bool:
    up = _norm_key(line)
    return any(_norm_key(m) in up for m in STOP_MARKERS)


_RE_ING_LINE = re.compile(r"^(?P<name>.+?)\s+(?P<q1>\d+(?:[\.,]\d+)?)\s*(?P<q2>\d+(?:[\.,]\d+)?)?\s*$")


def _parse_ingredient_line(line: str) -> tuple[str, float] | None:
    """Parse une ligne de composition "INGREDIENT 150" ou "INGREDIENT 60 2".

    Règle : on prend la 1ère quantité (grammes). Si 2ème nombre, on l'ignore.
    """

    s = _norm(line)
    if not s:
        return None
    # écarter lignes manifestement non ingrédients
    if _is_stop(s):
        return None
    up = _norm_key(s)
    if up.startswith("TOTAL"):
        return None
    m = _RE_ING_LINE.match(s)
    if not m:
        return None
    name = _norm(m.group("name"))
    q1 = m.group("q1").replace(",", ".")
    try:
        q = float(q1)
    except ValueError:
        return None
    if not name:
        return None
    return name, q


@dataclass
class ParsedRecette:
    nom: str
    source: str
    ingredients: list[tuple[str, float]]


def parse_pdf(pdf_path: str, *, source: str) -> list[ParsedRecette]:
    """Parse un PDF en une liste de recettes."""

    recettes: list[ParsedRecette] = []
    current_title: str | None = None
    in_composition = False
    buffer: list[tuple[str, float]] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = [l for l in text.splitlines()]
            for raw in lines:
                line = _norm(raw)
                if not line:
                    continue

                # Start composition section
                if "COMPOSITION" in _norm_key(line):
                    in_composition = True
                    continue

                # New title ends previous recipe
                if _is_title(line):
                    # flush previous if any
                    if current_title and buffer:
                        recettes.append(ParsedRecette(nom=current_title, source=source, ingredients=buffer))
                    current_title = line
                    buffer = []
                    in_composition = False
                    continue

                if not in_composition:
                    continue

                if _is_stop(line):
                    in_composition = False
                    continue

                parsed = _parse_ingredient_line(line)
                if parsed:
                    buffer.append(parsed)

    if current_title and buffer:
        recettes.append(ParsedRecette(nom=current_title, source=source, ingredients=buffer))

    # dédoublonnage simple (certains PDF répètent des recettes)
    unique: dict[str, ParsedRecette] = {}
    for r in recettes:
        key = f"{_norm_key(r.nom)}::{r.source}"
        if key not in unique:
            unique[key] = r
        else:
            # conserve la version la plus "riche"
            if len(r.ingredients) > len(unique[key].ingredients):
                unique[key] = r
    return list(unique.values())


async def _get_or_create_ingredient(session: AsyncSession, *, nom: str) -> tuple[Ingredient, bool]:
    nom = _norm(nom)
    res = await session.execute(select(Ingredient).where(Ingredient.nom == nom))
    ing = res.scalar_one_or_none()
    if ing is None:
        # Contrainte forte (voir ticket): ne jamais créer automatiquement d'ingrédient.
        raise RuntimeError(
            "Ingrédient manquant en table `ingredient`. "
            "Créer un alias (ingredient_alias) ou valider manuellement avant import."
        )
    else:
        ing.actif = True
        return ing, False


async def upsert_recette(
    session: AsyncSession,
    *,
    parsed: ParsedRecette,
    apply: bool,
    stats,
    pdf_path: str,
    ingredient_index,
) -> None:
    nom_db = f"{parsed.nom} ({parsed.source})"

    # En dry-run, on NE crée rien en base.
    if not apply:
        stats.recettes_dryrun += 1
        stats.lignes_prevues += len(parsed.ingredients)

        for ing_nom, q in parsed.ingredients:
            stats.rapport_rows.append((ing_nom, nom_db, float(q), None))
        return

    res = await session.execute(select(Recette).where(Recette.nom == nom_db))
    recette = res.scalar_one_or_none()
    if recette is None:
        recette = Recette(nom=nom_db)
        session.add(recette)
        await session.flush()
        stats.recettes_creees += 1
    else:
        stats.recettes_maj += 1

    # Idempotence:
    # - On ne supprime PAS l'historique d'import PDF (ligne_recette_importee)
    # - On remplace les lignes "résolues" (ligne_recette) de la recette
    await session.execute(delete(LigneRecette).where(LigneRecette.recette_id == recette.id))

    aggregated: dict[tuple[object, str], float] = {}

    for ordre, (ing_nom, q) in enumerate(parsed.ingredients):
        match = await match_ingredient_id_with_index(
            session,
            label_brut=ing_nom,
            ingredient_index=ingredient_index,
        )
        ingredient_normalise = match.normalized_label

        # 1) On conserve TOUJOURS la ligne PDF en base (staging)
        pdf_name = Path(pdf_path).name
        statut_mapping = "mapped" if match.ingredient_id is not None else "unmapped"

        # UPSERT staging (idempotent) via contrainte UNIQUE(recette_id, pdf, ordre)
        stmt = (
            insert(LigneRecetteImportee)
            .values(
                id=uuid4(),
                recette_id=recette.id,
                pdf=pdf_name,
                ordre=int(ordre),
                ingredient_brut=ing_nom,
                ingredient_normalise=ingredient_normalise,
                quantite=float(q),
                unite="g",
                ingredient_id=match.ingredient_id,
                statut_mapping=statut_mapping,
            )
            .on_conflict_do_update(
                constraint="uq_ligne_recette_importee_recette_pdf_ordre",
                set_={
                    "ingredient_brut": ing_nom,
                    "ingredient_normalise": ingredient_normalise,
                    "quantite": float(q),
                    "unite": "g",
                    "ingredient_id": match.ingredient_id,
                    "statut_mapping": statut_mapping,
                    # mis_a_jour_le géré par application (ModeleHorodate)
                },
            )
        )
        await session.execute(stmt)

        # Stocker libellés brut + normalisé (dans le CSV non mappés).
        # Hypothèse: aucune table "ligne_recette_pdf" n'existe actuellement.
        # On conserve donc l'info au niveau fichier d'export (exigence du ticket).
        if match.ingredient_id is None:
            stats.ingredients_non_mappes += 1
            continue

        stats.ingredients_mappes += 1
        key = (match.ingredient_id, "g")
        aggregated[key] = aggregated.get(key, 0.0) + float(q)

    # Insertion agrégée dans ligne_recette (compatible avec uq(recette_id, ingredient_id))
    for (ingredient_id, unite), quantite in aggregated.items():
        session.add(
            LigneRecette(
                recette_id=recette.id,
                ingredient_id=ingredient_id,
                quantite=float(quantite),
                unite=unite,
            )
        )
        stats.lignes_creees += 1


@dataclass
class RunStats:
    recettes_detectees: int = 0
    recettes_creees: int = 0
    recettes_maj: int = 0
    recettes_dryrun: int = 0
    ingredients_crees: int = 0
    lignes_creees: int = 0
    lignes_prevues: int = 0
    ingredients_mappes: int = 0
    ingredients_non_mappes: int = 0
    ingredients_remappes: int = 0

    rapport_rows: list[tuple[str, str, float, str | None]] = None

    non_mappes_rows: list[tuple[str, str, str, str, float, str, int]] = None

    _ingredients_seen: set = None

    def __post_init__(self):
        self._ingredients_seen = set()
        self.rapport_rows = []
        self.non_mappes_rows = []


@dataclass(frozen=True)
class IngredientImportRow:
    pdf: str
    recette: str
    ingredient_brut: str
    ingredient_normalise: str
    quantite: float
    unite: str



async def run(*, pdfs: list[str], apply: bool, remap_existing: bool = False) -> int:
    url_db = os.getenv("DATABASE_URL") or parametres_application.url_base_donnees
    engine = create_async_engine(url_db, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    stats = RunStats()

    # Parse
    async with Session() as session:
        ingredient_index = await build_ingredient_normalized_index(session)
        before_ing = (await session.execute(select(func.count()).select_from(Ingredient))).scalar_one()

        # Parse + import (on garde le nom du PDF pour l'export non mappés)
        parsed_all: list[tuple[str, ParsedRecette]] = []
        for pdf in pdfs:
            for pr in parse_pdf(pdf, source=SOURCE):
                parsed_all.append((pdf, pr))

        stats.recettes_detectees = len(parsed_all)

        for pdf_path, pr in sorted(parsed_all, key=lambda t: _norm_key(t[1].nom)):
            await upsert_recette(
                session,
                parsed=pr,
                apply=apply,
                stats=stats,
                pdf_path=pdf_path,
                ingredient_index=ingredient_index,
            )

        if apply:
            await session.commit()

            after_ing = (await session.execute(select(func.count()).select_from(Ingredient))).scalar_one()
            stats.ingredients_crees = max(0, int(after_ing) - int(before_ing))
        else:
            await session.rollback()

    await engine.dispose()

    print("=================== RAPPORT IMPORT RECETTES PDF ===================")
    print(f"pdfs                 = {len(pdfs)}")
    print(f"recettes_detectees    = {stats.recettes_detectees}")
    if not apply:
        print(f"recettes_dryrun       = {stats.recettes_dryrun}")
        print(f"lignes_prevues        = {stats.lignes_prevues}")
    print(f"recettes_creees       = {stats.recettes_creees}")
    print(f"recettes_mises_a_jour = {stats.recettes_maj}")
    print(f"ingredients_crees     = {stats.ingredients_crees}")
    print(f"lignes_recette_creees = {stats.lignes_creees}")
    print(f"ingredients_mappes    = {stats.ingredients_mappes}")
    print(f"ingredients_non_mappes= {stats.ingredients_non_mappes}")
    print(f"ingredients_remappes  = {stats.ingredients_remappes}")
    print("===================================================================")

    # Rapport CSV (toujours)
    with RAPPORT_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ingredient_nom", "recette_nom", "quantite", "produit_mapped"])
        for ing_nom, rec_nom, q, prod_lib in stats.rapport_rows:
            w.writerow([ing_nom, rec_nom, q, prod_lib if prod_lib is not None else "NULL"])

    # Export non mappés agrégé (basé sur la DB)
    async with Session() as session:
        res = await session.execute(
            select(
                LigneRecetteImportee.pdf,
                Recette.nom,
                LigneRecetteImportee.ingredient_brut,
                LigneRecetteImportee.ingredient_normalise,
                LigneRecetteImportee.quantite,
                LigneRecetteImportee.unite,
            ).join(Recette, Recette.id == LigneRecetteImportee.recette_id)
            .where(LigneRecetteImportee.statut_mapping == "unmapped")
        )
        counter: Counter[tuple[str, str, str, str, float, str]] = Counter()
        for pdf, recette_nom, brut, normed, q, unite in res.all():
            counter[(pdf, recette_nom, brut, normed, float(q), unite)] += 1

    with NON_MAPPES_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pdf", "recette", "ingredient_brut", "ingredient_normalise", "quantite", "unite", "occurences"])
        for (pdf, recette, brut, normed, q, unite), occ in sorted(counter.items()):
            w.writerow([pdf, recette, brut, normed, q, unite, occ])

    return 0


def build_parser() -> argparse.ArgumentParser:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s",
    )
    p = argparse.ArgumentParser(description="Import recettes depuis PDFs")
    p.add_argument("--pdf", action="append", required=True, help="Chemin PDF (répétable)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    return p


def main() -> None:
    args = build_parser().parse_args()

    logger.info(
        "import_recettes_from_pdfs_start nb_pdfs=%s dry_run=%s",
        len(args.pdf),
        bool(args.dry_run),
    )
    pdfs = [str(Path(p).expanduser()) for p in args.pdf]
    asyncio.run(run(pdfs=pdfs, apply=bool(args.apply)))


if __name__ == "__main__":
    main()
