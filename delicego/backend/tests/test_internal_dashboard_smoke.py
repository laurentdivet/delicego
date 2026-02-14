import os

from fastapi.testclient import TestClient

from tests._http_helpers import entetes_internes

from app.main import app
from scripts.seed_demo import seed_demo


def test_internal_impact_dashboard_smoke() -> None:
    """/api/interne/impact/dashboard doit être protégé et retourner le payload attendu."""

    # Arrange
    os.environ.pop("ENV", None)
    os.environ["INTERNAL_API_TOKEN"] = "secret-test-token"

    client = TestClient(app)

    # Seed demo requis pour avoir au moins 1 reco/action (idempotent)
    import asyncio

    asyncio.run(seed_demo())

    # 1) sans token => 401
    r = client.get("/api/interne/impact/dashboard?days=30")
    assert r.status_code == 401

    # 2) avec bon token => 200 + payload
    r = client.get(
        "/api/interne/impact/dashboard?days=30",
        headers=entetes_internes(),
    )
    assert r.status_code == 200
    data = r.json()

    assert "kpis" in data
    assert "recommendations" in data and isinstance(data["recommendations"], list)
    assert "alerts" in data and isinstance(data["alerts"], list)