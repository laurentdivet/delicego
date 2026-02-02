from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy.sql import text
from sqlalchemy.ext.asyncio import AsyncSession


# NOTE: on évite de dépendre d'une view, mais si elle existe on la privilégie.
SQL_VIEW_VENTES_JOUR_MENU = """
SELECT
  jour,
  magasin,
  magasin_id,
  menu,
  menu_id,
  qte
FROM v_ventes_jour_menu
ORDER BY jour, magasin, menu;
"""

"""NOTE

On évite volontairement d'écrire un SQL fallback "à paramètres optionnels" du style
  (:p IS NULL OR ...)
car asyncpg est très strict sur l'inférence de types et peut lever
AmbiguousParameterError.

On génère donc le SQL fallback dynamiquement dans `load_sales_dataframe()`.
"""


@dataclass(frozen=True)
class DatasetMetadata:
    date_from: date | None
    date_to: date | None
    magasin_id: UUID | None
    used_view: bool
    rows: int


async def load_sales_dataframe(
    session: AsyncSession,
    date_from: date | None,
    date_to: date | None,
    magasin_id: UUID | None = None,
) -> tuple[pd.DataFrame, DatasetMetadata]:
    """Charge les ventes journalières agrégées par (jour, magasin_id, menu_id).

    Retourne un DataFrame minimal avec colonnes:
    - jour (datetime64[ns, UTC])
    - magasin_id (uuid str)
    - menu_id (uuid str)
    - qte (float)
    - prix (float|null) si disponible
    """

    used_view = False
    rows: list[dict[str, Any]]
    try:
        # La view ne filtre pas (encore) sur date/magasin; on filtre côté pandas ensuite.
        res = await session.execute(text(SQL_VIEW_VENTES_JOUR_MENU))
        rows = res.mappings().all()
        used_view = True
    except Exception:
        # Version robuste: on construit le SQL dynamiquement pour éviter les paramètres optionnels
        # qui posent problème avec asyncpg (AmbiguousParameterError sur IS NULL / cast).
        sql = """
SELECT
  date_trunc('day', v.date_vente AT TIME ZONE 'UTC')::date AS jour,
  m.nom AS magasin,
  v.magasin_id,
  me.nom AS menu,
  v.menu_id,
  COALESCE(SUM(v.quantite), 0.0) AS qte,
  MAX(me.prix) AS prix
FROM vente v
JOIN magasin m ON m.id = v.magasin_id
JOIN menu me ON me.id = v.menu_id
WHERE v.menu_id IS NOT NULL
"""

        dyn_params: dict[str, Any] = {}
        if magasin_id is not None:
            sql += "\n  AND v.magasin_id = :magasin_id"
            dyn_params["magasin_id"] = str(magasin_id)
        if date_from is not None:
            sql += "\n  AND (v.date_vente AT TIME ZONE 'UTC')::date >= :date_from"
            dyn_params["date_from"] = date_from
        if date_to is not None:
            sql += "\n  AND (v.date_vente AT TIME ZONE 'UTC')::date <= :date_to"
            dyn_params["date_to"] = date_to

        sql += "\nGROUP BY 1,2,3,4,5\nORDER BY jour, magasin, menu;\n"

        # IMPORTANT: cast explicite sur les paramètres pour éviter AmbiguousParameterError
        # quand la table `vente` est vide (Postgres/asyncpg n'infère pas le type à partir
        # d'un plan sans aucune ligne).
        if magasin_id is not None:
            sql = sql.replace("v.magasin_id = :magasin_id", "v.magasin_id = CAST(:magasin_id AS uuid)")
        # Les dates doivent être passées comme `datetime.date` (pas str) pour asyncpg.

        res = await session.execute(text(sql), dyn_params)
        rows = res.mappings().all()

    df = pd.DataFrame(rows)
    if df.empty:
        return df, DatasetMetadata(
            date_from=date_from,
            date_to=date_to,
            magasin_id=magasin_id,
            used_view=used_view,
            rows=0,
        )

    # Normalisation types
    df["jour"] = pd.to_datetime(df["jour"], utc=True, errors="coerce")
    df["qte"] = df["qte"].astype(float)
    if "prix" in df.columns:
        df["prix"] = pd.to_numeric(df["prix"], errors="coerce")

    # Filtres si view
    if used_view:
        if magasin_id is not None:
            df = df[df["magasin_id"].astype(str) == str(magasin_id)]
        if date_from is not None:
            df = df[df["jour"].dt.date >= date_from]
        if date_to is not None:
            df = df[df["jour"].dt.date <= date_to]

        # Ajout prix si absent (la view peut ne pas le fournir)
        if "prix" not in df.columns:
            df["prix"] = pd.NA

    # Nettoyage
    df = df.dropna(subset=["jour", "magasin_id", "menu_id"]).copy()
    df["magasin_id"] = df["magasin_id"].astype(str)
    df["menu_id"] = df["menu_id"].astype(str)

    # Agrégation (sécurité): au cas où la source renvoie déjà agrégé partiellement
    df = (
        df.groupby(["jour", "magasin_id", "menu_id"], as_index=False)
        .agg({"qte": "sum", "prix": "max"})
        .sort_values(["jour", "magasin_id", "menu_id"])
    )

    return df, DatasetMetadata(
        date_from=date_from,
        date_to=date_to,
        magasin_id=magasin_id,
        used_view=used_view,
        rows=int(len(df)),
    )


