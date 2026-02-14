from __future__ import annotations

"""Backfill `produit_id` dans les tables stock (Phase B).

Idempotent et safe :
- par défaut, ne remplit que si `produit_id IS NULL`
- `--force` permet d'écraser un `produit_id` existant
- `--dry-run` n'écrit rien

Règle de mapping:
- table.*.ingredient_id -> ingredient.produit_id
"""

import argparse
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_donnees import creer_moteur_async


TABLES = [
    "lot",
    "mouvement_stock",
]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Backfill produit_id (stock) depuis ingredient.produit_id")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Ne commit rien, affiche seulement le rapport")
    mode.add_argument("--apply", action="store_true", help="Applique (commit)")

    p.add_argument("--force", action="store_true", help="Écrase produit_id même s'il est déjà renseigné")
    p.add_argument("--tables", nargs="*", default=None, help="Liste de tables à backfiller (défaut: lot + mouvement_stock)")
    return p


async def _backfill_table(*, session: AsyncSession, table: str, force: bool) -> tuple[int, int, int]:
    """Retourne (candidats, backfill, impossibles)."""

    # En environnement de tests (schema créé via metadata.create_all) ou si les migrations
    # n'ont pas été appliquées, la colonne produit_id peut ne pas exister.
    # On rend la fonction "no-op" plutôt que de planter.
    try:
        await session.execute(text(f"SELECT t.produit_id FROM {table} t WHERE 1=0"))
    except Exception:
        return 0, 0, 0

    # candidats: lignes avec ingredient_id présent, et produit_id NULL si pas force
    where_pf = "" if force else "AND t.produit_id IS NULL"
    candidats = (
        await session.execute(
            text(
                f"""
                SELECT count(*)
                FROM {table} t
                WHERE t.ingredient_id IS NOT NULL
                {where_pf}
                """
            )
        )
    ).scalar_one()

    # impossibles: candidats dont ingredient.produit_id est NULL
    impossibles = (
        await session.execute(
            text(
                f"""
                SELECT count(*)
                FROM {table} t
                JOIN ingredient i ON i.id = t.ingredient_id
                WHERE t.ingredient_id IS NOT NULL
                {where_pf}
                  AND i.produit_id IS NULL
                """
            )
        )
    ).scalar_one()

    # update: seulement quand ingredient.produit_id NOT NULL
    res = await session.execute(
        text(
            f"""
            UPDATE {table} t
            SET produit_id = i.produit_id
            FROM ingredient i
            WHERE i.id = t.ingredient_id
              AND i.produit_id IS NOT NULL
              {('' if force else 'AND t.produit_id IS NULL')}
            """
        )
    )
    backfill = int(res.rowcount or 0)
    return int(candidats or 0), int(backfill), int(impossibles or 0)


async def main() -> int:
    args = _parser().parse_args()
    tables = args.tables or TABLES

    # garde-fou
    for t in tables:
        if t not in TABLES:
            raise SystemExit(f"Table non supportée: {t}. Tables supportées: {', '.join(TABLES)}")

    moteur = creer_moteur_async()
    tot_cand = tot_bf = tot_imp = 0

    async with moteur.connect() as conn:
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            for t in tables:
                cand, bf, imp = await _backfill_table(session=session, table=t, force=bool(args.force))
                tot_cand += cand
                tot_bf += bf
                tot_imp += imp
                print(f"{t}: candidats={cand} backfill={bf} impossibles={imp}")

            if args.dry_run:
                await session.rollback()
                print("\nDRY-RUN: aucune écriture commitée")
            else:
                await session.commit()
                print("\nAPPLY: écritures commitées")
        finally:
            await session.close()
            await moteur.dispose()

    print(f"\nTOTAL: candidats={tot_cand} backfill={tot_bf} impossibles={tot_imp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
