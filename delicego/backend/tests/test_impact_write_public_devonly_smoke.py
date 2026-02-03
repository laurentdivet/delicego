import os

from fastapi.testclient import TestClient

from app.main import app
from scripts.seed_demo import seed_demo


def test_public_impact_write_endpoints_devonly_smoke():
    # Guard OFF -> 403
    os.environ.pop("IMPACT_DASHBOARD_PUBLIC_DEV", None)

    client = TestClient(app)

    r = client.get("/api/impact/dashboard")
    assert r.status_code == 403

    r = client.post(
        "/api/impact/recommendations/does-not-matter/actions",
        json={"action_type": "OTHER", "description": "x"},
    )
    assert r.status_code == 403

    r = client.patch(
        "/api/impact/actions/does-not-matter",
        json={"status": "DONE"},
    )
    assert r.status_code == 403

    r = client.patch(
        "/api/impact/recommendations/does-not-matter",
        json={"status": "RESOLVED"},
    )
    assert r.status_code == 403


def test_public_impact_write_endpoints_when_enabled_smoke():
    # Guard ON -> endpoints fonctionnent + persistance réelle
    os.environ["IMPACT_DASHBOARD_PUBLIC_DEV"] = "1"

    client = TestClient(app)

    # Seed DB demo pour avoir KPIs + au moins une recommendation event existante.
    # Le seed_demo ne crée pas d'impact_recommendation_event : on en insère une minimale.
    import asyncio
    from datetime import datetime, timezone
    from uuid import uuid4
    from sqlalchemy import text
    from app.api.dependances import fournir_session

    asyncio.run(seed_demo())

    async def _insert_reco_if_missing() -> str:
        async for session in fournir_session():
            # Idempotent: si déjà présent, on réutilise l'id existant.
            existing_id = (
                await session.execute(
                    text(
                        """
                        SELECT id::text
                        FROM impact_recommendation_event
                        WHERE code='DEMO_RECO' AND metric='demo' AND entities_signature='demo'
                        LIMIT 1
                        """
                    )
                )
            ).scalar_one_or_none()
            if existing_id is not None:
                return str(existing_id)

            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO impact_recommendation_event (
                          id,
                          code, metric, entities_signature, severity, entities,
                          first_seen_at, last_seen_at, occurrences,
                          status, resolved_at, comment,
                          cree_le, mis_a_jour_le
                        )
                        VALUES (
                          :id,
                          'DEMO_RECO', 'demo', 'demo', 'LOW', '{}'::jsonb,
                          :now, :now, 1,
                          'OPEN', NULL, NULL,
                          :now, :now
                        )
                        RETURNING id::text
                        """
                    ),
                    {"id": str(uuid4()), "now": datetime.now(timezone.utc)},
                )
            ).scalar_one()
            await session.commit()
            return str(row)

        raise RuntimeError("no session")

    reco_id = asyncio.run(_insert_reco_if_missing())

    # 1) GET dashboard -> reco existante
    r = client.get("/api/impact/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert len(data.get("recommendations") or []) >= 1

    # Prend une reco existante (celle seedée)
    reco_id = str((data["recommendations"][0]["id"]))

    # 2) POST action
    r = client.post(
        f"/api/impact/recommendations/{reco_id}/actions",
        json={"action_type": "OTHER", "description": "x"},
    )
    assert r.status_code == 201
    action = r.json()
    assert action["recommendation_event_id"] == reco_id
    action_id = action["id"]

    # 3) PATCH action -> DONE
    r = client.patch(
        f"/api/impact/actions/{action_id}",
        json={"status": "DONE"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "DONE"

    # 4) PATCH recommendation -> ACK + comment
    r = client.patch(
        f"/api/impact/recommendations/{reco_id}",
        json={"status": "ACKNOWLEDGED", "comment": "ok"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ACKNOWLEDGED"

    # 5) Re-GET dashboard -> action liée + statuts persistés
    r = client.get("/api/impact/dashboard")
    assert r.status_code == 200
    data2 = r.json()
    reco2 = [x for x in data2.get("recommendations") or [] if x.get("id") == reco_id][0]
    assert reco2["status"] == "ACKNOWLEDGED"
    assert any(a.get("id") == action_id and a.get("status") == "DONE" for a in (reco2.get("actions") or []))
