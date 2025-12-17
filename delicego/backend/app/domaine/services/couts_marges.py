from __future__ import annotations

"""Service de calcul des coûts matière et marges.

Règles :
- Coût recette = somme(quantite * cout_unitaire) sur les lignes
- Coût menu = coût de la recette principale rattachée au menu
- Marge menu = prix_vente - coût

Contraintes :
- Déterministe : uniquement DB + paramètres d’entrée.
- Testable : pas d’accès externe, pas d’effets de bord.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles.referentiel import Ingredient, LigneRecette, Menu, Recette


class ErreurCoutsMarges(Exception):
    """Erreur générique de calcul de coûts/marges."""


class RecetteIntrouvable(ErreurCoutsMarges):
    pass


class MenuSansRecette(ErreurCoutsMarges):
    pass


@dataclass(frozen=True)
class CoutMargeMenu:
    menu_id: UUID
    cout: float
    prix: float
    marge: float
    taux_marge: float


class ServiceCoutsMarges:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def calculer_cout_recette(self, recette_id: UUID) -> float:
        """Calcule le coût matière d’une recette."""

        # On vérifie l’existence pour une erreur contrôlée.
        res = await self._session.execute(select(Recette.id).where(Recette.id == recette_id))
        if res.scalar_one_or_none() is None:
            raise RecetteIntrouvable("Recette introuvable.")

        # somme(quantite * cout_unitaire)
        res = await self._session.execute(
            select(func.coalesce(func.sum(LigneRecette.quantite * Ingredient.cout_unitaire), 0.0))
            .select_from(LigneRecette)
            .join(Ingredient, Ingredient.id == LigneRecette.ingredient_id)
            .where(LigneRecette.recette_id == recette_id)
        )
        return float(res.scalar_one())

    async def calculer_cout_menu(self, menu_id: UUID) -> float:
        """Calcule le coût matière d’un menu (via sa recette principale)."""

        recette_id = await self._obtenir_recette_id_du_menu(menu_id)
        return await self.calculer_cout_recette(recette_id)

    async def calculer_marge_menu(self, menu_id: UUID, prix_vente: float) -> float:
        cout = await self.calculer_cout_menu(menu_id)
        return float(prix_vente) - float(cout)

    async def calculer_cout_marge_menu_depuis_prix_menu(self, menu_id: UUID) -> CoutMargeMenu:
        """Utilitaire : calcule coût + marge en utilisant Menu.prix comme prix_vente."""

        res = await self._session.execute(select(Menu).where(Menu.id == menu_id))
        menu = res.scalar_one_or_none()
        if menu is None:
            raise ErreurCoutsMarges("Menu introuvable.")

        cout = await self.calculer_cout_menu(menu_id)
        prix = float(menu.prix)
        marge = prix - cout
        taux = (marge / prix) if prix > 0 else 0.0

        return CoutMargeMenu(
            menu_id=menu_id,
            cout=float(cout),
            prix=prix,
            marge=float(marge),
            taux_marge=float(taux),
        )

    async def _obtenir_recette_id_du_menu(self, menu_id: UUID) -> UUID:
        res = await self._session.execute(select(Menu.recette_id).where(Menu.id == menu_id))
        recette_id = res.scalar_one_or_none()
        if recette_id is None:
            raise MenuSansRecette("Aucune recette associée à ce menu.")
        return recette_id
