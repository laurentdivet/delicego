from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMouvementStock
from app.domaine.modeles.achats import ReceptionMarchandise
from app.domaine.modeles.impact import FacteurCO2, IngredientImpact, PerteCasse
from app.domaine.modeles.production import LotProduction
from app.domaine.modeles.referentiel import Fournisseur, Ingredient, Recette
from app.domaine.modeles.stock_tracabilite import MouvementStock
from app.domaine.modeles.stock_tracabilite import Lot


PeriodUnit = Literal["day", "week"]


def _safe_delta(current: float, baseline: float) -> tuple[float | None, float | None]:
    """Return (delta_pct, delta_abs) with safe division.

    - delta_abs = current - baseline
    - delta_pct = (current - baseline) / baseline when baseline != 0 else None
    """

    delta_abs = float(current - baseline)
    if baseline == 0:
        return None, delta_abs
    return float(delta_abs / baseline), delta_abs


async def impact_trends_and_deltas(
    session: AsyncSession,
    *,
    days: int,
    compare_days: int | None = None,
    magasin_id: UUID | None = None,
    local_km_threshold: float = 100.0,
) -> dict[str, object]:
    """Compute daily series + deltas for dashboard.

    Returns dict compatible with `ImpactDashboardTrendsSchema`:
    {
      "waste_rate": {"series": [{date,value}], "delta_pct": .., "delta_abs": ..},
      "local_share": {..},
      "co2_kg": {..}
    }
    """

    if compare_days is None:
        compare_days = days
    if compare_days <= 0:
        raise ValueError("compare_days must be > 0")

    # --- current series
    w = await kpi_waste_rate(session, days=days, magasin_id=magasin_id)
    l = await kpi_local_share(
        session,
        days=days,
        magasin_id=magasin_id,
        local_km_threshold=local_km_threshold,
    )
    c = await kpi_co2_estimate(session, days=days, magasin_id=magasin_id)

    # --- baseline period bounds (previous compare_days days ending day before current start)
    start, *_ = _bounds(days)
    baseline_end = start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=compare_days - 1)
    baseline_start_dt = datetime.combine(baseline_start, datetime.min.time()).replace(tzinfo=timezone.utc)
    baseline_end_dt = datetime.combine(baseline_end, datetime.max.time()).replace(tzinfo=timezone.utc)

    # Waste baseline (same queries as kpi_waste_rate, but custom bounds)
    signe_perte = case((MouvementStock.type_mouvement == TypeMouvementStock.PERTE, 1), else_=0)
    signe_input = case(
        (
            MouvementStock.type_mouvement.in_([TypeMouvementStock.RECEPTION, TypeMouvementStock.CONSOMMATION]),
            1,
        ),
        else_=0,
    )
    q = (
        select(
            func.coalesce(func.sum(signe_perte * MouvementStock.quantite), 0.0).label("waste_qty"),
            func.coalesce(func.sum(signe_input * MouvementStock.quantite), 0.0).label("input_qty"),
        )
        .select_from(MouvementStock)
        .where(MouvementStock.horodatage >= baseline_start_dt, MouvementStock.horodatage <= baseline_end_dt)
    )
    if magasin_id is not None:
        q = q.where(MouvementStock.magasin_id == magasin_id)
    waste_qty_ms, input_qty = (await session.execute(q)).one()
    waste_qty = float(waste_qty_ms or 0.0)
    input_qty = float(input_qty or 0.0)

    q_pc = (
        select(func.coalesce(func.sum(PerteCasse.quantite), 0.0))
        .select_from(PerteCasse)
        .where(PerteCasse.jour >= baseline_start, PerteCasse.jour <= baseline_end)
    )
    if magasin_id is not None:
        q_pc = q_pc.where(PerteCasse.magasin_id == magasin_id)
    waste_qty += float((await session.execute(q_pc)).scalar_one() or 0.0)
    baseline_waste_rate = (waste_qty / input_qty) if input_qty > 0 else 0.0

    # Local baseline
    is_local = case(
        (
            (Fournisseur.distance_km.is_not(None)) & (Fournisseur.distance_km <= local_km_threshold),
            1,
        ),
        else_=0,
    )
    q = (
        select(
            func.count(ReceptionMarchandise.id).label("total"),
            func.coalesce(func.sum(is_local), 0).label("local"),
        )
        .select_from(ReceptionMarchandise)
        .join(Fournisseur, Fournisseur.id == ReceptionMarchandise.fournisseur_id)
        .where(ReceptionMarchandise.recu_le >= baseline_start_dt, ReceptionMarchandise.recu_le <= baseline_end_dt)
    )
    if magasin_id is not None:
        q = q.where(ReceptionMarchandise.magasin_id == magasin_id)
    total, local = (await session.execute(q)).one()
    total_i = int(total or 0)
    local_i = int(local or 0)
    baseline_local_share = (local_i / total_i) if total_i > 0 else 0.0

    # CO2 baseline
    q = (
        select(func.coalesce(func.sum(MouvementStock.quantite * FacteurCO2.facteur_kgco2e_par_kg), 0.0))
        .select_from(MouvementStock)
        .join(IngredientImpact, IngredientImpact.ingredient_id == MouvementStock.ingredient_id)
        .join(FacteurCO2, FacteurCO2.categorie == IngredientImpact.categorie_co2)
        .where(
            MouvementStock.horodatage >= baseline_start_dt,
            MouvementStock.horodatage <= baseline_end_dt,
            MouvementStock.type_mouvement == TypeMouvementStock.RECEPTION,
        )
    )
    if magasin_id is not None:
        q = q.where(MouvementStock.magasin_id == magasin_id)
    baseline_co2 = float((await session.execute(q)).scalar_one() or 0.0)

    w_pct, w_abs = _safe_delta(w.waste_rate, baseline_waste_rate)
    l_pct, l_abs = _safe_delta(l.local_share, baseline_local_share)
    c_pct, c_abs = _safe_delta(c.total_kgco2e, baseline_co2)

    return {
        "waste_rate": {
            "series": [
                {"date": p.date, "value": p.value}
                for p in w.series_waste_rate[: (days if days < 7 else len(w.series_waste_rate))]
            ],
            "delta_pct": w_pct,
            "delta_abs": w_abs,
        },
        "local_share": {
            "series": [
                {"date": p.date, "value": p.value}
                for p in l.series_local_share[: (days if days < 7 else len(l.series_local_share))]
            ],
            "delta_pct": l_pct,
            "delta_abs": l_abs,
        },
        "co2_kg": {
            "series": [
                {"date": p.date, "value": p.value}
                for p in c.series_kgco2e[: (days if days < 7 else len(c.series_kgco2e))]
            ],
            "delta_pct": c_pct,
            "delta_abs": c_abs,
        },
    }


