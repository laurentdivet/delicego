from __future__ import annotations

from datetime import date
from pydantic import BaseModel


class BesoinIngredientPrevuOut(BaseModel):
    date_jour: date
    ingredient_id: str
    ingredient_nom: str
    unite: str
    quantite: float


class ReponseBesoinsIngredientsPrevus(BaseModel):
    magasin_id: str
    date_debut: date
    date_fin: date
    besoins: list[BesoinIngredientPrevuOut]
