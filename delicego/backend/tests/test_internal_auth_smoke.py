import os

from fastapi.testclient import TestClient

from app.main import app
from scripts.seed_demo import seed_demo


def test_internal_bearer_token_smoke() -> None:
    """MVP: /api/interne/* doit exiger Authorization: Bearer <token>."""

    # Arrange
    os.environ.pop("ENV", None)
    os.environ["INTERNAL_API_TOKEN"] = "secret-test-token"

    client = TestClient(app)

    # DB demo (impact dashboard requiert tables + quelques données)
    import asyncio

    asyncio.run(seed_demo())

    # 1) pas de token
    r = client.get("/api/interne/impact/summary")
    assert r.status_code == 401

    # 2) mauvais token
    r = client.get(
        "/api/interne/impact/summary",
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401

    # 3) bon token
    r = client.get(
        "/api/interne/impact/summary",
        headers={"Authorization": "Bearer secret-test-token"},
    )
    assert r.status_code == 200