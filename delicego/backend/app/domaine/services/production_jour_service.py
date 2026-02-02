from __future__ import annotations

"""Cycle métier: production du jour.

But
---
Exécuter en une seule opération (déterministe) :

- calcul des besoins ingrédients (BOM) pour une liste (recette_id, quantite)
- création des lots de production
- exécution des consommations (FEFO) + mouvements stock associés
- historisation: plan (prévu) vs lots (produit)

Principe clé
------------
- Transaction atomique : si un seul ingrédient manque → aucun lot, aucune consommation.

On réutilise les tables existantes :
- PlanProduction / LignePlanProduction (prévu)
- LotProduction / LigneConsommation / MouvementStock (réel)
"""

from dataclasses import dataclass
from datetime import date
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles.production import LignePlanProduction, LotProduction, PlanProduction
# NOTE: on ne dépend pas des modèles Recette ici, on s'appuie sur les FK existantes.
from app.domaine.services.executer_production import ServiceExecutionProduction
from app.domaine.services.production_reelle import ServiceProductionReelle


logger = logging.getLogger(__name__)


class ErreurProductionJour(Exception):
    """Erreur générique du cycle production du jour."""


class DonneesInvalidesProductionJour(ErreurProductionJour):
    """Entrées invalides (recettes, quantités)."""


class StockInsuffisantProductionJour(ErreurProductionJour):
    """Stock insuffisant: aucun effet de bord ne doit être persisté."""


@dataclass(frozen=True)
class LigneProductionJour:
    recette_id: UUID
    quantite_a_produire: float


@dataclass(frozen=True)
class ResultatProductionJour:
    plan_production_id: UUID
    lots_production_ids: list[UUID]
    nb_mouvements_stock: int
    nb_lignes_consommation: int


class ServiceProductionJour:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._service_plan = ServiceProductionReelle(session)

    async def executer_production_du_jour(
        self,
        *,
        magasin_id: UUID,
        date_jour: date,
        lignes: list[LigneProductionJour],
        unite: str = "unite",
    ) -> ResultatProductionJour:
        """Exécute le cycle complet.

        - crée/écrase un plan pour la date (prévu)
        - crée les lots (réel)
        - exécute les consommations (FEFO)
        """

        self._valider_lignes(lignes)

        logger.info(
            "production_jour_start magasin_id=%s date=%s nb_lignes=%s",
            magasin_id,
            date_jour.isoformat(),
            len(lignes),
        )

        async with self._session.begin():
            # 1) Créer un PlanProduction si absent (sinon le réutiliser)
            plan = await self._get_or_create_plan(magasin_id=magasin_id, date_jour=date_jour)

            # 2) Historiser le prévu: LignePlanProduction
            await self._upsert_lignes_plan(plan_id=plan.id, lignes=lignes)

            # 3) Calculer les besoins (BOM) à partir du plan (lecture seule)
            #    -> force aussi les validations (recettes, unités incohérentes, etc.)
            await self._service_plan.calculer_besoins_ingredients(plan_id=plan.id)

            # 4) Créer les lots + exécuter la consommation (FEFO)
            service_exec = ServiceExecutionProduction(self._session)

            lots_ids: list[UUID] = []
            nb_mv = 0
            nb_conso = 0

            for l in lignes:
                logger.info(
                    "production_jour_lot_create magasin_id=%s plan_id=%s recette_id=%s quantite=%s unite=%s",
                    magasin_id,
                    plan.id,
                    l.recette_id,
                    float(l.quantite_a_produire),
                    unite,
                )
                lot = LotProduction(
                    magasin_id=magasin_id,
                    plan_production_id=plan.id,
                    recette_id=l.recette_id,
                    quantite_produite=float(l.quantite_a_produire),
                    unite=unite,
                )
                self._session.add(lot)
                await self._session.flush()  # lot.id
                lots_ids.append(lot.id)

                try:
                    res = await service_exec.executer_dans_transaction(lot_production_id=lot.id)
                except Exception as e:
                    # Message stock insuffisant déjà explicite via AllocateurFEFO.
                    # Ici on force un type métier clair.
                    msg = str(e)
                    if "Stock insuffisant" in msg or "Aucun lot disponible" in msg:
                        logger.warning(
                            "production_jour_stock_insuffisant magasin_id=%s plan_id=%s lot_id=%s err=%s",
                            magasin_id,
                            plan.id,
                            lot.id,
                            msg,
                        )
                        raise StockInsuffisantProductionJour(msg) from e

                    logger.exception(
                        "production_jour_erreur magasin_id=%s plan_id=%s lot_id=%s",
                        magasin_id,
                        plan.id,
                        lot.id,
                    )
                    raise ErreurProductionJour(msg) from e

                nb_mv += int(res.nb_mouvements_stock)
                nb_conso += int(res.nb_lignes_consommation)

            return ResultatProductionJour(
                plan_production_id=plan.id,
                lots_production_ids=lots_ids,
                nb_mouvements_stock=nb_mv,
                nb_lignes_consommation=nb_conso,
            )


    async def _get_or_create_plan(self, *, magasin_id: UUID, date_jour: date) -> PlanProduction:
        res = await self._session.execute(
            select(PlanProduction).where(
                PlanProduction.magasin_id == magasin_id,
                PlanProduction.date_plan == date_jour,
            )
        )
        plan = res.scalar_one_or_none()
        if plan is not None:
            return plan

        # Création minimaliste (statut défaut = BROUILLON)
        plan = PlanProduction(magasin_id=magasin_id, date_plan=date_jour)
        self._session.add(plan)
        await self._session.flush()
        return plan

    async def _upsert_lignes_plan(self, *, plan_id: UUID, lignes: list[LigneProductionJour]) -> None:
        """Remplace les lignes du plan par celles fournies.

        On fait simple et déterministe :
        - delete existant pour ce plan_id
        - insert nouvelles lignes
        """

        from sqlalchemy import delete

        await self._session.execute(delete(LignePlanProduction).where(LignePlanProduction.plan_production_id == plan_id))

        for l in lignes:
            self._session.add(
                LignePlanProduction(
                    plan_production_id=plan_id,
                    recette_id=l.recette_id,
                    quantite_a_produire=float(l.quantite_a_produire),
                    menu_id=None,
                )
            )

        await self._session.flush()

    @staticmethod
    def _valider_lignes(lignes: list[LigneProductionJour]) -> None:
        if not lignes:
            raise DonneesInvalidesProductionJour("Au moins une recette doit être fournie.")
        for l in lignes:
            if l.recette_id is None:
                raise DonneesInvalidesProductionJour("recette_id est obligatoire")
            if l.quantite_a_produire is None or float(l.quantite_a_produire) <= 0:
                raise DonneesInvalidesProductionJour("quantite_a_produire doit être > 0")
