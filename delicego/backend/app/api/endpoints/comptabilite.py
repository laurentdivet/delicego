from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.comptabilite import (
    EcritureComptableLecture,
    ReponseGenerationComptabilite,
    RequeteGenerationComptabilite,
)
from app.domaine.enums.types import TypeEcritureComptable
from app.domaine.modeles.comptabilite import EcritureComptable, JournalComptable
from app.domaine.services.comptabilite_pennylane import ErreurComptabilitePennylane, ServiceComptabilitePennylane


routeur_comptabilite = APIRouter(
    prefix="/comptabilite",
    tags=["comptabilite_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_comptabilite.post(
    "/generer",
    response_model=ReponseGenerationComptabilite,
    status_code=status.HTTP_201_CREATED,
)
async def generer_ecritures(
    requete: RequeteGenerationComptabilite,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseGenerationComptabilite:
    """Génère des écritures comptables exportables (simulation Pennylane).

    Lecture/écriture comptable uniquement : aucune logique métier.
    """

    service = ServiceComptabilitePennylane(session)

    try:
        ids = await service.generer_ecritures(date_debut=requete.date_debut, date_fin=requete.date_fin)
    except ErreurComptabilitePennylane as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur interne pendant la génération comptable.",
        ) from e

    # Dernier journal créé (simplification)
    res_j = await session.execute(
        select(JournalComptable).order_by(JournalComptable.date_generation.desc())
    )
    journal = res_j.scalars().first()
    if journal is None:
        raise HTTPException(status_code=500, detail="JournalComptable introuvable après génération.")

    return ReponseGenerationComptabilite(nombre_ecritures=len(ids), journal_id=journal.id)


@routeur_comptabilite.get("/ecritures", response_model=list[EcritureComptableLecture])
async def lister_ecritures(
    date_debut: date | None = None,
    date_fin: date | None = None,
    type: TypeEcritureComptable | None = None,  # noqa: A002 (nom demandé)
    exportee: bool | None = None,
    session: AsyncSession = Depends(fournir_session),
) -> list[EcritureComptableLecture]:
    """Liste les écritures comptables générées.

    Filtres : période, type, exportée.
    """

    conditions = []
    if date_debut is not None:
        conditions.append(EcritureComptable.date_ecriture >= date_debut)
    if date_fin is not None:
        conditions.append(EcritureComptable.date_ecriture <= date_fin)
    if type is not None:
        conditions.append(EcritureComptable.type == type)
    if exportee is not None:
        conditions.append(EcritureComptable.exportee == exportee)

    res = await session.execute(
        select(EcritureComptable)
        .where(*conditions)
        .order_by(EcritureComptable.date_ecriture.desc(), EcritureComptable.id.asc())
    )
    ecritures = list(res.scalars().all())

    return [
        EcritureComptableLecture(
            id=e.id,
            date_ecriture=e.date_ecriture,
            type=e.type.value,
            reference_interne=e.reference_interne,
            montant_ht=float(e.montant_ht),
            tva=float(e.tva),
            compte_comptable=e.compte_comptable,
            exportee=bool(e.exportee),
        )
        for e in ecritures
    ]
