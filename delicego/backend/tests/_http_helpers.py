"""Helpers HTTP STRICTEMENT côté tests.

Objectif: centraliser les headers d'accès interne pour éviter les 401
"Token interne invalide" en tests.
"""

from __future__ import annotations

import os



def entetes_internes(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Headers pour /api/interne/*.

    Règle: le token interne est toujours envoyé via X-CLE-INTERNE.
    La valeur provient de INTERNAL_API_TOKEN (fallback dev-token).

    `extra` permet d'ajouter d'autres headers (ex: Authorization pour un JWT applicatif).
    """

    # IMPORTANT :
    # Certaines routes internes exigent *aussi* un JWT applicatif via Authorization.
    # Le token interne doit donc rester sur X-CLE-INTERNE, et on force également
    # une valeur d'Authorization non vide pour satisfaire les endpoints qui ne
    # disposent pas (encore) d'une alternative en tests.
    #
    # Par convention on utilise "Bearer <INTERNAL_API_TOKEN>".
    token_interne = os.getenv("INTERNAL_API_TOKEN", "dev-token")

    h: dict[str, str] = {
        "X-CLE-INTERNE": token_interne,
        # Compat: certaines routes internes attendent encore Authorization: Bearer <token interne>
        "Authorization": f"Bearer {token_interne}",
    }
    if extra:
        h.update(extra)
    return h
