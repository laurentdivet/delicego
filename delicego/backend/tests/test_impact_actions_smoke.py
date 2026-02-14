import os

from fastapi.testclient import TestClient

from tests._http_helpers import entetes_internes

from app.main import app
from scripts.seed_demo import seed_demo


def test_impact_actions_create_and_patch_smoke() -> None:
    # Arrange
    os.environ.pop("ENV", None)
    os.environ["INTERNAL_API_TOKEN"] = "secret-test-token"
    # tests infra: DB obligatoire
    if not os.getenv("DATABASE_URL"):
        import pytest

        pytest.skip("DATABASE_URL is required to run impact action smoke tests")

    client = TestClient(app)

    import asyncio

    asyncio.run(seed_demo())

    # get one recommendation id from dashboard
    dash = client.get(
        "/api/interne/impact/dashboard?days=365&limit=1",
        headers=entetes_internes(),
    )
    assert dash.status_code == 200
    recos = dash.json().get("recommendations") or []
    assert recos, "seed_demo should create at least one recommendation"
    reco_id = recos[0]["id"]

    # Act: create action with extra fields
    r = client.post(
        f"/api/interne/impact/recommendations/{reco_id}/actions",
        headers=entetes_internes(),
        json={
            "action_type": "MANUAL",
            "description": "Action test",
            "assignee": "Alice",
            "due_date": "2030-01-15",
            "priority": 3,
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["assignee"] == "Alice"
    assert data["due_date"] == "2030-01-15"
    assert data["priority"] == 3
    assert data.get("updated_at")

    action_id = data["id"]
    updated_at_1 = data["updated_at"]

    # Act: patch should modify updated_at
    r2 = client.patch(
        f"/api/interne/impact/actions/{action_id}",
        headers=entetes_internes(),
        json={"description": "Action test modifiée", "priority": 2},
    )
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["description"] == "Action test modifiée"
    assert data2["priority"] == 2
    assert data2.get("updated_at")
    assert data2["updated_at"] != updated_at_1
