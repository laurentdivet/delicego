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

from app.domaine.enums.types import StatutPlanProduction
from app.domaine.modeles.base import ModeleHorodate


class PlanProduction(ModeleHorodate):
    """
    Plan de production journalier par magasin.

    Règle métier :
    - Un seul plan par magasin et par jour.
    """

    __tablename__ = "plan_production"
    __table_args__ = (
        UniqueConstraint(
            "magasin_id",
            "date_plan",
            name="uq_plan_production_magasin_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("magasin.id"),
        nullable=False,
    )

    date_plan: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    statut: Mapped[StatutPlanProduction] = mapped_column(
        Enum(StatutPlanProduction, name="statut_plan_production"),
        nullable=False,
        default=StatutPlanProduction.BROUILLON,
    )

    magasin = relationship("Magasin")


class LignePlanProduction(ModeleHorodate):
    """
    Ligne de planification d’une recette dans un plan de production.
    """

    __tablename__ = "ligne_plan_production"
    __table_args__ = (
        UniqueConstraint(
            "plan_production_id",
            "recette_id",
            name="uq_ligne_plan_production_plan_recette",
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    plan_production_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plan_production.id"),
        nullable=False,
    )

    recette_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recette.id"),
        nullable=False,
    )

    quantite_a_produire: Mapped[float] = mapped_column(
        nullable=False,
        comment="Quantité planifiée à produire",
    )

    plan_production = relationship("PlanProduction")
    recette = relationship("Recette")


class LotProduction(ModeleHorodate):
    """
    Lot de production réel (exécution du plan ou production hors plan).
    """

    __tablename__ = "lot_production"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("magasin.id"),
        nullable=False,
    )

    plan_production_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plan_production.id"),
        nullable=True,
        comment="Null si production hors plan",
    )

    recette_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recette.id"),
        nullable=False,
    )

    produit_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    quantite_produite: Mapped[float] = mapped_column(
        nullable=False,
        comment="Quantité réellement produite",
    )

    unite: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    magasin = relationship("Magasin")
    plan_production = relationship("PlanProduction")
    recette = relationship("Recette")


class LigneConsommation(ModeleHorodate):
    """
    Consommation réelle d’ingrédients pour un lot de production.

    Chaque ligne correspond à une allocation FEFO effective.
    """

    __tablename__ = "ligne_consommation"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    lot_production_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lot_production.id"),
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
        comment="Lot consommé (FEFO)",
    )

    mouvement_stock_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mouvement_stock.id"),
        nullable=True,
        comment="Mouvement de stock généré",
    )

    quantite: Mapped[float] = mapped_column(
        nullable=False,
    )

    unite: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    lot_production = relationship("LotProduction")
    ingredient = relationship("Ingredient")
    lot = relationship("Lot")
    mouvement_stock = relationship("MouvementStock")


Index("ix_plan_production_date_plan", PlanProduction.date_plan)
Index("ix_lot_production_produit_le", LotProduction.produit_le)
Index("ix_ligne_consommation_lot_production", LigneConsommation.lot_production_id)
