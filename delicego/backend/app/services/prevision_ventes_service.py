from __future__ import annotations

"""Service Prévisions Ventes.

IMPORTANT (décision produit)
---------------------------
La source de vérité des *prévisions API* est la table `prediction_vente`.

Historique : le repo contient aussi `LignePrevision` / `ExecutionPrevision` (planification interne).
Ces tables représentent un concept différent et ne doivent pas être utilisées comme prévision principale
dans l'API `/api/interne/previsions/ventes`.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles.prediction_vente import PredictionVente


@dataclass(frozen=True)
class PredictionVenteDTO:
    magasin_id: UUID
    menu_id: UUID
    date_jour: date
    qte_predite: float
    source: str


class PrevisionVentesService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lire_predictions(
        self,
        *,
        date_cible: date,
        magasin_id: UUID | None = None,
        horizon: int | None = None,
    ) -> list[PredictionVenteDTO]:
        """Lit les prédictions ML depuis `prediction_vente`.

        - `date_cible`: jour cible.
        - `horizon` (optionnel): nombre de jours à inclure (>=1).
          Si fourni, on renvoie les prédictions pour [date_cible, date_cible + horizon - 1].
        """

        if horizon is not None and horizon <= 0:
            horizon = 1

        date_fin = date_cible
        if horizon is not None:
            date_fin = date_cible + timedelta(days=int(horizon) - 1)

        q = select(
            PredictionVente.magasin_id,
            PredictionVente.menu_id,
            PredictionVente.date_jour,
            PredictionVente.qte_predite,
        ).where(PredictionVente.date_jour >= date_cible, PredictionVente.date_jour <= date_fin)

        if magasin_id is not None:
            q = q.where(PredictionVente.magasin_id == magasin_id)

        q = q.order_by(PredictionVente.magasin_id, PredictionVente.menu_id)

        rows = (await self._session.execute(q)).all()
        return [
            PredictionVenteDTO(
                magasin_id=r[0],
                menu_id=r[1],
                date_jour=r[2],
                qte_predite=float(r[3]),
                source="ml",
            )
            for r in rows
        ]
