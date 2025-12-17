from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMouvementStock
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock


@dataclass(frozen=True)
class DemandeConsommationIngredient:
    ingredient_id: UUID
    quantite: float
    unite: str


@dataclass(frozen=True)
class AllocationLot:
    lot_id: UUID
    quantite_allouee: float
    unite: str
    date_dlc: date | None


class ErreurFEFO(Exception):
    """Erreur générique FEFO."""


class StockInsuffisant(ErreurFEFO):
    """Le stock disponible ne permet pas de satisfaire la demande."""


class DonneesInvalidesFEFO(ErreurFEFO):
    """La demande ou les données sources sont invalides."""


class AllocateurFEFO:
    """
    Allocateur FEFO (First Expired, First Out).

    - Lit la base via AsyncSession
    - Calcule le solde par lot à partir des MouvementStock
    - Retourne une proposition d’allocations (sans écrire en base)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def allouer(
        self,
        *,
        magasin_id: UUID,
        demande: DemandeConsommationIngredient,
    ) -> list[AllocationLot]:
        self._valider_demande(demande)

        # 1) Récupérer les lots candidats (FEFO = DLC la plus proche d’abord, lots sans DLC à la fin)
        lots = await self._charger_lots_fefo(
            magasin_id=magasin_id,
            ingredient_id=demande.ingredient_id,
        )

        if not lots:
            raise StockInsuffisant("Aucun lot disponible pour cet ingrédient.")

        # 2) Calculer les soldes disponibles par lot (sum mouvements signés)
        soldes_par_lot = await self._calculer_soldes_par_lot(
            magasin_id=magasin_id,
            ingredient_id=demande.ingredient_id,
        )

        # 3) Allouer
        reste = float(demande.quantite)
        allocations: list[AllocationLot] = []

        for lot in lots:
            if reste <= 0:
                break

            solde = float(soldes_par_lot.get(lot.id, 0.0))
            if solde <= 0:
                continue

            a_prendre = solde if solde <= reste else reste
            allocations.append(
                AllocationLot(
                    lot_id=lot.id,
                    quantite_allouee=float(a_prendre),
                    unite=demande.unite,
                    date_dlc=lot.date_dlc,
                )
            )
            reste -= a_prendre

        if reste > 1e-9:
            # Demande non satisfaite
            disponible = sum(float(v) for v in soldes_par_lot.values() if float(v) > 0)
            raise StockInsuffisant(
                f"Stock insuffisant : demandé={demande.quantite} {demande.unite}, disponible≈{disponible:.3f} {demande.unite}."
            )

        return allocations

    @staticmethod
    def _valider_demande(demande: DemandeConsommationIngredient) -> None:
        if demande.quantite is None or float(demande.quantite) <= 0:
            raise DonneesInvalidesFEFO("La quantité demandée doit être > 0.")
        if not demande.unite or not demande.unite.strip():
            raise DonneesInvalidesFEFO("L’unité de la demande est obligatoire.")
        if demande.ingredient_id is None:
            raise DonneesInvalidesFEFO("ingredient_id est obligatoire.")

    async def _charger_lots_fefo(self, *, magasin_id: UUID, ingredient_id: UUID) -> list[Lot]:
        # Tri FEFO : date_dlc ASC, et les NULL en dernier
        requete = (
            select(Lot)
            .where(Lot.magasin_id == magasin_id, Lot.ingredient_id == ingredient_id)
            .order_by(
                # False (0) avant True (1) => non-null d’abord, puis null à la fin
                (Lot.date_dlc.is_(None)).asc(),
                Lot.date_dlc.asc(),
                Lot.id.asc(),
            )
        )
        resultat = await self._session.execute(requete)
        return list(resultat.scalars().all())

    async def _calculer_soldes_par_lot(self, *, magasin_id: UUID, ingredient_id: UUID) -> dict[UUID, float]:
        """
        Calcule un solde par lot en sommant les mouvements signés.

        Convention:
        - + : RECEPTION, AJUSTEMENT, TRANSFERT
        - - : CONSOMMATION, PERTE
        """
        signe = case(
            (MouvementStock.type_mouvement.in_([TypeMouvementStock.RECEPTION, TypeMouvementStock.AJUSTEMENT, TypeMouvementStock.TRANSFERT]), 1),
            (MouvementStock.type_mouvement.in_([TypeMouvementStock.CONSOMMATION, TypeMouvementStock.PERTE]), -1),
            else_=0,
        )

        requete = (
            select(
                MouvementStock.lot_id,
                func.coalesce(func.sum(signe * MouvementStock.quantite), 0.0).label("solde"),
            )
            .where(
                MouvementStock.magasin_id == magasin_id,
                MouvementStock.ingredient_id == ingredient_id,
                MouvementStock.lot_id.is_not(None),
            )
            .group_by(MouvementStock.lot_id)
        )

        resultat = await self._session.execute(requete)
        soldes: dict[UUID, float] = {}
        for lot_id, solde in resultat.all():
            if lot_id is None:
                continue
            soldes[lot_id] = float(solde or 0.0)
        return soldes
