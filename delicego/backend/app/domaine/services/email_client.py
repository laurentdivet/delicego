from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class EmailClient(Protocol):
    """Interface injectable d’envoi d’emails.

    Contrat (Étape 3) :
    - aucun SMTP réel dans le domaine
    - utilisé par le service d’envoi de commande fournisseur
    """

    async def envoyer(
        self,
        *,
        destinataire: str,
        sujet: str,
        corps: str,
        pieces_jointes: list[tuple[str, bytes]],
    ) -> None:
        ...


@dataclass
class EmailEnvoye:
    destinataire: str
    sujet: str
    corps: str
    pieces_jointes: list[tuple[str, bytes]]


class NoopEmailClient:
    """Email client par défaut : aucun envoi réel (no-op)."""

    async def envoyer(
        self,
        *,
        destinataire: str,
        sujet: str,
        corps: str,
        pieces_jointes: list[tuple[str, bytes]],
    ) -> None:
        return None


class FakeEmailClient:
    """Email client de test : stocke les emails en mémoire."""

    def __init__(self) -> None:
        self.emails: list[EmailEnvoye] = []

    async def envoyer(
        self,
        *,
        destinataire: str,
        sujet: str,
        corps: str,
        pieces_jointes: list[tuple[str, bytes]],
    ) -> None:
        self.emails.append(
            EmailEnvoye(
                destinataire=str(destinataire),
                sujet=str(sujet),
                corps=str(corps),
                pieces_jointes=[(str(nom), bytes(data)) for nom, data in pieces_jointes],
            )
        )
