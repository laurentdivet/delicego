from __future__ import annotations

"""Opérations (Inpulse core) - Domaine.

Contraintes:
- Module autonome, in-memory (pas de DB ici).
- Pas d'analytics.
- Ne touche pas HACCP.

Règles principales:
- Le stock est calculé UNIQUEMENT via les mouvements.
- Toute variation de stock = StockMovement.
- Historique obligatoire (append-only sur mouvements).
- Pas de suppression après validation (au niveau des entités validables).
"""

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import Enum
from uuid import UUID, uuid4


class OperationsError(ValueError):
    pass


class ValidationError(OperationsError):
    pass


class ImmutableAfterValidationError(OperationsError):
    pass


def _ensure_not_validated(validated: bool) -> None:
    if validated:
        raise ImmutableAfterValidationError("Entité immutable après validation")


# ---------------------------------------------------------------------------
# 1) Stocks
# ---------------------------------------------------------------------------


class StockMovementType(str, Enum):
    ENTREE = "ENTREE"
    SORTIE = "SORTIE"
    INVENTAIRE = "INVENTAIRE"
    TRANSFERT_SORTANT = "TRANSFERT_SORTANT"
    TRANSFERT_ENTRANT = "TRANSFERT_ENTRANT"
    PERTE = "PERTE"


@dataclass(frozen=True)
class StockMovement:
    id: UUID = field(default_factory=uuid4)

    produit_id: UUID = field(default_factory=uuid4)
    etablissement_id: UUID = field(default_factory=uuid4)

    type: StockMovementType = StockMovementType.ENTREE
    quantite: float = 0.0
    valeur_unitaire: float = 0.0

    date_heure: datetime = field(default_factory=datetime.utcnow)
    utilisateur_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class StockItem:
    """Vue de stock calculée.

    IMPORTANT: ne doit pas être modifiable directement (pas d'update via API).
    """

    produit_id: UUID
    etablissement_id: UUID
    quantite: float
    valeur_unitaire: float


def compute_stock(movements: list[StockMovement], *, produit_id: UUID, etablissement_id: UUID) -> StockItem:
    """Calcule le stock à partir des mouvements UNIQUEMENT."""

    qty = 0.0
    value_sum = 0.0

    for m in movements:
        if m.produit_id != produit_id or m.etablissement_id != etablissement_id:
            continue

        if m.type in (StockMovementType.ENTREE, StockMovementType.TRANSFERT_ENTRANT):
            qty += float(m.quantite)
            value_sum += float(m.quantite) * float(m.valeur_unitaire)
        elif m.type in (StockMovementType.SORTIE, StockMovementType.TRANSFERT_SORTANT, StockMovementType.PERTE):
            qty -= float(m.quantite)
            value_sum -= float(m.quantite) * float(m.valeur_unitaire)
        elif m.type == StockMovementType.INVENTAIRE:
            # mouvement correctif (delta)
            qty += float(m.quantite)
            value_sum += float(m.quantite) * float(m.valeur_unitaire)
        else:
            raise ValidationError(f"Type mouvement inconnu: {m.type}")

    valeur_unitaire = (value_sum / qty) if abs(qty) > 1e-9 else 0.0
    return StockItem(
        produit_id=produit_id,
        etablissement_id=etablissement_id,
        quantite=qty,
        valeur_unitaire=valeur_unitaire,
    )


# ---------------------------------------------------------------------------
# 2) Inventaires
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InventoryLine:
    id: UUID = field(default_factory=uuid4)
    produit_id: UUID = field(default_factory=uuid4)
    quantite_comptee: float = 0.0


@dataclass(frozen=True)
class Inventory:
    id: UUID = field(default_factory=uuid4)

    date: date = field(default_factory=date.today)
    etablissement_id: UUID = field(default_factory=uuid4)
    utilisateur_id: UUID = field(default_factory=uuid4)

    lines: list[InventoryLine] = field(default_factory=list)
    validated: bool = False

    def validate(self, *, existing_movements: list[StockMovement]) -> tuple["Inventory", list[StockMovement]]:
        _ensure_not_validated(self.validated)
        if not self.lines:
            raise ValidationError("Inventory: au moins une ligne")

        created: list[StockMovement] = []
        for line in self.lines:
            current = compute_stock(existing_movements, produit_id=line.produit_id, etablissement_id=self.etablissement_id)
            delta = float(line.quantite_comptee) - float(current.quantite)
            if abs(delta) < 1e-9:
                continue

            created.append(
                StockMovement(
                    produit_id=line.produit_id,
                    etablissement_id=self.etablissement_id,
                    type=StockMovementType.INVENTAIRE,
                    quantite=delta,
                    valeur_unitaire=current.valeur_unitaire,
                    utilisateur_id=self.utilisateur_id,
                )
            )

        return replace(self, validated=True), created


