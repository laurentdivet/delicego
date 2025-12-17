from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class CostMatterLineSchema(BaseModel):
    period_start: date
    value: float


class MarginLineSchema(BaseModel):
    period_start: date
    ca: float
    cost_real: float
    margin: float


class GapLineSchema(BaseModel):
    period_start: date
    cost_real: float
    cost_theoretical: float
    gap_eur: float
    gap_pct: float | None
