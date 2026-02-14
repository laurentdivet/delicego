from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.ingredients import IngredientOutEnrichi
from app.domaine.modeles.referentiel import Ingredient


routeur_ingredients_interne = APIRouter(
    prefix="/ingredients",
    tags=["ingredients_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_ingredients_interne.get("", response_model=list[IngredientOutEnrichi])
async def lister_ingredients(
    session: AsyncSession = Depends(fournir_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str | None = Query(default=None, min_length=1),
    has_produit: bool | None = Query(default=None),
) -> list[IngredientOutEnrichi]:
    filtres = []
    if q:
        filtres.append(Ingredient.nom.ilike(f"%{q}%"))
    # NOTE: le champ `Ingredient.produit_id` peut ne pas exister selon la version
    # du modèle / migrations. On garde une API stable: si non supporté, on refuse
    # explicitement plutôt que de planter en 500.
    if has_produit is not None and not hasattr(Ingredient, "produit_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filtre has_produit non supporté: aucun lien Ingredient -> Produit n'est défini.",
        )
    if has_produit is True:
        filtres.append(Ingredient.produit_id.is_not(None))
    if has_produit is False:
        filtres.append(Ingredient.produit_id.is_(None))

    stmt = (
        select(Ingredient)
        .options(selectinload(Ingredient.produit) if hasattr(Ingredient, "produit") else ())
        .order_by(Ingredient.nom.asc())
        .limit(limit)
        .offset(offset)
    )
    if filtres:
        stmt = stmt.where(and_(*filtres))

    res = await session.execute(stmt)
    return list(res.scalars().unique().all())


@routeur_ingredients_interne.get("/{ingredient_id}", response_model=IngredientOutEnrichi)
async def get_ingredient(
    ingredient_id: UUID,
    session: AsyncSession = Depends(fournir_session),
) -> IngredientOutEnrichi:
    stmt = select(Ingredient).where(Ingredient.id == ingredient_id).options(selectinload(Ingredient.produit))
    ing = (await session.execute(stmt)).scalar_one_or_none()
    if ing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingrédient introuvable.")
    return ing
