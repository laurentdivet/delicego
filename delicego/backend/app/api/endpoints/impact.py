from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.impact import (
    ImpactCO2Response,
    ImpactLocalResponse,
    ImpactSummaryResponse,
    ImpactWasteResponse,
)
from app.core.configuration import parametres_application
from app.impact.kpis import impact_summary, kpi_co2_estimate, kpi_local_share, kpi_waste_rate


routeur_impact_interne = APIRouter(
    prefix="/impact",
    tags=["impact"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_impact_interne.get("/summary", response_model=ImpactSummaryResponse)
async def impact_summary_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    include_savings_vs_baseline: bool = Query(default=False),
    session: AsyncSession = Depends(fournir_session),
) -> ImpactSummaryResponse:
    s = await impact_summary(
        session,
        days=days,
        local_km_threshold=parametres_application.impact_local_km_threshold,
        include_savings_vs_baseline=include_savings_vs_baseline,
    )
    return ImpactSummaryResponse(
        days=s.days,
        waste_rate=s.waste_rate,
        local_share=s.local_share,
        co2_kgco2e=s.co2_kgco2e,
        savings_vs_baseline=s.savings_vs_baseline,
    )


@routeur_impact_interne.get("/waste", response_model=ImpactWasteResponse)
async def impact_waste_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(fournir_session),
) -> ImpactWasteResponse:
    r = await kpi_waste_rate(session, days=days)
    return ImpactWasteResponse(
        days=r.days,
        waste_qty=r.waste_qty,
        input_qty=r.input_qty,
        waste_rate=r.waste_rate,
        series_waste_qty=[{"date": p.date, "value": p.value} for p in r.series_waste_qty],
        series_waste_rate=[{"date": p.date, "value": p.value} for p in r.series_waste_rate],
    )


@routeur_impact_interne.get("/local", response_model=ImpactLocalResponse)
async def impact_local_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    local_km_threshold: float | None = Query(default=None, ge=0.0, le=20000.0),
    session: AsyncSession = Depends(fournir_session),
) -> ImpactLocalResponse:
    threshold = (
        float(local_km_threshold)
        if local_km_threshold is not None
        else float(parametres_application.impact_local_km_threshold)
    )
    r = await kpi_local_share(session, days=days, local_km_threshold=threshold)
    return ImpactLocalResponse(
        days=r.days,
        local_km_threshold=r.local_km_threshold,
        local_receptions=r.local_receptions,
        total_receptions=r.total_receptions,
        local_share=r.local_share,
        series_local_share=[{"date": p.date, "value": p.value} for p in r.series_local_share],
    )


@routeur_impact_interne.get("/co2", response_model=ImpactCO2Response)
async def impact_co2_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(fournir_session),
) -> ImpactCO2Response:
    r = await kpi_co2_estimate(session, days=days)
    return ImpactCO2Response(
        days=r.days,
        total_kgco2e=r.total_kgco2e,
        series_kgco2e=[{"date": p.date, "value": p.value} for p in r.series_kgco2e],
    )