async def impact_top_causes(
    session: AsyncSession,
    *,
    days: int,
    magasin_id: UUID | None = None,
    local_km_threshold: float = 100.0,
    limit: int = 5,
) -> dict[str, object]:
    """Top causes explicables (règles simples, sans ML) pour le dashboard."""

    start, end, start_dt, end_dt = _bounds(days)

    # -----------------
    # Waste: top ingredients by PERTE qty
    # -----------------
    q = (
        select(
            MouvementStock.ingredient_id.label("id"),
            Ingredient.nom.label("label"),
            func.coalesce(func.sum(MouvementStock.quantite), 0.0).label("value"),
        )
        .select_from(MouvementStock)
        .join(Ingredient, Ingredient.id == MouvementStock.ingredient_id)
        .where(
            MouvementStock.horodatage >= start_dt,
            MouvementStock.horodatage <= end_dt,
            MouvementStock.type_mouvement == TypeMouvementStock.PERTE,
        )
        .group_by(MouvementStock.ingredient_id, Ingredient.nom)
        .order_by(func.sum(MouvementStock.quantite).desc())
        .limit(int(limit))
    )
    if magasin_id is not None:
        q = q.where(MouvementStock.magasin_id == magasin_id)
    rows = (await session.execute(q)).all()
    waste_ingredients = [
        {"id": str(r.id), "label": str(r.label), "value": float(r.value or 0.0)} for r in rows
    ]

    # Waste: top menus proxy = lots de production par recette/menu
    # (si menu_id est null: on retombe sur recette_id)
    q = (
        select(
            func.coalesce(LotProduction.recette_id, LotProduction.recette_id).label("recette_id"),
            Recette.nom.label("label"),
            func.count(LotProduction.id).label("value"),
        )
        .select_from(LotProduction)
        .join(Recette, Recette.id == LotProduction.recette_id)
        .where(LotProduction.produit_le >= start_dt, LotProduction.produit_le <= end_dt)
        .group_by(LotProduction.recette_id, Recette.nom)
        .order_by(func.count(LotProduction.id).desc())
        .limit(int(limit))
    )
    if magasin_id is not None:
        q = q.where(LotProduction.magasin_id == magasin_id)
    rows = (await session.execute(q)).all()
    waste_menus = [{"id": str(r.recette_id), "label": str(r.label), "value": float(r.value or 0)} for r in rows]

    # -----------------
    # Local: top non-local suppliers by receptions count
    # -----------------
    is_non_local = case(
        (
            (Fournisseur.distance_km.is_(None)) | (Fournisseur.distance_km > local_km_threshold),
            1,
        ),
        else_=0,
    )
    q = (
        select(
            Fournisseur.id.label("id"),
            Fournisseur.nom.label("nom"),
            func.count(ReceptionMarchandise.id).label("value"),
        )
        .select_from(ReceptionMarchandise)
        .join(Fournisseur, Fournisseur.id == ReceptionMarchandise.fournisseur_id)
        .where(
            ReceptionMarchandise.recu_le >= start_dt,
            ReceptionMarchandise.recu_le <= end_dt,
            is_non_local == 1,
        )
        .group_by(Fournisseur.id, Fournisseur.nom)
        .order_by(func.count(ReceptionMarchandise.id).desc())
        .limit(int(limit))
    )
    if magasin_id is not None:
        q = q.where(ReceptionMarchandise.magasin_id == magasin_id)
    rows = (await session.execute(q)).all()
    local_fournisseurs = [
        {"id": str(r.id), "nom": str(r.nom), "value": float(r.value or 0)} for r in rows
    ]

    # -----------------
    # CO2: top ingredients by receptions qty * facteur (ignore missing mapping)
    # -----------------
    q = (
        select(
            MouvementStock.ingredient_id.label("id"),
            Ingredient.nom.label("label"),
            func.coalesce(func.sum(MouvementStock.quantite * FacteurCO2.facteur_kgco2e_par_kg), 0.0).label(
                "kgco2e"
            ),
        )
        .select_from(MouvementStock)
        .join(Ingredient, Ingredient.id == MouvementStock.ingredient_id)
        .join(IngredientImpact, IngredientImpact.ingredient_id == MouvementStock.ingredient_id)
        .join(FacteurCO2, FacteurCO2.categorie == IngredientImpact.categorie_co2)
        .where(
            MouvementStock.horodatage >= start_dt,
            MouvementStock.horodatage <= end_dt,
            MouvementStock.type_mouvement == TypeMouvementStock.RECEPTION,
        )
        .group_by(MouvementStock.ingredient_id, Ingredient.nom)
        .order_by(func.sum(MouvementStock.quantite * FacteurCO2.facteur_kgco2e_par_kg).desc())
        .limit(int(limit))
    )
    if magasin_id is not None:
        q = q.where(MouvementStock.magasin_id == magasin_id)
    rows = (await session.execute(q)).all()
    co2_ingredients = [
        {"id": str(r.id), "label": str(r.label), "value_kgco2e": float(r.kgco2e or 0.0)} for r in rows
    ]

    # CO2: top suppliers by kgco2e (via mouvements stock -> lot -> fournisseur)
    q = (
        select(
            Fournisseur.id.label("id"),
            Fournisseur.nom.label("nom"),
            func.coalesce(func.sum(MouvementStock.quantite * FacteurCO2.facteur_kgco2e_par_kg), 0.0).label(
                "value"
            ),
        )
        .select_from(MouvementStock)
        .join(IngredientImpact, IngredientImpact.ingredient_id == MouvementStock.ingredient_id)
        .join(FacteurCO2, FacteurCO2.categorie == IngredientImpact.categorie_co2)
        .join(  # lot is optional
            Lot,
            Lot.id == MouvementStock.lot_id,
            isouter=True,
        )
        .join(Fournisseur, Fournisseur.id == Lot.fournisseur_id, isouter=True)
        .where(
            MouvementStock.horodatage >= start_dt,
            MouvementStock.horodatage <= end_dt,
            MouvementStock.type_mouvement == TypeMouvementStock.RECEPTION,
            Fournisseur.id.is_not(None),
        )
        .group_by(Fournisseur.id, Fournisseur.nom)
        .order_by(func.sum(MouvementStock.quantite * FacteurCO2.facteur_kgco2e_par_kg).desc())
        .limit(int(limit))
    )
    if magasin_id is not None:
        q = q.where(MouvementStock.magasin_id == magasin_id)
    rows = (await session.execute(q)).all()
    co2_fournisseurs = [
        {"id": str(r.id), "nom": str(r.nom), "value": float(r.value or 0.0)} for r in rows
    ]

    return {
        "waste": {"ingredients": waste_ingredients, "menus": waste_menus},
        "local": {"fournisseurs": local_fournisseurs},
        "co2": {"ingredients": co2_ingredients, "fournisseurs": co2_fournisseurs},
    }


