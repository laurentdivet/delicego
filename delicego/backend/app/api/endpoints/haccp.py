from __future__ import annotations

"""Endpoints HACCP Core.

CONTRAINTES:
- UNIQUEMENT :
  - POST /haccp (création)
  - POST /haccp/{id}/validate (validation)
  - GET  /haccp/{id} (lecture)
- Pas d'autres routes.

Stockage: in-memory (process) pour respecter le périmètre demandé et permettre
les tests métier. Aucune dépendance aux modules stocks/production/etc.
"""

from dataclasses import asdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.schemas.haccp import (
    ChecklistCreateSchema,
    EquipmentCreateSchema,
    HaccpCreateRequest,
    HaccpCreateResponse,
    HaccpReadResponse,
    HaccpValidateResponse,
    ReceptionControlCreateSchema,
    TemperatureLogCreateSchema,
    TraceabilityEventCreateSchema,
)
from app.domaine.modeles.haccp import (
    Checklist,
    ChecklistAnswer,
    ChecklistItem,
    Equipment,
    ReceptionControl,
    TemperatureLog,
    TraceabilityEvent,
    TraceabilityItem,
    ValidationError,
)


routeur_haccp_interne = APIRouter(prefix="/haccp", tags=["haccp"])


# In-memory store: id -> (type, entity)
_STORE: dict[UUID, tuple[str, Any]] = {}


def _entity_to_dict(type_: str, entity: Any) -> dict:
    d = asdict(entity)
    # Enum serialization for checklist answers
    if type_ == "checklist":
        for it in d.get("items", []) or []:
            # dataclasses.asdict converts Enum to Enum; ensure str
            if "reponse" in it and hasattr(it["reponse"], "value"):
                it["reponse"] = it["reponse"].value
    return d


@routeur_haccp_interne.post("", response_model=HaccpCreateResponse)
async def creer_haccp(req: HaccpCreateRequest) -> HaccpCreateResponse:
    try:
        if req.type == "traceability_event":
            payload = TraceabilityEventCreateSchema.model_validate(req.payload)
            ev = TraceabilityEvent(items=[TraceabilityItem(**it.model_dump()) for it in payload.items])
            _STORE[ev.id] = (req.type, ev)
            return HaccpCreateResponse(id=ev.id)

        if req.type == "reception_control":
            payload = ReceptionControlCreateSchema.model_validate(req.payload)
            rc = ReceptionControl(**payload.model_dump())
            _STORE[rc.id] = (req.type, rc)
            return HaccpCreateResponse(id=rc.id)

        if req.type == "equipment":
            payload = EquipmentCreateSchema.model_validate(req.payload)
            eq = Equipment(**payload.model_dump())
            _STORE[eq.id] = (req.type, eq)
            return HaccpCreateResponse(id=eq.id)

        if req.type == "temperature_log":
            payload = TemperatureLogCreateSchema.model_validate(req.payload)
            eq_id = payload.equipment_id
            if eq_id is None:
                raise ValidationError("temperature_log: equipment_id obligatoire")
            tl = TemperatureLog(
                equipment_id=eq_id,
                valeur=payload.valeur,
                seuil_min=payload.seuil_min,
                seuil_max=payload.seuil_max,
            )
            _STORE[tl.id] = (req.type, tl)
            return HaccpCreateResponse(id=tl.id)

        if req.type == "checklist":
            payload = ChecklistCreateSchema.model_validate(req.payload)
            items: list[ChecklistItem] = []
            for it in payload.items:
                ans = ChecklistAnswer(it.reponse)
                items.append(
                    ChecklistItem(
                        question=it.question,
                        reponse=ans,
                        commentaire=it.commentaire,
                        photo_path=it.photo_path,
                    )
                )
            cl = Checklist(titre=payload.titre, items=items)
            _STORE[cl.id] = (req.type, cl)
            return HaccpCreateResponse(id=cl.id)

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        # pydantic validation etc.
        raise HTTPException(status_code=400, detail=str(e))

    raise HTTPException(status_code=400, detail=f"type inconnu: {req.type}")


@routeur_haccp_interne.post("/{entity_id}/validate", response_model=HaccpValidateResponse)
async def valider_haccp(entity_id: UUID) -> HaccpValidateResponse:
    if entity_id not in _STORE:
        raise HTTPException(status_code=404, detail="not found")

    type_, entity = _STORE[entity_id]

    try:
        # All entities with validate() return a new immutable instance
        if hasattr(entity, "validate"):
            entity2 = entity.validate()
            _STORE[entity_id] = (type_, entity2)
            validated_at = getattr(entity2, "validated_at", None)
            if validated_at is None:
                # defensive
                raise ValidationError("validation a échoué")
            return HaccpValidateResponse(id=entity_id, validated_at=validated_at)

        raise ValidationError(f"type {type_} non validable")

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@routeur_haccp_interne.get("/{entity_id}", response_model=HaccpReadResponse)
async def lire_haccp(entity_id: UUID) -> HaccpReadResponse:
    if entity_id not in _STORE:
        raise HTTPException(status_code=404, detail="not found")

    type_, entity = _STORE[entity_id]
    return HaccpReadResponse(type=type_, data=_entity_to_dict(type_, entity))
