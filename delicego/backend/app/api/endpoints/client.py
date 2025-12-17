from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session
from app.api.schemas.client import MenuClientSchema
from app.api.schemas.magasin_client import MagasinClientSchema
from app.domaine.modeles.referentiel import Magasin, Menu

router = APIRouter(
    prefix="/api/client",
    tags=["client"],
)


@router.get("/magasins", response_model=list[MagasinClientSchema])
async def lister_magasins_client(
    session: AsyncSession = Depends(fournir_session),
) -> list[MagasinClientSchema]:
    """Retourne la liste des magasins (pour éviter de saisir un UUID à la main)."""

    resultat = await session.execute(select(Magasin).where(Magasin.actif.is_(True)).order_by(Magasin.nom.asc()))
    magasins = resultat.scalars().all()

    return [MagasinClientSchema(id=m.id, nom=m.nom) for m in magasins]


@router.get("/menus", response_model=list[MenuClientSchema])
async def lister_menus_client(
    magasin_id: str | None = None,
    session: AsyncSession = Depends(fournir_session),
) -> list[MenuClientSchema]:
    """Retourne la liste des menus commandables pour le frontend.

    - Menus actifs uniquement
    - Triés par nom
    - Si aucun menu : retourne []

    Optionnel:
    - magasin_id: filtre la liste à un seul magasin (MVP Inpulse-like)
    """

    requete = (
        select(Menu)
        .where(Menu.actif.is_(True))
        .where(Menu.commandable.is_(True))
    )
    if magasin_id:
        requete = requete.where(Menu.magasin_id == magasin_id)

    resultat = await session.execute(requete.order_by(Menu.nom.asc()))
    menus = resultat.scalars().all()

    return [
        MenuClientSchema(
            id=menu.id,
            nom=menu.nom,
            description=getattr(menu, "description", None),
            prix=getattr(menu, "prix", 0.0),
            actif=menu.actif,
            disponible=True,
        )
        for menu in menus
    ]
