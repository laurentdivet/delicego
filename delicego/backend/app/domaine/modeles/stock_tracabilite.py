from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domaine.enums.types import TypeMouvementStock
from app.domaine.modeles.base import ModeleHorodate


class Lot(ModeleHorodate):
    """
    Lot de traçabilité.

    IMPORTANT :
    - Un lot ne stocke JAMAIS de quantité calculée.
    - La quantité disponible est obtenue par la somme des mouvements associés.
    """

    __tablename__ = "lot"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("magasin.id"),
        nullable=False,
    )

    ingredient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingredient.id"),
        nullable=False,
    )


    fournisseur_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fournisseur.id"),
        nullable=True,
    )

    code_lot: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        comment="Code lot fournisseur si disponible",
    )

    date_dlc: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="Date limite de consommation",
    )

    unite: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Unité du lot (kg, g, l, pièce, etc.)",
    )

    magasin = relationship("Magasin")
    ingredient = relationship("Ingredient")
    fournisseur = relationship("Fournisseur")

    __table_args__ = (
        UniqueConstraint(
            "magasin_id",
            "ingredient_id",
            "fournisseur_id",
            "code_lot",
            name="uq_lot_magasin_ingredient_fournisseur_code",
        ),
        Index("ix_lot_date_dlc", "date_dlc"),
    )


class MouvementStock(ModeleHorodate):
    """
    Mouvement de stock immuable.

    RÈGLE D’OR :
    - AUCUNE modification de stock sans MouvementStock.
    - Les mouvements sont immuables (jamais modifiés, jamais supprimés).
    """

    __tablename__ = "mouvement_stock"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    type_mouvement: Mapped[TypeMouvementStock] = mapped_column(
        Enum(TypeMouvementStock, name="type_mouvement_stock", native_enum=False, length=50),
        nullable=False,
    )

    horodatage: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    magasin_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("magasin.id"),
        nullable=False,
    )

    ingredient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingredient.id"),
        nullable=False,
    )


    lot_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lot.id"),
        nullable=True,
        comment="Lot concerné (obligatoire pour la consommation FEFO)",
    )

    quantite: Mapped[float] = mapped_column(
        nullable=False,
        comment="Quantité absolue du mouvement (toujours positive)",
    )

    unite: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    reference_externe: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        comment="Référence externe (commande, production, perte, etc.)",
    )

    commentaire: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    magasin = relationship("Magasin")
    ingredient = relationship("Ingredient")
    lot = relationship("Lot")


Index("ix_mouvement_stock_horodatage", MouvementStock.horodatage)
Index("ix_mouvement_stock_type", MouvementStock.type_mouvement)
Index("ix_mouvement_stock_lot_id", MouvementStock.lot_id)
