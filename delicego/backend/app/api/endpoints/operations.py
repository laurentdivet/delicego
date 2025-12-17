from __future__ import annotations

"""Endpoints Opérations (Inpulse core).

API STRICTE:
- POST création
- POST validation / réception
- GET lecture

On expose un routeur unique avec une enveloppe type/payload.
"""

from dataclasses import asdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.schemas.operations import (
    InventoryCreateSchema,
    LossCreateSchema,
    OperationsCreateRequest,
    OperationsCreateResponse,
    OperationsReadResponse,
    PurchaseOrderCreateSchema,
    ProductionPlanCreateSchema,
    StockMovementCreateSchema,
    TransferCreateSchema,
)
from app.domaine.modeles.operations import (
    ImmutableAfterValidationError,
    InMemoryOperationsStore,
    Inventory,
    InventoryLine,
    Loss,
    OperationsError,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    ProductionLine,
    ProductionPlan,
    StockMovement,
    StockMovementType,
    Transfer,
    TransferLine,
    TransferStatus,
    ValidationError,
)


routeur_operations = APIRouter(prefix="/operations", tags=["operations"])
_STORE = InMemoryOperationsStore()
_ENTITIES: dict[UUID, tuple[str, Any]] = {}


def _to_dict(entity: Any) -> dict:
    d = asdict(entity)
    # enum -> str
    for k, v in list(d.items()):
        if hasattr(v, "value"):
            d[k] = v.value
    return d


