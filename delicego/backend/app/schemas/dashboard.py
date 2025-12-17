from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel


class LigneDashboardFournisseurSchema(BaseModel):
    fournisseur_id: UUID
    fournisseur_nom: str
    total_commandes: int
    total_montant_commande: float
    total_montant_recu: float
    taux_reception: float
    derniere_commande_date: date | None


class ReponseDashboardFournisseursSchema(BaseModel):
    fournisseurs: list[LigneDashboardFournisseurSchema]