@dataclass(frozen=True)
class SeriePoint:
    date: date
    value: float


@dataclass(frozen=True)
class ImpactWasteResult:
    days: int
    waste_qty: float
    input_qty: float
    waste_rate: float
    series_waste_qty: list[SeriePoint]
    series_waste_rate: list[SeriePoint]


@dataclass(frozen=True)
class ImpactLocalResult:
    days: int
    local_km_threshold: float
    local_receptions: int
    total_receptions: int
    local_share: float
    series_local_share: list[SeriePoint]


@dataclass(frozen=True)
class ImpactCO2Result:
    days: int
    total_kgco2e: float
    series_kgco2e: list[SeriePoint]


@dataclass(frozen=True)
class ImpactSummary:
    days: int
    waste_rate: float
    local_share: float
    co2_kgco2e: float
    # optionnel: variation vs période précédente
    savings_vs_baseline: dict[str, float] | None = None


def _daterange_days(start: date, end: date) -> list[date]:
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]


def _bounds(days: int) -> tuple[date, date, datetime, datetime]:
    if days <= 0:
        raise ValueError("days must be > 0")
    end = date.today()
    start = end - timedelta(days=days - 1)
    start_dt = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc)
    return start, end, start_dt, end_dt


async def kpi_waste_rate(
    session: AsyncSession,
    *,
    days: int = 30,
    magasin_id: UUID | None = None,
) -> ImpactWasteResult:
    """Pertes / (réception + production) sur une période.

    Implémentation MVP traçable :
    - pertes: somme des MouvementStock.PERTE + PerteCasse (si utilisée)
    - inputs: somme des MouvementStock.RECEPTION + MouvementStock.CONSOMMATION
      (consommation utilisée comme proxy de la "production" faute de modèle complet)

    NOTE: tout est en "quantité" sans conversion d'unité (MVP).
    """

    start, end, start_dt, end_dt = _bounds(days)

    # --- agrégats globaux via mouvements stock
    signe_perte = case((MouvementStock.type_mouvement == TypeMouvementStock.PERTE, 1), else_=0)
    signe_input = case(
        (
            MouvementStock.type_mouvement.in_([TypeMouvementStock.RECEPTION, TypeMouvementStock.CONSOMMATION]),
            1,
        ),
        else_=0,
    )

    q = (
        select(
            func.coalesce(func.sum(signe_perte * MouvementStock.quantite), 0.0).label("waste_qty"),
            func.coalesce(func.sum(signe_input * MouvementStock.quantite), 0.0).label("input_qty"),
        )
        .select_from(MouvementStock)
        .where(MouvementStock.horodatage >= start_dt, MouvementStock.horodatage <= end_dt)
    )
    if magasin_id is not None:
        q = q.where(MouvementStock.magasin_id == magasin_id)

    waste_qty_ms, input_qty = (await session.execute(q)).one()
    waste_qty = float(waste_qty_ms or 0.0)
    input_qty = float(input_qty or 0.0)

    # --- complément via PerteCasse (si utilisé)
    q_pc = (
        select(func.coalesce(func.sum(PerteCasse.quantite), 0.0))
        .select_from(PerteCasse)
        .where(PerteCasse.jour >= start, PerteCasse.jour <= end)
    )
    if magasin_id is not None:
        q_pc = q_pc.where(PerteCasse.magasin_id == magasin_id)
    waste_qty += float((await session.execute(q_pc)).scalar_one() or 0.0)

    waste_rate = (waste_qty / input_qty) if input_qty > 0 else 0.0

    # --- séries journalières
    days_list = _daterange_days(start, end)

    # mouvements stock groupés par jour
    jour_ms = func.date(MouvementStock.horodatage).label("jour")
    q_series = (
        select(
            jour_ms,
            func.coalesce(func.sum(signe_perte * MouvementStock.quantite), 0.0).label("waste_qty"),
            func.coalesce(func.sum(signe_input * MouvementStock.quantite), 0.0).label("input_qty"),
        )
        .select_from(MouvementStock)
        .where(MouvementStock.horodatage >= start_dt, MouvementStock.horodatage <= end_dt)
        .group_by(jour_ms)
        .order_by(jour_ms)
    )
    if magasin_id is not None:
        q_series = q_series.where(MouvementStock.magasin_id == magasin_id)

    rows = (await session.execute(q_series)).all()
    by_day_ms = {r.jour: (float(r.waste_qty or 0.0), float(r.input_qty or 0.0)) for r in rows}

    q_pc_series = (
        select(PerteCasse.jour, func.coalesce(func.sum(PerteCasse.quantite), 0.0).label("waste_qty"))
        .select_from(PerteCasse)
        .where(PerteCasse.jour >= start, PerteCasse.jour <= end)
        .group_by(PerteCasse.jour)
        .order_by(PerteCasse.jour)
    )
    if magasin_id is not None:
        q_pc_series = q_pc_series.where(PerteCasse.magasin_id == magasin_id)
    rows_pc = (await session.execute(q_pc_series)).all()
    by_day_pc = {r.jour: float(r.waste_qty or 0.0) for r in rows_pc}

    series_waste_qty: list[SeriePoint] = []
    series_waste_rate: list[SeriePoint] = []
    for d in days_list:
        ms_waste, ms_input = by_day_ms.get(d, (0.0, 0.0))
        pc_waste = by_day_pc.get(d, 0.0)
        w = ms_waste + pc_waste
        i = ms_input
        series_waste_qty.append(SeriePoint(date=d, value=w))
        series_waste_rate.append(SeriePoint(date=d, value=(w / i) if i > 0 else 0.0))

    return ImpactWasteResult(
        days=days,
        waste_qty=waste_qty,
        input_qty=input_qty,
        waste_rate=waste_rate,
        series_waste_qty=series_waste_qty,
        series_waste_rate=series_waste_rate,
    )


