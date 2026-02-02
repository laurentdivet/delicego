from __future__ import annotations

import argparse
import asyncio
import os
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.services.prevision_ventes_ml_service import PrevisionVentesMLService


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DeliceGo - run forecast (ML)")
    p.add_argument("--horizon", type=int, default=7)
    p.add_argument("--magasin-id", type=str, default=None)
    p.add_argument("--force-retrain", action="store_true")
    return p.parse_args()


async def main_async() -> int:
    args = _parse_args()
    url_db = os.getenv("DATABASE_URL") or parametres_application.url_base_donnees
    engine = create_async_engine(url_db, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    magasin_id = UUID(args.magasin_id) if args.magasin_id else None
    async with Session() as session:
        svc = PrevisionVentesMLService(session)
        report = await svc.run_forecast(horizon_days=int(args.horizon), magasin_id=magasin_id, force_retrain=bool(args.force_retrain))

    await engine.dispose()
    print("[run_forecast] OK")
    print(f"  magasin_id={report.magasin_id}")
    print(f"  horizon_days={report.horizon_days}")
    print(f"  model_type={report.model_type}")
    print(f"  model_version={report.model_version}")
    print(f"  train_rows={report.train_rows}")
    print(f"  predictions_written={report.predictions_written}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
