from __future__ import annotations

from dataclasses import dataclass
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles.referentiel import IngredientAlias, LigneRecette, LigneRecetteImportee


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemapStats:
    candidats: int
    remappes: int


async def remap_lignes_recette_importees(session: AsyncSession, *, limit: int = 1000) -> RemapStats:
    """Tente de remapper des lignes importées non mappées.

    - Ne crée jamais d'ingrédient
    - Ne modifie rien si introuvable
    - Ne modifie rien si ambigu (normalement impossible si contrainte d'unicité sur alias_normalise)

    IMPORTANT: cette fonction est utilitaire et n'est pas appelée automatiquement.
    """

    logger.info("remap_start limit=%s", limit)

    res = await session.execute(
        select(LigneRecetteImportee)
        .where(LigneRecetteImportee.statut_mapping == "unmapped")
        .limit(limit)
    )
    rows = res.scalars().all()

    remappes = 0
    recettes_a_rebuild: set = set()
    for row in rows:
        res_alias = await session.execute(
            select(IngredientAlias).where(
                IngredientAlias.alias_normalise == row.ingredient_normalise,
                IngredientAlias.actif.is_(True),
            )
        )
        alias = res_alias.scalar_one_or_none()
        if alias is None:
            continue

        row.ingredient_id = alias.ingredient_id
        row.statut_mapping = "mapped"

        recettes_a_rebuild.add(row.recette_id)

        remappes += 1

    logger.info("remap_done candidats=%s remappes=%s nb_recettes=%s", len(rows), remappes, len(recettes_a_rebuild))

    # Rebuild "résolu" par recette, depuis le staging mappé (agrégation explicite)
    for recette_id in recettes_a_rebuild:
        await _rebuild_ligne_recette_from_staging(session, recette_id=recette_id)

    return RemapStats(candidats=len(rows), remappes=remappes)


async def _rebuild_ligne_recette_from_staging(session: AsyncSession, *, recette_id) -> None:
    await session.execute(delete(LigneRecette).where(LigneRecette.recette_id == recette_id))

    res = await session.execute(
        select(
            LigneRecetteImportee.ingredient_id,
            LigneRecetteImportee.unite,
            LigneRecetteImportee.quantite,
        ).where(
            LigneRecetteImportee.recette_id == recette_id,
            LigneRecetteImportee.statut_mapping == "mapped",
            LigneRecetteImportee.ingredient_id.is_not(None),
        )
    )

    aggregated: dict[tuple[object, str], float] = {}
    for ingredient_id, unite, quantite in res.all():
        key = (ingredient_id, unite)
        aggregated[key] = aggregated.get(key, 0.0) + float(quantite)

    for (ingredient_id, unite), quantite in aggregated.items():
        session.add(
            LigneRecette(
                recette_id=recette_id,
                ingredient_id=ingredient_id,
                quantite=float(quantite),
                unite=unite,
            )
        )
