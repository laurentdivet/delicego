from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domaine.modeles.base import BaseModele


class AuditLog(BaseModele):
    """Journal d'audit technique (append-only).

    Intention:
    - Toute action métier (ou technique) est traçable.
    - Append-only: aucune mise à jour / suppression.

    Note: l'immutabilité stricte se renforce côté DB (droits) + côté applicatif
    (pas d'endpoint d'update/delete, pas de session.delete sur ce modèle).
    """

    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Contrainte "toute action liée à un utilisateur".
    # On autorise nullable=True uniquement pour les cas techniques (ex: healthcheck)
    # mais notre middleware le remplira pour toutes routes protégées.
    user_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=True, index=True)

    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # rempli en DB via default

    # Descripteurs
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    ressource: Mapped[str] = mapped_column(String(120), nullable=False)
    ressource_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    methode_http: Mapped[str | None] = mapped_column(String(20), nullable=True)
    chemin: Mapped[str | None] = mapped_column(String(300), nullable=True)

    statut_http: Mapped[int | None] = mapped_column(nullable=True)

    # Données libres (immutable) pour enrichir l'audit.
    donnees: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ip: Mapped[str | None] = mapped_column(String(60), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User")


# Index déjà couvert par mapped_column(index=True) ci-dessus.
