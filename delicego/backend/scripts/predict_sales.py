from __future__ import annotations

"""Prédictions de ventes (inference) pour DéliceGo.

Objectif
--------
- Charger le modèle XGBoost entraîné via `scripts.train_model`
- Générer des prédictions journalières (J+1..J+N) par (magasin_id, menu_id)
- Reconstituer les lags (lag_1, lag_7) en itérant jour par jour, en utilisant
  les dernières quantités connues (réelles sinon prévues)
- Upsert en base dans `prediction_vente` (idempotent)

Lancement (depuis backend/)
---------------------------
python -m scripts.predict_sales --horizon 7

Options:
--start-date YYYY-MM-DD  (par défaut: lendemain du max(jour) dans la view)
--horizon N              (par défaut 7)
--dry-run                (ne rien écrire, afficher uniquement)
--limit-menus N          (debug: limiter le nb de couples magasin/menu)

Contraintes
-----------
- SQLAlchemy ASYNC uniquement
- Aucun impact sur les endpoints / frontend
- Idempotent (upsert + create table safe)
"""

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application


# ----------------------------
# Config
# ----------------------------

SQL_VIEW = """
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

SQL_FALLBACK = """
SELECT
  date_trunc('day', v.date_vente AT TIME ZONE 'UTC')::date AS jour,
  m.nom AS magasin,
  v.magasin_id,
  me.nom AS menu,
  v.menu_id,
  COALESCE(SUM(v.quantite), 0.0) AS qte
FROM vente v
JOIN magasin m ON m.id = v.magasin_id
JOIN menu me ON me.id = v.menu_id
WHERE v.menu_id IS NOT NULL
GROUP BY 1,2,3,4,5
ORDER BY jour, magasin, menu;
"""

FEATURES = [
    "dow",
    "weekend",
    "day",
    "month",
    "magasin_cat",
    "menu_cat",
    "lag_1",
    "lag_7",
]

MODELS_DIR = Path("models")
MODEL_PATH = MODELS_DIR / "xgb_sales.json"
ENCODERS_PATH = MODELS_DIR / "encoders_sales.json"


# ----------------------------
# DB (idempotent)
# ----------------------------

SQL_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS prediction_vente (
  id uuid PRIMARY KEY,
  magasin_id uuid NOT NULL REFERENCES magasin(id),
  menu_id uuid NOT NULL REFERENCES menu(id),
  date_jour date NOT NULL,
  qte_predite double precision NOT NULL,
  modele_version text NULL,
  cree_le timestamptz NOT NULL DEFAULT now(),
  mis_a_jour_le timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_prediction_vente_magasin_menu_jour UNIQUE (magasin_id, menu_id, date_jour)
);
"""

SQL_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS ix_prediction_vente_date_magasin
  ON prediction_vente (date_jour, magasin_id);
"""

SQL_UPSERT = """
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


# ----------------------------
# Encoders + modèle
# ----------------------------


@dataclass(frozen=True)
class Encoders:
    magasin_to_code: dict[str, int]
    menu_to_code: dict[str, int]
    features: list[str]
    target: str


def _load_encoders(path: Path) -> Encoders:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Encoders(
        magasin_to_code={str(k): int(v) for k, v in raw["magasin_to_code"].items()},
        menu_to_code={str(k): int(v) for k, v in raw["menu_to_code"].items()},
        features=[str(x) for x in raw.get("features", [])],
        target=str(raw.get("target", "qte")),
    )


def _model_version(model_path: Path) -> str:
    # Version explicite: hash du fichier modèle (stable)
    h = hashlib.sha256()
    h.update(model_path.read_bytes())
    return f"sha256:{h.hexdigest()[:12]}"


def _load_model(model_path: Path):
    try:
        from xgboost import XGBRegressor
    except Exception as e:  # pragma: no cover
        raise SystemExit(
            "xgboost non installé. Fais: pip install xgboost\n"
            f"Détail: {e}"
        )

    model = XGBRegressor()
    model.load_model(str(model_path))
    return model


# ----------------------------
# Data prep
# ----------------------------


