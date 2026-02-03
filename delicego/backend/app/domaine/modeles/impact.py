from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domaine.modeles.base import ModeleHorodate


class PerteCasse(ModeleHorodate):
    """Événement de pertes / casse.

    Objectif : traçabilité simple, orientée KPI.
    - quantité + unité
    - date (jour)
    - magasin
    - ingrédient optionnel (si perte attribuable)
    - cause libre (texte)

    NOTE : on ne force pas l'utilisation de MouvementStock ici.
    Les pertes opérationnelles peuvent être saisies a posteriori.
    """

    __tablename__ = "perte_casse"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("magasin.id"), nullable=False)
    ingredient_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingredient.id"),
        nullable=True,
        comment="Optionnel : ingrédient concerné si la perte est attribuable.",
    )

    jour: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)

    quantite: Mapped[float] = mapped_column(nullable=False)
    unite: Mapped[str] = mapped_column(String(50), nullable=False)

    cause: Mapped[str | None] = mapped_column(String(200), nullable=True)

    creee_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    magasin = relationship("Magasin")
    ingredient = relationship("Ingredient")


class FacteurCO2(ModeleHorodate):
    """Facteur CO2e indicatif (configurable) par *catégorie*.

    Exemple :
    - categorie = "viande"
    - facteur_kgco2e_par_kg = 20.0

    IMPORTANT :
    - Valeurs indicatives par défaut uniquement.
    - Le but est d'avoir un mécanisme de remplacement facile plus tard.
    """

    __tablename__ = "facteur_co2"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    categorie: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    facteur_kgco2e_par_kg: Mapped[float] = mapped_column(
        nullable=False,
        comment="kgCO2e / kg (valeur indicative).",
    )

    source: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Source/justification (optionnel) pour traçabilité.",
    )


class IngredientImpact(ModeleHorodate):
    """Mapping minimal Ingredient -> catégorie CO2.

    But : pouvoir agréger des émissions par jour via les réceptions.
    """

    __tablename__ = "ingredient_impact"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    ingredient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingredient.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    categorie_co2: Mapped[str] = mapped_column(String(120), nullable=False)

    ingredient = relationship("Ingredient")

    __table_args__ = (
        UniqueConstraint("ingredient_id", name="uq_ingredient_impact_ingredient"),
        Index("ix_ingredient_impact_categorie", "categorie_co2"),
    )
