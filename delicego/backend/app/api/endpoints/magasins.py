from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session
from app.domaine.modeles.referentiel import Magasin


routeur_magasins_interne = APIRouter(prefix="/magasins", tags=["magasins"])


@routeur_magasins_interne.get("", summary="Lister les magasins (id, nom)")
async def lister_magasins_interne(
    session: AsyncSession = Depends(fournir_session),
) -> list[dict[str, str]]:
    res = await session.execute(select(Magasin.id, Magasin.nom).where(Magasin.actif.is_(True)).order_by(Magasin.nom.asc()))
    return [{"id": str(id_), "nom": str(nom)} for id_, nom in res.all()]
