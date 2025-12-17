from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import StatutCommandeFournisseur, TypeMouvementStock
from app.domaine.modeles.achats import CommandeFournisseur, LigneCommandeFournisseur
from app.domaine.modeles.production import LignePlanProduction, PlanProduction
from app.domaine.modeles.referentiel import Fournisseur, Ingredient, LigneRecette, Recette
from app.domaine.modeles.stock_tracabilite import MouvementStock


class ErreurGenerationBesoinsFournisseurs(Exception):
    """Erreur générique de génération des besoins fournisseurs."""


class DonneesInvalidesGenerationBesoinsFournisseurs(ErreurGenerationBesoinsFournisseurs):
    """Entrées invalides / incohérences."""


@dataclass(frozen=True)
class BesoinIngredientNet:
    ingredient_id: UUID
    quantite: float
    unite: str


class ServiceGenerationBesoinsFournisseurs:
    """Génération automatique de commandes fournisseurs (BROUILLON).

    Règles :
    - Se base sur les plans de production / prévisions (ici : PlanProduction existant).
    - Soustrait le stock disponible (somme signée des mouvements).
    - Ne crée AUCUNE écriture stock.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def generer(
        self,
        *,
        magasin_id: UUID,
        date_cible: date,
        horizon: int,
    ) -> list[UUID]:
        if magasin_id is None:
            raise DonneesInvalidesGenerationBesoinsFournisseurs("magasin_id est obligatoire.")
        if horizon is None or int(horizon) <= 0:
            raise DonneesInvalidesGenerationBesoinsFournisseurs("horizon doit être > 0.")

        date_fin = date_cible + timedelta(days=int(horizon) - 1)

        # IMPORTANT : `begin()` doit être le tout premier accès DB (autobegin SQLAlchemy).
        async with self._session.begin():
            # 1) Lire plans de production sur l’horizon
            plans = await self._charger_plans(
                magasin_id=magasin_id,
                date_debut=date_cible,
                date_fin=date_fin,
            )

            # 2) Besoins bruts ingrédients (BOM * quantités planifiées)
            besoins_bruts = await self._calculer_besoins_bruts(plans=plans)

            # 3) Stock disponible (global par ingrédient)
            stock_dispo = await self._calculer_stock_disponible(magasin_id=magasin_id)

            # 4) Netting
            besoins_nets: list[BesoinIngredientNet] = []
            for b in besoins_bruts:
                dispo = float(stock_dispo.get(b.ingredient_id, 0.0))
                net = float(b.quantite) - dispo
                if net <= 0:
                    continue
                besoins_nets.append(BesoinIngredientNet(ingredient_id=b.ingredient_id, quantite=net, unite=b.unite))

            # 5) Groupement par fournisseur
            # Le référentiel ne mappe pas ingrédient -> fournisseur. On utilise une règle déterministe :
            # - si un seul fournisseur existe : on l’utilise
            # - sinon : on choisit le fournisseur au nom le plus petit (tri) pour garder la déterminisme.
            fournisseur_id = await self._choisir_fournisseur_defaut()

            ids_commandes: list[UUID] = []

            # Créer une commande brouillon unique pour l’horizon
            commande = CommandeFournisseur(
                fournisseur_id=fournisseur_id,
                date_commande=date_cible,
                statut=StatutCommandeFournisseur.BROUILLON,
                commentaire=f"Besoins auto {date_cible.isoformat()} +{horizon}j",
            )
            self._session.add(commande)
            await self._session.flush()
            ids_commandes.append(commande.id)

            for b in besoins_nets:
                self._session.add(
                    LigneCommandeFournisseur(
                        commande_fournisseur_id=commande.id,
                        ingredient_id=b.ingredient_id,
                        quantite=float(b.quantite),
                        unite=b.unite,
                    )
                )

            await self._session.flush()
            return ids_commandes

    async def _charger_plans(self, *, magasin_id: UUID, date_debut: date, date_fin: date) -> list[UUID]:
        res = await self._session.execute(
            select(PlanProduction.id)
            .where(
                PlanProduction.magasin_id == magasin_id,
                PlanProduction.date_plan >= date_debut,
                PlanProduction.date_plan <= date_fin,
            )
            .order_by(PlanProduction.date_plan.asc())
        )
        return [pid for (pid,) in res.all()]

    async def _calculer_besoins_bruts(self, *, plans: list[UUID]) -> list[BesoinIngredientNet]:
        if not plans:
            return []

        # Agrégation SQL : somme(quantite_a_produire * quantite_bom) groupée par ingredient + unite
        q = (
            select(
                Ingredient.id.label("ingredient_id"),
                LigneRecette.unite.label("unite"),
                func.coalesce(func.sum(LignePlanProduction.quantite_a_produire * LigneRecette.quantite), 0.0).label(
                    "quantite"
                ),
            )
            .select_from(LignePlanProduction)
            .join(Recette, Recette.id == LignePlanProduction.recette_id)
            .join(LigneRecette, LigneRecette.recette_id == Recette.id)
            .join(Ingredient, Ingredient.id == LigneRecette.ingredient_id)
            .where(LignePlanProduction.plan_production_id.in_(plans))
            .group_by(Ingredient.id, LigneRecette.unite)
        )

        res = await self._session.execute(q)
        lignes = res.all()

        # Détecter conflit d’unités
        unites: dict[UUID, str] = {}
        besoins: list[BesoinIngredientNet] = []
        for ingredient_id, unite, quantite in lignes:
            unite_str = str(unite)
            if ingredient_id in unites and unites[ingredient_id] != unite_str:
                raise ErreurGenerationBesoinsFournisseurs(
                    f"Ingrédient {ingredient_id} a plusieurs unités ({unites[ingredient_id]} vs {unite_str})."
                )
            unites[ingredient_id] = unite_str
            besoins.append(BesoinIngredientNet(ingredient_id=ingredient_id, quantite=float(quantite or 0.0), unite=unite_str))

        return besoins

    async def _calculer_stock_disponible(self, *, magasin_id: UUID) -> dict[UUID, float]:
        signe = case(
            (
                MouvementStock.type_mouvement.in_(
                    [TypeMouvementStock.RECEPTION, TypeMouvementStock.AJUSTEMENT, TypeMouvementStock.TRANSFERT]
                ),
                1,
            ),
            (MouvementStock.type_mouvement.in_([TypeMouvementStock.CONSOMMATION, TypeMouvementStock.PERTE]), -1),
            else_=0,
        )

        res = await self._session.execute(
            select(
                MouvementStock.ingredient_id,
                func.coalesce(func.sum(signe * MouvementStock.quantite), 0.0).label("stock"),
            ).where(MouvementStock.magasin_id == magasin_id)
            .group_by(MouvementStock.ingredient_id)
        )

        return {ingredient_id: float(stock or 0.0) for ingredient_id, stock in res.all()}

    async def _choisir_fournisseur_defaut(self) -> UUID:
        res = await self._session.execute(select(Fournisseur.id, Fournisseur.nom).where(Fournisseur.actif.is_(True)))
        fournisseurs = [(fid, str(nom)) for fid, nom in res.all()]
        if not fournisseurs:
            raise DonneesInvalidesGenerationBesoinsFournisseurs("Aucun fournisseur actif : impossible de générer.")

        # déterministe
        fournisseurs = sorted(fournisseurs, key=lambda x: x[1])
        return fournisseurs[0][0]
