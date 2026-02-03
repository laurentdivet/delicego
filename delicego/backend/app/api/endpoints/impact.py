from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

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
from app.impact.kpis import impact_top_causes, impact_trends_and_deltas
from app.domaine.modeles.impact import ImpactAction, ImpactRecommendationEvent


def _priority_label(p: int | None) -> str:
    if p == 1:
        return "LOW"
    if p == 2:
        return "MEDIUM"
    if p == 3:
        return "HIGH"
    return ""


def _csv_escape(s: object | None) -> str:
    """Escape minimal CSV (RFC4180-ish) for our export."""

    if s is None:
        return ""
    txt = str(s)
    if any(c in txt for c in ["\n", "\r", ",", '"']):
        txt = txt.replace('"', '""')
        return f'"{txt}"'
    return txt


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


@routeur_impact_interne.post(
    "/recommendations/{recommendation_event_id}/actions",
    response_model=ImpactActionSchema,
    status_code=status.HTTP_201_CREATED,
)
async def impact_create_action_interne_endpoint(
    recommendation_event_id: str,
    body: ImpactActionCreateBody,
    session: AsyncSession = Depends(fournir_session),
) -> ImpactActionSchema:
    """Créer une action manuelle (API interne)."""

    try:
        reco_uuid = UUID(recommendation_event_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail="Recommendation event introuvable.") from e

    reco = await session.get(ImpactRecommendationEvent, reco_uuid)
    if reco is None:
        raise HTTPException(status_code=404, detail="Recommendation event introuvable.")

    now = datetime.now(timezone.utc)
    action = ImpactAction(
        id=uuid4(),
        recommendation_event_id=reco_uuid,
        action_type=body.action_type,
        description=body.description,
        assignee=body.assignee,
        due_date=body.due_date,
        priority=body.priority,
        status="OPEN",
        cree_le=now,
        mis_a_jour_le=now,
        updated_at=now,
    )
    session.add(action)
    await session.commit()
    await session.refresh(action)

    return ImpactActionSchema(
        id=str(action.id),
        recommendation_event_id=str(action.recommendation_event_id),
        action_type=str(action.action_type),
        description=action.description,
        assignee=getattr(action, "assignee", None),
        due_date=getattr(action, "due_date", None),
        priority=getattr(action, "priority", None),
        status=str(action.status),
        created_at=action.cree_le,
        updated_at=getattr(action, "updated_at", None),
    )


@routeur_impact_interne.patch("/actions/{action_id}", response_model=ImpactActionSchema)
async def impact_patch_action_interne_endpoint(
    action_id: str,
    body: ImpactActionPatchBody,
    session: AsyncSession = Depends(fournir_session),
) -> ImpactActionSchema:
    """Patch action (API interne)."""

    try:
        action_uuid = UUID(action_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail="Action introuvable.") from e

    action = await session.get(ImpactAction, action_uuid)
    if action is None:
        raise HTTPException(status_code=404, detail="Action introuvable.")

    if body.status is not None:
        action.status = body.status
    if body.description is not None:
        action.description = body.description
    if body.assignee is not None:
        action.assignee = body.assignee
    if body.due_date is not None:
        action.due_date = body.due_date
    if body.priority is not None:
        action.priority = body.priority

    now = datetime.now(timezone.utc)
    action.mis_a_jour_le = now
    action.updated_at = now
    await session.commit()
    await session.refresh(action)

    return ImpactActionSchema(
        id=str(action.id),
        recommendation_event_id=str(action.recommendation_event_id),
        action_type=str(action.action_type),
        description=action.description,
        assignee=getattr(action, "assignee", None),
        due_date=getattr(action, "due_date", None),
        priority=getattr(action, "priority", None),
        status=str(action.status),
        created_at=action.cree_le,
        updated_at=getattr(action, "updated_at", None),
    )


