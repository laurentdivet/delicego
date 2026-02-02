from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles.prediction_vente import PredictionVente
from app.domaine.modeles.referentiel import Ingredient, LigneRecette, Menu, Recette


@dataclass(frozen=True)
class BesoinIngredientPrevu:
    date_jour: date
    ingredient_id: UUID
    ingredient_nom: str
    unite: str
    quantite: float


class PrevisionsBesoinsService:
    """Calcule les besoins ingrédients futurs à partir des ventes prévues.

    Formule:
      besoin(ingredient, jour) = somme_{menus} qte_predite(menu, jour) * BOM(menu->recette->ligne_recette)

    Hypothèses (cohérentes avec le domaine existant):
    - Menu.recette_id est obligatoire
    - Les unités sont celles des lignes de recette (pas de conversion ici)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def calculer_besoins(
        self,
        *,
        magasin_id: UUID,
        date_debut: date,
        date_fin: date,
    ) -> list[BesoinIngredientPrevu]:
        if date_fin < date_debut:
            raise ValueError("date_fin doit être >= date_debut")

        res = await self._session.execute(
            select(
                PredictionVente.date_jour,
                Ingredient.id.label("ingredient_id"),
                Ingredient.nom.label("ingredient_nom"),
                LigneRecette.unite.label("unite"),
                func.coalesce(func.sum(PredictionVente.qte_predite * LigneRecette.quantite), 0.0).label("quantite"),
            )
            .select_from(PredictionVente)
            .join(Menu, Menu.id == PredictionVente.menu_id)
            .join(Recette, Recette.id == Menu.recette_id)
            .join(LigneRecette, LigneRecette.recette_id == Recette.id)
            .join(Ingredient, Ingredient.id == LigneRecette.ingredient_id)
            .where(
                PredictionVente.magasin_id == magasin_id,
                PredictionVente.date_jour >= date_debut,
                PredictionVente.date_jour <= date_fin,
            )
            .group_by(PredictionVente.date_jour, Ingredient.id, Ingredient.nom, LigneRecette.unite)
            .order_by(PredictionVente.date_jour.asc(), Ingredient.nom.asc())
        )

        out: list[BesoinIngredientPrevu] = []
        for d, ing_id, ing_nom, unite, q in res.all():
            out.append(
                BesoinIngredientPrevu(
                    date_jour=d,
                    ingredient_id=ing_id,
                    ingredient_nom=str(ing_nom),
                    unite=str(unite),
                    quantite=float(q or 0.0),
                )
            )
        return out
