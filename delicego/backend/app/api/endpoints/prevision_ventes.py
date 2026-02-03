from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.prevision_ventes import PredictionVenteOut, ReponsePrevisionVentes
from app.services.prevision_ventes_service import PrevisionVentesService


routeur_prevision_ventes_interne = APIRouter(
    prefix="/previsions",
    tags=["previsions_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_prevision_ventes_interne.get("/ventes", response_model=ReponsePrevisionVentes)
async def prevision_ventes(
    date_cible: date,
    magasin_id: UUID | None = None,
    horizon: int | None = None,
    session: AsyncSession = Depends(fournir_session),
) -> ReponsePrevisionVentes:
    """Prévisions ventes.

    Décision produit :
    - Prévisions API = `prediction_vente` (pipeline ML)
    - `LignePrevision` = planification interne historique (concept différent)

    Granularité: la prévision est au niveau **MENU** (`menu_id`) (et non produit/SKU).

    Exemples:

    curl -H "X-CLE-INTERNE: $CLE" \
      "http://localhost:8000/api/interne/previsions/ventes?date_cible=2026-02-02"

    curl -H "X-CLE-INTERNE: $CLE" \
      "http://localhost:8000/api/interne/previsions/ventes?date_cible=2026-02-02&magasin_id=<uuid>&horizon=7"
    """

    svc = PrevisionVentesService(session)
    preds = await svc.lire_predictions(date_cible=date_cible, magasin_id=magasin_id, horizon=horizon)

    # Format stable (pas de "prévu vs réel" ici) : la prévision = output ML.
    # Bonus éventuel : comparaison au réel peut être ajoutée plus tard sans casser ce contrat.
    return ReponsePrevisionVentes(
        date_cible=date_cible,
        predictions=[
            PredictionVenteOut(
                magasin_id=str(p.magasin_id),
                menu_id=str(p.menu_id),
                quantite_predite=float(p.qte_predite),
                source=p.source,
            )
            for p in preds
        ],
    )