async def _load_dataset_df() -> pd.DataFrame:
    engine = create_async_engine(parametres_application.url_base_donnees, pool_pre_ping=True)
    try:
        try:
            async with engine.connect() as conn:
                res = await conn.execute(text(SQL_VIEW))
                rows = res.mappings().all()
        except Exception as e_view:
            print(
                "[predict_sales] WARN: view v_ventes_jour_menu indisponible. "
                "Fallback sur agrégation de la table vente.\n"
                f"Détail: {type(e_view).__name__}: {e_view}"
            )
            async with engine.connect() as conn:
                res = await conn.execute(text(SQL_FALLBACK))
                rows = res.mappings().all()
    finally:
        await engine.dispose()

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("Dataset vide: la view v_ventes_jour_menu ne renvoie rien.")

    # Normalisation types
    df["jour"] = pd.to_datetime(df["jour"], utc=True, errors="coerce")
    if df["jour"].isna().any():
        raise RuntimeError("Certaines valeurs de 'jour' sont invalides (NaT).")

    df["qte"] = df["qte"].astype(float)
    return df


def _calendar_features(d: date) -> dict[str, Any]:
    dow = d.weekday()
    return {
        "dow": int(dow),
        "weekend": int(dow >= 5),
        "day": int(d.day),
        "month": int(d.month),
    }


def _infer_start_date(df: pd.DataFrame) -> date:
    # Base: max(jour) dans la view (UTC) puis +1 jour
    max_jour = df["jour"].max()
    return max_jour.date() + timedelta(days=1)


def _build_history_map(df: pd.DataFrame) -> dict[tuple[str, str, date], float]:
    """Index rapide pour retrouver qte réelle par (magasin_id, menu_id, jour)."""

    hist: dict[tuple[str, str, date], float] = {}
    for row in df.itertuples(index=False):
        jour_dt = getattr(row, "jour")
        hist[(str(getattr(row, "magasin_id")), str(getattr(row, "menu_id")), jour_dt.date())] = float(
            getattr(row, "qte")
        )
    return hist


def _build_name_maps(df: pd.DataFrame) -> tuple[dict[str, str], dict[str, str]]:
    """Maps id->nom.

    NOTE: depuis 2026-02, les encoders sont basés sur ID (plus stable que le nom).
    On conserve cette fonction, mais elle ne sert plus au mapping encoders.
    """

    mag: dict[str, str] = {}
    men: dict[str, str] = {}
    for row in df.itertuples(index=False):
        mag[str(getattr(row, "magasin_id"))] = str(getattr(row, "magasin"))
        men[str(getattr(row, "menu_id"))] = str(getattr(row, "menu"))
    return mag, men


# ----------------------------
# Inference
# ----------------------------


def _validate_encoders_presence(
    *,
    magasin_names_by_id: dict[str, str],
    menu_names_by_id: dict[str, str],
    enc: Encoders,
) -> None:
    """Contraintes imposées: si magasin/menu inconnu => erreur explicite."""

    unknown_mags = sorted({mid for mid in magasin_names_by_id.keys() if mid not in enc.magasin_to_code})
    unknown_menus = sorted({mid for mid in menu_names_by_id.keys() if mid not in enc.menu_to_code})

    if unknown_mags or unknown_menus:
        msg = ["Encoders incomplets (inference refusée):"]
        if unknown_mags:
            msg.append(f"- magasin_id inconnus: {unknown_mags}")
        if unknown_menus:
            msg.append(f"- menu_id inconnus: {unknown_menus}")
        raise RuntimeError("\n".join(msg))


def _predict_horizon(
    *,
    df_hist: pd.DataFrame,
    start_date: date,
    horizon: int,
    enc: Encoders,
    model,
    limit_menus: int | None,
) -> list[dict[str, Any]]:
    """Retourne une liste de lignes (prêtes à upsert)"""

    history = _build_history_map(df_hist)
    mag_name_by_id, menu_name_by_id = _build_name_maps(df_hist)
    _validate_encoders_presence(magasin_names_by_id=mag_name_by_id, menu_names_by_id=menu_name_by_id, enc=enc)

    # Couples à prédire = ceux présents dans le dataset historique
    pairs = sorted(
        {(str(mag), str(menu)) for mag, menu in zip(df_hist["magasin_id"], df_hist["menu_id"])},
        key=lambda x: (x[0], x[1]),
    )
    if limit_menus is not None:
        pairs = pairs[: int(limit_menus)]

    mv = _model_version(MODEL_PATH)
    out: list[dict[str, Any]] = []

    for i in range(horizon):
        d = start_date + timedelta(days=i)
        cal = _calendar_features(d)

        rows_for_day = []
        for magasin_id, menu_id in pairs:
            lag_1 = float(history.get((magasin_id, menu_id, d - timedelta(days=1)), 0.0))
            lag_7 = float(history.get((magasin_id, menu_id, d - timedelta(days=7)), 0.0))

            feat = {
                **cal,
                "magasin_cat": int(enc.magasin_to_code[magasin_id]),
                "menu_cat": int(enc.menu_to_code[menu_id]),
                "lag_1": float(lag_1),
                "lag_7": float(lag_7),
            }
            rows_for_day.append((magasin_id, menu_id, feat))

        X = pd.DataFrame([feat for _, _, feat in rows_for_day])[FEATURES].astype(float)
        pred = model.predict(X)
        pred = np.clip(pred.astype(float), 0.0, None)

        # On écrit aussi dans history pour permettre les lags futurs (réel sinon prévu)
        for (magasin_id, menu_id, _), yhat in zip(rows_for_day, pred):
            y = float(round(float(yhat), 2))
            history[(magasin_id, menu_id, d)] = y
            out.append(
                {
                    "id": str(uuid4()),
                    "magasin_id": magasin_id,
                    "menu_id": menu_id,
                    "date_jour": d,
                    "qte_predite": y,
                    "modele_version": mv,
                }
            )

    return out


