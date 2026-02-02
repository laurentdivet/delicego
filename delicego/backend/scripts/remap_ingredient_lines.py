from __future__ import annotations

"""Remap des lignes de recettes importées (staging) via aliases.

But:
- Appeler le service existant `remap_lignes_recette_importees`.
- Exposer un wrapper CLI déterministe et explicite (dry-run par défaut).

CLI:
    # dry-run (aucun commit)
    python -m scripts.remap_ingredient_lines --limit 1000

    # applique et commit
    python -m scripts.remap_ingredient_lines --limit 1000 --apply
"""

import argparse
import asyncio
import logging

from sqlalchemy import func, select

from app.core.base_donnees import fournir_session_async
from app.domaine.modeles.referentiel import LigneRecetteImportee
from app.domaine.services.remap_lignes_recette_importees import remap_lignes_recette_importees


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Remap lignes_recette_importee (staging) via IngredientAlias")
    p.add_argument("--limit", type=int, default=1000, help="Nombre max de lignes candidates traitées (default: 1000)")
    p.add_argument(
        "--apply",
        action="store_true",
        help="Commit les changements. Sans --apply: dry-run (rollback explicite)",
    )
    return p


async def _count_unmapped(session) -> int:
    res = await session.execute(
        select(func.count()).select_from(LigneRecetteImportee).where(LigneRecetteImportee.statut_mapping == "unmapped")
    )
    return int(res.scalar_one())


async def run(*, limit: int, apply: bool) -> int:
    if limit <= 0:
        raise ValueError("--limit doit être > 0")

    async for session in fournir_session_async():
        unmapped_before = await _count_unmapped(session)

        stats = await remap_lignes_recette_importees(session, limit=limit)

        # Le service rebuild une fois par recette_id touchée, donc le nombre de recettes
        # correspond au nombre de rows remappées au maximum (borne haute).
        # Pour un rapport déterministe sans nouvelle logique métier, on repart de remappes.
        recettes_rebuild = stats.remappes  # borne haute / indicateur (voir docstring)

        unmapped_after = await _count_unmapped(session)

        # Rapport
        print("=== remap_ingredient_lines ===")
        print(f"mode={'APPLY' if apply else 'DRY-RUN'}")
        print(f"limit={limit}")
        print(f"lignes_candidates={stats.candidats}")
        print(f"lignes_remappees={stats.remappes}")
        print(f"recettes_rebuild~={recettes_rebuild}")
        print(f"lignes_restantes_unmapped={unmapped_after}")
        print(f"delta_unmapped={unmapped_after - unmapped_before} (attendu <= 0)")

        if apply:
            await session.commit()
            logger.info("commit_done")
        else:
            # rollback explicite pour garantir le dry-run
            await session.rollback()
            logger.info("dry_run_rollback_done")

        return 0

    # fournir_session_async devrait toujours yield une session; garde-fou.
    raise RuntimeError("Impossible d'ouvrir une session DB")


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(run(limit=args.limit, apply=args.apply))


if __name__ == "__main__":
    main()
