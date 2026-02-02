from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd

from app.ml.dataset import build_features


ARTIFACTS_DIR = Path("artifacts")
MODEL_PATH = ARTIFACTS_DIR / "xgb_sales.json"
META_PATH = ARTIFACTS_DIR / "xgb_sales_meta.json"


class RegressorLike(Protocol):
    def predict(self, X: Any): ...  # noqa: ANN401


@dataclass(frozen=True)
class TrainResult:
    model_type: str  # "xgboost" | "baseline"
    model: Any
    metrics: dict[str, float]
    encoders: dict[str, Any]
    artifact_path: str | None
    model_version: str


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true = y_true.astype(float)
    y_pred = y_pred.astype(float)
    return float(np.mean(np.abs(y_true - y_pred)))


def _time_split_index(n: int, min_val: int = 1, val_ratio: float = 0.2) -> int:
    if n <= 0:
        return 0
    val = max(min_val, int(round(n * val_ratio)))
    return max(0, n - val)


class BaselineMeanByDow:
    """Baseline robuste: moyenne par jour de semaine + moyenne globale fallback."""

    def __init__(self, *, dow_to_mean: dict[int, float], global_mean: float) -> None:
        self._dow_to_mean = {int(k): float(v) for k, v in dow_to_mean.items()}
        self._global_mean = float(global_mean)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        dow = X["dow"].astype(int).to_numpy()
        out = np.array([self._dow_to_mean.get(int(d), self._global_mean) for d in dow], dtype=float)
        return np.clip(out, 0.0, None)


def train_model(df_sales: pd.DataFrame, params: dict[str, Any] | None = None) -> TrainResult:
    """Entraîne un modèle (XGBoost si possible) à partir du dataframe de ventes.

    Si pas assez de données: fallback baseline (moyenne par jour de semaine).
    """

    params = params or {}
    min_rows = int(params.get("min_rows", 30))

    X, y, enc = build_features(df_sales)
    if X.empty or len(X) < min_rows:
        # Baseline
        if df_sales.empty:
            global_mean = 0.0
            dow_means: dict[int, float] = {}
        else:
            tmp = df_sales.copy()
            tmp["jour"] = pd.to_datetime(tmp["jour"], utc=True, errors="coerce")
            tmp = tmp.dropna(subset=["jour"]).copy()
            tmp["dow"] = tmp["jour"].dt.dayofweek.astype(int)
            tmp["qte"] = tmp["qte"].astype(float)
            dow_means = tmp.groupby("dow")["qte"].mean().to_dict()
            global_mean = float(tmp["qte"].mean()) if len(tmp) else 0.0

        model = BaselineMeanByDow(dow_to_mean=dow_means, global_mean=global_mean)
        mv = f"baseline:mean_dow:{hashlib.sha256(json.dumps(dow_means, sort_keys=True).encode()).hexdigest()[:12]}"
        return TrainResult(
            model_type="baseline",
            model=model,
            metrics={"mae": float("nan")},
            encoders=enc,
            artifact_path=None,
            model_version=mv,
        )

    # Split temporel strict (par ordre des lignes déjà temporellement triées dans build_features)
    split = _time_split_index(len(X), min_val=5, val_ratio=float(params.get("val_ratio", 0.2)))
    X_train, y_train = X.iloc[:split], y.iloc[:split]
    X_val, y_val = X.iloc[split:], y.iloc[split:]
    if len(X_train) == 0 or len(X_val) == 0:
        # fallback baseline si split invalide
        model = BaselineMeanByDow(dow_to_mean={}, global_mean=float(y.mean()))
        mv = f"baseline:mean:{hashlib.sha256(str(float(y.mean())).encode()).hexdigest()[:12]}"
        return TrainResult(
            model_type="baseline",
            model=model,
            metrics={"mae": float("nan")},
            encoders=enc,
            artifact_path=None,
            model_version=mv,
        )

    try:
        from xgboost import XGBRegressor
    except Exception:
        # xgboost non dispo => baseline
        model = BaselineMeanByDow(dow_to_mean={}, global_mean=float(y_train.mean()))
        mv = f"baseline:mean:{hashlib.sha256(str(float(y_train.mean())).encode()).hexdigest()[:12]}"
        return TrainResult(
            model_type="baseline",
            model=model,
            metrics={"mae": float("nan")},
            encoders=enc,
            artifact_path=None,
            model_version=mv,
        )

    model = XGBRegressor(
        n_estimators=int(params.get("n_estimators", 400)),
        learning_rate=float(params.get("learning_rate", 0.05)),
        max_depth=int(params.get("max_depth", 6)),
        subsample=float(params.get("subsample", 0.9)),
        colsample_bytree=float(params.get("colsample_bytree", 0.9)),
        reg_alpha=float(params.get("reg_alpha", 0.0)),
        reg_lambda=float(params.get("reg_lambda", 1.0)),
        objective="reg:squarederror",
        random_state=int(params.get("random_state", 42)),
        n_jobs=int(params.get("n_jobs", -1)),
    )

    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    pred_val = model.predict(X_val)
    mae = _mae(y_val.to_numpy(), np.asarray(pred_val))

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODEL_PATH))

    meta = {
        "model_type": "xgboost",
        "features": enc.get("features"),
        "target": enc.get("target"),
        "mae": mae,
    }
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    h = hashlib.sha256()
    h.update(MODEL_PATH.read_bytes())
    mv = f"sha256:{h.hexdigest()[:12]}"

    return TrainResult(
        model_type="xgboost",
        model=model,
        metrics={"mae": float(mae)},
        encoders=enc,
        artifact_path=str(MODEL_PATH),
        model_version=mv,
    )
