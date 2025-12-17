from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.dashboard import (
    AlertesDashboard,
    AlertesResume,
    CommandeClientDashboard,
    ConsommationIngredientDashboard,
    PlanProductionDashboard,
    VueGlobaleDashboard,
)
from app.domaine.enums.types import StatutCommandeClient
from app.domaine.services.dashboard import (
    ServiceDashboardCommandes,
    ServiceDashboardProduction,
    ServiceDashboardStock,
    ServiceDashboardVueGlobale,
)


routeur_dashboard = APIRouter(
    prefix="/dashboard",
    tags=["dashboard_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_dashboard.get("/vue-globale", response_model=VueGlobaleDashboard)
async def vue_globale(
    date_cible: date,
    session: AsyncSession = Depends(fournir_session),
) -> VueGlobaleDashboard:
    """Vue globale (home dashboard).

    Lecture seule : aucune écriture en base.
    """

    service = ServiceDashboardVueGlobale(session)
    dto = await service.obtenir_vue_globale(date_cible=date_cible)

    return VueGlobaleDashboard(
        date=dto.date,
        commandes_du_jour=dto.commandes_du_jour,
        productions_du_jour=dto.productions_du_jour,
        quantite_produite=dto.quantite_produite,
        alertes=AlertesResume(
            stocks_bas=dto.alertes.stocks_bas,
            lots_proches_dlc=dto.alertes.lots_proches_dlc,
        ),
    )


@routeur_dashboard.get("/plans-production", response_model=list[PlanProductionDashboard])
async def plans_production(session: AsyncSession = Depends(fournir_session)) -> list[PlanProductionDashboard]:
    """Liste des plans de production (lecture seule)."""

    service = ServiceDashboardProduction(session)
    dtos = await service.lister_plans_production()

    return [
        PlanProductionDashboard(
            id=d.id,
            date_plan=d.date_plan,
            statut=d.statut.value,
            nombre_lignes=d.nombre_lignes,
        )
        for d in dtos
    ]


@routeur_dashboard.get("/commandes-clients", response_model=list[CommandeClientDashboard])
async def commandes_clients(
    date_cible: date | None = None,
    statut: StatutCommandeClient | None = None,
    session: AsyncSession = Depends(fournir_session),
) -> list[CommandeClientDashboard]:
    """Liste des commandes clients, filtrables par date et statut (lecture seule)."""

    service = ServiceDashboardCommandes(session)
    dtos = await service.lister_commandes_clients(date_cible=date_cible, statut=statut)

    return [
        CommandeClientDashboard(
            id=d.id,
            date_commande=d.date_commande,
            statut=d.statut.value,
            nombre_lignes=d.nombre_lignes,
            quantite_totale=d.quantite_totale,
        )
        for d in dtos
    ]


@routeur_dashboard.get("/consommation", response_model=list[ConsommationIngredientDashboard])
async def consommation(
    date_debut: date,
    date_fin: date,
    session: AsyncSession = Depends(fournir_session),
) -> list[ConsommationIngredientDashboard]:
    """Consommation & stock estimé sur une période.

    Le stock est toujours calculé via `MouvementStock` (lecture seule).
    """

    service = ServiceDashboardStock(session)
    dtos = await service.obtenir_consommation(date_debut=date_debut, date_fin=date_fin)

    return [
        ConsommationIngredientDashboard(
            ingredient_id=d.ingredient_id,
            ingredient=d.ingredient,
            quantite_consommee=d.quantite_consommee,
            stock_estime=d.stock_estime,
            lots_proches_dlc=d.lots_proches_dlc,
        )
        for d in dtos
    ]


@routeur_dashboard.get("/alertes", response_model=AlertesDashboard)
async def alertes(
    date_cible: date,
    session: AsyncSession = Depends(fournir_session),
) -> AlertesDashboard:
    """Retourne la liste détaillée des alertes (stocks bas / DLC proche)."""

    service = ServiceDashboardStock(session)
    dto = await service.obtenir_alertes(date_cible=date_cible)

    return AlertesDashboard(
        stocks_bas=[
            {
                "ingredient_id": a.ingredient_id,
                "ingredient": a.ingredient,
                "stock_estime": a.stock_estime,
            }
            for a in dto.stocks_bas
        ],
        lots_proches_dlc=[
            {
                "ingredient_id": a.ingredient_id,
                "ingredient": a.ingredient,
                "date_dlc": a.date_dlc,
            }
            for a in dto.lots_proches_dlc
        ],
    )