@routeur_impact_interne.get("/dashboard", response_model=ImpactDashboardResponse)
async def impact_dashboard_interne_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    compare_days: int | None = Query(default=None, ge=1, le=365),
    limit: int = Query(default=200, ge=1, le=5000),
    magasin_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None, description="OPEN|ACKNOWLEDGED|RESOLVED"),
    severity: str | None = Query(default=None, description="LOW|MEDIUM|HIGH"),
    sort: str = Query(default="last_seen_desc", description="last_seen_desc|occurrences_desc"),
    session: AsyncSession = Depends(fournir_session),
) -> ImpactDashboardResponse:
    """Dashboard interne protégé.

    IMPORTANT: on réutilise EXACTEMENT la logique de l'endpoint public
    `/api/impact/dashboard` (mais sans guard DEV-only).

    La protection se fait via la dépendance router-level sur `/api/interne`.
    """

    # --- KPIs (déjà implémentés)
    waste = await kpi_waste_rate(session, days=days, magasin_id=magasin_id)
    local = await kpi_local_share(
        session,
        days=days,
        magasin_id=magasin_id,
        local_km_threshold=parametres_application.impact_local_km_threshold,
    )
    co2 = await kpi_co2_estimate(session, days=days, magasin_id=magasin_id)

    trends = await impact_trends_and_deltas(
        session,
        days=days,
        compare_days=compare_days,
        magasin_id=magasin_id,
        local_km_threshold=parametres_application.impact_local_km_threshold,
    )
    top_causes = await impact_top_causes(
        session,
        days=days,
        magasin_id=magasin_id,
        local_km_threshold=parametres_application.impact_local_km_threshold,
        limit=5,
    )

    # --- Recommendations + actions (ORM)
    q = select(ImpactRecommendationEvent).options(selectinload(ImpactRecommendationEvent.actions))
    # magasin filter: either direct column (if exists) or entities JSONB contains.
    if magasin_id is not None:
        if hasattr(ImpactRecommendationEvent, "magasin_id"):
            q = q.where(getattr(ImpactRecommendationEvent, "magasin_id") == magasin_id)
        else:
            # convention: entities.magasin_id = <uuid>
            q = q.where(ImpactRecommendationEvent.entities["magasin_id"].astext == str(magasin_id))

    if status is not None:
        q = q.where(ImpactRecommendationEvent.status == status)
    if severity is not None:
        q = q.where(ImpactRecommendationEvent.severity == severity)

    sort_key = (sort or "").strip().lower()
    if sort_key == "occurrences_desc":
        q = q.order_by(ImpactRecommendationEvent.occurrences.desc(), ImpactRecommendationEvent.last_seen_at.desc())
    else:
        q = q.order_by(ImpactRecommendationEvent.last_seen_at.desc())

    q = q.limit(int(limit))
    reco_events = (await session.execute(q)).scalars().all()

    recommendations = []
    for r in reco_events:
        recommendations.append(
            {
                "id": str(r.id),
                "code": r.code,
                "severity": r.severity,
                "status": r.status,
                "occurrences": int(r.occurrences or 0),
                "last_seen_at": r.last_seen_at,
                "entities": r.entities,
                "actions": [
                    {
                        "id": str(a.id),
                        "status": a.status,
                        "description": a.description,
                        "assignee": getattr(a, "assignee", None),
                        "due_date": getattr(a, "due_date", None),
                        "priority": getattr(a, "priority", None),
                        "created_at": getattr(a, "cree_le", None),
                        "updated_at": getattr(a, "updated_at", None),
                    }
                    for a in sorted(r.actions or [], key=lambda x: x.cree_le, reverse=True)
                ],
            }
        )

    return ImpactDashboardResponse(
        kpis={
            "days": days,
            "waste_rate": waste.waste_rate,
            "local_share": local.local_share,
            "co2_kgco2e": co2.total_kgco2e,
        },
        trends=trends,
        top_causes=top_causes,
        alerts=[],
        recommendations=recommendations,
    )


