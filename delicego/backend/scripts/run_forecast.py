from __future__ import annotations

import argparse
import asyncio
import os
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.prevision_ventes_ml_service import PrevisionVentesMLService


def _display_db_target(database_url: str) -> str:
    """Return DB target without secrets: host:port/dbname."""

    p = urlparse(database_url)
    host = p.hostname or "?"
    port = p.port or 5432
    dbname = (p.path or "").lstrip("/") or "?"
    return f"{host}:{port}/{dbname}"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DeliceGo - run forecast (ML)")
    p.add_argument("--horizon", type=int, default=7)
    p.add_argument("--magasin-id", type=str, default=None)
    p.add_argument("--force-retrain", action="store_true")
    p.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Override DATABASE_URL (SQLAlchemy async URL, ex: postgresql+asyncpg://...)",
    )
    return p.parse_args()


async def main_async() -> int:
    args = _parse_args()

    # DATABASE_URL must be explicit to avoid accidentally targeting a different DB.
    url_db = args.database_url or os.getenv("DATABASE_URL")
    if not url_db:
        print("[run_forecast][ERROR] Missing DATABASE_URL.")
        print("Set env var DATABASE_URL or pass --database-url.")
        print("Example:")
        print("  DATABASE_URL='postgresql+asyncpg://delicego:delicego@localhost:5432/delicego' \\")
        print("  python scripts/run_forecast.py --horizon 7")
        return 2

    print(f"[run_forecast] Using database: {_display_db_target(url_db)}")

    engine = create_async_engine(url_db, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    magasin_id = UUID(args.magasin_id) if args.magasin_id else None
    async with Session() as session:
        svc = PrevisionVentesMLService(session)
        report = await svc.run_forecast(
            horizon_days=int(args.horizon),
            magasin_id=magasin_id,
            force_retrain=bool(args.force_retrain),
        )

        # Invariant: forecast granularity is MENU-level => menu_id must never be NULL.
        from sqlalchemy import text

        r = await session.execute(
            text(
                """
SELECT count(*)
FROM prediction_vente
WHERE magasin_id = :magasin_id
  AND menu_id IS NULL;
"""
            ),
            {"magasin_id": str(report.magasin_id)},
        )
        null_menu = int(r.scalar() or 0)
        if null_menu:
            raise RuntimeError(
                f"[run_forecast] Invariant violated: {null_menu} prediction_vente rows have NULL menu_id. "
                "Forecast granularity is MENU-level (menu_id is required)."
            )

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
