from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class RequetePlanReel(BaseModel):
    magasin_id: UUID
    date_plan: date
    fenetre_jours: int = 7
    donnees_meteo: dict[str, float] = Field(default_factory=dict)
    evenements: list[str] = Field(default_factory=list)


class ReponsePlanReel(BaseModel):
    plan_production_id: UUID


class BesoinIngredientSchema(BaseModel):
    ingredient_id: UUID
    ingredient_nom: str
    quantite: float
    unite: str


class ReponseBesoins(BaseModel):
    plan_production_id: UUID
    besoins: list[BesoinIngredientSchema]
