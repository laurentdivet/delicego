from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.api.schemas.catalogue import ProduitMini


class IngredientOutEnrichi(BaseModel):
    id: UUID
    nom: str
    unite_stock: str
    cout_unitaire: float
    actif: bool

    produit_id: UUID | None
    produit: ProduitMini | None

    unite_consommation: str | None
    facteur_conversion: float | None

    class Config:
        from_attributes = True