@routeur_impact_interne.get("/export/actions.csv")
async def impact_export_actions_csv_interne_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    magasin_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None, description="OPEN|ACKNOWLEDGED|RESOLVED"),
    severity: str | None = Query(default=None, description="LOW|MEDIUM|HIGH"),
    action_status: str | None = Query(default=None, description="OPEN|DONE|CANCELLED"),
    session: AsyncSession = Depends(fournir_session),
) -> Response:
    """Export CSV des actions Impact (API interne, Bearer)."""

    since = datetime.now(timezone.utc) - timedelta(days=int(days))

    q = (
        select(ImpactRecommendationEvent)
        .options(selectinload(ImpactRecommendationEvent.actions))
        .where(ImpactRecommendationEvent.last_seen_at >= since)
    )
    if magasin_id is not None:
        if hasattr(ImpactRecommendationEvent, "magasin_id"):
            q = q.where(getattr(ImpactRecommendationEvent, "magasin_id") == magasin_id)
        else:
            q = q.where(ImpactRecommendationEvent.entities["magasin_id"].astext == str(magasin_id))
    if status is not None:
        q = q.where(ImpactRecommendationEvent.status == status)
    if severity is not None:
        q = q.where(ImpactRecommendationEvent.severity == severity)

    reco_events = (await session.execute(q)).scalars().all()

    # Build rows
    header = [
        "magasin",
        "reco_code",
        "reco_status",
        "reco_severity",
        "action_id",
        "action_status",
        "priority",
        "due_date",
        "assignee",
        "description",
        "created_at",
        "updated_at",
        "occurrences",
        "last_seen_at",
    ]

    lines: list[str] = []
    lines.append(",".join(header))

    for r in reco_events:
        magasin = None
        if hasattr(r, "magasin_id"):
            magasin = str(getattr(r, "magasin_id"))
        else:
            try:
                magasin = str((r.entities or {}).get("magasin_id") or "")
            except Exception:
                magasin = ""

        for a in (r.actions or []):
            if action_status is not None and (a.status or "").upper() != action_status.upper():
                continue
            row = [
                magasin or "",
                r.code,
                r.status,
                r.severity,
                str(a.id),
                a.status,
                _priority_label(getattr(a, "priority", None)),
                (getattr(a, "due_date", None).isoformat() if getattr(a, "due_date", None) else ""),
                getattr(a, "assignee", None) or "",
                a.description or "",
                (getattr(a, "cree_le", None).isoformat() if getattr(a, "cree_le", None) else ""),
                (getattr(a, "updated_at", None).isoformat() if getattr(a, "updated_at", None) else ""),
                str(int(r.occurrences or 0)),
                (r.last_seen_at.isoformat() if r.last_seen_at else ""),
            ]
            lines.append(",".join(_csv_escape(x) for x in row))

    csv_text = "\n".join(lines) + "\n"
    return Response(content=csv_text, media_type="text/csv")


