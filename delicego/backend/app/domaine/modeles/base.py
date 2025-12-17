from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class BaseModele(DeclarativeBase):
    """Base declarative SQLAlchemy.

    Les noms d’attributs restent en français, conformément aux règles.
    """


class ModeleHorodate(BaseModele):
    """Mixin de dates techniques."""

    __abstract__ = True

    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    mis_a_jour_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
