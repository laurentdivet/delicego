from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.previsions_alertes import (
    AlerteRupturePrevueOut,
    AlerteSurstockPrevuOut,
    ReponseAlertesStockPrevues,
)
from app.services.previsions_alertes_stock_service import PrevisionsAlertesStockService


routeur_previsions_alertes_interne = APIRouter(
    prefix="/previsions",
    tags=["previsions_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_previsions_alertes_interne.get("/alertes", response_model=ReponseAlertesStockPrevues)
async def previsions_alertes_stock(
    magasin_id: UUID,
    date_debut: date,
    date_fin: date,
    seuil_surstock_ratio: float = 2.0,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseAlertesStockPrevues:
    svc = PrevisionsAlertesStockService(session)
    ruptures, surstocks = await svc.calculer_alertes(
        magasin_id=magasin_id,
        date_debut=date_debut,
        date_fin=date_fin,
        seuil_surstock_ratio=seuil_surstock_ratio,
    )

    return ReponseAlertesStockPrevues(
        magasin_id=str(magasin_id),
        date_debut=date_debut,
        date_fin=date_fin,
        seuil_surstock_ratio=float(seuil_surstock_ratio),
        ruptures=[
            AlerteRupturePrevueOut(
                ingredient_id=str(a.ingredient_id),
                ingredient_nom=a.ingredient_nom,
                unite=a.unite,
                stock_estime=float(a.stock_estime),
                besoin_total=float(a.besoin_total),
                delta=float(a.delta),
            )
            for a in ruptures
        ],
        surstocks=[
            AlerteSurstockPrevuOut(
                ingredient_id=str(a.ingredient_id),
                ingredient_nom=a.ingredient_nom,
                unite=a.unite,
                stock_estime=float(a.stock_estime),
                besoin_total=float(a.besoin_total),
                surplus=float(a.surplus),
            )
            for a in surstocks
        ],
    )
