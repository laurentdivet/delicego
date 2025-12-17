from __future__ import annotations

"""Disponibilité temps réel des menus (stock -> menu disponible).

Règles :
- Un menu est disponible si sa recette associée est produisible pour une quantité donnée.
- On vérifie chaque ingrédient de la BOM (LigneRecette).
- Allocation FEFO obligatoire (via AllocateurFEFO) : si l’allocateur ne peut pas allouer,
  alors le menu est indisponible.

Contraintes :
- Déterministe et testable : lecture seule, aucun effet de bord.
- Pas de mock : s’appuie sur les modèles stock (Lot/MouvementStock) existants.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles.referentiel import LigneRecette, Menu, Recette
from app.domaine.services.allocateur_fefo import AllocateurFEFO, DemandeConsommationIngredient
from app.domaine.services.allocateur_fefo import DonneesInvalidesFEFO, StockInsuffisant


class ErreurDisponibiliteMenu(Exception):
    """Erreur générique de disponibilité."""


class MenuIntrouvable(ErreurDisponibiliteMenu):
    pass


class MenuSansRecette(ErreurDisponibiliteMenu):
    pass


class RecetteInvalide(ErreurDisponibiliteMenu):
    pass


class ServiceDisponibiliteMenu:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._allocateur = AllocateurFEFO(session)

    async def est_menu_disponible(self, *, menu_id: UUID, quantite: float = 1.0) -> bool:
        """Retourne True si le stock permet de produire `quantite` unités du menu."""

        if quantite is None or float(quantite) <= 0:
            raise ErreurDisponibiliteMenu("La quantité doit être > 0.")

        # 1) menu existe
        res_menu = await self._session.execute(select(Menu.id).where(Menu.id == menu_id))
        if res_menu.scalar_one_or_none() is None:
            raise MenuIntrouvable("Menu introuvable.")

        # 2) recette associée (modèle Inpulse-like : menu -> recette)
        res_recette_id = await self._session.execute(select(Menu.recette_id).where(Menu.id == menu_id))
        recette_id = res_recette_id.scalar_one_or_none()
        if recette_id is None:
            raise MenuSansRecette("Aucune recette associée à ce menu.")

        res_recette = await self._session.execute(select(Recette).where(Recette.id == recette_id))
        recette = res_recette.scalar_one_or_none()
        if recette is None:
            raise MenuSansRecette("Aucune recette associée à ce menu.")

        # 3) lignes de recette
        res_lignes = await self._session.execute(
            select(LigneRecette).where(LigneRecette.recette_id == recette.id)
        )
        lignes = list(res_lignes.scalars().all())
        if not lignes:
            raise RecetteInvalide("La recette ne contient aucune ligne (BOM vide).")

        # 4) pour chaque ingrédient, tenter une allocation FEFO
        for ligne in lignes:
            quantite_necessaire = float(ligne.quantite) * float(quantite)
            if quantite_necessaire <= 0:
                continue

            demande = DemandeConsommationIngredient(
                ingredient_id=ligne.ingredient_id,
                quantite=quantite_necessaire,
                unite=ligne.unite,
            )

            try:
                # La recette est désormais globale; le magasin de stock est celui du menu.
                res_magasin = await self._session.execute(select(Menu.magasin_id).where(Menu.id == menu_id))
                magasin_id = res_magasin.scalar_one()
                await self._allocateur.allouer(magasin_id=magasin_id, demande=demande)
            except (StockInsuffisant, DonneesInvalidesFEFO):
                return False

        return True
