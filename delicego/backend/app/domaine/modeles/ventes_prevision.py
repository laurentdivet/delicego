from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domaine.enums.types import CanalVente
from app.domaine.modeles.base import ModeleHorodate


class Vente(ModeleHorodate):
    __tablename__ = "vente"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("magasin.id"), nullable=False)
    date_vente: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    canal: Mapped[CanalVente] = mapped_column(nullable=False)

    menu_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("menu.id"), nullable=True)

    quantite: Mapped[float] = mapped_column(nullable=False, default=1.0)

    magasin = relationship("Magasin")
    menu = relationship("Menu")


class ExecutionPrevision(ModeleHorodate):
    __tablename__ = "execution_prevision"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    magasin_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("magasin.id"), nullable=False)

    creee_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    magasin = relationship("Magasin")


class LignePrevision(ModeleHorodate):
    __tablename__ = "ligne_prevision"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    execution_prevision_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_prevision.id"), nullable=False
    )

    date_prevue: Mapped[date] = mapped_column(Date, nullable=False)

    menu_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("menu.id"), nullable=False)
    quantite_prevue: Mapped[float] = mapped_column(nullable=False)

    execution_prevision = relationship("ExecutionPrevision")
    menu = relationship("Menu")


Index("ix_vente_date_vente", Vente.date_vente)
Index("ix_ligne_prevision_date_prevue", LignePrevision.date_prevue)
