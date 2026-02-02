from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domaine.enums.types import StatutCommandeClient
from app.domaine.modeles.base import ModeleHorodate


class CommandeClient(ModeleHorodate):
    """Commande passée par un client externe (canal en ligne).

    IMPORTANT :
    - Ce modèle n’embarque pas de logique métier.
    - L’exécution (réservation/production/stock) est gérée par un service dédié.
    """

    __tablename__ = "commande_client"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("magasin.id"),
        nullable=False,
    )

    date_commande: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    statut: Mapped[StatutCommandeClient] = mapped_column(
        Enum(StatutCommandeClient, name="statut_commande_client", native_enum=False, length=50),
        nullable=False,
        default=StatutCommandeClient.EN_ATTENTE,
    )

    commentaire: Mapped[str | None] = mapped_column(String(500), nullable=True)

    lignes = relationship("LigneCommandeClient", back_populates="commande_client")
    magasin = relationship("Magasin")


class LigneCommandeClient(ModeleHorodate):
    """Ligne de commande : un menu et une quantité."""

    __tablename__ = "ligne_commande_client"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    commande_client_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("commande_client.id"),
        nullable=False,
    )

    menu_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu.id"),
        nullable=False,
    )

    quantite: Mapped[float] = mapped_column(nullable=False)

    # Lien vers le lot de production créé pour cette ligne.
    # (Permet la traçabilité sans modifier les modèles existants.)
    lot_production_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lot_production.id"),
        nullable=True,
    )

    commande_client = relationship("CommandeClient", back_populates="lignes")
    menu = relationship("Menu")
    lot_production = relationship("LotProduction")


Index("ix_commande_client_date", CommandeClient.date_commande)
Index("ix_ligne_commande_client_commande", LigneCommandeClient.commande_client_id)
