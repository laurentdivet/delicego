from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.production_preparation import (
    EvenementTraceabilite,
    ReponseCreneauQuantite,
    ReponseLectureProductionPreparation,
    ReponseLigneCuisine,
    ReponseLigneProductionScan,
    ReponseScanGencode,
    ReponseTraceabiliteProductionPreparation,
    RequeteActionAjuste,
    RequeteActionNonProduit,
    RequeteActionProduit,
    RequeteScanGencode,
)
from app.domaine.modeles.production import LotProduction
from app.domaine.modeles.referentiel import Menu
from app.domaine.services.executer_production import (
    DonneesInvalidesProduction,
    ErreurProduction,
    ProductionDejaExecutee,
    ServiceExecutionProduction,
)
from app.services.production_cuisine_service import CRENEAUX, ServiceProductionCuisine


routeur_production_preparation_interne = APIRouter(
    prefix="/production-preparation",
    tags=["production_preparation_interne"],
    dependencies=[Depends(verifier_acces_interne)],
)


def _hhmm(h: int) -> str:
    return f"{int(h):02d}:00"


@routeur_production_preparation_interne.get(
    "",
    response_model=ReponseLectureProductionPreparation,
)
async def lire_ecran_cuisine(
    magasin_id: UUID,
    date: date,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseLectureProductionPreparation:
    service = ServiceProductionCuisine(session)

    try:
        plan = await service.trouver_plan(magasin_id=magasin_id, date_plan=date)
        kpis = await service.calculer_kpis(plan=plan)
        lignes = await service.lire_lignes(plan_production_id=plan.id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    cuisine = [
        ReponseLigneCuisine(
            recette_id=str(l.recette_id),
            recette_nom=l.recette_nom,
            quantite_planifiee=float(l.quantite_planifiee),
            quantite_produite=float(l.quantite_produite),
            statut=ServiceProductionCuisine.statut_ligne(
                quantite_planifiee=float(l.quantite_planifiee),
                quantite_produite=float(l.quantite_produite),
                dernier_lot_quantite=l.dernier_lot_quantite,
            ),
        )
        for l in lignes
    ]

    # Remap TEL QUEL de `calculer_kpis()` (valeurs déjà calculées là-bas)
    # -> format demandé : {debut, fin, quantite}
    # On utilise la table CRENEAUX du service (pas de nouvelle logique).
    creneaux = []
    for c in CRENEAUX:
        q = float(kpis.quantites_par_creneau.get(c.code, 0.0))
        creneaux.append(
            ReponseCreneauQuantite(
                debut=_hhmm(c.heure_debut),
                fin=_hhmm(c.heure_fin_incluse),
                quantite=q,
            )
        )

    return ReponseLectureProductionPreparation(
        quantites_a_produire_aujourdhui=float(kpis.quantite_totale_a_produire),
        quantites_par_creneau=creneaux,
        cuisine=cuisine,
    )


@routeur_production_preparation_interne.post(
    "/produit",
    status_code=status.HTTP_200_OK,
)
async def action_produit(
    requete: RequeteActionProduit,
    session: AsyncSession = Depends(fournir_session),
) -> dict[str, str]:
    """Action opérateur "Produit".

    - Crée un LotProduction (quantité planifiée)
    - Déclenche la consommation via le service existant `ServiceExecutionProduction`
    """

    service_cuisine = ServiceProductionCuisine(session)
    service_exec = ServiceExecutionProduction(session)

    try:
        async with session.begin():
            plan = await service_cuisine.trouver_plan(
                magasin_id=requete.magasin_id,
                date_plan=requete.date,
            )

            lignes = await service_cuisine.lire_lignes(plan_production_id=plan.id)
            ligne = next((l for l in lignes if l.recette_id == requete.recette_id), None)
            if ligne is None:
                raise HTTPException(status_code=404, detail="Recette absente du plan.")

            lot = await service_cuisine.creer_lot(
                plan=plan,
                recette_id=requete.recette_id,
                quantite=float(ligne.quantite_planifiee),
                unite="unite",
            )
            await service_exec.executer_dans_transaction(lot_production_id=lot.id)

    except HTTPException:
        raise
    except (DonneesInvalidesProduction, ProductionDejaExecutee) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return {"status": "ok"}


@routeur_production_preparation_interne.post(
    "/ajuste",
    status_code=status.HTTP_200_OK,
)
async def action_ajuste(
    requete: RequeteActionAjuste,
    session: AsyncSession = Depends(fournir_session),
) -> dict[str, str]:
    """Action opérateur "Ajusté".

    - Crée un LotProduction avec la quantité ajustée
    - Déclenche la consommation via le service existant
    """

    service_cuisine = ServiceProductionCuisine(session)
    service_exec = ServiceExecutionProduction(session)

    try:
        async with session.begin():
            plan = await service_cuisine.trouver_plan(
                magasin_id=requete.magasin_id,
                date_plan=requete.date,
            )

            lot = await service_cuisine.creer_lot(
                plan=plan,
                recette_id=requete.recette_id,
                quantite=float(requete.quantite),
                unite="unite",
            )
            await service_exec.executer_dans_transaction(lot_production_id=lot.id)

    except (DonneesInvalidesProduction, ProductionDejaExecutee) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return {"status": "ok"}


@routeur_production_preparation_interne.post(
    "/non-produit",
    status_code=status.HTTP_200_OK,
)
async def action_non_produit(
    requete: RequeteActionNonProduit,
    session: AsyncSession = Depends(fournir_session),
) -> dict[str, str]:
    """Action opérateur "Non produit".

    - Crée un LotProduction de quantité 0
    - Ne déclenche aucune consommation (pas d'appel à ServiceExecutionProduction)
    """

    service_cuisine = ServiceProductionCuisine(session)

    try:
        async with session.begin():
            plan = await service_cuisine.trouver_plan(
                magasin_id=requete.magasin_id,
                date_plan=requete.date,
            )

            await service_cuisine.creer_lot(
                plan=plan,
                recette_id=requete.recette_id,
                quantite=0.0,
                unite="unite",
            )

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return {"status": "ok"}


@routeur_production_preparation_interne.post(
    "/scan",
    response_model=ReponseScanGencode,
    status_code=status.HTTP_200_OK,
)
async def scan_gencode(
    requete: RequeteScanGencode,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseScanGencode:
    """Scan d'un gencode en production.

    Règles :
    - On résout `Menu` via `Menu.gencode`.
    - On trouve le PlanProduction du jour (magasin/date).
    - On incrémente la production réelle via `LotProduction` (quantite_produite += 1).
    - On renvoie l'état recalculé de la ligne (a_produire / produit / restant).

    IMPORTANT :
    - Le gencode n'est jamais renvoyé au frontend.
    """

    service_cuisine = ServiceProductionCuisine(session)
    service_exec = ServiceExecutionProduction(session)

    gencode = (requete.gencode or "").strip()
    if not gencode:
        raise HTTPException(status_code=400, detail="gencode manquant")

    try:
        async with session.begin():
            res = await session.execute(select(Menu).where(Menu.gencode == gencode))
            menu = res.scalar_one_or_none()
            if menu is None:
                raise HTTPException(status_code=404, detail="Produit introuvable pour ce gencode.")

            plan = await service_cuisine.trouver_plan(
                magasin_id=requete.magasin_id,
                date_plan=requete.date,
            )

            # Incrément production réelle : un lot de +1.
            lot = await service_cuisine.creer_lot(
                plan=plan,
                recette_id=menu.recette_id,
                quantite=1.0,
                unite="unite",
            )

            # Consommation stock associée (réel)
            #
            # NOTE terrain : en environnement "setup" (stock non initialisé),
            # l'exécution FEFO peut échouer (ex: "Aucun lot disponible...").
            # Pour ne pas bloquer le flux opérationnel de scan, on dégrade en "scan compté"
            # (le lot de production est quand même persisté).
            try:
                await service_exec.executer_dans_transaction(lot_production_id=lot.id)
            except (DonneesInvalidesProduction, ProductionDejaExecutee, ErreurProduction):
                # En mode "scan compté" (ou si lot déjà exécuté / stock non initialisé),
                # on ne bloque pas le scan.
                pass

            # Recalcule de la ligne
            lignes = await service_cuisine.lire_lignes(plan_production_id=plan.id)
            ligne = next((l for l in lignes if l.recette_id == menu.recette_id), None)
            if ligne is None:
                raise HTTPException(status_code=404, detail="Recette absente du plan du jour.")

            a_produire = float(ligne.quantite_planifiee)
            produit = float(ligne.quantite_produite)
            restant = float(a_produire - produit)

            return ReponseScanGencode(
                ligne=ReponseLigneProductionScan(
                    id=str(ligne.recette_id),
                    produit_nom=menu.nom,
                    a_produire=a_produire,
                    produit=produit,
                    restant=restant,
                )
            )

    except HTTPException:
        raise
    except (DonneesInvalidesProduction, ProductionDejaExecutee) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@routeur_production_preparation_interne.get(
    "/traceabilite",
    response_model=ReponseTraceabiliteProductionPreparation,
)
async def traceabilite(
    magasin_id: UUID,
    date: date,
    recette_id: UUID,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseTraceabiliteProductionPreparation:
    service_cuisine = ServiceProductionCuisine(session)

    try:
        plan = await service_cuisine.trouver_plan(magasin_id=magasin_id, date_plan=date)

        res = await session.execute(
            select(LotProduction)
            .where(
                LotProduction.plan_production_id == plan.id,
                LotProduction.recette_id == recette_id,
            )
            .order_by(LotProduction.produit_le.asc())
        )
        lots = list(res.scalars().all())

        lignes = await service_cuisine.lire_lignes(plan_production_id=plan.id)
        ligne_plan = next((l for l in lignes if l.recette_id == recette_id), None)

        evenements: list[EvenementTraceabilite] = []
        for lot in lots:
            if float(lot.quantite_produite) <= 0:
                typ = "NON_PRODUIT"
                qte = 0.0
            else:
                # Règle minimale : si quantite != plan => AJUSTE sinon PRODUIT
                if (
                    ligne_plan is not None
                    and abs(float(lot.quantite_produite) - float(ligne_plan.quantite_planifiee)) > 1e-6
                ):
                    typ = "AJUSTE"
                else:
                    typ = "PRODUIT"
                qte = float(lot.quantite_produite)

            evenements.append(
                EvenementTraceabilite(
                    type=typ,
                    date_heure=lot.produit_le.isoformat(),
                    quantite=qte,
                    lot_production_id=str(lot.id),
                )
            )

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return ReponseTraceabiliteProductionPreparation(evenements=evenements)
