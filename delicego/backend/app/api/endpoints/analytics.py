from __future__ import annotations

"""Endpoints Analytics (READ-ONLY).

API STRICTE:
- GET /analytics/cost-matter
- GET /analytics/margin
- GET /analytics/gaps

Aucune route d'écriture.

Les données sont injectées via un store in-memory minimal pour les tests.
"""

from datetime import date

from fastapi import APIRouter, HTTPException

from app.api.schemas.analytics import CostMatterLineSchema, GapLineSchema, MarginLineSchema
from app.domaine.modeles.operations import StockMovement
from app.domaine.services.analytics import Period, cost_matter_real, cost_matter_theoretical, gaps, margin


routeur_analytics = APIRouter(prefix="/analytics", tags=["analytics"])


class AnalyticsStore:
    def __init__(self) -> None:
        self.movements: list[StockMovement] = []
        self.sales: list[dict] = []  # {date, ca, cost_rate}


_STORE = AnalyticsStore()


@routeur_analytics.get("/cost-matter", response_model=list[CostMatterLineSchema])
async def get_cost_matter(period: str = "day", start: date | None = None, end: date | None = None) -> list[CostMatterLineSchema]:
    try:
        p = Period(period)
    except Exception as e:
        raise HTTPException(status_code=400, detail="invalid period") from e

    res = cost_matter_real(_STORE.movements, period=p, start=start, end=end)
    return [CostMatterLineSchema(period_start=l.period_start, value=l.value) for l in res]


@routeur_analytics.get("/margin", response_model=list[MarginLineSchema])
async def get_margin(period: str = "day", start: date | None = None, end: date | None = None) -> list[MarginLineSchema]:
    try:
        p = Period(period)
    except Exception as e:
        raise HTTPException(status_code=400, detail="invalid period") from e

    res = margin(movements=_STORE.movements, sales=_STORE.sales, period=p, start=start, end=end)
    return [
        MarginLineSchema(period_start=l.period_start, ca=l.ca, cost_real=l.cost_real, margin=l.margin)
        for l in res
    ]


@routeur_analytics.get("/gaps", response_model=list[GapLineSchema])
async def get_gaps(period: str = "day", start: date | None = None, end: date | None = None) -> list[GapLineSchema]:
    try:
        p = Period(period)
    except Exception as e:
        raise HTTPException(status_code=400, detail="invalid period") from e

    res = gaps(movements=_STORE.movements, sales=_STORE.sales, period=p, start=start, end=end)
    return [
        GapLineSchema(
            period_start=l.period_start,
            cost_real=l.cost_real,
            cost_theoretical=l.cost_theoretical,
            gap_eur=l.gap_eur,
            gap_pct=l.gap_pct,
        )
        for l in res
    ]