# ----------------------------
# Main
# ----------------------------


async def _ensure_table_exists(engine) -> None:
    async with engine.begin() as conn:
        # asyncpg n'accepte pas les multi-statements dans une requête préparée.
        await conn.execute(text(SQL_CREATE_TABLE))
        await conn.execute(text(SQL_CREATE_INDEX))


async def _upsert_predictions(*, engine, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    async with engine.begin() as conn:
        # executemany
        await conn.execute(text(SQL_UPSERT), rows)
    return len(rows)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DéliceGo - Prédictions ventes (inference)")
    p.add_argument("--horizon", type=int, default=7, help="Nombre de jours à prédire (défaut: 7)")
    p.add_argument("--start-date", type=str, default=None, help="Date de départ (YYYY-MM-DD). Défaut: demain.")
    p.add_argument("--dry-run", action="store_true", help="Ne pas écrire en DB, afficher uniquement")
    p.add_argument(
        "--limit-menus",
        type=int,
        default=None,
        help="DEBUG: limiter le nombre de couples magasin/menu traités",
    )
    return p.parse_args(argv)


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except Exception as e:
        raise SystemExit(f"--start-date invalide: {s}. Attendu YYYY-MM-DD. Détail: {e}")


async def main_async(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.horizon <= 0:
        raise SystemExit("--horizon doit être > 0")

    if not MODEL_PATH.exists():
        raise SystemExit(f"Modèle introuvable: {MODEL_PATH}. Lance d'abord `python -m scripts.train_model`.")
    if not ENCODERS_PATH.exists():
        raise SystemExit(f"Encoders introuvables: {ENCODERS_PATH}. Lance d'abord `python -m scripts.train_model`.")

    enc = _load_encoders(ENCODERS_PATH)
    if enc.features and enc.features != FEATURES:
        raise SystemExit(
            "Features mismatch entre train et inference. "
            f"train={enc.features} | inference={FEATURES}"
        )

    df = await _load_dataset_df()
    start = _parse_date(args.start_date) if args.start_date else _infer_start_date(df)

    model = _load_model(MODEL_PATH)
    rows = _predict_horizon(
        df_hist=df,
        start_date=start,
        horizon=int(args.horizon),
        enc=enc,
        model=model,
        limit_menus=args.limit_menus,
    )

    # Affichage
    print("\n=== PREDICT SALES: RÉSUMÉ ===")
    print(f"start_date   = {start.isoformat()} (UTC, basé sur max(jour) si non fourni)")
    print(f"horizon_days = {int(args.horizon)}")
    print(f"rows         = {len(rows)}")
    print(f"model        = {MODEL_PATH}")
    print(f"encoders     = {ENCODERS_PATH}")
    print(f"model_ver    = {_model_version(MODEL_PATH)}")

    # Affiche un échantillon lisible
    sample = rows[: min(15, len(rows))]
    if sample:
        print("\nAperçu (max 15 lignes):")
        for r in sample:
            print(
                f"- {r['date_jour']} | magasin={r['magasin_id']} | menu={r['menu_id']} | qte={r['qte_predite']}"
            )

    if args.dry_run:
        print("\nDRY-RUN: aucune écriture en base.")
        return 0

    engine = create_async_engine(parametres_application.url_base_donnees, pool_pre_ping=True)
    try:
        await _ensure_table_exists(engine)
        written = await _upsert_predictions(engine=engine, rows=rows)
    finally:
        await engine.dispose()

    print(f"\nOK: upsert effectué ({written} lignes).")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
