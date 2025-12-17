from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domaine.enums.types import StatutCommandeFournisseur


class RequeteCreerCommandeFournisseur(BaseModel):
    fournisseur_id: UUID
    date_commande: datetime | None = None
    commentaire: str | None = None


class ReponseCreerCommandeFournisseur(BaseModel):
    commande_fournisseur_id: UUID


class RequeteAjouterLigneCommandeFournisseur(BaseModel):
    ingredient_id: UUID
    quantite: float
    unite: str


class ReponseAjouterLigneCommandeFournisseur(BaseModel):
    ligne_commande_fournisseur_id: UUID


class RequeteReceptionnerCommandeFournisseur(BaseModel):
    magasin_id: UUID
    reference_externe: str | None = None
    commentaire: str | None = None
    # optionnel : override lignes de réception
    lignes: list[RequeteAjouterLigneCommandeFournisseur] = Field(default_factory=list)


class RequeteEnvoyerCommandeFournisseurEmail(BaseModel):
    destinataire: str
    sujet: str
    corps: str


class RequeteGenererBesoinsFournisseurs(BaseModel):
    magasin_id: UUID
    date_cible: date
    horizon: int = 7


class ReponseCommandeFournisseur(BaseModel):
    commande_fournisseur_id: UUID
    statut: StatutCommandeFournisseur


class ReponseGenererBesoinsFournisseurs(BaseModel):
    commandes_ids: list[UUID]
