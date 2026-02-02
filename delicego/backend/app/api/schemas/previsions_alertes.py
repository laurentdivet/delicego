from __future__ import annotations

from datetime import date
from pydantic import BaseModel


class AlerteRupturePrevueOut(BaseModel):
    ingredient_id: str
    ingredient_nom: str
    unite: str
    stock_estime: float
    besoin_total: float
    delta: float


class AlerteSurstockPrevuOut(BaseModel):
    ingredient_id: str
    ingredient_nom: str
    unite: str
    stock_estime: float
    besoin_total: float
    surplus: float


class ReponseAlertesStockPrevues(BaseModel):
    magasin_id: str
    date_debut: date
    date_fin: date
    seuil_surstock_ratio: float
    ruptures: list[AlerteRupturePrevueOut]
    surstocks: list[AlerteSurstockPrevuOut]
