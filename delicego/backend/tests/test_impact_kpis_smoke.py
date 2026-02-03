from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import creer_application


def _client_interne() -> TestClient:
    return TestClient(creer_application())


def _entetes_internes() -> dict[str, str]:
    return {"X-CLE-INTERNE": "cle-technique"}


@pytest.mark.asyncio
async def test_impact_endpoints_smoke(session_test) -> None:
    """Smoke test : DB neuve seedée -> endpoints Impact renvoient un JSON cohérent.

    Hypothèses :
    - la fixture `session_test` recrée le schéma via BaseModele.metadata.create_all
    - l'accès interne est autorisé en test via header X-CLE-INTERNE
    """

    # Seed minimal pour rendre les KPI non vides
    from scripts.seed_demo import seed_demo

    await seed_demo()

    # /impact/summary
    client = _client_interne()

    r = client.get("/api/interne/impact/summary?days=30", headers=_entetes_internes())
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"days", "waste_rate", "local_share", "co2_kgco2e"}
    assert data["days"] == 30
    assert data["waste_rate"] >= 0
    assert 0 <= data["local_share"] <= 1
    assert data["co2_kgco2e"] >= 0

    # /impact/waste
    r = client.get("/api/interne/impact/waste?days=30", headers=_entetes_internes())
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"days", "waste_qty", "input_qty", "waste_rate", "series_waste_qty", "series_waste_rate"}
    assert data["waste_qty"] >= 0
    assert data["input_qty"] >= 0
    assert data["waste_rate"] >= 0
    assert isinstance(data["series_waste_qty"], list)

    # /impact/local
    r = client.get("/api/interne/impact/local?days=30", headers=_entetes_internes())
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"days", "local_km_threshold", "local_receptions", "total_receptions", "local_share", "series_local_share"}
    assert data["local_km_threshold"] >= 0
    assert data["local_receptions"] >= 0
    assert data["total_receptions"] >= 0
    assert 0 <= data["local_share"] <= 1

    # /impact/co2
    r = client.get("/api/interne/impact/co2?days=30", headers=_entetes_internes())
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"days", "total_kgco2e", "series_kgco2e"}
    assert data["total_kgco2e"] >= 0
    assert isinstance(data["series_kgco2e"], list)
