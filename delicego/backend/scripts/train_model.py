from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sklearn.metrics import mean_absolute_error, mean_squared_error

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

# Fallback robuste si la view n'existe pas en DB (cas fréquent en local).
# On agrège depuis `vente`.
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

MODELS_DIR = Path("models")
MODEL_PATH = MODELS_DIR / "xgb_sales.json"
ENCODERS_PATH = MODELS_DIR / "encoders_sales.json"

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
TARGET = "qte"


# ----------------------------
# Data loading (async SQLAlchemy)
# ----------------------------
async def _try_query(engine, sql: str) -> list[dict]:
    async with engine.connect() as conn:
        res = await conn.execute(text(sql))
        return res.mappings().all()


async def load_dataset() -> pd.DataFrame:
    engine = create_async_engine(
        parametres_application.url_base_donnees,
        pool_pre_ping=True,
    )
    try:
        try:
            rows = await _try_query(engine, SQL_VIEW)
        except Exception as e_view:
            print(
                "[train_model] WARN: view v_ventes_jour_menu indisponible. "
                "Fallback sur agrégation de la table vente.\n"
                f"Détail: {type(e_view).__name__}: {e_view}"
            )
            rows = await _try_query(engine, SQL_FALLBACK)
    finally:
        await engine.dispose()

    df = pd.DataFrame(rows)
    return df


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    - Encode magasin/menu en codes stables (mapping sauvegardé)
    - Features calendaires
    - Lags par (magasin_id, menu_id)
    """
    df = df.copy()

    if "jour" not in df.columns:
        raise ValueError("Colonne 'jour' manquante dans le dataset.")
    if TARGET not in df.columns:
        raise ValueError(f"Colonne '{TARGET}' manquante dans le dataset.")

    df["jour"] = pd.to_datetime(df["jour"], utc=True, errors="coerce")
    if df["jour"].isna().any():
        raise ValueError("Certaines valeurs de 'jour' sont invalides (NaT).")

    df[TARGET] = df[TARGET].astype(float)

    # Mappings stables (utile pour predict plus tard)
    # IMPORTANT : on encode par ID (pas par nom) pour éviter les surprises
    # si le libellé d'un menu/magasin change.
    magasins = sorted(df["magasin_id"].dropna().astype(str).unique().tolist())
    menus = sorted(df["menu_id"].dropna().astype(str).unique().tolist())

    magasin_to_code = {mid: i for i, mid in enumerate(magasins)}
    menu_to_code = {mid: i for i, mid in enumerate(menus)}

    df["magasin_cat"] = df["magasin_id"].astype(str).map(magasin_to_code).astype(int)
    df["menu_cat"] = df["menu_id"].astype(str).map(menu_to_code).astype(int)

    # Features temporelles
    df["dow"] = df["jour"].dt.dayofweek
    df["weekend"] = (df["dow"] >= 5).astype(int)
    df["day"] = df["jour"].dt.day
    df["month"] = df["jour"].dt.month

    # Lags (fondamental)
    df = df.sort_values(["magasin_id", "menu_id", "jour"])
    df["lag_1"] = df.groupby(["magasin_id", "menu_id"])[TARGET].shift(1).fillna(0.0)
    df["lag_7"] = df.groupby(["magasin_id", "menu_id"])[TARGET].shift(7).fillna(0.0)

    encoders = {
        "magasin_to_code": magasin_to_code,
        "menu_to_code": menu_to_code,
        "features": FEATURES,
        "target": TARGET,
    }
    return df, encoders


def time_split(df: pd.DataFrame, val_days: int = 2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split temporel strict :
    - train = tout avant les `val_days` derniers jours
    - val   = les `val_days` derniers jours
    """
    if val_days < 1:
        raise ValueError("val_days doit être >= 1")

    max_day = df["jour"].max().normalize()
    cutoff = max_day - pd.Timedelta(days=val_days - 1)  # ex: val_days=2 => cutoff = J-1

    train_df = df[df["jour"].dt.normalize() < cutoff].copy()
    val_df = df[df["jour"].dt.normalize() >= cutoff].copy()
    return train_df, val_df


async def main() -> None:
    try:
        from xgboost import XGBRegressor
    except Exception as e:
        raise SystemExit(
            "xgboost non installé. Fais: pip install xgboost\n"
            f"Détail: {e}"
        )

    df_raw = await load_dataset()
    if df_raw.empty:
        raise SystemExit("Dataset vide: la view v_ventes_jour_menu ne renvoie rien.")

    df, encoders = build_features(df_raw)
    train_df, val_df = time_split(df, val_days=2)

    if len(train_df) == 0 or len(val_df) == 0:
        raise SystemExit(
            f"Split invalide: train={len(train_df)} val={len(val_df)}. "
            "Augmente la période de ventes ou réduis val_days."
        )

    X_train = train_df[FEATURES].astype(float)
    y_train = train_df[TARGET].astype(float)

    X_val = val_df[FEATURES].astype(float)
    y_val = val_df[TARGET].astype(float)

    # Modèle baseline solide
    model = XGBRegressor(
        n_estimators=600,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_alpha=0.0,
        reg_lambda=1.0,
        objective="reg:squarederror",
        random_state=42,
        n_jobs=-1,
    )

    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    # Évaluation
    pred_val = model.predict(X_val)
    mae = mean_absolute_error(y_val, pred_val)

    # Compat sklearn (pas de squared=False)
    mse = mean_squared_error(y_val, pred_val)
    rmse = float(np.sqrt(mse))

    # Sauvegarde
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODEL_PATH))
    ENCODERS_PATH.write_text(
        json.dumps(encoders, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Quick sanity check: top features
    importances = getattr(model, "feature_importances_", None)
    top: list[tuple[str, float]] = []
    if importances is not None:
        top = sorted(
            [(name, float(score)) for name, score in zip(FEATURES, importances)],
            key=lambda x: x[1],
            reverse=True,
        )

    print("\n=== TRAIN MODEL: RÉSUMÉ ===")
    print(f"train rows = {len(train_df)} | val rows = {len(val_df)}")
    print(f"val MAE  = {mae:.4f}")
    print(f"val RMSE = {rmse:.4f}")
    print(f"model    = {MODEL_PATH}")
    print(f"encoders = {ENCODERS_PATH}")

    if top:
        print("\nTop features:")
        for name, score in top[:8]:
            print(f"- {name}: {score:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
