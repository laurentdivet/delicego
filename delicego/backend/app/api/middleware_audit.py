from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances_auth import _extraire_bearer
from app.core.configuration import parametres_application
from app.core.securite import decoder_token_acces
from app.domaine.modeles.audit import AuditLog


class MiddlewareAudit(BaseHTTPMiddleware):
    """Middleware d’audit automatique.

    - Journalise chaque requête (hors /health) en append-only.
    - Associe l'utilisateur si un Bearer token valide est fourni.

    Note: on journalise en "best effort" : l'audit ne doit pas casser la route.
    """

    def __init__(self, app: Any, *, session_factory: Any):
        super().__init__(app)
        self._session_factory = session_factory

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        # Exécuter la requête d'abord
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            await self._audit(request, response)

    async def _audit(self, request: Request, response: Response | None) -> None:
        user_id = None
        token = _extraire_bearer(request.headers.get("authorization"))
        if token:
            try:
                payload = decoder_token_acces(token, secret=parametres_application.jwt_secret)
                user_id = payload.get("sub")
            except Exception:
                user_id = None

        # Body: uniquement pour méthodes non-GET et en limitant la taille
        donnees = None
        try:
            if request.method.upper() not in {"GET", "HEAD"}:
                corps = await request.body()
                if corps and len(corps) <= 10_000:
                    try:
                        donnees = json.loads(corps.decode("utf-8"))
                    except Exception:
                        donnees = {"raw": corps[:200].decode("utf-8", errors="replace")}
        except Exception:
            donnees = None

        # NB: sub est un UUID string. SQLAlchemy peut caster automatiquement,
        # mais on cast explicitement si possible.
        try:
            from uuid import UUID

            user_uuid = UUID(user_id) if user_id is not None else None
        except Exception:
            user_uuid = None

        audit = AuditLog(
            user_id=user_uuid,
            cree_le=datetime.now(tz=timezone.utc),
            action="http_request",
            ressource="http",
            ressource_id=None,
            methode_http=request.method,
            chemin=str(request.url.path),
            statut_http=(response.status_code if response else None),
            donnees=donnees,
            ip=(request.client.host if request.client else None),
            user_agent=request.headers.get("user-agent"),
        )

        try:
            async with self._session_factory() as session:  # type: ignore[call-arg]
                session: AsyncSession
                session.add(audit)
                await session.commit()
        except Exception:
            # Best effort: ne jamais casser la prod
            return
