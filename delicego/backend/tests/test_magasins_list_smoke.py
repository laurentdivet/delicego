import os

from fastapi.testclient import TestClient

from tests._http_helpers import entetes_internes

from app.main import app
from scripts.seed_demo import seed_demo


def test_internal_magasins_list_smoke() -> None:
    os.environ.pop("ENV", None)
    os.environ["INTERNAL_API_TOKEN"] = "secret-test-token"

    client = TestClient(app)

    import asyncio

    asyncio.run(seed_demo())

    r = client.get("/api/interne/magasins", headers=entetes_internes())
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "id" in data[0] and "nom" in data[0]
