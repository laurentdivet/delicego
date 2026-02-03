import os
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.domaine.modeles.impact import ImpactRecommendationEvent
from app.domaine.modeles.referentiel import Magasin
from app.domaine.enums.types import TypeMagasin
from app.main import app


def test_internal_impact_dashboard_magasin_filter_smoke() -> None:
    """Le dashboard doit filtrer les reco/events par magasin_id quand fourni."""

    # Arrange
    os.environ.pop("ENV", None)
    os.environ["INTERNAL_API_TOKEN"] = "secret-test-token"

    client = TestClient(app)

    # Seed minimal: 2 magasins + 2 reco events
    from app.core.configuration import parametres_application
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    url_db = os.getenv("DATABASE_URL")
    if not url_db:
        raise RuntimeError(
            "DATABASE_URL is required to run DB tests. "
            "Example: DATABASE_URL='postgresql+asyncpg://user:pass@localhost:5432/dbname' pytest"
        )

    engine = create_async_engine(url_db, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    import asyncio

    async def _seed() -> tuple[str, str]:
        async with session_maker() as session:
            m1 = Magasin(id=uuid4(), nom=f"Magasin A {uuid4().hex[:6]}", type_magasin=TypeMagasin.VENTE, actif=True)
            m2 = Magasin(id=uuid4(), nom=f"Magasin B {uuid4().hex[:6]}", type_magasin=TypeMagasin.VENTE, actif=True)
            session.add_all([m1, m2])
            await session.flush()

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
            session.add_all([r1, r2])
            await session.commit()
            return str(m1.id), str(m2.id)

    magasin_a_id, magasin_b_id = asyncio.run(_seed())

    # Act 1: filtre magasin A
    r = client.get(
        f"/api/interne/impact/dashboard?days=30&magasin_id={magasin_a_id}",
        headers={"Authorization": "Bearer secret-test-token"},
    )
    assert r.status_code == 200
    data = r.json()
    codes = {x["code"] for x in (data.get("recommendations") or [])}
    assert "TEST_RECO_A" in codes
    assert "TEST_RECO_B" not in codes

    # Act 2: sans filtre => les deux
    r2 = client.get(
        "/api/interne/impact/dashboard?days=30",
        headers={"Authorization": "Bearer secret-test-token"},
    )
    assert r2.status_code == 200
    data2 = r2.json()
    codes2 = {x["code"] for x in (data2.get("recommendations") or [])}
    assert "TEST_RECO_A" in codes2
    assert "TEST_RECO_B" in codes2

    # cleanup engine
    asyncio.run(engine.dispose())
