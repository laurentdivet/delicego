from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class RequeteGenerationComptabilite(BaseModel):
    date_debut: date
    date_fin: date


class ReponseGenerationComptabilite(BaseModel):
    nombre_ecritures: int
    journal_id: UUID


class EcritureComptableLecture(BaseModel):
    id: UUID
    date_ecriture: date
    type: str
    reference_interne: str
    montant_ht: float
    tva: float
    compte_comptable: str
    exportee: bool


class JournalComptableLecture(BaseModel):
    id: UUID
    date_debut: date
    date_fin: date
    total_ventes: float
    total_achats: float
    date_generation: datetime
