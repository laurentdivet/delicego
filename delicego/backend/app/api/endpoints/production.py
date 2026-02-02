from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.dependances_auth import verifier_authentifie, verifier_roles_requis_legacy
from app.api.schemas.production import (
    ReponseExecutionProduction,
    ReponsePlanificationProduction,
    RequetePlanificationProduction,
)
from app.domaine.services.executer_production import (
    DonneesInvalidesProduction,
    ProductionDejaExecutee,
    ServiceExecutionProduction,
)
from app.domaine.services.planifier_production import (
    ErreurPlanificationProduction,
    PlanProductionDejaExistant,
    ServicePlanificationProduction,
)


routeur_production_interne = APIRouter(
    prefix="/production",
    tags=["production_interne"],
    dependencies=[
        Depends(verifier_acces_interne),
        Depends(verifier_authentifie),
        Depends(verifier_roles_requis_legacy("admin")),
    ],
)


@routeur_production_interne.post(
    "/planifier",
    response_model=ReponsePlanificationProduction,
    status_code=status.HTTP_201_CREATED,
)
async def planifier_production(
    requete: RequetePlanificationProduction,
    session: AsyncSession = Depends(fournir_session),
) -> ReponsePlanificationProduction:
    """Génère un plan de production (API interne).

    Endpoint technique :
    - Valide le payload (Pydantic)
    - Appelle uniquement le service métier
    - Traduit les exceptions métier en statuts HTTP

    Retour : l’identifiant du PlanProduction créé.
    """

    service = ServicePlanificationProduction(session)

    try:
        plan = await service.planifier(
            magasin_id=requete.magasin_id,
            date_plan=requete.date_plan,
            date_debut_historique=requete.date_debut_historique,
            date_fin_historique=requete.date_fin_historique,
            donnees_meteo=requete.donnees_meteo,
            evenements=requete.evenements,
        )
    except PlanProductionDejaExistant as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ErreurPlanificationProduction as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        # Pour l’API interne, on renvoie le message pour faciliter le diagnostic.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur inattendue pendant la planification : {e}",
        ) from e

    return ReponsePlanificationProduction(plan_production_id=plan.id)


@routeur_production_interne.post(
    "/{lot_production_id}/executer",
    response_model=ReponseExecutionProduction,
)
async def executer_production(
    lot_production_id: UUID,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseExecutionProduction:
    """Exécute une production (API interne).

    Endpoint technique :
    - Appelle uniquement le service métier d’exécution
    - Traduit les exceptions métier en statuts HTTP

    Retour : compte rendu (mouvements stock + lignes de consommation).
    """

    service = ServiceExecutionProduction(session)

    try:
        resultat = await service.executer(lot_production_id=lot_production_id)
    except ProductionDejaExecutee as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except DonneesInvalidesProduction as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur inattendue pendant l’exécution de production.",
        ) from e

    return ReponseExecutionProduction(
        lot_production_id=resultat.lot_production_id,
        nb_mouvements_stock=resultat.nb_mouvements_stock,
        nb_lignes_consommation=resultat.nb_lignes_consommation,
    )
