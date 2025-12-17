from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import StatutCommandeClient
from app.domaine.modeles.commande_client import CommandeClient, LigneCommandeClient
from app.domaine.modeles.production import LotProduction
from app.domaine.modeles.referentiel import Menu, Recette
from app.domaine.services.allocateur_fefo import StockInsuffisant
from app.domaine.services.executer_production import (
    DonneesInvalidesProduction,
    ErreurProduction,
    ServiceExecutionProduction,
)


class ErreurCommandeClient(Exception):
    """Erreur générique de commande client."""


class DonneesInvalidesCommandeClient(ErreurCommandeClient):
    """La commande ne peut pas être créée (menus, quantités…)."""


class StockInsuffisantCommandeClient(ErreurCommandeClient):
    """La commande échoue car le stock ne permet pas la production."""


class ServiceCommandeClient:
    """Service de commande client (canal en ligne).

    Principes (non négociables) :
    - Aucune logique stock en direct : tout passe par `ServiceExecutionProduction`.
    - Aucune duplication FEFO : l’exécution utilise le service existant.
    - Transaction atomique : si la production échoue => commande + lots annulés (rollback).

    Détail technique important :
    `ServiceExecutionProduction` ouvre sa propre transaction via `session.begin()`.
    Pour conserver l’atomicité sans transactions imbriquées sur une même session,
    on pilote une transaction au niveau *connexion* (BEGIN) et on exécute les
    services à l’intérieur.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commander(
        self,
        *,
        magasin_id: UUID,
        lignes: list[tuple[UUID, float]],
        commentaire: str | None = None,
    ) -> UUID:
        """Crée une commande client et déclenche la production associée.

        Paramètres :
        - magasin_id : magasin de production (où les lots seront consommés)
        - lignes : liste de tuples (menu_id, quantite)

        Retour : commande_client_id.
        """

        self._valider_lignes(lignes)

        moteur = self._session.bind
        if moteur is None:
            raise ErreurCommandeClient("Session SQLAlchemy non liée à un moteur.")

        # Transaction *globale* sur connexion : rollback total si un seul lot échoue.
        async with moteur.connect() as connexion:  # type: ignore[union-attr]
            async with connexion.begin():
                commande_id: UUID | None = None
                lots_a_executer: list[UUID] = []

                try:
                    # 1) Écriture de la commande + des lots (sans lancer d’exécution ici)
                    session_ecriture = AsyncSession(bind=connexion, expire_on_commit=False)
                    try:
                        commande = CommandeClient(
                            magasin_id=magasin_id,
                            date_commande=datetime.now(timezone.utc),
                            statut=StatutCommandeClient.EN_ATTENTE,
                            commentaire=commentaire,
                        )
                        session_ecriture.add(commande)
                        await session_ecriture.flush()  # obtenir commande.id
                        commande_id = commande.id

                        for menu_id, quantite in lignes:
                            recette_id = await self._trouver_recette_id_pour_menu(
                                session=session_ecriture,
                                menu_id=menu_id,
                            )

                            lot_production = LotProduction(
                                magasin_id=magasin_id,
                                plan_production_id=None,
                                recette_id=recette_id,
                                quantite_produite=float(quantite),
                                unite="unite",
                            )
                            session_ecriture.add(lot_production)
                            await session_ecriture.flush()  # obtenir lot_production.id

                            session_ecriture.add(
                                LigneCommandeClient(
                                    commande_client_id=commande.id,
                                    menu_id=menu_id,
                                    quantite=float(quantite),
                                    lot_production_id=lot_production.id,
                                )
                            )

                            lots_a_executer.append(lot_production.id)

                        await session_ecriture.flush()
                    finally:
                        await session_ecriture.close()

                    # 2) Exécuter les lots via le service existant.
                    # IMPORTANT : on utilise une session dédiée par exécution pour éviter
                    # les conflits de transaction (`ServiceExecutionProduction` fait `session.begin()`).
                    for lot_production_id in lots_a_executer:
                        session_exec = AsyncSession(bind=connexion, expire_on_commit=False)
                        try:
                            service_production = ServiceExecutionProduction(session_exec)
                            await service_production.executer(lot_production_id=lot_production_id)
                        finally:
                            await session_exec.close()

                    # 3) Finaliser la commande
                    assert commande_id is not None
                    session_final = AsyncSession(bind=connexion, expire_on_commit=False)
                    try:
                        res = await session_final.execute(
                            select(CommandeClient).where(CommandeClient.id == commande_id)
                        )
                        commande_finale = res.scalar_one()
                        commande_finale.statut = StatutCommandeClient.CONFIRMEE
                        await session_final.flush()
                    finally:
                        await session_final.close()

                    return commande_id

                except StockInsuffisant as e:
                    raise StockInsuffisantCommandeClient(str(e)) from e
                except (DonneesInvalidesProduction, ErreurProduction) as e:
                    # ErreurProduction peut encapsuler un StockInsuffisant (message explicite).
                    # On mappe donc sur un conflit de stock si c’est le cas.
                    if "Stock insuffisant" in str(e):
                        raise StockInsuffisantCommandeClient(str(e)) from e
                    raise DonneesInvalidesCommandeClient(str(e)) from e

    @staticmethod
    def _valider_lignes(lignes: list[tuple[UUID, float]]) -> None:
        if not lignes:
            raise DonneesInvalidesCommandeClient("La commande doit contenir au moins une ligne.")

        for menu_id, quantite in lignes:
            if menu_id is None:
                raise DonneesInvalidesCommandeClient("menu_id est obligatoire.")
            if quantite is None or float(quantite) <= 0:
                raise DonneesInvalidesCommandeClient("La quantité doit être > 0.")

    async def _trouver_recette_id_pour_menu(
        self,
        *,
        session: AsyncSession,
        menu_id: UUID,
    ) -> UUID:
        # Valider que le menu existe
        res_menu = await session.execute(select(Menu.id).where(Menu.id == menu_id))
        if res_menu.scalar_one_or_none() is None:
            raise DonneesInvalidesCommandeClient("Menu introuvable.")

        # Trouver la recette associée (modèle Inpulse-like : menu -> recette)
        res_recette = await session.execute(select(Menu.recette_id).where(Menu.id == menu_id))
        recette_id = res_recette.scalar_one_or_none()
        if recette_id is None:
            raise DonneesInvalidesCommandeClient("Aucune recette associée à ce menu.")

        return recette_id
