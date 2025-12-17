from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Traçabilité produits
# ---------------------------------------------------------------------------


class TraceabilityItemCreateSchema(BaseModel):
    dlc_ddm: date | None = None
    numero_lot: str | None = None
    photo_path: str | None = None


class TraceabilityEventCreateSchema(BaseModel):
    items: list[TraceabilityItemCreateSchema] = Field(default_factory=list)


class TraceabilityItemReadSchema(BaseModel):
    id: UUID
    dlc_ddm: date | None
    numero_lot: str | None
    photo_path: str | None


class TraceabilityEventReadSchema(BaseModel):
    id: UUID
    created_at: datetime
    validated_at: datetime | None
    items: list[TraceabilityItemReadSchema]


# ---------------------------------------------------------------------------
# Contrôle à réception
# ---------------------------------------------------------------------------


class ReceptionControlCreateSchema(BaseModel):
    conforme: bool = True
    commentaire: str | None = None
    photo_path: str | None = None


class ReceptionControlReadSchema(BaseModel):
    id: UUID
    created_at: datetime
    validated_at: datetime | None
    conforme: bool
    commentaire: str | None
    photo_path: str | None


# ---------------------------------------------------------------------------
# Températures
# ---------------------------------------------------------------------------


class EquipmentCreateSchema(BaseModel):
    nom: str
    seuil_min: float | None = None
    seuil_max: float | None = None


class EquipmentReadSchema(BaseModel):
    id: UUID
    nom: str
    seuil_min: float | None
    seuil_max: float | None


class TemperatureLogCreateSchema(BaseModel):
    equipment_id: UUID | None = None
    valeur: float
    seuil_min: float | None = None
    seuil_max: float | None = None


class TemperatureLogReadSchema(BaseModel):
    id: UUID
    created_at: datetime
    equipment_id: UUID
    valeur: float
    seuil_min: float | None
    seuil_max: float | None
    conforme: bool


# ---------------------------------------------------------------------------
# Checklists
# ---------------------------------------------------------------------------


class ChecklistItemCreateSchema(BaseModel):
    question: str
    reponse: str = "NON_EVALUE"  # OUI | NON | NON_EVALUE
    commentaire: str | None = None
    photo_path: str | None = None


class ChecklistCreateSchema(BaseModel):
    titre: str
    items: list[ChecklistItemCreateSchema] = Field(default_factory=list)


class ChecklistItemReadSchema(BaseModel):
    id: UUID
    question: str
    reponse: str
    commentaire: str | None
    photo_path: str | None


class ChecklistReadSchema(BaseModel):
    id: UUID
    created_at: datetime
    validated_at: datetime | None
    titre: str
    items: list[ChecklistItemReadSchema]


# ---------------------------------------------------------------------------
# API envelope
# ---------------------------------------------------------------------------


class HaccpCreateRequest(BaseModel):
    """Requête générique de création.

    type: traceability_event | reception_control | equipment | temperature_log | checklist
    """

    type: str
    payload: dict


class HaccpCreateResponse(BaseModel):
    id: UUID


class HaccpValidateResponse(BaseModel):
    id: UUID
    validated_at: datetime


class HaccpReadResponse(BaseModel):
    type: str
    data: dict
