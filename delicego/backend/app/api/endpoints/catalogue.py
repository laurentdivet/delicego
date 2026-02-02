from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.catalogue import (
    ProduitCreate,
    ProduitFournisseurCreate,
    ProduitFournisseurOut,
    ProduitFournisseurUpdate,
    ProduitOut,
    ProduitUpdate,
)
from app.domaine.modeles.catalogue import Produit, ProduitFournisseur
from app.domaine.modeles.referentiel import Fournisseur


logger = logging.getLogger(__name__)


routeur_catalogue_interne = APIRouter(
    prefix="/catalogue",
    tags=["catalogue_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_catalogue_interne.get("/produits", response_model=list[ProduitOut])
async def lister_produits(
    session: AsyncSession = Depends(fournir_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actif: bool | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1),
) -> list[ProduitOut]:
    filtres = []
    if actif is not None:
        filtres.append(Produit.actif == actif)
    if q:
        filtres.append(Produit.libelle.ilike(f"%{q}%"))

    stmt = select(Produit).order_by(Produit.libelle.asc()).limit(limit).offset(offset)
    if filtres:
        stmt = stmt.where(and_(*filtres))

    res = await session.execute(stmt)
    return list(res.scalars().all())


@routeur_catalogue_interne.post(
    "/produits",
    response_model=ProduitOut,
    status_code=status.HTTP_201_CREATED,
)
async def creer_produit(
    body: ProduitCreate,
    session: AsyncSession = Depends(fournir_session),
) -> ProduitOut:
    p = Produit(libelle=body.libelle.strip(), categorie=body.categorie, actif=body.actif)
    session.add(p)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        logger.info("catalogue_creer_produit_conflit libelle=%s", body.libelle)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflit: un produit avec ce libellé existe déjà.",
        ) from e

    await session.refresh(p)
    return p


@routeur_catalogue_interne.get("/produits/{produit_id}", response_model=ProduitOut)
async def get_produit(
    produit_id: UUID,
    session: AsyncSession = Depends(fournir_session),
) -> ProduitOut:
    res = await session.execute(select(Produit).where(Produit.id == produit_id))
    p = res.scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produit introuvable.")
    return p


@routeur_catalogue_interne.patch("/produits/{produit_id}", response_model=ProduitOut)
async def patch_produit(
    produit_id: UUID,
    body: ProduitUpdate,
    session: AsyncSession = Depends(fournir_session),
) -> ProduitOut:
    res = await session.execute(select(Produit).where(Produit.id == produit_id))
    p = res.scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produit introuvable.")

    if body.libelle is not None:
        p.libelle = body.libelle.strip()
    if body.categorie is not None:
        p.categorie = body.categorie
    if body.actif is not None:
        p.actif = body.actif

    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        logger.info("catalogue_patch_produit_conflit produit_id=%s libelle=%s", produit_id, body.libelle)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflit: un produit avec ce libellé existe déjà.",
        ) from e

    await session.refresh(p)
    return p


@routeur_catalogue_interne.get(
    "/fournisseurs/{fournisseur_id}/produits",
    response_model=list[ProduitFournisseurOut],
)
async def lister_produits_fournisseur(
    fournisseur_id: UUID,
    session: AsyncSession = Depends(fournir_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actif: bool | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1),
) -> list[ProduitFournisseurOut]:
    # vérifie existence fournisseur (meilleur message)
    f = (await session.execute(select(Fournisseur).where(Fournisseur.id == fournisseur_id))).scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fournisseur introuvable.")

    filtres = [ProduitFournisseur.fournisseur_id == fournisseur_id]
    if actif is not None:
        filtres.append(ProduitFournisseur.actif == actif)
    if q:
        filtres.append(
            or_(
                ProduitFournisseur.libelle_fournisseur.ilike(f"%{q}%"),
                ProduitFournisseur.reference_fournisseur.ilike(f"%{q}%"),
            )
        )

    stmt = (
        select(ProduitFournisseur)
        .where(and_(*filtres))
        .order_by(ProduitFournisseur.reference_fournisseur.asc())
        .limit(limit)
        .offset(offset)
    )
    res = await session.execute(stmt)
    return list(res.scalars().unique().all())


