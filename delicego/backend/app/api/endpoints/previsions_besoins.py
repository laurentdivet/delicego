from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.previsions_besoins import BesoinIngredientPrevuOut, ReponseBesoinsIngredientsPrevus
from app.services.previsions_besoins_service import PrevisionsBesoinsService


routeur_previsions_besoins_interne = APIRouter(
    prefix="/previsions",
    tags=["previsions_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_previsions_besoins_interne.get("/besoins", response_model=ReponseBesoinsIngredientsPrevus)
async def previsions_besoins_ingredients(
    magasin_id: UUID,
    date_debut: date,
    date_fin: date,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseBesoinsIngredientsPrevus:
    svc = PrevisionsBesoinsService(session)
    besoins = await svc.calculer_besoins(magasin_id=magasin_id, date_debut=date_debut, date_fin=date_fin)

    return ReponseBesoinsIngredientsPrevus(
        magasin_id=str(magasin_id),
        date_debut=date_debut,
        date_fin=date_fin,
        besoins=[
            BesoinIngredientPrevuOut(
                date_jour=b.date_jour,
                ingredient_id=str(b.ingredient_id),
                ingredient_nom=b.ingredient_nom,
                unite=b.unite,
                quantite=float(b.quantite),
            )
            for b in besoins
        ],
    )
