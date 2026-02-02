from __future__ import annotations

"""Export d'un résumé agrégé des ingrédients non mappés.

But:
- Lire `ligne_recette_importee` (statut_mapping='unmapped')
- Agréger par `ingredient_normalise`
- Sortie CSV triée par occurences DESC

CLI:
    python -m scripts.export_ingredient_unmapped_summary --apply

Note: lecture DB uniquement (aucune écriture).
"""

import argparse
import asyncio
import csv
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.modeles.referentiel import LigneRecetteImportee


OUT_PATH = Path(__file__).with_name("ingredient_unmapped_summary.csv")


@dataclass
class Agg:
    occurences: int = 0
    recettes_ids: set[str] = None
    exemples: list[str] = None

    def __post_init__(self) -> None:
        self.recettes_ids = set()
        self.exemples = []


async def run(*, apply: bool) -> int:
    # option apply pour uniformiser avec les autres scripts; ici: pas d'écriture DB.
    url_db = os.getenv("DATABASE_URL") or parametres_application.url_base_donnees
    engine = create_async_engine(url_db, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    agg: dict[str, Agg] = defaultdict(Agg)

    async with Session() as session:
        res = await session.execute(
            select(
                LigneRecetteImportee.ingredient_normalise,
                LigneRecetteImportee.ingredient_brut,
                LigneRecetteImportee.recette_id,
            ).where(LigneRecetteImportee.statut_mapping == "unmapped")
        )

        for ing_norm, ing_brut, recette_id in res.all():
            key = (ing_norm or "").strip()
            if not key:
                continue

            a = agg[key]
            a.occurences += 1
            a.recettes_ids.add(str(recette_id))

            brut = (ing_brut or "").strip()
            if brut and brut not in a.exemples and len(a.exemples) < 3:
                a.exemples.append(brut)

    await engine.dispose()

    rows = []
    for ing_norm, a in agg.items():
        rows.append(
            (
                ing_norm,
                " | ".join(a.exemples),
                a.occurences,
                len(a.recettes_ids),
            )
        )
    rows.sort(key=lambda r: r[2], reverse=True)

    with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ingredient_normalise", "ingredient_brut_exemples", "occurences", "recettes_count"])
        for r in rows:
            w.writerow(list(r))

    print(f"CSV généré: {OUT_PATH}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Export résumé ingrédients non mappés (staging)")
    # flag apply requis par le ticket, même si le script est read-only
    p.add_argument("--apply", action="store_true", help="(read-only) exécute l'export")
    return p


def main() -> None:
    args = build_parser().parse_args()
    if not args.apply:
        raise SystemExit("Utiliser --apply pour lancer l'export (aucune écriture DB).")
    asyncio.run(run(apply=True))


if __name__ == "__main__":
    main()
