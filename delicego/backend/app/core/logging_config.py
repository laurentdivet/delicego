from __future__ import annotations

import logging
import os


def configurer_logging() -> None:
    """Configuration de logging minimaliste pour la prod.

    Objectifs:
    - logs JSON-friendly (clé=valeur) mais sans dépendances externes
    - niveau configurable via LOG_LEVEL
    - sortie stdout (compatible Docker)

    NOTE: volontairement simple. Si besoin ultérieur, on pourra brancher
    structlog / OpenTelemetry, etc.
    """

    level_str = os.getenv("LOG_LEVEL", "INFO").upper().strip()
    level = getattr(logging, level_str, logging.INFO)

    # Évite les doubles handlers si appelé plusieurs fois
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return

    logging.basicConfig(
        level=level,
        format="%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s",
    )
