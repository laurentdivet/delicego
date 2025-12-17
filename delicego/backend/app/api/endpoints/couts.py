from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session
from app.api.schemas.couts import CoutMenuSchema
from app.domaine.modeles.referentiel import Menu
from app.domaine.services.couts_marges import MenuSansRecette, ServiceCoutsMarges


# NOTE: ce routeur est inclus dans `routeur_interne` (préfixe "/api/interne").
# On évite donc de répéter "/api/interne" ici.
routeur_couts_interne = APIRouter(prefix="/couts", tags=["couts"])


@routeur_couts_interne.get("/menus", response_model=list[CoutMenuSchema])
async def lister_couts_marges_menus(
    session: AsyncSession = Depends(fournir_session),
) -> list[CoutMenuSchema]:
    """Liste coûts/marges par menu (API interne).

    Retour :
    - menu_id, cout, prix, marge, taux_marge

    Règles :
    - prix = Menu.prix
    - menus sans recette : ignorés (ce cas est testé via service)
    """

    service = ServiceCoutsMarges(session)

    res = await session.execute(select(Menu.id).order_by(Menu.nom.asc()))
    menu_ids = [r[0] for r in res.all()]

    resultats: list[CoutMenuSchema] = []
    for menu_id in menu_ids:
        try:
            cm = await service.calculer_cout_marge_menu_depuis_prix_menu(menu_id)
        except MenuSansRecette:
            continue

        resultats.append(
            CoutMenuSchema(
                menu_id=cm.menu_id,
                cout=cm.cout,
                prix=cm.prix,
                marge=cm.marge,
                taux_marge=cm.taux_marge,
            )
        )

    return resultats
