from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
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


class ImpactRecommendationEvent(ModeleHorodate):
    """Event de recommandation (source: moteur Impact).

    Table existante en DB: `impact_recommendation_event`.
    """

    __tablename__ = "impact_recommendation_event"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    code: Mapped[str] = mapped_column(String(120), nullable=False)
    metric: Mapped[str] = mapped_column(String(120), nullable=False)
    entities_signature: Mapped[str] = mapped_column(String(64), nullable=False)

    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    entities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrences: Mapped[int] = mapped_column(nullable=False)

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)

    actions: Mapped[list[ImpactAction]] = relationship(
        "ImpactAction",
        back_populates="recommendation_event",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ImpactAction(ModeleHorodate):
    """Action manuelle associée à une recommandation.

    Table existante en DB: `impact_action`.
    """

    __tablename__ = "impact_action"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    recommendation_event_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("impact_recommendation_event.id"),
        nullable=False,
    )

    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expected_impact: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # B3: actions exploitables
    assignee: Mapped[str | None] = mapped_column(String(120), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # convention: 1=LOW, 2=MEDIUM, 3=HIGH
    priority: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        comment="Horodatage applicatif (remplace/complète mis_a_jour_le).",
    )

    recommendation_event: Mapped[ImpactRecommendationEvent] = relationship(
        "ImpactRecommendationEvent",
        back_populates="actions",
    )
