from __future__ import annotations

from uuid import UUID
from pydantic import BaseModel


class MenuClientSchema(BaseModel):
    id: UUID
    nom: str
    description: str | None = None
    prix: float
    actif: bool
    disponible: bool = True

    class Config:
        from_attributes = True
