from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class StatutKPI(BaseModel):
    """Statut d'un KPI pour l'affichage exécutif (codes couleur)."""

    # "vert" | "orange" | "rouge"
    niveau: str
    # Court message affichable sans cliquer (bandeau alertes).
    message: str | None = None


class KPITendance(BaseModel):
    valeur: float
    # Variation vs période précédente (optionnel)
    variation_pct: float | None = None


class KPIDashboardInpulse(BaseModel):
    date_cible: date

    # KPI affichés en priorité (Inpulse)
    ca_jour: KPITendance
    ca_semaine: KPITendance
    ca_mois: KPITendance

    ecart_vs_prevision_pct: float | None = None

    food_cost_reel_pct: float | None = None
    marge_brute_eur: float | None = None
    marge_brute_pct: float | None = None

    pertes_gaspillage_eur: float | None = None

    ruptures_produits_nb: int
    ruptures_impact_eur: float | None = None

    heures_economisees: float | None = None


class DashboardExecutif(BaseModel):
    """Payload dashboard executif (KPI + alertes + statuts)."""

    magasin_id: str | None = None
    date_cible: date

    kpis: KPIDashboardInpulse

    # Codes couleur / statuts
    statuts: dict[str, StatutKPI]

    # Alertes visibles sans cliquer (bandeau)
    alertes: list[str]


class ReponseKPIDashboardInpulse(BaseModel):
    magasin_id: str | None = None
    kpis: KPIDashboardInpulse
