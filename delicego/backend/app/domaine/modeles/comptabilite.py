from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, Enum, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domaine.enums.types import TypeEcritureComptable
from app.domaine.modeles.base import ModeleHorodate


class EcritureComptable(ModeleHorodate):
    """Écriture comptable (projection pour Pennylane).

    Règles :
    - Lecture/traçabilité uniquement : aucune logique métier.
    - `reference_interne` pointe vers l’ID métier d’origine (commande, achat…).
    """

    __tablename__ = "ecriture_comptable"

    __table_args__ = (
        UniqueConstraint(
            "type",
            "reference_interne",
            "compte_comptable",
            name="uq_ecriture_type_reference_compte",
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    date_ecriture: Mapped[date] = mapped_column(Date, nullable=False)

    type: Mapped[TypeEcritureComptable] = mapped_column(
        Enum(TypeEcritureComptable, name="type_ecriture_comptable", native_enum=False, length=50),
        nullable=False,
    )

    reference_interne: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        comment="UUID (ou identifiant) de la source interne (commande, achat, etc.)",
    )

    montant_ht: Mapped[float] = mapped_column(nullable=False)
    tva: Mapped[float] = mapped_column(nullable=False)

    compte_comptable: Mapped[str] = mapped_column(String(20), nullable=False)

    exportee: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class JournalComptable(ModeleHorodate):
    """Journal comptable (résumé d’une génération).

    - Période : date_debut / date_fin
    - Totaux : ventes/achats (HT)
    - date_generation : horodatage de génération
    """

    __tablename__ = "journal_comptable"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)

    total_ventes: Mapped[float] = mapped_column(nullable=False, default=0.0)
    total_achats: Mapped[float] = mapped_column(nullable=False, default=0.0)

    date_generation: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


Index("ix_ecriture_comptable_date", EcritureComptable.date_ecriture)
Index("ix_ecriture_comptable_exportee", EcritureComptable.exportee)
Index("ix_journal_comptable_periode", JournalComptable.date_debut, JournalComptable.date_fin)
