from __future__ import annotations

from fastapi import FastAPI

from app.api.middleware_audit import MiddlewareAudit
from app.api.routeur import router
from app.api.sante import routeur_sante
from app.core.base_donnees import fournir_session_async


def creer_application() -> FastAPI:
    application = FastAPI(title="DéliceGo")

    # Middleware audit (append-only)
    application.add_middleware(MiddlewareAudit, session_factory=lambda: fournir_session_async())

    # Routes
    application.include_router(router)

    # Santé
    application.include_router(routeur_sante)

    return application


app = creer_application()
