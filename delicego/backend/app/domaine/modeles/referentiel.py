from __future__ import annotations

from uuid import uuid4

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Enum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domaine.modeles.base import ModeleHorodate
from app.domaine.enums.types import TypeMagasin


class Magasin(ModeleHorodate):
    """
    Un magasin représente un site physique.

    - PRODUCTION : site de production central (ex : Escat)
    - VENTE : point de vente
    """

    __tablename__ = "magasin"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    nom: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    type_magasin: Mapped[TypeMagasin] = mapped_column(
        Enum(TypeMagasin, name="type_magasin"),
        nullable=False,
    )

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Utilisateur(ModeleHorodate):
    __tablename__ = "utilisateur"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    nom_affiche: Mapped[str] = mapped_column(String(200), nullable=False)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Fournisseur(ModeleHorodate):
    __tablename__ = "fournisseur"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    nom: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Ingredient(ModeleHorodate):
    """
    Ingrédient de base utilisé dans les recettes.
    """

    __tablename__ = "ingredient"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    nom: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    unite_stock: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Unité utilisée pour le stock (ex : kg, g, l, pièce)",
    )

    unite_mesure: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Unité de mesure de référence pour les calculs",
    )

    cout_unitaire: Mapped[float] = mapped_column(
        nullable=False,
        default=0.0,
        comment="Coût unitaire dans l’unité de mesure (ex: €/kg, €/L, €/pièce)",
    )

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Menu(ModeleHorodate):
    """Un menu représente un produit vendable (LOCAL, par magasin).

    Alignement Inpulse-like:
    - Le menu porte le prix et la disponibilité (actif/commandable)
    - Le menu référence une Recette (globale)
    """

    __tablename__ = "menu"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    nom: Mapped[str] = mapped_column(String(200), nullable=False)

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Description courte pour l’affichage client",
    )

    prix: Mapped[float] = mapped_column(
        nullable=False,
        default=0.0,
        comment="Prix TTC en euros (provisoire)",
    )

    commandable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Menu vendable / commandable côté client",
    )

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    magasin_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("magasin.id"),
        nullable=False,
    )
    magasin: Mapped[Magasin] = relationship()

    recette_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recette.id"),
        nullable=False,
    )
    recette: Mapped["Recette"] = relationship("Recette", back_populates="menus")


class Recette(ModeleHorodate):
    """Recette GLOBALE (métier), réutilisable par plusieurs menus et magasins."""

    __tablename__ = "recette"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    nom: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    # L'ancien champ `menu_id` reste en base (nullable) pour compat migration/downgrade,
    # mais on ne le mappe plus en ORM pour éviter une dépendance circulaire Menu<->Recette
    # qui casse les tests (drop_all).

    menus: Mapped[list[Menu]] = relationship("Menu", back_populates="recette")


class LigneRecette(ModeleHorodate):
    """
    Ligne de composition d’une recette (BOM).
    """

    __tablename__ = "ligne_recette"
    __table_args__ = (
        UniqueConstraint(
            "recette_id",
            "ingredient_id",
            name="uq_ligne_recette_recette_ingredient",
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    recette_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recette.id"),
        nullable=False,
    )
    recette: Mapped[Recette] = relationship()

    ingredient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingredient.id"),
        nullable=False,
    )
    ingredient: Mapped[Ingredient] = relationship()

    quantite: Mapped[float] = mapped_column(
        nullable=False,
        comment="Quantité d’ingrédient nécessaire pour la recette",
    )

    unite: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Unité utilisée pour cette ligne de recette",
    )


# Index pour les performances et la cohérence
Index("ix_menu_magasin_id", Menu.magasin_id)
Index("ix_menu_recette_id", Menu.recette_id)
Index("ix_ligne_recette_recette_id", LigneRecette.recette_id)
Index("ix_ligne_recette_ingredient_id", LigneRecette.ingredient_id)
