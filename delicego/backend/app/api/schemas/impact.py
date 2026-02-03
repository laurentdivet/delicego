from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


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


# ==============================
# Impact dashboard (public DEV-only) + write schemas (public DEV-only)
# ==============================


class ImpactDashboardActionSchema(BaseModel):
    id: str
    status: str
    description: str | None = None


class ImpactDashboardRecommendationSchema(BaseModel):
    id: str
    code: str
    severity: str
    status: str
    occurrences: int
    last_seen_at: datetime
    entities: dict[str, object] | None = None
    actions: list[ImpactDashboardActionSchema] = Field(default_factory=list)


class ImpactDashboardAlertSchema(BaseModel):
    key: str
    severity: str
    title: str
    message: str
    metric: str
    value: float
    threshold: float
    days: int
    period_end: datetime


class ImpactDashboardKpisSchema(BaseModel):
    days: int
    waste_rate: float
    local_share: float
    co2_kgco2e: float


class ImpactDashboardResponse(BaseModel):
    kpis: ImpactDashboardKpisSchema
    alerts: list[ImpactDashboardAlertSchema] = Field(default_factory=list)
    recommendations: list[ImpactDashboardRecommendationSchema] = Field(default_factory=list)


class ImpactActionCreateBody(BaseModel):
    action_type: str = Field(description="CHANGE_SUPPLIER|ADJUST_QUANTITY|REMOVE_MENU|TRAINING|OTHER")
    description: str | None = Field(default=None)


class ImpactActionPatchBody(BaseModel):
    status: str | None = Field(default=None, description="OPEN|DONE|CANCELLED")
    description: str | None = Field(default=None)


class ImpactRecommendationPatchBody(BaseModel):
    status: str | None = Field(default=None, description="OPEN|ACKNOWLEDGED|RESOLVED")
    comment: str | None = Field(default=None)


class ImpactActionSchema(BaseModel):
    id: str
    recommendation_event_id: str
    action_type: str
    description: str | None = None
    status: str
    created_at: datetime