async def kpi_local_share(
    session: AsyncSession,
    *,
    days: int = 30,
    local_km_threshold: float = 100.0,
    magasin_id: UUID | None = None,
) -> ImpactLocalResult:
    """Part des réceptions "locales" (proxy d'achats) sur une période.

    Méthode MVP :
    - Achats = nombre de réceptions
    - Local = fournisseur.distance_km <= threshold (si distance_km null => non local)

    Alternative future : valoriser en € ou en kg via lignes de réception.
    """

    start, end, start_dt, end_dt = _bounds(days)

    is_local = case(
        (
            (Fournisseur.distance_km.is_not(None)) & (Fournisseur.distance_km <= local_km_threshold),
            1,
        ),
        else_=0,
    )

    q = (
        select(
            func.count(ReceptionMarchandise.id).label("total"),
            func.coalesce(func.sum(is_local), 0).label("local"),
        )
        .select_from(ReceptionMarchandise)
        .join(Fournisseur, Fournisseur.id == ReceptionMarchandise.fournisseur_id)
        .where(ReceptionMarchandise.recu_le >= start_dt, ReceptionMarchandise.recu_le <= end_dt)
    )
    if magasin_id is not None:
        q = q.where(ReceptionMarchandise.magasin_id == magasin_id)

    total, local = (await session.execute(q)).one()
    total_i = int(total or 0)
    local_i = int(local or 0)
    local_share = (local_i / total_i) if total_i > 0 else 0.0

    # série journalière
    jour = func.date(ReceptionMarchandise.recu_le).label("jour")
    q_series = (
        select(
            jour,
            func.count(ReceptionMarchandise.id).label("total"),
            func.coalesce(func.sum(is_local), 0).label("local"),
        )
        .select_from(ReceptionMarchandise)
        .join(Fournisseur, Fournisseur.id == ReceptionMarchandise.fournisseur_id)
        .where(ReceptionMarchandise.recu_le >= start_dt, ReceptionMarchandise.recu_le <= end_dt)
        .group_by(jour)
        .order_by(jour)
    )
    if magasin_id is not None:
        q_series = q_series.where(ReceptionMarchandise.magasin_id == magasin_id)
    rows = (await session.execute(q_series)).all()
    by_day = {r.jour: (int(r.local or 0), int(r.total or 0)) for r in rows}

    series: list[SeriePoint] = []
    for d in _daterange_days(start, end):
        l, t = by_day.get(d, (0, 0))
        series.append(SeriePoint(date=d, value=(l / t) if t > 0 else 0.0))

    return ImpactLocalResult(
        days=days,
        local_km_threshold=local_km_threshold,
        local_receptions=local_i,
        total_receptions=total_i,
        local_share=local_share,
        series_local_share=series,
    )


