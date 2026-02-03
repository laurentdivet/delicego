from __future__ import annotations

from datetime import date
from pydantic import BaseModel


class SeriePointSchema(BaseModel):
    date: date
    value: float


class ImpactWasteResponse(BaseModel):
    days: int
    waste_qty: float
    input_qty: float
    waste_rate: float
    series_waste_qty: list[SeriePointSchema]
    series_waste_rate: list[SeriePointSchema]


class ImpactLocalResponse(BaseModel):
    days: int
    local_km_threshold: float
    local_receptions: int
    total_receptions: int
    local_share: float
    series_local_share: list[SeriePointSchema]


class ImpactCO2Response(BaseModel):
    days: int
    total_kgco2e: float
    series_kgco2e: list[SeriePointSchema]


class ImpactSummaryResponse(BaseModel):
    days: int
    waste_rate: float
    local_share: float
    co2_kgco2e: float
    savings_vs_baseline: dict[str, float] | None = None
