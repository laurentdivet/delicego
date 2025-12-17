from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class RequetePlanificationProduction(BaseModel):
    """Payload de planification (API interne)."""

    magasin_id: UUID

    date_plan: date
    date_debut_historique: date
    date_fin_historique: date

    donnees_meteo: dict[str, float] = Field(default_factory=dict)
    evenements: list[str] = Field(default_factory=list)


class ReponsePlanificationProduction(BaseModel):
    """Réponse de planification : identifiant du plan créé."""

    plan_production_id: UUID


class ReponseExecutionProduction(BaseModel):
    """Réponse d’exécution : compte rendu technique."""

    lot_production_id: UUID
    nb_mouvements_stock: int
    nb_lignes_consommation: int
