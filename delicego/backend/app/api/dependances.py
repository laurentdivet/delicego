from __future__ import annotations

import os
from collections.abc import AsyncIterator

import hmac
import logging

from fastapi import Header, HTTPException, Request, status
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
    request: Request,
    x_cle_interne: str | None = Header(default=None, alias="X-CLE-INTERNE"),
) -> None:
    """Contrôle d’accès minimal (API interne) par Bearer token.

    Règle : toutes les routes /api/interne/* exigent un header:
        Authorization: Bearer <token>

    Le token attendu est configuré via la variable d’environnement:
        INTERNAL_API_TOKEN

    Comportement:
    - Prod (ENV=prod) : INTERNAL_API_TOKEN requis, sinon 500 au démarrage de la dépendance.
    - Dev : si absent, fallback possible sur "dev-token" avec warning explicite.

    Compat:
    - On garde le header legacy X-CLE-INTERNE (si présent) pour ne pas casser
      des tests/clients existants, mais il est considéré *uniquement* comme token.
    """

    logger = logging.getLogger(__name__)

    # Environnement (best-effort)
    env = (os.getenv("ENV") or os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    is_prod = env in {"prod", "production"}

    expected = (os.getenv("INTERNAL_API_TOKEN") or "").strip()
    if not expected:
        if is_prod:
            # C’est une misconfiguration: on préfère expliciter.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="INTERNAL_API_TOKEN manquant en prod.",
            )
        expected = "dev-token"
        logger.warning(
            "INTERNAL_API_TOKEN absent: fallback DEV sur 'dev-token' (à NE PAS utiliser en prod).",
        )

    # 1) Authorization: Bearer <token>
    authorization = request.headers.get("Authorization")
    token: str | None = None
    if authorization:
        prefix = "bearer "
        if authorization.lower().startswith(prefix):
            token = authorization[len(prefix) :].strip()

    # 2) Legacy: X-CLE-INTERNE (si jamais présent)
    if not token and x_cle_interne and x_cle_interne.strip():
        token = x_cle_interne.strip()

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token interne manquant.")

    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token interne invalide.")
