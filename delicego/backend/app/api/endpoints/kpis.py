from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.kpis import DashboardExecutif, KPIDashboardInpulse, KPITendance, StatutKPI
from app.domaine.services.dashboard import ServiceDashboardStock
from app.services.kpis_dashboard_service import KPIsDashboardService


routeur_kpis_interne = APIRouter(
    prefix="/kpis",
    tags=["kpis_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


def _statut_ecart_prevision(ecart_pct: float | None) -> StatutKPI:
    if ecart_pct is None:
        return StatutKPI(niveau="orange", message="Prévision non disponible")
    if ecart_pct >= -2.0:
        return StatutKPI(niveau="vert")
    if ecart_pct >= -8.0:
        return StatutKPI(niveau="orange")
    return StatutKPI(niveau="rouge")


def _statut_food_cost(food_cost_pct: float | None) -> StatutKPI:
    if food_cost_pct is None:
        return StatutKPI(niveau="orange", message="Food cost indisponible")
    if food_cost_pct <= 30.0:
        return StatutKPI(niveau="vert")
    if food_cost_pct <= 35.0:
        return StatutKPI(niveau="orange")
    return StatutKPI(niveau="rouge")


def _statut_marge(marge_pct: float | None) -> StatutKPI:
    if marge_pct is None:
        return StatutKPI(niveau="orange", message="Marge indisponible")
    if marge_pct >= 70.0:
        return StatutKPI(niveau="vert")
    if marge_pct >= 65.0:
        return StatutKPI(niveau="orange")
    return StatutKPI(niveau="rouge")


def _statut_pertes(pertes_eur: float | None) -> StatutKPI:
    if pertes_eur is None:
        return StatutKPI(niveau="orange", message="Pertes indisponibles")
    if pertes_eur <= 20.0:
        return StatutKPI(niveau="vert")
    if pertes_eur <= 80.0:
        return StatutKPI(niveau="orange")
    return StatutKPI(niveau="rouge")


def _statut_ruptures(nb: int, impact_eur: float | None) -> StatutKPI:
    if nb <= 0:
        return StatutKPI(niveau="vert")
    if nb <= 2:
        return StatutKPI(niveau="orange", message=f"{nb} rupture(s)")
    return StatutKPI(niveau="rouge", message=f"{nb} rupture(s)")


@routeur_kpis_interne.get("/dashboard-executif", response_model=DashboardExecutif)
async def dashboard_executif(
    date_cible: date,
    magasin_id: UUID | None = None,
    session: AsyncSession = Depends(fournir_session),
) -> DashboardExecutif:
    """Dashboard exécutif: KPI prioritaires + codes couleur + alertes.

    Objectif: en 30s savoir si le business est sous contrôle.

    - date_cible: date d'analyse
    - magasin_id: filtre site (optionnel)

    Note: seuils couleurs MVP (à paramétrer par client plus tard).
    """

    svc = KPIsDashboardService(session)
    k = await svc.calculer(date_cible=date_cible, magasin_id=magasin_id)

    kpis = KPIDashboardInpulse(
        date_cible=k.date_cible,
        ca_jour=KPITendance(valeur=k.ca_jour.valeur, variation_pct=k.ca_jour.variation_pct),
        ca_semaine=KPITendance(valeur=k.ca_semaine.valeur, variation_pct=k.ca_semaine.variation_pct),
        ca_mois=KPITendance(valeur=k.ca_mois.valeur, variation_pct=k.ca_mois.variation_pct),
        ecart_vs_prevision_pct=k.ecart_vs_prevision_pct,
        food_cost_reel_pct=k.food_cost_reel_pct,
        marge_brute_eur=k.marge_brute_eur,
        marge_brute_pct=k.marge_brute_pct,
        pertes_gaspillage_eur=k.pertes_gaspillage_eur,
        ruptures_produits_nb=k.ruptures_produits_nb,
        ruptures_impact_eur=k.ruptures_impact_eur,
        heures_economisees=k.heures_economisees,
    )

    statuts: dict[str, StatutKPI] = {
        "ecart_vs_prevision_pct": _statut_ecart_prevision(k.ecart_vs_prevision_pct),
        "food_cost_reel_pct": _statut_food_cost(k.food_cost_reel_pct),
        "marge_brute_pct": _statut_marge(k.marge_brute_pct),
        "pertes_gaspillage_eur": _statut_pertes(k.pertes_gaspillage_eur),
        "ruptures": _statut_ruptures(k.ruptures_produits_nb, k.ruptures_impact_eur),
    }

    # Alertes visibles sans cliquer: on réutilise le résumé stock bas + DLC proche.
    svc_stock = ServiceDashboardStock(session)
    resume = await svc_stock.obtenir_resume_alertes(date_cible=date_cible, seuil_stock_bas=2.0, delai_dlc_jours=2)

    alertes: list[str] = []
    if resume.stocks_bas > 0:
        alertes.append(f"Stocks bas: {resume.stocks_bas}")
    if resume.lots_proches_dlc > 0:
        alertes.append(f"DLC proches: {resume.lots_proches_dlc}")

    # KPI indisponibles => message
    if k.ecart_vs_prevision_pct is None:
        alertes.append("Prévision: non disponible")

    return DashboardExecutif(
        magasin_id=str(magasin_id) if magasin_id is not None else None,
        date_cible=date_cible,
        kpis=kpis,
        statuts=statuts,
        alertes=alertes,
    )
