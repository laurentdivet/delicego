from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class AlertesResume(BaseModel):
    stocks_bas: int
    lots_proches_dlc: int


class VueGlobaleDashboard(BaseModel):
    date: date
    commandes_du_jour: int
    productions_du_jour: int
    quantite_produite: float
    alertes: AlertesResume


class PlanProductionDashboard(BaseModel):
    id: UUID
    date_plan: date
    statut: str
    nombre_lignes: int


class CommandeClientDashboard(BaseModel):
    id: UUID
    date_commande: datetime
    statut: str
    nombre_lignes: int
    quantite_totale: float


class ConsommationIngredientDashboard(BaseModel):
    ingredient_id: UUID
    ingredient: str
    quantite_consommee: float
    stock_estime: float
    lots_proches_dlc: int


class AlerteStockBas(BaseModel):
    ingredient_id: UUID
    ingredient: str
    stock_estime: float


class AlerteLotProcheDLC(BaseModel):
    ingredient_id: UUID
    ingredient: str
    date_dlc: date


class AlertesDashboard(BaseModel):
    stocks_bas: list[AlerteStockBas]
    lots_proches_dlc: list[AlerteLotProcheDLC]