@routeur_catalogue_interne.post(
    "/produit-fournisseur",
    response_model=ProduitFournisseurOut,
    status_code=status.HTTP_201_CREATED,
)
async def creer_produit_fournisseur(
    body: ProduitFournisseurCreate,
    session: AsyncSession = Depends(fournir_session),
) -> ProduitFournisseurOut:
    pf = ProduitFournisseur(
        fournisseur_id=body.fournisseur_id,
        produit_id=body.produit_id,
        reference_fournisseur=body.reference_fournisseur.strip(),
        libelle_fournisseur=body.libelle_fournisseur,
        unite_achat=body.unite_achat,
        quantite_par_unite=body.quantite_par_unite,
        prix_achat_ht=body.prix_achat_ht,
        tva=body.tva,
        actif=body.actif,
    )
    session.add(pf)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        logger.info(
            "catalogue_creer_produit_fournisseur_conflit fournisseur_id=%s reference=%s",
            body.fournisseur_id,
            body.reference_fournisseur,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflit: (fournisseur_id, reference_fournisseur) doit être unique.",
        ) from e

    await session.refresh(pf)
    # charger relation produit pour la sérialisation Pydantic (évite lazy-load async)
    pf = (
        await session.execute(
            select(ProduitFournisseur)
            .where(ProduitFournisseur.id == pf.id)
            .options(selectinload(ProduitFournisseur.produit))
        )
    ).scalar_one()
    return pf


@routeur_catalogue_interne.get("/produit-fournisseur/{pf_id}", response_model=ProduitFournisseurOut)
async def get_produit_fournisseur(
    pf_id: UUID,
    session: AsyncSession = Depends(fournir_session),
) -> ProduitFournisseurOut:
    pf = (
        await session.execute(
            select(ProduitFournisseur)
            .where(ProduitFournisseur.id == pf_id)
            .options(selectinload(ProduitFournisseur.produit))
        )
    ).scalar_one_or_none()
    if pf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ProduitFournisseur introuvable.")
    return pf


@routeur_catalogue_interne.patch("/produit-fournisseur/{pf_id}", response_model=ProduitFournisseurOut)
async def patch_produit_fournisseur(
    pf_id: UUID,
    body: ProduitFournisseurUpdate,
    session: AsyncSession = Depends(fournir_session),
) -> ProduitFournisseurOut:
    pf = (
        await session.execute(
            select(ProduitFournisseur)
            .where(ProduitFournisseur.id == pf_id)
            .options(selectinload(ProduitFournisseur.produit))
        )
    ).scalar_one_or_none()
    if pf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ProduitFournisseur introuvable.")

    if body.produit_id is not None:
        pf.produit_id = body.produit_id
    if body.reference_fournisseur is not None:
        pf.reference_fournisseur = body.reference_fournisseur.strip()
    if body.libelle_fournisseur is not None:
        pf.libelle_fournisseur = body.libelle_fournisseur
    if body.unite_achat is not None:
        pf.unite_achat = body.unite_achat
    if body.quantite_par_unite is not None:
        pf.quantite_par_unite = body.quantite_par_unite
    if body.prix_achat_ht is not None or body.prix_achat_ht is None:
        pf.prix_achat_ht = body.prix_achat_ht
    if body.tva is not None or body.tva is None:
        pf.tva = body.tva
    if body.actif is not None:
        pf.actif = body.actif

    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        logger.info(
            "catalogue_patch_produit_fournisseur_conflit pf_id=%s fournisseur_id=%s reference=%s",
            pf_id,
            pf.fournisseur_id,
            pf.reference_fournisseur,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflit: (fournisseur_id, reference_fournisseur) doit être unique.",
        ) from e

    await session.refresh(pf)
    pf = (
        await session.execute(
            select(ProduitFournisseur)
            .where(ProduitFournisseur.id == pf.id)
            .options(selectinload(ProduitFournisseur.produit))
        )
    ).scalar_one()
    return pf
