from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class CreneauQuantite(BaseModel):
    """Quantités à produire par créneau horaire (MVP)."""

    code: str  # ex: "MATIN", "MIDI", "SOIR"
    libelle: str
    quantite_a_produire: float


class KPIProductionPreparation(BaseModel):
    date_plan: date
    plan_production_id: str
    magasin_id: str

    quantite_totale_a_produire: float
    quantite_totale_produite: float
    quantite_restante: float

    quantites_par_creneau: list[CreneauQuantite]

    # MVP : on garde des champs optionnels, à brancher sur une vraie valorisation (coût matière / marge / POS).
    surproduction_evitee_eur: float | None = None
    sous_production_evitee_eur: float | None = None


class LigneProductionCuisine(BaseModel):
    recette_id: str
    recette_nom: str

    quantite_planifiee: float
    quantite_produite: float

    statut: str  # "A_PRODUIRE" | "PRODUIT" | "AJUSTE" | "NON_PRODUIT"

    dernier_lot_production_id: str | None = None


class ReponseProductionCuisine(BaseModel):
    kpis: KPIProductionPreparation
    lignes: list[LigneProductionCuisine]


class RequeteActionCuisine(BaseModel):
    plan_production_id: str
    recette_id: str


class RequeteAjusterCuisine(RequeteActionCuisine):
    quantite: float


class ReponseActionCuisine(BaseModel):
    lot_production_id: str
    nb_mouvements_stock: int | None = None
    nb_lignes_consommation: int | None = None