def _fill_missing_days(df: pd.DataFrame) -> pd.DataFrame:
    """Comble les trous de jours (jours sans vente) par 0.

    On reindexe par couple (magasin_id, menu_id).
    """

    if df.empty:
        return df

    out = []
    for (magasin_id, menu_id), g in df.groupby(["magasin_id", "menu_id"], as_index=False):
        g = g.sort_values("jour")
        start = g["jour"].min().normalize()
        end = g["jour"].max().normalize()
        idx = pd.date_range(start=start, end=end, freq="D", tz="UTC")

        g2 = g.set_index(g["jour"].dt.normalize())
        g2 = g2.reindex(idx)
        g2.index.name = "jour_norm"
        g2 = g2.reset_index()
        g2["jour"] = pd.to_datetime(g2["jour_norm"], utc=True)
        g2["magasin_id"] = magasin_id
        g2["menu_id"] = menu_id
        g2["qte"] = pd.to_numeric(g2["qte"], errors="coerce").fillna(0.0)
        if "prix" in g2.columns:
            g2["prix"] = pd.to_numeric(g2["prix"], errors="coerce")
        out.append(g2[["jour", "magasin_id", "menu_id", "qte", "prix"]])

    return pd.concat(out, ignore_index=True).sort_values(["jour", "magasin_id", "menu_id"])


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, dict[str, Any]]:
    """Construit X, y et des metadata d'encodage.

    Features:
    - calendaires (dow, weekend, day, month)
    - encodage catégoriel stable basé sur IDs (magasin_id/menu_id)
    - lags (lag_1, lag_7) par (magasin_id, menu_id)
    - prix (optionnel)
    """

    if df.empty:
        X = pd.DataFrame()
        y = pd.Series(dtype=float)
        return X, y, {"features": [], "target": "qte"}

    df = df.copy()
    df = _fill_missing_days(df)

    df["jour"] = pd.to_datetime(df["jour"], utc=True, errors="coerce")
    df = df.dropna(subset=["jour"]).copy()
    df["qte"] = df["qte"].astype(float)

    magasins = sorted(df["magasin_id"].dropna().astype(str).unique().tolist())
    menus = sorted(df["menu_id"].dropna().astype(str).unique().tolist())
    magasin_to_code = {mid: i for i, mid in enumerate(magasins)}
    menu_to_code = {mid: i for i, mid in enumerate(menus)}
    df["magasin_cat"] = df["magasin_id"].astype(str).map(magasin_to_code).astype(int)
    df["menu_cat"] = df["menu_id"].astype(str).map(menu_to_code).astype(int)

    df["dow"] = df["jour"].dt.dayofweek
    df["weekend"] = (df["dow"] >= 5).astype(int)
    df["day"] = df["jour"].dt.day
    df["month"] = df["jour"].dt.month

    df = df.sort_values(["magasin_id", "menu_id", "jour"])
    df["lag_1"] = df.groupby(["magasin_id", "menu_id"])["qte"].shift(1).fillna(0.0)
    df["lag_7"] = df.groupby(["magasin_id", "menu_id"])["qte"].shift(7).fillna(0.0)

    # prix optionnel
    if "prix" not in df.columns:
        df["prix"] = pd.NA
    df["prix"] = pd.to_numeric(df["prix"], errors="coerce")
    df["prix"] = df.groupby(["magasin_id", "menu_id"])["prix"].ffill().bfill()

    features = ["dow", "weekend", "day", "month", "magasin_cat", "menu_cat", "lag_1", "lag_7", "prix"]
    X = df[features].astype(float)
    y = df["qte"].astype(float)

    meta = {
        "magasin_to_code": magasin_to_code,
        "menu_to_code": menu_to_code,
        "features": features,
        "target": "qte",
        "built_at": datetime.utcnow().isoformat(),
    }
    return X, y, meta
