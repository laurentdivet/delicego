from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.schemas.impact import (
    ImpactCO2Response,
    ImpactActionCreateBody,
    ImpactActionPatchBody,
    ImpactActionSchema,
    ImpactDashboardResponse,
    ImpactLocalResponse,
    ImpactRecommendationPatchBody,
    ImpactSummaryResponse,
    ImpactWasteResponse,
)
from app.core.configuration import parametres_application
from app.impact.kpis import impact_summary, kpi_co2_estimate, kpi_local_share, kpi_waste_rate


def verifier_acces_public_impact_dashboard() -> None:
    """Guard DEV-only (public impact dashboard + write endpoints).

    Autorise seulement si IMPACT_DASHBOARD_PUBLIC_DEV est truthy.
    """

    if (os.getenv("IMPACT_DASHBOARD_PUBLIC_DEV") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès public impact désactivé (IMPACT_DASHBOARD_PUBLIC_DEV requis).",
        )


routeur_impact_public = APIRouter(
    prefix="/api/impact",
    tags=["impact_public"],
    dependencies=[Depends(verifier_acces_public_impact_dashboard)],
)


routeur_impact_interne = APIRouter(
    prefix="/impact",
    tags=["impact"],
    dependencies=[Depends(verifier_acces_interne)],
)


@routeur_impact_public.get("/dashboard", response_model=ImpactDashboardResponse)
async def impact_dashboard_public_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=200, ge=1, le=5000),
    session: AsyncSession = Depends(fournir_session),
) -> ImpactDashboardResponse:
    """Dashboard public DEV-only.

    Retourne les *vraies* données de pilotage attendues par l'UI /impact :
    - KPIs (waste/local/co2)
    - alertes (MVP: vide)
    - recommandations + actions associées

    NOTE: Les modèles SQLAlchemy pour `impact_recommendation_event` et `impact_action`
    ne sont pas (encore) déclarés dans `app.domaine.modeles.*` dans ce repo.
    Pour rester compatible avec le schéma existant et fournir une persistance réelle,
    on passe par du SQL explicite via la même session DI.
    """

    # --- KPIs (déjà implémentés)
    waste = await kpi_waste_rate(session, days=days)
    local = await kpi_local_share(
        session,
        days=days,
        local_km_threshold=parametres_application.impact_local_km_threshold,
    )
    co2 = await kpi_co2_estimate(session, days=days)

    # --- Recommendations + actions
    # On récupère d'abord les reco events.
    reco_rows = (
        await session.execute(
            text(
                """
                SELECT
                  id::text AS id,
                  code,
                  severity,
                  status,
                  occurrences,
                  last_seen_at,
                  entities
                FROM impact_recommendation_event
                ORDER BY last_seen_at DESC
                LIMIT :limit
                """
            ),
            {"limit": int(limit)},
        )
    ).mappings().all()

    reco_ids = [r["id"] for r in reco_rows]
    actions_by_reco: dict[str, list[dict[str, object]]] = {}
    if reco_ids:
        action_rows = (
            await session.execute(
                text(
                    """
                    SELECT
                      id::text AS id,
                      recommendation_event_id::text AS recommendation_event_id,
                      status,
                      description
                    FROM impact_action
                    WHERE recommendation_event_id = ANY(CAST(:reco_ids AS uuid[]))
                    ORDER BY cree_le DESC
                    """
                ),
                {"reco_ids": reco_ids},
            )
        ).mappings().all()

        for a in action_rows:
            rid = str(a["recommendation_event_id"])
            actions_by_reco.setdefault(rid, []).append(
                {
                    "id": str(a["id"]),
                    "status": str(a["status"]),
                    "description": a["description"],
                }
            )

    recommendations = []
    for r in reco_rows:
        rid = str(r["id"])
        recommendations.append(
            {
                "id": rid,
                "code": r["code"],
                "severity": r["severity"],
                "status": r["status"],
                "occurrences": int(r["occurrences"] or 0),
                "last_seen_at": r["last_seen_at"],
                "entities": r["entities"],
                "actions": actions_by_reco.get(rid, []),
            }
        )

    return ImpactDashboardResponse(
        kpis={
            "days": days,
            "waste_rate": waste.waste_rate,
            "local_share": local.local_share,
            "co2_kgco2e": co2.total_kgco2e,
        },
        alerts=[],
        recommendations=recommendations,
    )


