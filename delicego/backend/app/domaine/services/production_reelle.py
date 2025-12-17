from __future__ import annotations

"""Production réelle : génération automatique d’un plan journalier + besoins ingrédients.

Objectifs :
- Générer un PlanProduction pour une date donnée en s’appuyant sur l’existant
  `ServicePlanificationProduction` (moyennes ventes + météo/événements + arrondi).
- Calculer les besoins ingrédients (BOM) à partir d’un PlanProduction.

Contraintes :
- Déterministe et testable : pas d’accès externe.
- Aucune régression sur l’existant : on réutilise les services actuels.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles.production import LignePlanProduction, PlanProduction
from app.domaine.modeles.referentiel import Ingredient, LigneRecette, Recette
from app.domaine.services.planifier_production import ServicePlanificationProduction


class ErreurProductionReelle(Exception):
    """Erreur générique de production réelle."""


@dataclass(frozen=True)
class BesoinIngredient:
    ingredient_id: UUID
    ingredient_nom: str
    quantite: float
    unite: str


class ServiceProductionReelle:
    """Service de production réelle (plan journalier + besoins ingrédients)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._service_planif = ServicePlanificationProduction(session)

    async def generer_plan_production(
        self,
        *,
        magasin_id: UUID,
        date_plan: date,
        fenetre_jours: int = 7,
        donnees_meteo: dict[str, float] | None = None,
        evenements: list[str] | None = None,
    ) -> PlanProduction:
        """Génère un plan de production pour `date_plan`.

        Stratégie :
        - Fenêtre historique glissante : [date_plan - fenetre_jours ; date_plan - 1]
        - Réutilise `ServicePlanificationProduction.planifier`.
        """

        if fenetre_jours <= 0:
            raise ErreurProductionReelle("fenetre_jours doit être > 0")

        donnees_meteo = donnees_meteo or {}
        evenements = evenements or []

        date_fin_historique = date_plan - timedelta(days=1)
        date_debut_historique = date_plan - timedelta(days=fenetre_jours)

        return await self._service_planif.planifier(
            magasin_id=magasin_id,
            date_plan=date_plan,
            date_debut_historique=date_debut_historique,
            date_fin_historique=date_fin_historique,
            donnees_meteo=donnees_meteo,
            evenements=evenements,
        )

    async def calculer_besoins_ingredients(self, *, plan_id: UUID) -> list[BesoinIngredient]:
        """Calcule les besoins ingrédients d’un plan.

        Règle :
        besoin_ingredient = somme_sur_recettes(quantite_planifiee * quantite_bom)

        Note :
        - On conserve l’unité de la LigneRecette.
        - Si plusieurs unités existent pour un même ingrédient sur des lignes différentes,
          on lève une erreur (cas à normaliser côté recettes).
        """

        res = await self._session.execute(select(PlanProduction.id).where(PlanProduction.id == plan_id))
        if res.scalar_one_or_none() is None:
            raise ErreurProductionReelle("PlanProduction introuvable.")

        # Agrégation SQL : join Plan -> lignes -> recette -> ligne_recette -> ingredient
        q = (
            select(
                Ingredient.id.label("ingredient_id"),
                Ingredient.nom.label("ingredient_nom"),
                LigneRecette.unite.label("unite"),
                func.coalesce(
                    func.sum(LignePlanProduction.quantite_a_produire * LigneRecette.quantite),
                    0.0,
                ).label("quantite"),
            )
            .select_from(LignePlanProduction)
            .join(Recette, Recette.id == LignePlanProduction.recette_id)
            .join(LigneRecette, LigneRecette.recette_id == Recette.id)
            .join(Ingredient, Ingredient.id == LigneRecette.ingredient_id)
            .where(LignePlanProduction.plan_production_id == plan_id)
            .group_by(Ingredient.id, Ingredient.nom, LigneRecette.unite)
            .order_by(Ingredient.nom.asc())
        )

        res = await self._session.execute(q)
        lignes = res.all()

        # Détecter conflit d’unités (même ingredient_id avec plusieurs unités)
        unites_par_ingredient: dict[UUID, str] = {}
        besoins: list[BesoinIngredient] = []

        for ingredient_id, ingredient_nom, unite, quantite in lignes:
            unite_str = str(unite)
            if ingredient_id in unites_par_ingredient and unites_par_ingredient[ingredient_id] != unite_str:
                raise ErreurProductionReelle(
                    f"Ingrédient {ingredient_nom} a plusieurs unités dans les recettes ({unites_par_ingredient[ingredient_id]} vs {unite_str})."
                )
            unites_par_ingredient[ingredient_id] = unite_str

            besoins.append(
                BesoinIngredient(
                    ingredient_id=ingredient_id,
                    ingredient_nom=str(ingredient_nom),
                    quantite=float(quantite or 0.0),
                    unite=unite_str,
                )
            )

        return besoins
