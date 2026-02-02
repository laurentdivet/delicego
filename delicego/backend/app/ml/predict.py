from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


SQL_UPSERT_PREDICTION = """
INSERT INTO prediction_vente (
  id,
  magasin_id,
  menu_id,
  date_jour,
  qte_predite,
  modele_version,
  cree_le,
  mis_a_jour_le
) VALUES (
  :id,
  :magasin_id,
  :menu_id,
  :date_jour,
  :qte_predite,
  :modele_version,
  now(),
  now()
)
ON CONFLICT (magasin_id, menu_id, date_jour)
DO UPDATE SET
  qte_predite = EXCLUDED.qte_predite,
  modele_version = EXCLUDED.modele_version,
  mis_a_jour_le = now();
"""


def _calendar_features(d: date) -> dict[str, float]:
    dow = d.weekday()
    return {
        "dow": float(dow),
        "weekend": float(1 if dow >= 5 else 0),
        "day": float(d.day),
        "month": float(d.month),
    }


def predict_next_days(
    *,
    model: Any,
    horizon_days: int,
    history_df: pd.DataFrame,
    start_date: date,
    encoders: dict[str, Any],
    magasin_id: UUID | None = None,
) -> pd.DataFrame:
    """Génère un DF de prédictions J+0..J+horizon-1.

    `history_df` doit contenir: jour (UTC datetime), magasin_id(str), menu_id(str), qte(float), prix(optionnel).
    """

    if horizon_days <= 0:
        return pd.DataFrame(columns=["magasin_id", "menu_id", "date_jour", "qte_predite", "modele_version"])

    hist = history_df.copy()
    if hist.empty:
        pairs: list[tuple[str, str]] = []
    else:
        hist["jour"] = pd.to_datetime(hist["jour"], utc=True, errors="coerce")
        hist = hist.dropna(subset=["jour"]).copy()
        if magasin_id is not None:
            hist = hist[hist["magasin_id"].astype(str) == str(magasin_id)]
        hist["magasin_id"] = hist["magasin_id"].astype(str)
        hist["menu_id"] = hist["menu_id"].astype(str)
        hist["qte"] = hist["qte"].astype(float)

        pairs = sorted({(m, me) for m, me in zip(hist["magasin_id"], hist["menu_id"])})

    magasin_to_code: dict[str, int] = {str(k): int(v) for k, v in encoders.get("magasin_to_code", {}).items()}
    menu_to_code: dict[str, int] = {str(k): int(v) for k, v in encoders.get("menu_to_code", {}).items()}
    features: list[str] = list(encoders.get("features", []))

    # map historique pour reconstruire les lags (réel sinon prévu)
    history_map: dict[tuple[str, str, date], float] = {}
    price_map: dict[tuple[str, str], float] = {}
    for r in hist.itertuples(index=False):
        d = getattr(r, "jour").date()
        key = (str(getattr(r, "magasin_id")), str(getattr(r, "menu_id")), d)
        history_map[key] = float(getattr(r, "qte"))
        if hasattr(r, "prix") and getattr(r, "prix") is not None and not pd.isna(getattr(r, "prix")):
            price_map[(str(getattr(r, "magasin_id")), str(getattr(r, "menu_id")))] = float(getattr(r, "prix"))

    out_rows: list[dict[str, Any]] = []
    mv = str(encoders.get("model_version") or encoders.get("version") or "")

    for i in range(int(horizon_days)):
        d = start_date + timedelta(days=i)
        cal = _calendar_features(d)
        feats_for_day = []
        pairs_for_day = []

        for mag_id, menu_id in pairs:
            if mag_id not in magasin_to_code or menu_id not in menu_to_code:
                # inconnu => on skip (par sécurité, sans crasher en prod)
                continue
            lag_1 = float(history_map.get((mag_id, menu_id, d - timedelta(days=1)), 0.0))
            lag_7 = float(history_map.get((mag_id, menu_id, d - timedelta(days=7)), 0.0))
            prix = float(price_map.get((mag_id, menu_id), 0.0))

            feat = {
                **cal,
                "magasin_cat": float(magasin_to_code[mag_id]),
                "menu_cat": float(menu_to_code[menu_id]),
                "lag_1": float(lag_1),
                "lag_7": float(lag_7),
                "prix": float(prix),
            }
            feats_for_day.append(feat)
            pairs_for_day.append((mag_id, menu_id))

        if not feats_for_day:
            continue

        X = pd.DataFrame(feats_for_day)
        if features:
            X = X[features]

        pred = model.predict(X)
        pred = np.clip(np.asarray(pred, dtype=float), 0.0, None)

        for (mag_id, menu_id), yhat in zip(pairs_for_day, pred):
            y = float(round(float(yhat), 2))
            history_map[(mag_id, menu_id, d)] = y
            out_rows.append(
                {
                    "magasin_id": mag_id,
                    "menu_id": menu_id,
                    "date_jour": d,
                    "qte_predite": y,
                    "modele_version": mv,
                }
            )

    return pd.DataFrame(out_rows)


async def upsert_predictions(session: AsyncSession, predictions: pd.DataFrame, model_version: str) -> int:
    if predictions.empty:
        return 0
    rows = []
    for r in predictions.itertuples(index=False):
        d = getattr(r, "date_jour")
        if isinstance(d, str):
            d = date.fromisoformat(d)
        rows.append(
            {
                "id": str(uuid4()),
                "magasin_id": str(getattr(r, "magasin_id")),
                "menu_id": str(getattr(r, "menu_id")),
                # IMPORTANT: asyncpg attend un `datetime.date` (pas une string)
                "date_jour": d,
                "qte_predite": float(getattr(r, "qte_predite")),
                "modele_version": model_version,
            }
        )
    # Assure que les entités référencées (magasin/menu) sont bien en base.
    # On évite un FK violation si le caller a seedé magasin/menu puis a rollback.
    await session.flush()

    stmt = text(SQL_UPSERT_PREDICTION)
    try:
        await session.execute(stmt, rows)
        return len(rows)
    except Exception:
        # Fallback robuste: certains combos SQLAlchemy/asyncpg peuvent être sensibles
        # à executemany() (types/date binding). On repasse en exécution unitaire.
        await session.rollback()
        written = 0
        for row in rows:
            await session.execute(stmt, row)
            written += 1
        return written