@routeur_operations.post("", response_model=OperationsCreateResponse)
async def creer(req: OperationsCreateRequest) -> OperationsCreateResponse:
    try:
        if req.type == "stock_movement":
            p = StockMovementCreateSchema.model_validate(req.payload)
            m = StockMovement(
                produit_id=p.produit_id,
                etablissement_id=p.etablissement_id,
                type=StockMovementType(p.type),
                quantite=p.quantite,
                valeur_unitaire=p.valeur_unitaire,
                utilisateur_id=p.utilisateur_id,
            )
            _STORE.append_movement(m)
            _ENTITIES[m.id] = (req.type, m)
            return OperationsCreateResponse(id=m.id)

        if req.type == "inventory":
            p = InventoryCreateSchema.model_validate(req.payload)
            inv = Inventory(
                date=p.date,
                etablissement_id=p.etablissement_id,
                utilisateur_id=p.utilisateur_id,
                lines=[InventoryLine(produit_id=l.produit_id, quantite_comptee=l.quantite_comptee) for l in p.lines],
            )
            _STORE.inventories[inv.id] = inv
            _ENTITIES[inv.id] = (req.type, inv)
            return OperationsCreateResponse(id=inv.id)

        if req.type == "transfer":
            p = TransferCreateSchema.model_validate(req.payload)
            tr = Transfer(
                source_etablissement_id=p.source_etablissement_id,
                cible_etablissement_id=p.cible_etablissement_id,
                date=p.date,
                statut=TransferStatus(p.statut),
                lines=[TransferLine(produit_id=l.produit_id, quantite=l.quantite) for l in p.lines],
            )
            _STORE.transfers[tr.id] = tr
            _ENTITIES[tr.id] = (req.type, tr)
            return OperationsCreateResponse(id=tr.id)

        if req.type == "loss":
            p = LossCreateSchema.model_validate(req.payload)
            loss = Loss(
                produit_id=p.produit_id,
                etablissement_id=p.etablissement_id,
                quantite=p.quantite,
                motif=p.motif,
                date=p.date,
                utilisateur_id=p.utilisateur_id,
            )
            _STORE.losses[loss.id] = loss
            _ENTITIES[loss.id] = (req.type, loss)
            return OperationsCreateResponse(id=loss.id)

        if req.type == "production_plan":
            p = ProductionPlanCreateSchema.model_validate(req.payload)
            plan = ProductionPlan(
                date=p.date,
                etablissement_id=p.etablissement_id,
                lines=[
                    ProductionLine(
                        produit_id=l.produit_id,
                        quantite_a_produire=l.quantite_a_produire,
                        quantite_produite=l.quantite_produite,
                    )
                    for l in p.lines
                ],
            )
            _STORE.production_plans[plan.id] = plan
            _ENTITIES[plan.id] = (req.type, plan)
            return OperationsCreateResponse(id=plan.id)

        if req.type == "purchase_order":
            p = PurchaseOrderCreateSchema.model_validate(req.payload)
            po = PurchaseOrder(
                fournisseur_id=p.fournisseur_id,
                etablissement_id=p.etablissement_id,
                date=p.date,
                statut=PurchaseOrderStatus(p.statut),
                lines=[PurchaseOrderLine(produit_id=l.produit_id, quantite=l.quantite, prix_unitaire=l.prix_unitaire) for l in p.lines],
            )
            _STORE.purchase_orders[po.id] = po
            _ENTITIES[po.id] = (req.type, po)
            return OperationsCreateResponse(id=po.id)

        raise ValidationError(f"type inconnu: {req.type}")

    except (ValidationError, ImmutableAfterValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@routeur_operations.post("/{entity_id}/validate")
async def valider(entity_id: UUID, action: str = "validate", utilisateur_id: UUID | None = None) -> dict:
    if entity_id not in _ENTITIES:
        raise HTTPException(status_code=404, detail="not found")

    type_, entity = _ENTITIES[entity_id]

    try:
        if type_ == "inventory":
            inv2, moves = entity.validate(existing_movements=_STORE.movements)
            _STORE.inventories[entity_id] = inv2
            _ENTITIES[entity_id] = (type_, inv2)
            _STORE.append_movements(moves)
            return {"id": str(entity_id), "movements_created": len(moves)}

        if type_ == "transfer":
            if action == "send":
                if utilisateur_id is None:
                    raise ValidationError("utilisateur_id obligatoire")
                tr2, moves = entity.envoyer(existing_movements=_STORE.movements, utilisateur_id=utilisateur_id)
                _STORE.transfers[entity_id] = tr2
                _ENTITIES[entity_id] = (type_, tr2)
                _STORE.append_movements(moves)
                return {"id": str(entity_id), "statut": tr2.statut.value, "movements_created": len(moves)}
            if action == "receive":
                if utilisateur_id is None:
                    raise ValidationError("utilisateur_id obligatoire")
                tr2, moves = entity.recevoir(existing_movements=_STORE.movements, utilisateur_id=utilisateur_id)
                _STORE.transfers[entity_id] = tr2
                _ENTITIES[entity_id] = (type_, tr2)
                _STORE.append_movements(moves)
                return {"id": str(entity_id), "statut": tr2.statut.value, "movements_created": len(moves)}
            raise ValidationError("action transfer invalide")

        if type_ == "loss":
            loss2, move = entity.validate(existing_movements=_STORE.movements)
            _STORE.losses[entity_id] = loss2
            _ENTITIES[entity_id] = (type_, loss2)
            _STORE.append_movement(move)
            return {"id": str(entity_id), "movement_created": True}

        if type_ == "production_plan":
            if utilisateur_id is None:
                raise ValidationError("utilisateur_id obligatoire")
            plan2, moves = entity.produire(existing_movements=_STORE.movements, utilisateur_id=utilisateur_id)
            _STORE.production_plans[entity_id] = plan2
            _ENTITIES[entity_id] = (type_, plan2)
            _STORE.append_movements(moves)
            return {"id": str(entity_id), "movements_created": len(moves)}

        if type_ == "purchase_order":
            if action == "send":
                po2 = entity.envoyer()
                _STORE.purchase_orders[entity_id] = po2
                _ENTITIES[entity_id] = (type_, po2)
                return {"id": str(entity_id), "statut": po2.statut.value}
            if action == "receive":
                if utilisateur_id is None:
                    raise ValidationError("utilisateur_id obligatoire")
                po2, moves = entity.recevoir(utilisateur_id=utilisateur_id)
                _STORE.purchase_orders[entity_id] = po2
                _ENTITIES[entity_id] = (type_, po2)
                _STORE.append_movements(moves)
                return {"id": str(entity_id), "statut": po2.statut.value, "movements_created": len(moves)}
            raise ValidationError("action purchase_order invalide")

        raise ValidationError(f"type non validable: {type_}")

    except (ValidationError, ImmutableAfterValidationError, OperationsError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@routeur_operations.get("/{entity_id}", response_model=OperationsReadResponse)
async def lire(entity_id: UUID) -> OperationsReadResponse:
    if entity_id not in _ENTITIES:
        raise HTTPException(status_code=404, detail="not found")
    type_, entity = _ENTITIES[entity_id]
    return OperationsReadResponse(type=type_, data=_to_dict(entity))
