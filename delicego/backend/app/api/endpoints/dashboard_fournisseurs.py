from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.schemas.dashboard import ReponseDashboardFournisseursSchema
from app.services.dashboard_fournisseurs_service import DashboardFournisseursService

routeur_dashboard_fournisseurs_interne = APIRouter(
    prefix="/dashboard",
    tags=["dashboard_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_dashboard_fournisseurs_interne.get(
    "/fournisseurs",
    response_model=ReponseDashboardFournisseursSchema,
)
async def dashboard_fournisseurs(
    date_start: date | None = None,
    date_end: date | None = None,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseDashboardFournisseursSchema:
    service = DashboardFournisseursService(session)
    lignes = await service.lire(date_start=date_start, date_end=date_end)

    return ReponseDashboardFournisseursSchema(
        fournisseurs=[
            {
                "fournisseur_id": l.fournisseur_id,
                "fournisseur_nom": l.fournisseur_nom,
                "total_commandes": l.total_commandes,
                "total_montant_commande": l.total_montant_commande,
                "total_montant_recu": l.total_montant_recu,
                "taux_reception": l.taux_reception,
                "derniere_commande_date": l.derniere_commande_date,
            }
            for l in lignes
        ]
    )
