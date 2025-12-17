from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.endpoints.analytics import _STORE as ANALYTICS_STORE
from app.domaine.modeles.operations import StockMovement, StockMovementType
from app.domaine.services.analytics import Period, cost_matter_real, cost_matter_theoretical, gaps, margin
from app.main import app


@pytest.fixture(autouse=True)
def reset_store() -> None:
    ANALYTICS_STORE.movements.clear()
    ANALYTICS_STORE.sales.clear()


def test_calcul_cout_matiere_reel_correct() -> None:
    p = uuid4()
    e = uuid4()
    u = uuid4()

    ANALYTICS_STORE.movements.extend(
        [
            StockMovement(
                produit_id=p,
                etablissement_id=e,
                type=StockMovementType.SORTIE,
                quantite=2,
                valeur_unitaire=3,
                utilisateur_id=u,
                date_heure=datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
            StockMovement(
                produit_id=p,
                etablissement_id=e,
                type=StockMovementType.PERTE,
                quantite=1,
                valeur_unitaire=5,
                utilisateur_id=u,
                date_heure=datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
        ]
    )

    res = cost_matter_real(ANALYTICS_STORE.movements, period=Period.DAY)
    assert len(res) == 1
    assert res[0].value == 2 * 3 + 1 * 5


def test_calcul_cout_matiere_theorique() -> None:
    ANALYTICS_STORE.sales.extend(
        [
            {"date": datetime(2025, 1, 1, tzinfo=timezone.utc).date(), "ca": 100.0, "cost_rate": 0.3},
        ]
    )
    res = cost_matter_theoretical(ANALYTICS_STORE.sales, period=Period.DAY)
    assert res[0].value == 30.0


def test_calcul_marge() -> None:
    p = uuid4()
    e = uuid4()
    u = uuid4()
    ANALYTICS_STORE.movements.append(
        StockMovement(
            produit_id=p,
            etablissement_id=e,
            type=StockMovementType.SORTIE,
            quantite=10,
            valeur_unitaire=2,
            utilisateur_id=u,
            date_heure=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    )
    ANALYTICS_STORE.sales.append({"date": datetime(2025, 1, 1, tzinfo=timezone.utc).date(), "ca": 50.0, "cost_rate": 0.0})

    res = margin(movements=ANALYTICS_STORE.movements, sales=ANALYTICS_STORE.sales, period=Period.DAY)
    assert res[0].margin == 50.0 - 20.0


def test_calcul_ecarts_euros() -> None:
    p = uuid4()
    e = uuid4()
    u = uuid4()
    ANALYTICS_STORE.movements.append(
        StockMovement(
            produit_id=p,
            etablissement_id=e,
            type=StockMovementType.SORTIE,
            quantite=10,
            valeur_unitaire=2,
            utilisateur_id=u,
            date_heure=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    )
    ANALYTICS_STORE.sales.append({"date": datetime(2025, 1, 1, tzinfo=timezone.utc).date(), "ca": 50.0, "cost_rate": 0.3})

    res = gaps(movements=ANALYTICS_STORE.movements, sales=ANALYTICS_STORE.sales, period=Period.DAY)
    assert res[0].gap_eur == 20.0 - 15.0


def test_endpoints_read_only_refus_post_put_delete() -> None:
    client = TestClient(app)

    # routes GET existent
    assert client.get("/analytics/cost-matter").status_code == 200
    assert client.get("/analytics/margin").status_code == 200
    assert client.get("/analytics/gaps").status_code == 200

    # tentatives d'écriture => 405
    assert client.post("/analytics/cost-matter").status_code in (404, 405)
    assert client.put("/analytics/margin").status_code in (404, 405)
    assert client.delete("/analytics/gaps").status_code in (404, 405)
