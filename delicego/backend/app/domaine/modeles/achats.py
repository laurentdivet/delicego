from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String

from app.domaine.enums.types import StatutCommandeFournisseur
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domaine.modeles.base import ModeleHorodate


class CommandeAchat(ModeleHorodate):
    __tablename__ = "commande_achat"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("magasin.id"), nullable=False)
    fournisseur_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fournisseur.id"), nullable=False)

    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    creee_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    magasin = relationship("Magasin")
    fournisseur = relationship("Fournisseur")


class LigneCommandeAchat(ModeleHorodate):
    __tablename__ = "ligne_commande_achat"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    commande_achat_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commande_achat.id"), nullable=False
    )
    ingredient_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredient.id"), nullable=False)

    quantite: Mapped[float] = mapped_column(nullable=False)
    unite: Mapped[str] = mapped_column(String(50), nullable=False)

    commande_achat = relationship("CommandeAchat")
    ingredient = relationship("Ingredient")


class ReceptionMarchandise(ModeleHorodate):
    __tablename__ = "reception_marchandise"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("magasin.id"), nullable=False)
    fournisseur_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fournisseur.id"), nullable=False)

    commande_achat_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commande_achat.id"), nullable=True
    )

    recu_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    magasin = relationship("Magasin")
    fournisseur = relationship("Fournisseur")
    commande_achat = relationship("CommandeAchat")


class LigneReceptionMarchandise(ModeleHorodate):
    __tablename__ = "ligne_reception_marchandise"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    reception_marchandise_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reception_marchandise.id"), nullable=False
    )
    ingredient_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredient.id"), nullable=False)

    lot_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("lot.id"), nullable=True)
    mouvement_stock_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mouvement_stock.id"), nullable=True
    )

    quantite: Mapped[float] = mapped_column(nullable=False)
    unite: Mapped[str] = mapped_column(String(50), nullable=False)

    reception_marchandise = relationship("ReceptionMarchandise")
    ingredient = relationship("Ingredient")
    lot = relationship("Lot")
    mouvement_stock = relationship("MouvementStock")



class CommandeFournisseur(ModeleHorodate):
    """Commande fournisseur métier.

    IMPORTANT :
    - Aucune écriture stock à la création.
    - Le stock n’est impacté que lors de la réception.
    """

    __tablename__ = "commande_fournisseur"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    fournisseur_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fournisseur.id"), nullable=False)

    date_commande: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    statut: Mapped[StatutCommandeFournisseur] = mapped_column(
        Enum(StatutCommandeFournisseur, name="statut_commande_fournisseur"),
        nullable=False,
        default=StatutCommandeFournisseur.BROUILLON,
    )

    commentaire: Mapped[str | None] = mapped_column(String(500), nullable=True)

    fournisseur = relationship("Fournisseur")


class LigneCommandeFournisseur(ModeleHorodate):
    __tablename__ = "ligne_commande_fournisseur"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    commande_fournisseur_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commande_fournisseur.id"), nullable=False
    )
    ingredient_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredient.id"), nullable=False)

    quantite: Mapped[float] = mapped_column(nullable=False)
    quantite_recue: Mapped[float] = mapped_column(nullable=False, default=0.0)
    unite: Mapped[str] = mapped_column(String(50), nullable=False)

    commande_fournisseur = relationship("CommandeFournisseur")
    ingredient = relationship("Ingredient")


Index("ix_commande_achat_creee_le", CommandeAchat.creee_le)
Index("ix_reception_marchandise_recu_le", ReceptionMarchandise.recu_le)
Index("ix_commande_fournisseur_date_commande", CommandeFournisseur.date_commande)
