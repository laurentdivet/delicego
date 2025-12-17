from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.schemas.dashboard_production_stock import ReponseDashboardProductionStockSchema
from app.services.dashboard_production_stock_service import DashboardProductionStockService

# ⚠️ IMPORTANT : le router DOIT s'appeler "router"
router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)

# Compatibilité avec le routeur principal (app/api/routeur.py)
routeur_dashboard_production_stock_interne = router


@router.get(
    "/production-stock",
    response_model=ReponseDashboardProductionStockSchema,
)
async def dashboard_production_stock(
    date_cible: date,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseDashboardProductionStockSchema:
    service = DashboardProductionStockService(session)
    data = await service.lire(date_cible=date_cible)

    return ReponseDashboardProductionStockSchema(
        date_cible=data.date_cible,
        production={
            "nombre_lots": data.production.nombre_lots,
            "quantites_par_recette": [
                {
                    "recette_id": l.recette_id,
                    "recette_nom": l.recette_nom,
                    "quantite_produite": l.quantite_produite,
                }
                for l in data.production.quantites_par_recette
            ],
        },
        consommation=[
            {
                "ingredient_id": c.ingredient_id,
                "ingredient_nom": c.ingredient_nom,
                "quantite_consommee": c.quantite_consommee,
            }
            for c in data.consommation
        ],
        stock=[
            {
                "ingredient_id": s.ingredient_id,
                "ingredient_nom": s.ingredient_nom,
                "stock_total": s.stock_total,
            }
            for s in data.stock
        ],
        alertes={
            "stocks_bas": [
                {
                    "ingredient_id": a.ingredient_id,
                    "ingredient_nom": a.ingredient_nom,
                    "stock_total": a.stock_total,
                }
                for a in data.alertes.stocks_bas
            ],
            "dlc": [
                {
                    "ingredient_id": a.ingredient_id,
                    "ingredient_nom": a.ingredient_nom,
                    "date_dlc": a.date_dlc,
                }
                for a in data.alertes.dlc
            ],
        },
    )
