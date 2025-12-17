from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_donnees import fournir_session_async
from app.domaine.services.email_client import EmailClient, NoopEmailClient


async def fournir_session() -> AsyncIterator[AsyncSession]:
    """Dépendance FastAPI : fournit une session SQLAlchemy asynchrone."""

    async for session in fournir_session_async():
        yield session


def fournir_email_client() -> EmailClient:
    """Dépendance FastAPI : client email injectable.

    Par défaut : aucun envoi réel.
    """

    return NoopEmailClient()


def verifier_acces_interne(
    x_cle_interne: str | None = Header(default=None, alias="X-CLE-INTERNE"),
) -> None:
    """Contrôle d’accès minimal (API interne).

    Règle : un header technique doit être présent.

    NOTE :
    - Pas d’auth lourde (non demandé).
    - La vérification reste volontairement simple.
    """

    if x_cle_interne is None or not x_cle_interne.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Accès interne refusé (header X-CLE-INTERNE manquant).",
        )
