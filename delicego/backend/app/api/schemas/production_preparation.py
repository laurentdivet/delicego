from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel


# ==============================
# Contrat API figé (écran cuisine)
# ==============================


class ReponseCreneauQuantite(BaseModel):
    debut: str  # "HH:MM"
    fin: str  # "HH:MM"
    quantite: float


class ReponseLigneCuisine(BaseModel):
    recette_id: str
    recette_nom: str

    quantite_planifiee: float
    quantite_produite: float

    statut: str  # "A_PRODUIRE" | "PRODUIT" | "AJUSTE" | "NON_PRODUIT"


class ReponseLectureProductionPreparation(BaseModel):
    quantites_a_produire_aujourdhui: float
    quantites_par_creneau: list[ReponseCreneauQuantite]
    cuisine: list[ReponseLigneCuisine]


# ==============================
# Contrat API (scan gencode)
# ==============================


class RequeteScanGencode(BaseModel):
    gencode: str
    magasin_id: UUID
    date: date


class ReponseLigneProductionScan(BaseModel):
    id: str
    produit_nom: str
    a_produire: float
    produit: float
    restant: float


class RequeteActionProduit(BaseModel):
    magasin_id: UUID
    date: date
    recette_id: UUID


class RequeteActionAjuste(BaseModel):
    magasin_id: UUID
    date: date
    recette_id: UUID
    quantite: float


class RequeteActionNonProduit(BaseModel):
    magasin_id: UUID
    date: date
    recette_id: UUID


class EvenementTraceabilite(BaseModel):
    type: str  # "PRODUIT" | "AJUSTE" | "NON_PRODUIT"
    date_heure: str
    quantite: float | None
    lot_production_id: str | None


class ReponseTraceabiliteProductionPreparation(BaseModel):
    evenements: list[EvenementTraceabilite]


class ReponseScanGencode(BaseModel):
    ligne: ReponseLigneProductionScan
