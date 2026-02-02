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
        Enum(TypeMagasin, name="type_magasin", native_enum=False, length=50),
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

    # ⬇️ SEULE CORRECTION : renommage du champ
    unite_consommation: Mapped[str] = mapped_column(
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


class IngredientAlias(ModeleHorodate):
    """Alias d'un ingrédient de référence.

    Objectif: mapper des libellés bruts (PDF, saisie manuelle, etc.) vers Ingredient,
    de manière déterministe et sans jamais créer d'ingrédient automatiquement.
    """

    __tablename__ = "ingredient_alias"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    alias: Mapped[str] = mapped_column(
        String(),
        nullable=False,
        comment="Texte brut original (ex: issu d'un PDF)",
    )
    alias_normalise: Mapped[str] = mapped_column(
        String(),
        nullable=False,
        unique=True,
        index=True,
        comment="Texte normalisé (unique) destiné au matching",
    )

    ingredient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingredient.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ingredient: Mapped[Ingredient] = relationship()

    source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="Ex: 'pdf', 'manual', 'auto'",
    )

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Menu(ModeleHorodate):
    """Un menu représente un produit vendable (LOCAL, par magasin)."""

    __tablename__ = "menu"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    nom: Mapped[str] = mapped_column(String(200), nullable=False)

    gencode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        unique=True,
        index=True,
        default=lambda: f"AUTO-{uuid4().hex[:27]}",
        comment="Clé machine scannée (EAN/UPC). Ne jamais afficher à l'écran.",
    )

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
    __tablename__ = "recette"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    nom: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    menus: Mapped[list[Menu]] = relationship("Menu", back_populates="recette")


class LigneRecette(ModeleHorodate):
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

    quantite: Mapped[float] = mapped_column(nullable=False)

    unite: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Unité utilisée pour cette ligne de recette",
    )


Index("ix_menu_magasin_id", Menu.magasin_id)
Index("ix_menu_recette_id", Menu.recette_id)
Index("ix_ligne_recette_recette_id", LigneRecette.recette_id)
Index("ix_ligne_recette_ingredient_id", LigneRecette.ingredient_id)


class LigneRecetteImportee(ModeleHorodate):
    """Staging des lignes issues de PDFs.

    Choix structurel: `ligne_recette.ingredient_id` est NOT NULL.
    On conserve donc les lignes PDF ici (ingredient_id nullable + libellés brut/normalisé).
    """

    __tablename__ = "ligne_recette_importee"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    recette_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recette.id", ondelete="CASCADE"),
        nullable=False,
    )
    recette: Mapped[Recette] = relationship()

    pdf: Mapped[str] = mapped_column(String(), nullable=False)
    ingredient_brut: Mapped[str] = mapped_column(String(), nullable=False)
    ingredient_normalise: Mapped[str] = mapped_column(String(), nullable=False, index=True)

    quantite: Mapped[float] = mapped_column(nullable=False)
    unite: Mapped[str] = mapped_column(String(50), nullable=False)

    ordre: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="Ordre stable de la ligne dans la recette (0..N-1)",
    )

    ingredient_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingredient.id", ondelete="RESTRICT"),
        nullable=True,
    )
    ingredient: Mapped[Ingredient | None] = relationship()

    statut_mapping: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="mapped|unmapped",
    )


Index("ix_ligne_recette_importee_recette_id", LigneRecetteImportee.recette_id)
Index("ix_ligne_recette_importee_statut_mapping", LigneRecetteImportee.statut_mapping)