async def kpi_co2_estimate(
    session: AsyncSession,
    *,
    days: int = 30,
    magasin_id: UUID | None = None,
) -> ImpactCO2Result:
    """Estimation CO2e simple via les réceptions (stock). 

    Méthode MVP :
    - on agrège les mouvements stock de type RECEPTION
    - on mappe ingredient -> categorie via IngredientImpact
    - on mappe categorie -> facteur via FacteurCO2

    Hypothèse unité : quantite en kg (ou compatible). Pas de conversion d'unité en MVP.
    Si l'ingredient n'est pas mappé ou facteur absent => 0 pour cette ligne.
    """

    start, end, start_dt, end_dt = _bounds(days)

    # join IngredientImpact + FacteurCO2 via catégorie
    q = (
        select(
            func.coalesce(func.sum(MouvementStock.quantite * FacteurCO2.facteur_kgco2e_par_kg), 0.0).label("kgco2e"),
        )
        .select_from(MouvementStock)
        .join(IngredientImpact, IngredientImpact.ingredient_id == MouvementStock.ingredient_id)
        .join(FacteurCO2, FacteurCO2.categorie == IngredientImpact.categorie_co2)
        .where(
            MouvementStock.horodatage >= start_dt,
            MouvementStock.horodatage <= end_dt,
            MouvementStock.type_mouvement == TypeMouvementStock.RECEPTION,
        )
    )
    if magasin_id is not None:
        q = q.where(MouvementStock.magasin_id == magasin_id)

    total_kgco2e = float((await session.execute(q)).scalar_one() or 0.0)

    jour = func.date(MouvementStock.horodatage).label("jour")
    q_series = (
        select(
            jour,
            func.coalesce(func.sum(MouvementStock.quantite * FacteurCO2.facteur_kgco2e_par_kg), 0.0).label("kgco2e"),
        )
        .select_from(MouvementStock)
        .join(IngredientImpact, IngredientImpact.ingredient_id == MouvementStock.ingredient_id)
        .join(FacteurCO2, FacteurCO2.categorie == IngredientImpact.categorie_co2)
        .where(
            MouvementStock.horodatage >= start_dt,
            MouvementStock.horodatage <= end_dt,
            MouvementStock.type_mouvement == TypeMouvementStock.RECEPTION,
        )
        .group_by(jour)
        .order_by(jour)
    )
    if magasin_id is not None:
        q_series = q_series.where(MouvementStock.magasin_id == magasin_id)
    rows = (await session.execute(q_series)).all()
    by_day = {r.jour: float(r.kgco2e or 0.0) for r in rows}

    series = [SeriePoint(date=d, value=by_day.get(d, 0.0)) for d in _daterange_days(start, end)]
    return ImpactCO2Result(days=days, total_kgco2e=total_kgco2e, series_kgco2e=series)


