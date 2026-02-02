from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles.prediction_vente import PredictionVente
import pytest

from app.services.prevision_ventes_ml_service import PrevisionVentesMLService


@pytest.mark.asyncio
async def test_run_forecast_writes_predictions(session_test: AsyncSession) -> None:
    """Smoke test: sur DB seedée (fixtures), on peut lancer run_forecast et écrire prediction_vente.

    NB: en CI, la DB est souvent pauvre en ventes => le service bascule en dataset synthétique.
    """

    svc = PrevisionVentesMLService(session_test)
    report = await svc.run_forecast(horizon_days=7)
    assert report.predictions_written > 0

    n = (
        await session_test.execute(select(func.count()).select_from(PredictionVente))
    ).scalar_one()
    assert int(n) > 0
