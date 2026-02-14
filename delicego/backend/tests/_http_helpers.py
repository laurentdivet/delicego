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

    h: dict[str, str] = {"X-CLE-INTERNE": os.getenv("INTERNAL_API_TOKEN", "dev-token")}
    if extra:
        h.update(extra)
    return h
