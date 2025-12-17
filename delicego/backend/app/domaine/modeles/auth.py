from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domaine.modeles.base import ModeleHorodate


class Role(ModeleHorodate):
    __tablename__ = "role"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    libelle: Mapped[str] = mapped_column(String(120), nullable=False)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class User(ModeleHorodate):
    __tablename__ = "user"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    nom_affiche: Mapped[str] = mapped_column(String(200), nullable=False)

    mot_de_passe_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    dernier_login_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    roles: Mapped[list["UserRole"]] = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserRole(ModeleHorodate):
    __tablename__ = "user_role"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role_user_id_role_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    role_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("role.id"), nullable=False, index=True)

    user: Mapped[User] = relationship("User", back_populates="roles")
    role: Mapped[Role] = relationship("Role")


# Indexes déjà couverts par mapped_column(index=True) ci-dessus.
