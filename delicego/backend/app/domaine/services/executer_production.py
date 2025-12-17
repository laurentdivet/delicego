from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMouvementStock
from app.domaine.modeles.production import LigneConsommation, LotProduction
from app.domaine.modeles.referentiel import LigneRecette, Recette
from app.domaine.modeles.stock_tracabilite import MouvementStock
from app.domaine.services.allocateur_fefo import (
    AllocateurFEFO,
    DemandeConsommationIngredient,
    DonneesInvalidesFEFO,
    StockInsuffisant,
)


class ErreurProduction(Exception):
    """Erreur générique de production."""


class ProductionDejaExecutee(ErreurProduction):
    """La production a déjà été exécutée (consommations déjà enregistrées)."""


class DonneesInvalidesProduction(ErreurProduction):
    """Les données (recette, unités, quantités) ne permettent pas d’exécuter la production."""


@dataclass(frozen=True)
class ResultatExecutionProduction:
    lot_production_id: UUID
    nb_lignes_consommation: int
    nb_mouvements_stock: int


class ServiceExecutionProduction:
    """Exécute une production réelle et génère :
    - les LigneConsommation
    - les MouvementStock de type CONSOMMATION

    Règles :
    - Transaction unique (tout ou rien)
    - FEFO pour choisir les lots consommés
    - Aucun calcul de stock “en dur” : uniquement via MouvementStock

    NOTE :
    - `executer()` ouvre une transaction.
    - `executer_dans_transaction()` permet d'appeler l'exécution depuis un workflow qui gère déjà la transaction
      (ex: écran cuisine Produit / Ajusté / Non produit) sans imbriquer de transactions.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._allocateur = AllocateurFEFO(session)

    async def executer(self, *, lot_production_id: UUID) -> ResultatExecutionProduction:
        async with self._session.begin():
            return await self.executer_dans_transaction(lot_production_id=lot_production_id)

    async def executer_dans_transaction(self, *, lot_production_id: UUID) -> ResultatExecutionProduction:
        """Même logique que `executer` mais sans ouvrir de transaction."""

        lot_production = await self._charger_lot_production(lot_production_id)

        # Empêcher double exécution
        deja = await self._compter_lignes_consommation(lot_production_id)
        if deja > 0:
            raise ProductionDejaExecutee(
                "Des lignes de consommation existent déjà pour ce lot de production."
            )

        # Charger la recette + lignes
        recette, lignes_recette = await self._charger_recette_et_lignes(lot_production.recette_id)

        # Calculer besoins (très simple : quantite_ligne * quantite_produite)
        # Hypothèse : quantite_produite = “nombre d’unités produites” (portions, menus, etc.)
        if lot_production.quantite_produite <= 0:
            raise DonneesInvalidesProduction("La quantité produite doit être > 0.")

        lignes_consommation_creees: list[LigneConsommation] = []
        mouvements_crees: list[MouvementStock] = []

        for ligne in lignes_recette:
            quantite_necessaire = float(ligne.quantite) * float(lot_production.quantite_produite)

            if quantite_necessaire <= 0:
                continue

            demande = DemandeConsommationIngredient(
                ingredient_id=ligne.ingredient_id,
                quantite=quantite_necessaire,
                unite=ligne.unite,
            )

            try:
                allocations = await self._allocateur.allouer(
                    magasin_id=lot_production.magasin_id,
                    demande=demande,
                )
            except (StockInsuffisant, DonneesInvalidesFEFO) as e:
                # Toute la transaction est rollback automatiquement
                raise ErreurProduction(str(e)) from e

            for alloc in allocations:
                # 1) Mouvement de stock (CONSOMMATION)
                mouvement = MouvementStock(
                    type_mouvement=TypeMouvementStock.CONSOMMATION,
                    magasin_id=lot_production.magasin_id,
                    ingredient_id=ligne.ingredient_id,
                    lot_id=alloc.lot_id,
                    quantite=float(alloc.quantite_allouee),
                    unite=alloc.unite,
                    reference_externe=str(lot_production.id),
                    commentaire=f"Consommation production (recette={recette.id})",
                )
                self._session.add(mouvement)
                await self._session.flush()  # obtenir mouvement.id

                # 2) Ligne de consommation (traceabilité aval)
                ligne_conso = LigneConsommation(
                    lot_production_id=lot_production.id,
                    ingredient_id=ligne.ingredient_id,
                    lot_id=alloc.lot_id,
                    mouvement_stock_id=mouvement.id,
                    quantite=float(alloc.quantite_allouee),
                    unite=alloc.unite,
                )
                self._session.add(ligne_conso)

                mouvements_crees.append(mouvement)
                lignes_consommation_creees.append(ligne_conso)

        # flush final pour que tout soit réellement écrit dans la transaction
        await self._session.flush()

        return ResultatExecutionProduction(
            lot_production_id=lot_production.id,
            nb_lignes_consommation=len(lignes_consommation_creees),
            nb_mouvements_stock=len(mouvements_crees),
        )

    async def _charger_lot_production(self, lot_production_id: UUID) -> LotProduction:
        resultat = await self._session.execute(
            select(LotProduction).where(LotProduction.id == lot_production_id)
        )
        lot = resultat.scalar_one_or_none()
        if lot is None:
            raise DonneesInvalidesProduction("LotProduction introuvable.")
        return lot

    async def _compter_lignes_consommation(self, lot_production_id: UUID) -> int:
        resultat = await self._session.execute(
            select(func.count(LigneConsommation.id)).where(
                LigneConsommation.lot_production_id == lot_production_id
            )
        )
        return int(resultat.scalar_one())

    async def _charger_recette_et_lignes(self, recette_id: UUID) -> tuple[Recette, list[LigneRecette]]:
        resultat = await self._session.execute(select(Recette).where(Recette.id == recette_id))
        recette = resultat.scalar_one_or_none()
        if recette is None:
            raise DonneesInvalidesProduction("Recette introuvable.")

        resultat_lignes = await self._session.execute(
            select(LigneRecette).where(LigneRecette.recette_id == recette_id)
        )
        lignes = list(resultat_lignes.scalars().all())

        if not lignes:
            raise DonneesInvalidesProduction("La recette ne contient aucune ligne (BOM vide).")

        return recette, lignes
