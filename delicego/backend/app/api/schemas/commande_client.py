from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class MenuClient(BaseModel):
    """Représentation d’un menu côté API client."""

    menu_id: UUID
    nom: str
    disponible: bool
    estimation_capacite: float


class LigneCommandeClientRequete(BaseModel):
    """Ligne de commande envoyée par le client."""

    menu_id: UUID
    quantite: float = Field(gt=0)


class RequeteCommandeClient(BaseModel):
    """Payload de commande client."""

    magasin_id: UUID
    lignes: list[LigneCommandeClientRequete]
    commentaire: str | None = None


class ReponseCommandeClient(BaseModel):
    """Réponse de création de commande."""

    commande_client_id: UUID
    statut: str