@routeur_impact_public.get("/dashboard", response_model=ImpactDashboardResponse)
async def impact_dashboard_public_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    compare_days: int | None = Query(default=None, ge=1, le=365),
    limit: int = Query(default=200, ge=1, le=5000),
    magasin_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None, description="OPEN|ACKNOWLEDGED|RESOLVED"),
    severity: str | None = Query(default=None, description="LOW|MEDIUM|HIGH"),
    sort: str = Query(default="last_seen_desc", description="last_seen_desc|occurrences_desc"),
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
    waste = await kpi_waste_rate(session, days=days, magasin_id=magasin_id)
    local = await kpi_local_share(
        session,
        days=days,
        magasin_id=magasin_id,
        local_km_threshold=parametres_application.impact_local_km_threshold,
    )
    co2 = await kpi_co2_estimate(session, days=days, magasin_id=magasin_id)

    trends = await impact_trends_and_deltas(
        session,
        days=days,
        compare_days=compare_days,
        magasin_id=magasin_id,
        local_km_threshold=parametres_application.impact_local_km_threshold,
    )
    top_causes = await impact_top_causes(
        session,
        days=days,
        magasin_id=magasin_id,
        local_km_threshold=parametres_application.impact_local_km_threshold,
        limit=5,
    )

    # --- Recommendations + actions (ORM)
    q = select(ImpactRecommendationEvent).options(selectinload(ImpactRecommendationEvent.actions))
    if magasin_id is not None:
        if hasattr(ImpactRecommendationEvent, "magasin_id"):
            q = q.where(getattr(ImpactRecommendationEvent, "magasin_id") == magasin_id)
        else:
            q = q.where(ImpactRecommendationEvent.entities["magasin_id"].astext == str(magasin_id))

    if status is not None:
        q = q.where(ImpactRecommendationEvent.status == status)
    if severity is not None:
        q = q.where(ImpactRecommendationEvent.severity == severity)

    sort_key = (sort or "").strip().lower()
    if sort_key == "occurrences_desc":
        q = q.order_by(ImpactRecommendationEvent.occurrences.desc(), ImpactRecommendationEvent.last_seen_at.desc())
    else:
        q = q.order_by(ImpactRecommendationEvent.last_seen_at.desc())

    q = q.limit(int(limit))
    reco_events = (await session.execute(q)).scalars().all()

    recommendations = []
    for r in reco_events:
        recommendations.append(
            {
                "id": str(r.id),
                "code": r.code,
                "severity": r.severity,
                "status": r.status,
                "occurrences": int(r.occurrences or 0),
                "last_seen_at": r.last_seen_at,
                "entities": r.entities,
                "actions": [
                    {
                        "id": str(a.id),
                        "status": a.status,
                        "description": a.description,
                        "assignee": getattr(a, "assignee", None),
                        "due_date": getattr(a, "due_date", None),
                        "priority": getattr(a, "priority", None),
                        "created_at": getattr(a, "cree_le", None),
                        "updated_at": getattr(a, "updated_at", None),
                    }
                    for a in sorted(r.actions or [], key=lambda x: x.cree_le, reverse=True)
                ],
            }
        )

    return ImpactDashboardResponse(
        kpis={
            "days": days,
            "waste_rate": waste.waste_rate,
            "local_share": local.local_share,
            "co2_kgco2e": co2.total_kgco2e,
        },
        trends=trends,
        top_causes=top_causes,
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

    reco = await session.get(ImpactRecommendationEvent, reco_uuid)
    if reco is None:
        raise HTTPException(status_code=404, detail="Recommendation event introuvable.")

    now = datetime.now(timezone.utc)
    action = ImpactAction(
        id=uuid4(),
        recommendation_event_id=reco_uuid,
        action_type=body.action_type,
        description=body.description,
        assignee=body.assignee,
        due_date=body.due_date,
        priority=body.priority,
        status="OPEN",
        cree_le=now,
        mis_a_jour_le=now,
        updated_at=now,
    )
    session.add(action)
    await session.commit()
    await session.refresh(action)

    # 201: on garde le décorateur FastAPI simple + on renvoie quand même l'objet.
    # (FastAPI mettra 200 par défaut; on force explicitement.)
    # NOTE: on ne dépend pas de Response ici pour garder l'endpoint simple.
    # On utilise le status_code dans le décorateur ci-dessous.
    return ImpactActionSchema(
        id=str(action.id),
        recommendation_event_id=str(action.recommendation_event_id),
        action_type=str(action.action_type),
        description=action.description,
        assignee=getattr(action, "assignee", None),
        due_date=getattr(action, "due_date", None),
        priority=getattr(action, "priority", None),
        status=str(action.status),
        created_at=action.cree_le,
        updated_at=getattr(action, "updated_at", None),
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

    action = await session.get(ImpactAction, action_uuid)
    if action is None:
        raise HTTPException(status_code=404, detail="Action introuvable.")

    if body.status is not None:
        action.status = body.status
    if body.description is not None:
        action.description = body.description
    if body.assignee is not None:
        action.assignee = body.assignee
    if body.due_date is not None:
        action.due_date = body.due_date
    if body.priority is not None:
        action.priority = body.priority

    now = datetime.now(timezone.utc)
    action.mis_a_jour_le = now
    action.updated_at = now
    await session.commit()
    await session.refresh(action)

    return ImpactActionSchema(
        id=str(action.id),
        recommendation_event_id=str(action.recommendation_event_id),
        action_type=str(action.action_type),
        description=action.description,
        assignee=getattr(action, "assignee", None),
        due_date=getattr(action, "due_date", None),
        priority=getattr(action, "priority", None),
        status=str(action.status),
        created_at=action.cree_le,
        updated_at=getattr(action, "updated_at", None),
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

    reco = await session.get(ImpactRecommendationEvent, reco_uuid)
    if reco is None:
        raise HTTPException(status_code=404, detail="Recommendation event introuvable.")

    now = datetime.now(timezone.utc)
    if body.status is not None:
        reco.status = body.status
        if body.status == "RESOLVED":
            reco.resolved_at = reco.resolved_at or now
        else:
            reco.resolved_at = None

    if body.comment is not None:
        reco.comment = body.comment

    reco.mis_a_jour_le = now
    await session.commit()
    await session.refresh(reco)

    return {
        "id": str(reco.id),
        "status": str(reco.status),
        "comment": str(reco.comment or ""),
        "resolved_at": (reco.resolved_at.isoformat() if reco.resolved_at else ""),
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
