from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_email_client, fournir_session, verifier_acces_interne
from app.api.schemas.achats import (
    ReponseAjouterLigneCommandeFournisseur,
    ReponseCreerCommandeFournisseur,
    ReponseGenererBesoinsFournisseurs,
    RequeteAjouterLigneCommandeFournisseur,
    RequeteCreerCommandeFournisseur,
    RequeteEnvoyerCommandeFournisseurEmail,
    RequeteGenererBesoinsFournisseurs,
    RequeteReceptionnerCommandeFournisseur,
)
from app.domaine.services.commander_fournisseur import (
    DonneesInvalidesCommandeFournisseur,
    ErreurCommandeFournisseur,
    ServiceCommandeFournisseur,
    TransitionStatutInterditeCommandeFournisseur,
)
from app.domaine.services.generer_besoins_fournisseurs import (
    DonneesInvalidesGenerationBesoinsFournisseurs,
    ErreurGenerationBesoinsFournisseurs,
    ServiceGenerationBesoinsFournisseurs,
)
from app.domaine.services.bon_commande_fournisseur import (
    BonCommandeIntrouvable,
    ServiceBonCommandeFournisseur,
)
from app.domaine.services.email_client import EmailClient
from app.domaine.services.envoyer_commande_fournisseur import (
    ErreurEnvoiCommandeFournisseur,
    ServiceEnvoiCommandeFournisseur,
    TransitionStatutInterditeEnvoiCommandeFournisseur,
)


routeur_achats_interne = APIRouter(
    prefix="/achats",
    tags=["achats_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_achats_interne.post(
    "/commandes",
    response_model=ReponseCreerCommandeFournisseur,
    status_code=status.HTTP_201_CREATED,
)
async def creer_commande_fournisseur(
    requete: RequeteCreerCommandeFournisseur,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseCreerCommandeFournisseur:
    service = ServiceCommandeFournisseur(session)

    try:
        commande_id = await service.creer_commande(
            fournisseur_id=requete.fournisseur_id,
            date_commande=requete.date_commande,
            commentaire=requete.commentaire,
        )
    except DonneesInvalidesCommandeFournisseur as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Erreur inattendue : {e}") from e

    return ReponseCreerCommandeFournisseur(commande_fournisseur_id=commande_id)


@routeur_achats_interne.post(
    "/commandes/{commande_id}/lignes",
    response_model=ReponseAjouterLigneCommandeFournisseur,
    status_code=status.HTTP_201_CREATED,
)
async def ajouter_ligne_commande_fournisseur(
    commande_id: UUID,
    requete: RequeteAjouterLigneCommandeFournisseur,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseAjouterLigneCommandeFournisseur:
    service = ServiceCommandeFournisseur(session)

    try:
        ligne_id = await service.ajouter_ligne(
            commande_fournisseur_id=commande_id,
            ingredient_id=requete.ingredient_id,
            quantite=requete.quantite,
            unite=requete.unite,
        )
    except TransitionStatutInterditeCommandeFournisseur as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except DonneesInvalidesCommandeFournisseur as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Erreur inattendue : {e}") from e

    return ReponseAjouterLigneCommandeFournisseur(ligne_commande_fournisseur_id=ligne_id)


@routeur_achats_interne.post(
    "/{commande_id}/envoyer",
    status_code=status.HTTP_200_OK,
)
async def envoyer_commande_fournisseur_email(
    commande_id: UUID,
    requete: RequeteEnvoyerCommandeFournisseurEmail,
    email_client: EmailClient = Depends(fournir_email_client),
    session: AsyncSession = Depends(fournir_session),
) -> dict[str, str]:
    """Envoi logique email d’une commande fournisseur (sans SMTP réel)."""

    service = ServiceEnvoiCommandeFournisseur(
        session,
        email_client=email_client,
    )

    try:
        await service.envoyer(
            commande_fournisseur_id=commande_id,
            destinataire=requete.destinataire,
            sujet=requete.sujet,
            corps=requete.corps,
        )
    except TransitionStatutInterditeEnvoiCommandeFournisseur as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ErreurEnvoiCommandeFournisseur as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Erreur inattendue : {e}") from e

    return {"status": "ok"}


@routeur_achats_interne.post(
    "/commandes/{commande_id}/receptionner",
    status_code=status.HTTP_200_OK,
)
async def receptionner_commande_fournisseur(
    commande_id: UUID,
    requete: RequeteReceptionnerCommandeFournisseur,
    session: AsyncSession = Depends(fournir_session),
) -> dict[str, str]:
    service = ServiceCommandeFournisseur(session)

    try:
        lignes = None
        if requete.lignes:
            lignes = [(l.ingredient_id, float(l.quantite), str(l.unite)) for l in requete.lignes]

        await service.receptionner_commande(
            commande_fournisseur_id=commande_id,
            magasin_id=requete.magasin_id,
            lignes_reception=lignes,
            reference_externe=requete.reference_externe,
            commentaire=requete.commentaire,
        )
    except TransitionStatutInterditeCommandeFournisseur as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except DonneesInvalidesCommandeFournisseur as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Erreur inattendue : {e}") from e

    return {"status": "ok"}


@routeur_achats_interne.get(
    "/{commande_id}/bon-commande",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def telecharger_bon_commande_fournisseur(
    commande_id: UUID,
    session: AsyncSession = Depends(fournir_session),
) -> Response:
    """Retourne le PDF du bon de commande fournisseur."""

    service = ServiceBonCommandeFournisseur(session)

    try:
        pdf = await service.generer_pdf(commande_id)
    except BonCommandeIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    return Response(content=pdf, media_type="application/pdf")


@routeur_achats_interne.post(
    "/besoins/generer",
    response_model=ReponseGenererBesoinsFournisseurs,
    status_code=status.HTTP_201_CREATED,
)
async def generer_besoins_fournisseurs(
    requete: RequeteGenererBesoinsFournisseurs,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseGenererBesoinsFournisseurs:
    service = ServiceGenerationBesoinsFournisseurs(session)

    try:
        ids = await service.generer(
            magasin_id=requete.magasin_id,
            date_cible=requete.date_cible,
            horizon=requete.horizon,
        )
    except DonneesInvalidesGenerationBesoinsFournisseurs as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except ErreurGenerationBesoinsFournisseurs as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Erreur inattendue : {e}") from e

    return ReponseGenererBesoinsFournisseurs(commandes_ids=ids)
