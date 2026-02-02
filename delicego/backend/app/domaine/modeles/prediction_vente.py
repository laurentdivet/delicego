from __future__ import annotations

from datetime import date
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domaine.modeles.base import ModeleHorodate


class PredictionVente(ModeleHorodate):
    """Sortie du pipeline ML: quantités prévues par jour / magasin / menu.

    Table créée par migration Alembic `9c1c1ab7b2c1_add_prediction_vente_table`.
    """

    __tablename__ = "prediction_vente"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    magasin_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("magasin.id"), nullable=False)
    menu_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("menu.id"), nullable=False)

    date_jour: Mapped[date] = mapped_column(Date, nullable=False)
    qte_predite: Mapped[float] = mapped_column(nullable=False)

    modele_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    cree_le: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    mis_a_jour_le: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)

    magasin = relationship("Magasin")
    menu = relationship("Menu")


Index("ix_prediction_vente_date_magasin", PredictionVente.date_jour, PredictionVente.magasin_id)
