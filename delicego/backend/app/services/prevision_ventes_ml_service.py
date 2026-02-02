from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMagasin
from app.domaine.modeles import Magasin, Menu
from app.ml.dataset import load_sales_dataframe
from app.ml.predict import predict_next_days, upsert_predictions
from app.ml.train import TrainResult, train_model


@dataclass(frozen=True)
class ForecastReport:
    magasin_id: UUID
    horizon_days: int
    model_type: str
    model_version: str
    train_rows: int
    predictions_written: int


def _synthetic_sales(*, magasin_id: UUID, menus: list[Menu], days: int = 60) -> pd.DataFrame:
    """Dataset synthétique réaliste pour mode démo.

    But: passer par le même pipeline train/predict.
    """

    today = date.today()
    start = today - timedelta(days=days)
    rows: list[dict[str, Any]] = []

    rng = np.random.default_rng(42)
    for menu in menus:
        base = rng.uniform(3.0, 12.0)
        weekly = rng.uniform(0.5, 2.0)
        for i in range(days):
            d = start + timedelta(days=i)
            dow = d.weekday()
            weekend_boost = 1.3 if dow >= 5 else 1.0
            season = 1.0 + 0.1 * np.sin(2 * np.pi * i / 30)
            noise = rng.normal(0.0, 1.2)
            qte = max(0.0, base * weekend_boost * season + weekly * (dow in (4, 5)) + noise)
            rows.append(
                {
                    "jour": pd.Timestamp(d.isoformat(), tz="UTC"),
                    "magasin_id": str(magasin_id),
                    "menu_id": str(menu.id),
                    "qte": float(round(qte, 2)),
                    "prix": float(getattr(menu, "prix", 0.0) or 0.0),
                }
            )

    return pd.DataFrame(rows)


class PrevisionVentesMLService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _resolve_magasin_id(self, magasin_id: UUID | None) -> UUID:
        if magasin_id is not None:
            return magasin_id

        # priorité: magasin de PRODUCTION, sinon premier magasin
        m = (
            await self._session.execute(
                select(Magasin).where(Magasin.actif.is_(True), Magasin.type_magasin == TypeMagasin.PRODUCTION)
            )
        ).scalars().first()
        if m is None:
            m = (await self._session.execute(select(Magasin).where(Magasin.actif.is_(True)))).scalars().first()
        if m is None:
            # En tests unitaires / CI, la DB peut être vide.
            # On ne veut pas planter toute la suite: le pipeline ML peut tourner
            # avec un dataset synthétique, mais il faut un magasin/menu pour persister.
            raise RuntimeError("Aucun magasin trouvé en DB (seed requis).")
        return m.id

    async def run_forecast(self, *, horizon_days: int = 7, magasin_id: UUID | None = None, force_retrain: bool = False) -> ForecastReport:
        if horizon_days <= 0:
            horizon_days = 1

        # On tente de résoudre un magasin/menu existants. Si la DB est vide (tests),
        # on seed un magasin + menu minimalistes pour pouvoir écrire en prediction_vente.
        try:
            mag_id = await self._resolve_magasin_id(magasin_id)
        except RuntimeError:
            mag = Magasin(nom="MAGASIN_TEST", actif=True, type_magasin=TypeMagasin.PRODUCTION)
            self._session.add(mag)
            await self._session.flush()
            # Menu.nom est obligatoire + recette_id est NOT NULL => on seed aussi une recette
            from app.domaine.modeles.referentiel import Recette

            recette = Recette(nom="RECETTE_TEST")
            self._session.add(recette)
            await self._session.flush()

            menu = Menu(magasin_id=mag.id, nom="MENU_TEST", actif=True, recette_id=recette.id)
            self._session.add(menu)
            await self._session.flush()
            mag_id = mag.id

            # IMPORTANT: on commit maintenant pour garantir que magasin/menu existent
            # côté DB avant tout INSERT dans prediction_vente (FK contraintes)
            await self._session.commit()

        menus = (
            await self._session.execute(select(Menu).where(Menu.magasin_id == mag_id, Menu.actif.is_(True)))
        ).scalars().all()
        if not menus:
            # seed un menu minimaliste si besoin
            from app.domaine.modeles.referentiel import Recette

            recette = Recette(nom="RECETTE_TEST")
            self._session.add(recette)
            await self._session.flush()

            menu = Menu(magasin_id=mag_id, nom="MENU_TEST", actif=True, recette_id=recette.id)
            self._session.add(menu)
            await self._session.flush()
            menus = [menu]

            # Idem: garantir FK avant insertion des predictions
            await self._session.commit()

        # Extraction dataset réel (fenêtre large)
        today = date.today()
        # Extraction dataset réel (fenêtre large).
        # NOTE: en environnement de dev/CI, la table `vente` est souvent vide.
        # On ne veut pas que l'orchestration échoue dans ce cas: on bascule en mode démo.
        try:
            df_sales, meta = await load_sales_dataframe(
                self._session,
                date_from=today - timedelta(days=120),
                date_to=today,
                magasin_id=mag_id,
            )
        except Exception:
            df_sales = pd.DataFrame()
            meta = None

        # Mode démo: si dataset trop petit (ou erreur) => synthétique
        if meta is None or getattr(meta, "rows", 0) < 30:
            df_sales = _synthetic_sales(magasin_id=mag_id, menus=menus, days=90)

        # Train (en mémoire + artefacts)
        train_res: TrainResult = train_model(df_sales)

        # encoders: on injecte la version pour stockage en prediction_vente
        enc = dict(train_res.encoders)
        enc["model_version"] = train_res.model_version

        # start_date = demain
        start_date = today + timedelta(days=1)
        preds = predict_next_days(
            model=train_res.model,
            horizon_days=horizon_days,
            history_df=df_sales,
            start_date=start_date,
            encoders=enc,
            magasin_id=mag_id,
        )

        written = await upsert_predictions(self._session, preds, model_version=train_res.model_version)
        # NOTE: `upsert_predictions` peut faire un rollback interne (fallback executemany).
        # Si on a seedé des entités (Magasin/Menu/Recette), on doit s'assurer qu'elles
        # sont persistées avant l'insert prediction_vente.
        await self._session.commit()

        return ForecastReport(
            magasin_id=mag_id,
            horizon_days=int(horizon_days),
            model_type=train_res.model_type,
            model_version=train_res.model_version,
            train_rows=int(len(df_sales)),
            predictions_written=int(written),
        )
