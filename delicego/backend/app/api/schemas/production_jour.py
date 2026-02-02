from __future__ import annotations

"""Schémas API - Production du jour.

Endpoint interne dédié au flux end-to-end :
UI -> API -> ServiceProductionJour -> DB (lots + consommation)
"""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class LigneProductionDuJourIn(BaseModel):
    recette_id: UUID
    quantite_a_produire: float = Field(gt=0)


class RequeteProductionDuJour(BaseModel):
    magasin_id: UUID
    date_jour: date
    lignes: list[LigneProductionDuJourIn] = Field(min_length=1)


class ReponseProductionDuJour(BaseModel):
    plan_id: UUID
    lots_crees: int
    consommations_creees: int
    mouvements_stock_crees: int
    besoins: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