async def kpi_savings_vs_baseline(
    session: AsyncSession,
    *,
    days: int,
    magasin_id: UUID | None = None,
    local_km_threshold: float = 100.0,
) -> dict[str, float]:
    """Comparaison simple vs période précédente (même durée)."""

    current_w = await kpi_waste_rate(session, days=days, magasin_id=magasin_id)
    current_l = await kpi_local_share(
        session, days=days, magasin_id=magasin_id, local_km_threshold=local_km_threshold
    )
    current_c = await kpi_co2_estimate(session, days=days, magasin_id=magasin_id)

    # baseline : shift back by `days`
    start, end, *_ = _bounds(days)
    baseline_end = start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=days - 1)
    baseline_start_dt = datetime.combine(baseline_start, datetime.min.time()).replace(tzinfo=timezone.utc)
    baseline_end_dt = datetime.combine(baseline_end, datetime.max.time()).replace(tzinfo=timezone.utc)

    # Recompute with custom bounds (inline minimal, pour éviter de dupliquer trop de code)
    # Waste baseline
    signe_perte = case((MouvementStock.type_mouvement == TypeMouvementStock.PERTE, 1), else_=0)
    signe_input = case(
        (
            MouvementStock.type_mouvement.in_([TypeMouvementStock.RECEPTION, TypeMouvementStock.CONSOMMATION]),
            1,
        ),
        else_=0,
    )
    q = (
        select(
            func.coalesce(func.sum(signe_perte * MouvementStock.quantite), 0.0).label("waste_qty"),
            func.coalesce(func.sum(signe_input * MouvementStock.quantite), 0.0).label("input_qty"),
        )
        .select_from(MouvementStock)
        .where(MouvementStock.horodatage >= baseline_start_dt, MouvementStock.horodatage <= baseline_end_dt)
    )
    if magasin_id is not None:
        q = q.where(MouvementStock.magasin_id == magasin_id)
    waste_qty_ms, input_qty = (await session.execute(q)).one()
    waste_qty = float(waste_qty_ms or 0.0)
    input_qty = float(input_qty or 0.0)
    q_pc = (
        select(func.coalesce(func.sum(PerteCasse.quantite), 0.0))
        .select_from(PerteCasse)
        .where(PerteCasse.jour >= baseline_start, PerteCasse.jour <= baseline_end)
    )
    if magasin_id is not None:
        q_pc = q_pc.where(PerteCasse.magasin_id == magasin_id)
    waste_qty += float((await session.execute(q_pc)).scalar_one() or 0.0)
    baseline_waste_rate = (waste_qty / input_qty) if input_qty > 0 else 0.0

    # Local baseline
    is_local = case(
        (
            (Fournisseur.distance_km.is_not(None)) & (Fournisseur.distance_km <= local_km_threshold),
            1,
        ),
        else_=0,
    )
    q = (
        select(
            func.count(ReceptionMarchandise.id).label("total"),
            func.coalesce(func.sum(is_local), 0).label("local"),
        )
        .select_from(ReceptionMarchandise)
        .join(Fournisseur, Fournisseur.id == ReceptionMarchandise.fournisseur_id)
        .where(ReceptionMarchandise.recu_le >= baseline_start_dt, ReceptionMarchandise.recu_le <= baseline_end_dt)
    )
    if magasin_id is not None:
        q = q.where(ReceptionMarchandise.magasin_id == magasin_id)
    total, local = (await session.execute(q)).one()
    total_i = int(total or 0)
    local_i = int(local or 0)
    baseline_local_share = (local_i / total_i) if total_i > 0 else 0.0

    # CO2 baseline
    q = (
        select(func.coalesce(func.sum(MouvementStock.quantite * FacteurCO2.facteur_kgco2e_par_kg), 0.0))
        .select_from(MouvementStock)
        .join(IngredientImpact, IngredientImpact.ingredient_id == MouvementStock.ingredient_id)
        .join(FacteurCO2, FacteurCO2.categorie == IngredientImpact.categorie_co2)
        .where(
            MouvementStock.horodatage >= baseline_start_dt,
            MouvementStock.horodatage <= baseline_end_dt,
            MouvementStock.type_mouvement == TypeMouvementStock.RECEPTION,
        )
    )
    if magasin_id is not None:
        q = q.where(MouvementStock.magasin_id == magasin_id)
    baseline_co2 = float((await session.execute(q)).scalar_one() or 0.0)

    return {
        "waste_rate_delta": float(current_w.waste_rate - baseline_waste_rate),
        "local_share_delta": float(current_l.local_share - baseline_local_share),
        "co2_kgco2e_delta": float(current_c.total_kgco2e - baseline_co2),
    }


async def impact_summary(
    session: AsyncSession,
    *,
    days: int = 30,
    magasin_id: UUID | None = None,
    local_km_threshold: float = 100.0,
    include_savings_vs_baseline: bool = False,
) -> ImpactSummary:
    w = await kpi_waste_rate(session, days=days, magasin_id=magasin_id)
    l = await kpi_local_share(session, days=days, magasin_id=magasin_id, local_km_threshold=local_km_threshold)
    c = await kpi_co2_estimate(session, days=days, magasin_id=magasin_id)

    savings = None
    if include_savings_vs_baseline:
        savings = await kpi_savings_vs_baseline(
            session,
            days=days,
            magasin_id=magasin_id,
            local_km_threshold=local_km_threshold,
        )

    return ImpactSummary(
        days=days,
        waste_rate=w.waste_rate,
        local_share=l.local_share,
        co2_kgco2e=c.total_kgco2e,
        savings_vs_baseline=savings,
    )
