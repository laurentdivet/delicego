from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel


class ProductionRecetteDuJourSchema(BaseModel):
    recette_id: UUID
    recette_nom: str
    quantite_produite: float


class ProductionDuJourSchema(BaseModel):
    nombre_lots: int
    quantites_par_recette: list[ProductionRecetteDuJourSchema]


class ConsommationIngredientDuJourSchema(BaseModel):
    ingredient_id: UUID
    ingredient_nom: str
    quantite_consommee: float


class StockIngredientCourantSchema(BaseModel):
    ingredient_id: UUID
    ingredient_nom: str
    stock_total: float


class AlerteStockBasSchema(BaseModel):
    ingredient_id: UUID
    ingredient_nom: str
    stock_total: float


class AlerteDLCSchema(BaseModel):
    ingredient_id: UUID
    ingredient_nom: str
    date_dlc: date


class AlertesDashboardSchema(BaseModel):
    stocks_bas: list[AlerteStockBasSchema]
    dlc: list[AlerteDLCSchema]


class ReponseDashboardProductionStockSchema(BaseModel):
    date_cible: date
    production: ProductionDuJourSchema
    consommation: list[ConsommationIngredientDuJourSchema]
    stock: list[StockIngredientCourantSchema]
    alertes: AlertesDashboardSchema
