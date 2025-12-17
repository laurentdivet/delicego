from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.production_reelle import ReponseBesoins, ReponsePlanReel, RequetePlanReel
from app.domaine.services.production_reelle import ErreurProductionReelle, ServiceProductionReelle


routeur_production_reelle_interne = APIRouter(
    prefix="/production",
    tags=["production_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_production_reelle_interne.post(
    "/plan-reel",
    response_model=ReponsePlanReel,
    status_code=status.HTTP_201_CREATED,
)
async def creer_plan_reel(
    requete: RequetePlanReel,
    session: AsyncSession = Depends(fournir_session),
) -> ReponsePlanReel:
    service = ServiceProductionReelle(session)

    try:
        plan = await service.generer_plan_production(
            magasin_id=requete.magasin_id,
            date_plan=requete.date_plan,
            fenetre_jours=requete.fenetre_jours,
            donnees_meteo=requete.donnees_meteo,
            evenements=requete.evenements,
        )
    except ErreurProductionReelle as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur inattendue pendant la génération du plan réel : {e}",
        ) from e

    return ReponsePlanReel(plan_production_id=plan.id)


@routeur_production_reelle_interne.get(
    "/besoins",
    response_model=ReponseBesoins,
)
async def lire_besoins(
    plan_production_id: str,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseBesoins:
    service = ServiceProductionReelle(session)

    try:
        from uuid import UUID

        plan_id = UUID(plan_production_id)
        besoins = await service.calculer_besoins_ingredients(plan_id=plan_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="plan_production_id invalide") from e
    except ErreurProductionReelle as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return ReponseBesoins(
        plan_production_id=plan_id,
        besoins=[
            {
                "ingredient_id": b.ingredient_id,
                "ingredient_nom": b.ingredient_nom,
                "quantite": b.quantite,
                "unite": b.unite,
            }
            for b in besoins
        ],
    )