# ---------------------------------------------------------------------------
# 3) Transferts inter-établissements
# ---------------------------------------------------------------------------


class TransferStatus(str, Enum):
    BROUILLON = "BROUILLON"
    ENVOYE = "ENVOYE"
    RECU = "RECU"


@dataclass(frozen=True)
class TransferLine:
    id: UUID = field(default_factory=uuid4)
    produit_id: UUID = field(default_factory=uuid4)
    quantite: float = 0.0


@dataclass(frozen=True)
class Transfer:
    id: UUID = field(default_factory=uuid4)

    source_etablissement_id: UUID = field(default_factory=uuid4)
    cible_etablissement_id: UUID = field(default_factory=uuid4)
    date: date = field(default_factory=date.today)

    statut: TransferStatus = TransferStatus.BROUILLON
    lines: list[TransferLine] = field(default_factory=list)

    def envoyer(self, *, existing_movements: list[StockMovement], utilisateur_id: UUID) -> tuple["Transfer", list[StockMovement]]:
        if self.statut != TransferStatus.BROUILLON:
            raise ImmutableAfterValidationError("Transfer: seul BROUILLON peut être ENVOYE")
        if not self.lines:
            raise ValidationError("Transfer: au moins une ligne")

        created: list[StockMovement] = []
        for line in self.lines:
            current = compute_stock(
                existing_movements,
                produit_id=line.produit_id,
                etablissement_id=self.source_etablissement_id,
            )
            created.append(
                StockMovement(
                    produit_id=line.produit_id,
                    etablissement_id=self.source_etablissement_id,
                    type=StockMovementType.TRANSFERT_SORTANT,
                    quantite=float(line.quantite),
                    valeur_unitaire=current.valeur_unitaire,
                    utilisateur_id=utilisateur_id,
                )
            )

        return replace(self, statut=TransferStatus.ENVOYE), created

    def recevoir(
        self,
        *,
        existing_movements: list[StockMovement],
        utilisateur_id: UUID,
    ) -> tuple["Transfer", list[StockMovement]]:
        if self.statut != TransferStatus.ENVOYE:
            raise ImmutableAfterValidationError("Transfer: seul ENVOYE peut être RECU")

        created: list[StockMovement] = []
        # Valorisation conservée: on reprend la valeur unitaire des mouvements sortants
        for line in self.lines:
            # retrouve le dernier transfert sortant correspondant
            candidates = [
                m
                for m in existing_movements
                if m.produit_id == line.produit_id
                and m.etablissement_id == self.source_etablissement_id
                and m.type == StockMovementType.TRANSFERT_SORTANT
            ]
            vu = candidates[-1].valeur_unitaire if candidates else 0.0

            created.append(
                StockMovement(
                    produit_id=line.produit_id,
                    etablissement_id=self.cible_etablissement_id,
                    type=StockMovementType.TRANSFERT_ENTRANT,
                    quantite=float(line.quantite),
                    valeur_unitaire=float(vu),
                    utilisateur_id=utilisateur_id,
                )
            )

        return replace(self, statut=TransferStatus.RECU), created


# ---------------------------------------------------------------------------
# 4) Pertes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Loss:
    id: UUID = field(default_factory=uuid4)

    produit_id: UUID = field(default_factory=uuid4)
    etablissement_id: UUID = field(default_factory=uuid4)

    quantite: float = 0.0
    motif: str = ""
    date: date = field(default_factory=date.today)
    utilisateur_id: UUID = field(default_factory=uuid4)

    validated: bool = False

    def validate(self, *, existing_movements: list[StockMovement]) -> tuple["Loss", StockMovement]:
        _ensure_not_validated(self.validated)
        if not self.motif or self.motif.strip() == "":
            raise ValidationError("Loss: motif obligatoire")

        current = compute_stock(existing_movements, produit_id=self.produit_id, etablissement_id=self.etablissement_id)
        move = StockMovement(
            produit_id=self.produit_id,
            etablissement_id=self.etablissement_id,
            type=StockMovementType.PERTE,
            quantite=float(self.quantite),
            valeur_unitaire=current.valeur_unitaire,
            utilisateur_id=self.utilisateur_id,
        )
        return replace(self, validated=True), move


