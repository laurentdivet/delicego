from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domaine.modeles.base import ModeleHorodate


class Produit(ModeleHorodate):
    """Produit (catalogue).

    Règle métier fondamentale:
    - PRODUIT = article acheté chez un fournisseur (conditionnement, référence, prix)
    - INGRÉDIENT = quantité consommée d’un produit dans une recette
    """

    __tablename__ = "produit"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    libelle: Mapped[str] = mapped_column(
        String(250),
        nullable=False,
        unique=True,
        index=True,
        comment="Nom métier unique du produit.",
    )

    categorie: Mapped[str | None] = mapped_column(String(120), nullable=True)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ProduitFournisseur(ModeleHorodate):
    """Association Produit <-> Fournisseur avec attributs."""

    __tablename__ = "produit_fournisseur"
    __table_args__ = (
        # NB: un fournisseur vend plusieurs produits: pas d'unicité sur (produit_id, fournisseur_id).
        # L'idempotence import est assurée par (fournisseur_id, reference_fournisseur).
        Index("ix_produit_fournisseur_produit_id", "produit_id"),
        Index("ix_produit_fournisseur_fournisseur_id", "fournisseur_id"),
        # Un SKU fournisseur doit être unique *pour un fournisseur*, sinon l'import idempotent est impossible.
        UniqueConstraint("fournisseur_id", "reference_fournisseur", name="uq_produit_fournisseur_sku"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    produit_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("produit.id"), nullable=False)
    fournisseur_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fournisseur.id"), nullable=False)

    reference_fournisseur: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        comment="SKU / référence chez le fournisseur",
    )

    libelle_fournisseur: Mapped[str | None] = mapped_column(String(250), nullable=True)

    unite_achat: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Unité d'achat (kg, pièce, carton, sac, bidon, etc.)",
    )

    quantite_par_unite: Mapped[float] = mapped_column(
        nullable=False,
        default=1.0,
        comment="Quantité contenue dans l'unité d'achat (ex: 20 pour SAC 20KG).",
    )

    prix_achat_ht: Mapped[float | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="Prix HT pour l'unité d'achat.",
    )

    tva: Mapped[float | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
        comment="Taux de TVA (ex: 0.055, 0.10, 0.20).",
    )

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    produit: Mapped[Produit] = relationship("Produit")
    fournisseur = relationship("Fournisseur")
