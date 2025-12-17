from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session
from app.api.schemas.client import MenuClientSchema
from app.api.schemas.magasin_client import MagasinClientSchema
from app.api.schemas.commande_client import ReponseCommandeClient, RequeteCommandeClient
from app.domaine.enums.types import StatutCommandeClient
from app.domaine.modeles.referentiel import Magasin, Menu
from app.domaine.services.disponibilite_menu import ServiceDisponibiliteMenu
from app.domaine.services.commander_client import (
    DonneesInvalidesCommandeClient,
    ServiceCommandeClient,
    StockInsuffisantCommandeClient,
)


routeur_commande_client = APIRouter(prefix="/api/client", tags=["client"])


@routeur_commande_client.get("/magasins", response_model=list[MagasinClientSchema])
async def lister_magasins(session: AsyncSession = Depends(fournir_session)) -> list[MagasinClientSchema]:
    """Liste des magasins actifs (API client)."""

    res = await session.execute(select(Magasin).where(Magasin.actif.is_(True)).order_by(Magasin.nom.asc()))
    magasins = list(res.scalars().all())

    return [MagasinClientSchema(id=m.id, nom=m.nom) for m in magasins]


@routeur_commande_client.get("/menus", response_model=list[MenuClientSchema])
async def lister_menus(session: AsyncSession = Depends(fournir_session)) -> list[MenuClientSchema]:
    """Liste des menus commandables (API client).

    Contrat attendu par le frontend /api/client :
    - id, nom, prix, actif (+ description optionnelle)
    - uniquement menus actifs ET commandables
    - triés par nom
    """

    res = await session.execute(
        select(Menu)
        .where(Menu.actif.is_(True))
        .where(Menu.commandable.is_(True))
        .order_by(Menu.nom.asc())
    )
    menus = list(res.scalars().all())

    # Stratégie choisie : on *marque* les menus indisponibles au lieu de filtrer,
    # pour permettre au client d’afficher l’état sans perdre le catalogue.
    service_dispo = ServiceDisponibiliteMenu(session)

    resultats: list[MenuClientSchema] = []
    for m in menus:
        try:
            disponible = await service_dispo.est_menu_disponible(menu_id=m.id, quantite=1.0)
        except Exception:
            # En base locale/dev, certains menus peuvent exister sans recette ou sans BOM.
            # On choisit de les marquer indisponibles (pas d'erreur 500).
            disponible = False

        resultats.append(
            MenuClientSchema(
                id=m.id,
                nom=m.nom,
                description=m.description,
                prix=m.prix,
                actif=m.actif,
                disponible=bool(disponible),
            )
        )

    return resultats


@routeur_commande_client.post(
    "/commande",
    response_model=ReponseCommandeClient,
    status_code=status.HTTP_201_CREATED,
)
async def passer_commande(
    requete: RequeteCommandeClient,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseCommandeClient:
    """Passe une commande client (API client).

    - Valide le payload via Pydantic
    - Appelle uniquement `ServiceCommandeClient`
    - Traduit les exceptions métier en HTTP
    """

    service = ServiceCommandeClient(session)

    try:
        commande_id = await service.commander(
            magasin_id=requete.magasin_id,
            lignes=[(l.menu_id, l.quantite) for l in requete.lignes],
            commentaire=requete.commentaire,
        )
    except StockInsuffisantCommandeClient as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except DonneesInvalidesCommandeClient as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur interne pendant la commande client.",
        ) from e

    return ReponseCommandeClient(
        commande_client_id=commande_id,
        statut=StatutCommandeClient.CONFIRMEE.value,
    )