# ---------------------------------------------------------------------------
# 5) Production
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProductionLine:
    id: UUID = field(default_factory=uuid4)
    produit_id: UUID = field(default_factory=uuid4)
    quantite_a_produire: float = 0.0
    quantite_produite: float = 0.0


@dataclass(frozen=True)
class ProductionPlan:
    id: UUID = field(default_factory=uuid4)

    date: date = field(default_factory=date.today)
    etablissement_id: UUID = field(default_factory=uuid4)
    lines: list[ProductionLine] = field(default_factory=list)

    validated: bool = False

    def produire(
        self,
        *,
        existing_movements: list[StockMovement],
        utilisateur_id: UUID,
    ) -> tuple["ProductionPlan", list[StockMovement]]:
        _ensure_not_validated(self.validated)
        if not self.lines:
            raise ValidationError("ProductionPlan: au moins une ligne")

        created: list[StockMovement] = []
        for line in self.lines:
            # Entrée stock du produit fini.
            created.append(
                StockMovement(
                    produit_id=line.produit_id,
                    etablissement_id=self.etablissement_id,
                    type=StockMovementType.ENTREE,
                    quantite=float(line.quantite_produite),
                    valeur_unitaire=0.0,
                    utilisateur_id=utilisateur_id,
                )
            )

        return replace(self, validated=True), created


# ---------------------------------------------------------------------------
# 6) Commandes fournisseurs
# ---------------------------------------------------------------------------


class PurchaseOrderStatus(str, Enum):
    BROUILLON = "BROUILLON"
    ENVOYEE = "ENVOYEE"
    RECUE = "RECUE"


@dataclass(frozen=True)
class PurchaseOrderLine:
    id: UUID = field(default_factory=uuid4)
    produit_id: UUID = field(default_factory=uuid4)
    quantite: float = 0.0
    prix_unitaire: float = 0.0


@dataclass(frozen=True)
class PurchaseOrder:
    id: UUID = field(default_factory=uuid4)

    fournisseur_id: UUID = field(default_factory=uuid4)
    etablissement_id: UUID = field(default_factory=uuid4)
    date: date = field(default_factory=date.today)
    statut: PurchaseOrderStatus = PurchaseOrderStatus.BROUILLON

    lines: list[PurchaseOrderLine] = field(default_factory=list)

    def envoyer(self) -> "PurchaseOrder":
        if self.statut != PurchaseOrderStatus.BROUILLON:
            raise ImmutableAfterValidationError("PO: seul BROUILLON peut être ENVOYEE")
        return replace(self, statut=PurchaseOrderStatus.ENVOYEE)

    def recevoir(self, *, utilisateur_id: UUID) -> tuple["PurchaseOrder", list[StockMovement]]:
        if self.statut != PurchaseOrderStatus.ENVOYEE:
            raise ImmutableAfterValidationError("PO: seul ENVOYEE peut être RECUE")
        if not self.lines:
            raise ValidationError("PO: au moins une ligne")

        created: list[StockMovement] = []
        for line in self.lines:
            created.append(
                StockMovement(
                    produit_id=line.produit_id,
                    etablissement_id=self.etablissement_id,
                    type=StockMovementType.ENTREE,
                    quantite=float(line.quantite),
                    valeur_unitaire=float(line.prix_unitaire),
                    utilisateur_id=utilisateur_id,
                )
            )

        return replace(self, statut=PurchaseOrderStatus.RECUE), created


# ---------------------------------------------------------------------------
# In-memory store / service
# ---------------------------------------------------------------------------


class InMemoryOperationsStore:
    def __init__(self) -> None:
        self.movements: list[StockMovement] = []  # append-only

        self.inventories: dict[UUID, Inventory] = {}
        self.transfers: dict[UUID, Transfer] = {}
        self.losses: dict[UUID, Loss] = {}
        self.production_plans: dict[UUID, ProductionPlan] = {}
        self.purchase_orders: dict[UUID, PurchaseOrder] = {}

    def append_movement(self, m: StockMovement) -> None:
        self.movements.append(m)

    def append_movements(self, ms: list[StockMovement]) -> None:
        self.movements.extend(ms)
