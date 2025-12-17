from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class MagasinClientSchema(BaseModel):
    id: UUID
    nom: str

    class Config:
        from_attributes = True
