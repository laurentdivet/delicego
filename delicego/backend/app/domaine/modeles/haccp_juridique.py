from __future__ import annotations

from datetime import datetime, date
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domaine.modeles.base import BaseModele


# -------------------------
# 1) Traçabilité produits
# -------------------------


class TraceabilityEvent(BaseModele):
    __tablename__ = "traceability_event"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    etablissement_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    utilisateur_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)

    date_heure: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    valide: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    items: Mapped[list["TraceabilityItem"]] = relationship(
        "TraceabilityItem",
        back_populates="event",
        cascade="all, delete-orphan",
    )

    def valider(self) -> None:
        """Valide l'événement si toutes les lignes sont valides.

        Règle: impossible si au moins une ligne est invalide.
        Une fois validé: immutable via règles applicatives (pas d'update/delete endpoints)
        + DB constraint sur items.
        """

        if self.valide:
            return

        if not self.items:
            raise ValueError("Impossible de valider: aucun item de traçabilité.")

        invalides = [i for i in self.items if not i.est_valide()]
        if invalides:
            raise ValueError("Impossible de valider: au moins une ligne de traçabilité est invalide.")

        self.valide = True


class TraceabilityItem(BaseModele):
    __tablename__ = "traceability_item"
    __table_args__ = (
        CheckConstraint(
            "NOT (dlc_ddm IS NULL AND numero_lot IS NULL AND photo_path IS NULL)",
            name="ck_traceability_item_preuve",
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    traceability_event_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("traceability_event.id"),
        nullable=False,
    )

    produit_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    categorie: Mapped[str] = mapped_column(String(30), nullable=False)

    dlc_ddm: Mapped[date | None] = mapped_column(nullable=True)
    numero_lot: Mapped[str | None] = mapped_column(String(120), nullable=True)
    photo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    event: Mapped[TraceabilityEvent] = relationship("TraceabilityEvent", back_populates="items")

    def est_valide(self) -> bool:
        return not (self.dlc_ddm is None and self.numero_lot is None and self.photo_path is None)


# -------------------------
# 2) Contrôle à réception fournisseur
# -------------------------


class ReceptionControl(BaseModele):
    __tablename__ = "reception_control"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    fournisseur_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fournisseur.id"), nullable=False)
    utilisateur_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)

    date_heure: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    conforme: Mapped[bool] = mapped_column(Boolean, nullable=False)
    commentaire: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    valide: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    fournisseur = relationship("Fournisseur")

    def valider(self) -> None:
        if self.valide:
            return

        if not self.conforme:
            if not (self.commentaire and self.commentaire.strip()):
                raise ValueError("Commentaire obligatoire si réception non conforme")
            if not (self.photo_path and self.photo_path.strip()):
                raise ValueError("Photo obligatoire si réception non conforme")

        self.valide = True


# -------------------------
# 3) Températures
# -------------------------


class Equipment(BaseModele):
    __tablename__ = "equipment"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # frigo, vitrine, produit

    seuil_min: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    seuil_max: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)


class TemperatureLog(BaseModele):
    __tablename__ = "temperature_log"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    equipment_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("equipment.id"), nullable=False)
    utilisateur_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)

    valeur: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    date_heure: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # conforme calculé et persisté (juridiquement opposable / historique)
    conforme: Mapped[bool] = mapped_column(Boolean, nullable=False)

    equipment = relationship("Equipment")

    @staticmethod
    def calculer_conformite(*, valeur: float, seuil_min: float, seuil_max: float) -> bool:
        return float(seuil_min) <= float(valeur) <= float(seuil_max)


# -------------------------
# 4) Checklists normées
# -------------------------


class Checklist(BaseModele):
    __tablename__ = "checklist"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    type: Mapped[str] = mapped_column(String(30), nullable=False)  # poids, thermometre, pH

    utilisateur_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    date_heure: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    valide: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    items: Mapped[list["ChecklistItem"]] = relationship(
        "ChecklistItem",
        back_populates="checklist",
        cascade="all, delete-orphan",
    )

    def valider(self) -> None:
        if self.valide:
            return

        if not self.items:
            raise ValueError("Impossible de valider: aucun item")

        for it in self.items:
            it.valider_regles()

        self.valide = True


class ChecklistItem(BaseModele):
    __tablename__ = "checklist_item"
    __table_args__ = (
        UniqueConstraint("checklist_id", "code", name="uq_checklist_item_checklist_id_code"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    checklist_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("checklist.id"), nullable=False)

    code: Mapped[str] = mapped_column(String(80), nullable=False)
    question: Mapped[str] = mapped_column(String(300), nullable=False)

    reponse: Mapped[str] = mapped_column(String(20), nullable=False)  # OUI/NON/NON_EVALUE

    commentaire: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    checklist: Mapped[Checklist] = relationship("Checklist", back_populates="items")

    def valider_regles(self) -> None:
        if self.reponse == "NON":
            if not (self.commentaire and self.commentaire.strip()):
                raise ValueError("Commentaire obligatoire si réponse NON")
            if not (self.photo_path and self.photo_path.strip()):
                raise ValueError("Photo obligatoire si réponse NON")
