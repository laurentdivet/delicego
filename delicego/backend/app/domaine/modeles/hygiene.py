from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domaine.enums.types import TypeEquipementThermique, ZoneEquipementThermique
from app.domaine.modeles.base import ModeleHorodate


class EquipementThermique(ModeleHorodate):
    __tablename__ = "equipement_thermique"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("magasin.id"), nullable=False)

    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    type_equipement: Mapped[TypeEquipementThermique] = mapped_column(nullable=False)
    zone: Mapped[ZoneEquipementThermique] = mapped_column(nullable=False)

    temperature_min: Mapped[float | None] = mapped_column(nullable=True)
    temperature_max: Mapped[float | None] = mapped_column(nullable=True)

    magasin = relationship("Magasin")


class ReleveTemperature(ModeleHorodate):
    __tablename__ = "releve_temperature"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    equipement_thermique_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipement_thermique.id"), nullable=False
    )

    releve_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    temperature: Mapped[float] = mapped_column(nullable=False)

    commentaire: Mapped[str | None] = mapped_column(String(500), nullable=True)

    equipement_thermique = relationship("EquipementThermique")


class ControleHACCP(ModeleHorodate):
    __tablename__ = "controle_haccp"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("magasin.id"), nullable=False)

    controle_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    type_controle: Mapped[str] = mapped_column(String(120), nullable=False)

    resultat: Mapped[str | None] = mapped_column(String(500), nullable=True)

    magasin = relationship("Magasin")


class NonConformiteHACCP(ModeleHorodate):
    """Non-conformité détectée (température, DLC, etc.)."""

    __tablename__ = "non_conformite_haccp"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("magasin.id"), nullable=False)

    detectee_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    type_non_conformite: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        comment="TEMP_HORS_SEUIL, DLC_DEPASSEE, etc.",
    )

    reference: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Référence externe (ex: lot_id, equipement_id).",
    )

    description: Mapped[str] = mapped_column(String(500), nullable=False)

    statut: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="OUVERTE",
        comment="OUVERTE/CLOTUREE",
    )

    magasin = relationship("Magasin")


class ActionCorrective(ModeleHorodate):
    """Action corrective liée à une non-conformité."""

    __tablename__ = "action_corrective"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    non_conformite_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("non_conformite_haccp.id"),
        nullable=False,
    )

    creee_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    description: Mapped[str] = mapped_column(String(500), nullable=False)

    realisee: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    non_conformite = relationship("NonConformiteHACCP")


class JournalNettoyage(ModeleHorodate):
    __tablename__ = "journal_nettoyage"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("magasin.id"), nullable=False)

    realise_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    zone: Mapped[str] = mapped_column(String(120), nullable=False)

    commentaire: Mapped[str | None] = mapped_column(String(500), nullable=True)

    magasin = relationship("Magasin")


Index("ix_releve_temperature_releve_le", ReleveTemperature.releve_le)
Index("ix_controle_haccp_controle_le", ControleHACCP.controle_le)
Index("ix_journal_nettoyage_realise_le", JournalNettoyage.realise_le)
