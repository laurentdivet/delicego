from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    id: UUID


class DocumentValidateResponse(BaseModel):
    id: UUID
    validated: bool


class DocumentReadSchema(BaseModel):
    id: UUID
    category_id: UUID
    etablissement_id: UUID
    filename: str
    filepath: str
    uploaded_at: datetime
    uploaded_by: UUID
    validated: bool
