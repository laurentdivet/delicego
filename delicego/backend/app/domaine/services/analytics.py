from __future__ import annotations

"""Analytique (READ-ONLY).

Contraintes:
- Ne modifie aucune donnée métier.
- Ne dépend pas des endpoints d'écriture.
- Calculs basés sur données fournies (mouvements stock, ventes simulées).

Les modèles "opérations" peuvent être importés en lecture (StockMovement), mais
ce module n'écrit rien.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum

from app.domaine.modeles.operations import StockMovement, StockMovementType


class Period(str, Enum):
    DAY = "day"
    WEEK = "week"


@dataclass(frozen=True)
class CostMatterRealLine:
    period_start: date
    value: float


@dataclass(frozen=True)
class CostMatterTheoreticalLine:
    period_start: date
    value: float


@dataclass(frozen=True)
class MarginLine:
    period_start: date
    ca: float
    cost_real: float
    margin: float


@dataclass(frozen=True)
class GapLine:
    period_start: date
    cost_real: float
    cost_theoretical: float
    gap_eur: float
    gap_pct: float | None


def _period_start(d: date, period: Period) -> date:
    if period == Period.DAY:
        return d
    # semaine ISO (lundi)
    return d.fromisocalendar(d.isocalendar().year, d.isocalendar().week, 1)


def cost_matter_real(
    movements: list[StockMovement],
    *,
    period: Period,
    start: date | None = None,
    end: date | None = None,
) -> list[CostMatterRealLine]:
    """Coût matière réel = somme (quantite * valeur_unitaire) sur SORTIES + PERTES.

    Convention:
    - On prend la valeur absolue pour obtenir un coût positif.
    """

    agg: dict[date, float] = {}

    for m in movements:
        if m.type not in (StockMovementType.SORTIE, StockMovementType.PERTE):
            continue
        d = m.date_heure.date()
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue

        key = _period_start(d, period)
        agg[key] = agg.get(key, 0.0) + abs(float(m.quantite) * float(m.valeur_unitaire))

    return [CostMatterRealLine(period_start=k, value=v) for k, v in sorted(agg.items())]


def cost_matter_theoretical(
    sales: list[dict],
    *,
    period: Period,
    start: date | None = None,
    end: date | None = None,
) -> list[CostMatterTheoreticalLine]:
    """Coût matière théorique simplifié basé sur ventes simulées.

    Chaque vente est un dict attendu:
    - date: date
    - ca: float
    - cost_rate: float (ex: 0.35)

    cost_theoretical = ca * cost_rate
    """

    agg: dict[date, float] = {}
    for s in sales:
        d: date = s["date"]
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue

        ca = float(s.get("ca", 0.0))
        cost_rate = float(s.get("cost_rate", 0.0))
        key = _period_start(d, period)
        agg[key] = agg.get(key, 0.0) + ca * cost_rate

    return [CostMatterTheoreticalLine(period_start=k, value=v) for k, v in sorted(agg.items())]


def margin(
    *,
    movements: list[StockMovement],
    sales: list[dict],
    period: Period,
    start: date | None = None,
    end: date | None = None,
) -> list[MarginLine]:
    real = {l.period_start: l.value for l in cost_matter_real(movements, period=period, start=start, end=end)}

    # CA par période
    ca_agg: dict[date, float] = {}
    for s in sales:
        d: date = s["date"]
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue
        key = _period_start(d, period)
        ca_agg[key] = ca_agg.get(key, 0.0) + float(s.get("ca", 0.0))

    keys = sorted(set(real.keys()) | set(ca_agg.keys()))
    out: list[MarginLine] = []
    for k in keys:
        ca = ca_agg.get(k, 0.0)
        cost = real.get(k, 0.0)
        out.append(MarginLine(period_start=k, ca=ca, cost_real=cost, margin=ca - cost))
    return out


def gaps(
    *,
    movements: list[StockMovement],
    sales: list[dict],
    period: Period,
    start: date | None = None,
    end: date | None = None,
) -> list[GapLine]:
    real = {l.period_start: l.value for l in cost_matter_real(movements, period=period, start=start, end=end)}
    theo = {l.period_start: l.value for l in cost_matter_theoretical(sales, period=period, start=start, end=end)}

    keys = sorted(set(real.keys()) | set(theo.keys()))
    out: list[GapLine] = []
    for k in keys:
        r = real.get(k, 0.0)
        t = theo.get(k, 0.0)
        gap_eur = r - t
        gap_pct = (gap_eur / t * 100.0) if abs(t) > 1e-9 else None
        out.append(GapLine(period_start=k, cost_real=r, cost_theoretical=t, gap_eur=gap_eur, gap_pct=gap_pct))
    return out
