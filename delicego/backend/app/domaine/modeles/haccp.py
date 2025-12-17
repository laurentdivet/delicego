from __future__ import annotations

"""HACCP Core (PMS) - Modèles de domaine.

IMPORTANT:
- Ce module est volontairement autonome et minimal.
- Pas de dépendance aux modules stocks/production/analytics/pipeline.

On implémente ici des entités *immutables après validation* et des règles métier
strictes.

Ces modèles sont des "entités" en mémoire, utilisables par l'API et les tests.
Ils ne sont pas encore persistés en DB (pas de SQLAlchemy ici), conformément au
périmètre demandé.
"""

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import Enum
from uuid import UUID, uuid4


class HaccpError(ValueError):
    """Erreur métier HACCP."""


class ValidationError(HaccpError):
    """Erreur de validation d'une entité HACCP."""


class ImmutableAfterValidationError(HaccpError):
    """Modification interdite après validation."""


def _ensure_not_validated(validated: bool) -> None:
    if validated:
        raise ImmutableAfterValidationError("Entité immutable après validation")


# ---------------------------------------------------------------------------
# 1) Traçabilité produits
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TraceabilityItem:
    """Élément de traçabilité.

    Règle:
    - Au moins une preuve parmi (dlc_ddm, numero_lot, photo_path) doit être fournie.
    """

    id: UUID = field(default_factory=uuid4)
    dlc_ddm: date | None = None
    numero_lot: str | None = None
    photo_path: str | None = None

    def validate(self) -> None:
        if self.dlc_ddm is None and (self.numero_lot is None or self.numero_lot.strip() == "") and (
            self.photo_path is None or self.photo_path.strip() == ""
        ):
            raise ValidationError(
                "TraceabilityItem invalide: fournir au moins dlc_ddm OU numero_lot OU photo_path"
            )


@dataclass(frozen=True)
class TraceabilityEvent:
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)
    validated_at: datetime | None = None
    items: list[TraceabilityItem] = field(default_factory=list)

    @property
    def validated(self) -> bool:
        return self.validated_at is not None

    def add_item(self, item: TraceabilityItem) -> "TraceabilityEvent":
        _ensure_not_validated(self.validated)
        return replace(self, items=[*self.items, item])

    def validate(self, *, at: datetime | None = None) -> "TraceabilityEvent":
        _ensure_not_validated(self.validated)
        if not self.items:
            raise ValidationError("TraceabilityEvent invalide: au moins un item requis")
        for it in self.items:
            it.validate()
        return replace(self, validated_at=at or datetime.utcnow())


# ---------------------------------------------------------------------------
# 2) Contrôle à réception
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReceptionControl:
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)
    validated_at: datetime | None = None

    conforme: bool = True
    commentaire: str | None = None
    photo_path: str | None = None

    @property
    def validated(self) -> bool:
        return self.validated_at is not None

    def validate(self, *, at: datetime | None = None) -> "ReceptionControl":
        _ensure_not_validated(self.validated)

        if self.conforme is False:
            if self.commentaire is None or self.commentaire.strip() == "":
                raise ValidationError("ReceptionControl non conforme: commentaire obligatoire")
            if self.photo_path is None or self.photo_path.strip() == "":
                raise ValidationError("ReceptionControl non conforme: photo_path obligatoire")

        return replace(self, validated_at=at or datetime.utcnow())


# ---------------------------------------------------------------------------
# 3) Températures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Equipment:
    id: UUID = field(default_factory=uuid4)
    nom: str = ""
    seuil_min: float | None = None
    seuil_max: float | None = None


@dataclass(frozen=True)
class TemperatureLog:
    """Relevé de température.

    Règles:
    - conforme = seuil_min <= valeur <= seuil_max
    - aucune suppression (non applicable in-memory; l'API n'expose pas de DELETE)
    - historisation obligatoire => on conserve tous les logs
    """

    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)
    equipment_id: UUID = field(default_factory=uuid4)

    valeur: float = 0.0
    seuil_min: float | None = None
    seuil_max: float | None = None

    @property
    def conforme(self) -> bool:
        if self.seuil_min is not None and self.valeur < float(self.seuil_min):
            return False
        if self.seuil_max is not None and self.valeur > float(self.seuil_max):
            return False
        return True


# ---------------------------------------------------------------------------
# 4) Checklists normées
# ---------------------------------------------------------------------------


class ChecklistAnswer(str, Enum):
    OUI = "OUI"
    NON = "NON"
    NON_EVALUE = "NON_EVALUE"


@dataclass(frozen=True)
class ChecklistItem:
    id: UUID = field(default_factory=uuid4)
    question: str = ""

    reponse: ChecklistAnswer = ChecklistAnswer.NON_EVALUE
    commentaire: str | None = None
    photo_path: str | None = None

    def validate(self) -> None:
        if self.reponse == ChecklistAnswer.NON:
            if self.commentaire is None or self.commentaire.strip() == "":
                raise ValidationError("ChecklistItem NON: commentaire obligatoire")
            if self.photo_path is None or self.photo_path.strip() == "":
                raise ValidationError("ChecklistItem NON: photo_path obligatoire")


@dataclass(frozen=True)
class Checklist:
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)
    validated_at: datetime | None = None

    titre: str = ""
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def validated(self) -> bool:
        return self.validated_at is not None

    def add_item(self, item: ChecklistItem) -> "Checklist":
        _ensure_not_validated(self.validated)
        return replace(self, items=[*self.items, item])

    def validate(self, *, at: datetime | None = None) -> "Checklist":
        _ensure_not_validated(self.validated)
        if not self.items:
            raise ValidationError("Checklist invalide: au moins un item requis")
        for it in self.items:
            it.validate()
        return replace(self, validated_at=at or datetime.utcnow())