@routeur_impact_public.post(
    "/recommendations/{recommendation_event_id}/actions",
    response_model=ImpactActionSchema,
    status_code=status.HTTP_201_CREATED,
)
async def impact_create_action_public_endpoint(
    recommendation_event_id: str,
    body: ImpactActionCreateBody,
    session: AsyncSession = Depends(fournir_session),
) -> ImpactActionSchema:
    # --- validate reco event exists
    try:
        reco_uuid = UUID(recommendation_event_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail="Recommendation event introuvable.") from e

    exists = (
        await session.execute(
            text("SELECT 1 FROM impact_recommendation_event WHERE id = :id"),
            {"id": reco_uuid},
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Recommendation event introuvable.")

    now = datetime.now(timezone.utc)
    row = (
        await session.execute(
            text(
                """
                INSERT INTO impact_action (
                  id,
                  recommendation_event_id,
                  action_type,
                  description,
                  status,
                  cree_le,
                  mis_a_jour_le
                )
                VALUES (
                  :id,
                  :recommendation_event_id,
                  :action_type,
                  :description,
                  'OPEN',
                  :now,
                  :now
                )
                RETURNING
                  id::text AS id,
                  recommendation_event_id::text AS recommendation_event_id,
                  action_type,
                  description,
                  status,
                  cree_le AS created_at
                """
            ),
            {
                "id": uuid4(),
                "recommendation_event_id": reco_uuid,
                "action_type": body.action_type,
                "description": body.description,
                "now": now,
            },
        )
    ).mappings().one()
    await session.commit()

    # 201: on garde le décorateur FastAPI simple + on renvoie quand même l'objet.
    # (FastAPI mettra 200 par défaut; on force explicitement.)
    # NOTE: on ne dépend pas de Response ici pour garder l'endpoint simple.
    # On utilise le status_code dans le décorateur ci-dessous.
    return ImpactActionSchema(
        id=str(row["id"]),
        recommendation_event_id=str(row["recommendation_event_id"]),
        action_type=str(row["action_type"]),
        description=row["description"],
        status=str(row["status"]),
        created_at=row["created_at"],
    )


@routeur_impact_public.patch("/actions/{action_id}", response_model=ImpactActionSchema)
async def impact_patch_action_public_endpoint(
    action_id: str,
    body: ImpactActionPatchBody,
    session: AsyncSession = Depends(fournir_session),
) -> ImpactActionSchema:
    try:
        action_uuid = UUID(action_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail="Action introuvable.") from e

    row = (
        await session.execute(
            text(
                """
                SELECT
                  id::text AS id,
                  recommendation_event_id::text AS recommendation_event_id,
                  action_type,
                  description,
                  status,
                  cree_le AS created_at
                FROM impact_action
                WHERE id = :id
                """
            ),
            {"id": action_uuid},
        )
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Action introuvable.")

    updates: dict[str, object] = {"id": action_uuid, "now": datetime.now(timezone.utc)}
    sets: list[str] = ["mis_a_jour_le = :now"]

    if body.status is not None:
        sets.append("status = :status")
        updates["status"] = body.status
    if body.description is not None:
        sets.append("description = :description")
        updates["description"] = body.description

    if len(sets) > 1:
        updated = (
            await session.execute(
                text(
                    """
                    UPDATE impact_action
                    SET {sets}
                    WHERE id = :id
                    RETURNING
                      id::text AS id,
                      recommendation_event_id::text AS recommendation_event_id,
                      action_type,
                      description,
                      status,
                      cree_le AS created_at
                    """.format(sets=", ".join(sets))
                ),
                updates,
            )
        ).mappings().one()
        await session.commit()
        row = updated

    return ImpactActionSchema(
        id=str(row["id"]),
        recommendation_event_id=str(row["recommendation_event_id"]),
        action_type=str(row["action_type"]),
        description=row["description"],
        status=str(row["status"]),
        created_at=row["created_at"],
    )


@routeur_impact_public.patch("/recommendations/{recommendation_event_id}")
async def impact_patch_recommendation_public_endpoint(
    recommendation_event_id: str,
    body: ImpactRecommendationPatchBody,
    session: AsyncSession = Depends(fournir_session),
) -> dict[str, str]:
    try:
        reco_uuid = UUID(recommendation_event_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail="Recommendation event introuvable.") from e

    existing = (
        await session.execute(
            text(
                """
                SELECT
                  id::text AS id,
                  status,
                  comment,
                  resolved_at
                FROM impact_recommendation_event
                WHERE id = :id
                """
            ),
            {"id": reco_uuid},
        )
    ).mappings().one_or_none()
    if existing is None:
        raise HTTPException(status_code=404, detail="Recommendation event introuvable.")

    updates: dict[str, object] = {"id": reco_uuid, "now": datetime.now(timezone.utc)}
    sets: list[str] = ["mis_a_jour_le = :now"]

    # Règle choisie (cohérente et simple):
    # - status=RESOLVED => resolved_at = now (si pas déjà set)
    # - status!=RESOLVED => resolved_at = NULL (on considère que l'event est à nouveau actif)
    if body.status is not None:
        sets.append("status = :status")
        updates["status"] = body.status
        if body.status == "RESOLVED":
            sets.append("resolved_at = COALESCE(resolved_at, :now)")
        else:
            sets.append("resolved_at = NULL")

    if body.comment is not None:
        sets.append("comment = :comment")
        updates["comment"] = body.comment

    if len(sets) > 1:
        updated = (
            await session.execute(
                text(
                    """
                    UPDATE impact_recommendation_event
                    SET {sets}
                    WHERE id = :id
                    RETURNING
                      id::text AS id,
                      status,
                      comment,
                      resolved_at
                    """.format(sets=", ".join(sets))
                ),
                updates,
            )
        ).mappings().one()
        await session.commit()
        existing = updated

    return {
        "id": str(existing["id"]),
        "status": str(existing["status"]),
        "comment": str(existing["comment"] or ""),
        "resolved_at": (existing["resolved_at"].isoformat() if existing["resolved_at"] else ""),
    }


@routeur_impact_interne.get("/summary", response_model=ImpactSummaryResponse)
async def impact_summary_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    include_savings_vs_baseline: bool = Query(default=False),
    session: AsyncSession = Depends(fournir_session),
) -> ImpactSummaryResponse:
    s = await impact_summary(
        session,
        days=days,
        local_km_threshold=parametres_application.impact_local_km_threshold,
        include_savings_vs_baseline=include_savings_vs_baseline,
    )
    return ImpactSummaryResponse(
        days=s.days,
        waste_rate=s.waste_rate,
        local_share=s.local_share,
        co2_kgco2e=s.co2_kgco2e,
        savings_vs_baseline=s.savings_vs_baseline,
    )


@routeur_impact_interne.get("/waste", response_model=ImpactWasteResponse)
async def impact_waste_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(fournir_session),
) -> ImpactWasteResponse:
    r = await kpi_waste_rate(session, days=days)
    return ImpactWasteResponse(
        days=r.days,
        waste_qty=r.waste_qty,
        input_qty=r.input_qty,
        waste_rate=r.waste_rate,
        series_waste_qty=[{"date": p.date, "value": p.value} for p in r.series_waste_qty],
        series_waste_rate=[{"date": p.date, "value": p.value} for p in r.series_waste_rate],
    )


@routeur_impact_interne.get("/local", response_model=ImpactLocalResponse)
async def impact_local_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    local_km_threshold: float | None = Query(default=None, ge=0.0, le=20000.0),
    session: AsyncSession = Depends(fournir_session),
) -> ImpactLocalResponse:
    threshold = (
        float(local_km_threshold)
        if local_km_threshold is not None
        else float(parametres_application.impact_local_km_threshold)
    )
    r = await kpi_local_share(session, days=days, local_km_threshold=threshold)
    return ImpactLocalResponse(
        days=r.days,
        local_km_threshold=r.local_km_threshold,
        local_receptions=r.local_receptions,
        total_receptions=r.total_receptions,
        local_share=r.local_share,
        series_local_share=[{"date": p.date, "value": p.value} for p in r.series_local_share],
    )


@routeur_impact_interne.get("/co2", response_model=ImpactCO2Response)
async def impact_co2_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(fournir_session),
) -> ImpactCO2Response:
    r = await kpi_co2_estimate(session, days=days)
    return ImpactCO2Response(
        days=r.days,
        total_kgco2e=r.total_kgco2e,
        series_kgco2e=[{"date": p.date, "value": p.value} for p in r.series_kgco2e],
    )
