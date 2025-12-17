from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class CoutMenuSchema(BaseModel):
    menu_id: UUID
    cout: float
    prix: float
    marge: float
    taux_marge: float

    class Config:
        from_attributes = True
