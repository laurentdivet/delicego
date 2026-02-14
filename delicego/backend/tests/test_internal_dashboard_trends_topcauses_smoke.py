from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests._http_helpers import entetes_internes

from app.main import creer_application


def _client_interne() -> TestClient:
    return TestClient(creer_application())


def _entetes_internes() -> dict[str, str]:
    return entetes_internes()


@pytest.mark.asyncio
async def test_internal_impact_dashboard_trends_topcauses_smoke(session_test) -> None:
    # Seed demo data
    from scripts.seed_demo import seed_demo

    await seed_demo()

    # when
    client = _client_interne()
    r = client.get("/api/interne/impact/dashboard?days=30", headers=_entetes_internes())

    # then
    assert r.status_code == 200
    data = r.json()

    assert "trends" in data
    assert data["trends"] is not None
    assert "waste_rate" in data["trends"]
    assert "series" in data["trends"]["waste_rate"]
    assert isinstance(data["trends"]["waste_rate"]["series"], list)
    assert len(data["trends"]["waste_rate"]["series"]) > 0

    assert "top_causes" in data
    assert data["top_causes"] is not None
    # structure keys must exist, lists can be empty
    assert set(data["top_causes"].keys()) >= {"waste", "local", "co2"}
    assert set(data["top_causes"]["waste"].keys()) >= {"ingredients", "menus"}
    assert set(data["top_causes"]["local"].keys()) >= {"fournisseurs"}
    assert set(data["top_causes"]["co2"].keys()) >= {"ingredients", "fournisseurs"}
