import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tests._http_helpers import entetes_internes

from app.domaine.modeles.impact import ImpactRecommendationEvent
from app.domaine.modeles.referentiel import Magasin
from app.domaine.enums.types import TypeMagasin
from app.api.dependances import fournir_session
from app.main import creer_application


def _app_avec_dependances_test(session_test: AsyncSession):
    app = creer_application()

    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    async def _fournir_session_override():
        assert session_test.bind is not None
        async with _AsyncSession(bind=session_test.bind, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[fournir_session] = _fournir_session_override
    return app


async def _client_api(session_test: AsyncSession) -> httpx.AsyncClient:
    app = _app_avec_dependances_test(session_test)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_internal_impact_dashboard_magasin_filter_smoke(session_test: AsyncSession) -> None:
    """Le dashboard doit filtrer les reco/events par magasin_id quand fourni."""

    # Arrange
    os.environ.pop("ENV", None)
    os.environ["INTERNAL_API_TOKEN"] = "secret-test-token"

    client = await _client_api(session_test)

    # Seed minimal: 2 magasins + 2 reco events
    m1 = Magasin(id=uuid4(), nom=f"Magasin A {uuid4().hex[:6]}", type_magasin=TypeMagasin.VENTE, actif=True)
    m2 = Magasin(id=uuid4(), nom=f"Magasin B {uuid4().hex[:6]}", type_magasin=TypeMagasin.VENTE, actif=True)
    session_test.add_all([m1, m2])
    await session_test.flush()

    now = datetime.now(timezone.utc)
    r1 = ImpactRecommendationEvent(
        id=uuid4(),
        code="TEST_RECO_A",
        metric="waste",
        entities_signature=uuid4().hex,
        severity="LOW",
        status="OPEN",
        entities={"magasin_id": str(m1.id)},
        first_seen_at=now,
        last_seen_at=now,
        occurrences=1,
        resolved_at=None,
        comment=None,
    )
    r2 = ImpactRecommendationEvent(
        id=uuid4(),
        code="TEST_RECO_B",
        metric="waste",
        entities_signature=uuid4().hex,
        severity="LOW",
        status="OPEN",
        entities={"magasin_id": str(m2.id)},
        first_seen_at=now,
        last_seen_at=now,
        occurrences=1,
        resolved_at=None,
        comment=None,
    )
    session_test.add_all([r1, r2])
    await session_test.commit()

    magasin_a_id, magasin_b_id = str(m1.id), str(m2.id)

    # Act 1: filtre magasin A
    r = await client.get(
        f"/api/interne/impact/dashboard?days=30&magasin_id={magasin_a_id}",
        headers=entetes_internes(),
    )
    assert r.status_code == 200
    data = r.json()
    codes = {x["code"] for x in (data.get("recommendations") or [])}
    assert "TEST_RECO_A" in codes
    assert "TEST_RECO_B" not in codes

    # Act 2: sans filtre => les deux
    r2 = await client.get(
        "/api/interne/impact/dashboard?days=30",
        headers=entetes_internes(),
    )
    assert r2.status_code == 200
    data2 = r2.json()
    codes2 = {x["code"] for x in (data2.get("recommendations") or [])}
    assert "TEST_RECO_A" in codes2
    assert "TEST_RECO_B" in codes2

    await client.aclose()
