from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import StatutCommandeFournisseur
from app.domaine.modeles.achats import CommandeFournisseur
from app.domaine.modeles.referentiel import Fournisseur
from app.domaine.services.bon_commande_fournisseur import ServiceBonCommandeFournisseur
from app.domaine.services.email_client import EmailClient


class ErreurEnvoiCommandeFournisseur(Exception):
    """Erreur générique d’envoi de commande fournisseur."""


class CommandeFournisseurIntrouvable(ErreurEnvoiCommandeFournisseur):
    """Commande fournisseur introuvable."""


class TransitionStatutInterditeEnvoiCommandeFournisseur(ErreurEnvoiCommandeFournisseur):
    """La commande ne peut pas être envoyée depuis son statut courant."""


class EchecEnvoiEmailCommandeFournisseur(ErreurEnvoiCommandeFournisseur):
    """Erreur lors de l’appel au client email."""


@dataclass(frozen=True)
class ParametresEmailCommandeFournisseur:
    destinataire: str
    sujet: str
    corps: str
    nom_piece_jointe: str = "bon-commande.pdf"


class ServiceEnvoiCommandeFournisseur:
    """Service métier : envoi logique d’une commande fournisseur par email.

    Contraintes (Étape 3) :
    - pas d’implémentation SMTP réelle
    - transaction atomique
    - aucune logique métier dans les endpoints
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        email_client: EmailClient,
        service_pdf: ServiceBonCommandeFournisseur | None = None,
    ) -> None:
        self._session = session
        self._email_client = email_client
        self._service_pdf = service_pdf or ServiceBonCommandeFournisseur(session)

    async def envoyer(
        self,
        *,
        commande_fournisseur_id: UUID,
        destinataire: str,
        sujet: str,
        corps: str,
    ) -> None:
        """Envoie (logiquement) la commande si elle est en BROUILLON, puis passe à ENVOYEE.

        Rollback total si l’envoi email échoue.
        """

        # IMPORTANT : ne pas exécuter de requête AVANT `begin()` (autobegin SQLAlchemy).
        async with self._session.begin():
            commande = await self._charger_commande(commande_fournisseur_id)

            if commande.statut != StatutCommandeFournisseur.BROUILLON:
                raise TransitionStatutInterditeEnvoiCommandeFournisseur(
                    "On ne peut envoyer que des commandes en BROUILLON."
                )

            # On génère le PDF en mémoire (bytes)
            pdf = await self._service_pdf.generer_pdf(commande.id)

            # destinataire : on exige un email explicite (pas de champ sur Fournisseur)
            if destinataire is None or not str(destinataire).strip():
                raise ErreurEnvoiCommandeFournisseur("destinataire est obligatoire.")

            try:
                await self._email_client.envoyer(
                    destinataire=str(destinataire),
                    sujet=str(sujet),
                    corps=str(corps),
                    pieces_jointes=[("bon-commande.pdf", bytes(pdf))],
                )
            except Exception as e:  # pragma: no cover
                # laisser l’exception casser la transaction => rollback
                raise EchecEnvoiEmailCommandeFournisseur(str(e)) from e

            # Transition de statut après succès de l’email
            commande.statut = StatutCommandeFournisseur.ENVOYEE
            await self._session.flush()

    async def _charger_commande(self, commande_fournisseur_id: UUID) -> CommandeFournisseur:
        res = await self._session.execute(
            select(CommandeFournisseur).where(CommandeFournisseur.id == commande_fournisseur_id)
        )
        commande = res.scalar_one_or_none()
        if commande is None:
            raise CommandeFournisseurIntrouvable("CommandeFournisseur introuvable.")
        return commande

    async def _charger_nom_fournisseur(self, fournisseur_id: UUID) -> str:
        res = await self._session.execute(select(Fournisseur.nom).where(Fournisseur.id == fournisseur_id))
        return str(res.scalar_one_or_none() or "(inconnu)")
