from __future__ import annotations

from fastapi import APIRouter

routeur_sante = APIRouter(tags=["sante"])


@routeur_sante.get("/health")
async def health() -> dict[str, str]:
    """Endpoint minimal pour valider que l’application démarre."""

    return {"statut": "ok"}
