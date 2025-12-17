from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class StockMovementCreateSchema(BaseModel):
    produit_id: UUID
    etablissement_id: UUID
    type: str
    quantite: float
    valeur_unitaire: float
    date_heure: datetime | None = None
    utilisateur_id: UUID


class InventoryLineSchema(BaseModel):
    produit_id: UUID
    quantite_comptee: float


class InventoryCreateSchema(BaseModel):
    date: date
    etablissement_id: UUID
    utilisateur_id: UUID
    lines: list[InventoryLineSchema] = Field(default_factory=list)


class TransferLineSchema(BaseModel):
    produit_id: UUID
    quantite: float


class TransferCreateSchema(BaseModel):
    source_etablissement_id: UUID
    cible_etablissement_id: UUID
    date: date
    statut: str = "BROUILLON"
    lines: list[TransferLineSchema] = Field(default_factory=list)


class LossCreateSchema(BaseModel):
    produit_id: UUID
    etablissement_id: UUID
    quantite: float
    motif: str
    date: date
    utilisateur_id: UUID


class ProductionLineSchema(BaseModel):
    produit_id: UUID
    quantite_a_produire: float
    quantite_produite: float


class ProductionPlanCreateSchema(BaseModel):
    date: date
    etablissement_id: UUID
    lines: list[ProductionLineSchema] = Field(default_factory=list)


class PurchaseOrderLineSchema(BaseModel):
    produit_id: UUID
    quantite: float
    prix_unitaire: float


class PurchaseOrderCreateSchema(BaseModel):
    fournisseur_id: UUID
    etablissement_id: UUID
    date: date
    statut: str = "BROUILLON"
    lines: list[PurchaseOrderLineSchema] = Field(default_factory=list)


class OperationsCreateRequest(BaseModel):
    type: str  # stock_movement|inventory|transfer|loss|production_plan|purchase_order
    payload: dict


class OperationsCreateResponse(BaseModel):
    id: UUID


class OperationsReadResponse(BaseModel):
    type: str
    data: dict
