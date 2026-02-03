import os

from fastapi.testclient import TestClient

from app.main import app
from scripts.seed_demo import seed_demo


def test_impact_actions_export_csv_smoke() -> None:
    os.environ.pop("ENV", None)
    os.environ["INTERNAL_API_TOKEN"] = "secret-test-token"
    if not os.getenv("DATABASE_URL"):
        import pytest

        pytest.skip("DATABASE_URL is required to run impact export csv smoke tests")

    client = TestClient(app)

    import asyncio

    asyncio.run(seed_demo())

    # get one recommendation id
    dash = client.get(
        "/api/interne/impact/dashboard?days=365&limit=1",
        headers={"Authorization": "Bearer secret-test-token"},
    )
    assert dash.status_code == 200
    reco_id = (dash.json().get("recommendations") or [])[0]["id"]

    # create one action
    r = client.post(
        f"/api/interne/impact/recommendations/{reco_id}/actions",
        headers={"Authorization": "Bearer secret-test-token"},
        json={
            "action_type": "MANUAL",
            "description": "Action export",
            "assignee": "Bob",
            "due_date": "2030-02-01",
            "priority": 1,
        },
    )
    assert r.status_code == 201

    exp = client.get(
        "/api/interne/impact/export/actions.csv?days=365",
        headers={"Authorization": "Bearer secret-test-token"},
    )
    assert exp.status_code == 200
    assert exp.headers.get("content-type", "").startswith("text/csv")

    txt = exp.text.strip().splitlines()
    assert len(txt) >= 2
    assert txt[0].startswith(
        "magasin,reco_code,reco_status,reco_severity,action_id,action_status,priority,due_date,assignee,description,created_at,updated_at,occurrences,last_seen_at"
    )
