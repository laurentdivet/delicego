from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.prevision_ventes import FiabiliteModele, LignePrevisionProduit, PointHoraireVentes, ReponsePrevisionVentes
from app.services.prevision_ventes_service import PrevisionVentesService


routeur_prevision_ventes_interne = APIRouter(
    prefix="/previsions",
    tags=["previsions_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_prevision_ventes_interne.get("/ventes", response_model=ReponsePrevisionVentes)
async def prevision_ventes(
    date_cible: date,
    magasin_id: UUID | None = None,
    fenetre_fiabilite_jours: int = 14,
    session: AsyncSession = Depends(fournir_session),
) -> ReponsePrevisionVentes:
    """Prévision des ventes (prévu vs réel).

    - Prévision par jour/produit/site via `LignePrevision`.
    - Réel via `Vente`.
    - Prévision horaire: dérivée (MVP) par distribution horaire des ventes du jour.
    - Fiabilité: WAPE/MAPE calculés sur une fenêtre N jours avant date_cible.

    Sert directement à : production, achats fournisseurs, staffing.
    """

    svc = PrevisionVentesService(session)
    dto = await svc.obtenir(date_cible=date_cible, magasin_id=magasin_id, fenetre_fiabilite_jours=fenetre_fiabilite_jours)

    table = [
        LignePrevisionProduit(
            menu_id=str(l.menu_id),
            menu_nom=l.menu_nom,
            quantite_prevue=float(l.quantite_prevue),
            quantite_vendue=float(l.quantite_reelle),
            ecart_quantite=float(l.quantite_reelle - l.quantite_prevue),
            ca_prevu=float(l.ca_prevu),
            ca_reel=float(l.ca_reel),
            ecart_ca=float(l.ca_reel - l.ca_prevu),
            impact_meteo_pct=None,
            impact_jour_ferie_pct=None,
        )
        for l in dto.table_produits
    ]

    courbe = [
        PointHoraireVentes(
            heure=p.heure,
            quantite_prevue=float(p.quantite_prevue),
            quantite_reelle=float(p.quantite_reelle),
            ecart_quantite=float(p.quantite_reelle - p.quantite_prevue),
            ca_prevu=float(p.ca_prevu),
            ca_reel=float(p.ca_reel),
            ecart_ca=float(p.ca_reel - p.ca_prevu),
        )
        for p in dto.courbe_horaire
    ]

    return ReponsePrevisionVentes(
        magasin_id=str(magasin_id) if magasin_id is not None else None,
        date_cible=dto.date_cible,
        ca_prevu=float(dto.ca_prevu),
        ca_reel=float(dto.ca_reel),
        ecart_ca=float(dto.ca_reel - dto.ca_prevu),
        quantite_prevue=float(dto.quantite_prevue),
        quantite_reelle=float(dto.quantite_reelle),
        ecart_quantite=float(dto.quantite_reelle - dto.quantite_prevue),
        fiabilite=FiabiliteModele(
            wape_ca_pct=dto.fiabilite.wape_ca_pct,
            mape_ca_pct=dto.fiabilite.mape_ca_pct,
            fiabilite_ca_pct=dto.fiabilite.fiabilite_ca_pct,
        ),
        courbe_horaire=courbe,
        table_produits=table,
        facteurs={"meteo_active": False, "jour_ferie_active": False},
    )
