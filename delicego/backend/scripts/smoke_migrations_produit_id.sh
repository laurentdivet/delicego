#!/usr/bin/env bash
set -euo pipefail

# Smoke migrations on a clean DB and assert produit_id columns exist.
#
# Usage:
#   DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5433/delicego_smoke \
#     ./scripts/smoke_migrations_produit_id.sh

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL must be set to a clean database." >&2
  exit 1
fi

echo "Running alembic upgrade head on $DATABASE_URL"
alembic -c alembic.ini upgrade head

python - <<'PY'
import os, asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    url = os.environ['DATABASE_URL']
    engine = create_async_engine(url, pool_pre_ping=True)
    async with engine.connect() as conn:
        for t in ['lot','mouvement_stock']:
            ok = (await conn.execute(text('''
                select 1 from information_schema.columns
                where table_schema='public' and table_name=:t and column_name='produit_id'
            '''), {'t': t})).scalar_one_or_none() is not None
            print(t, 'produit_id:', ok)
            if not ok:
                raise SystemExit(2)
    await engine.dispose()

asyncio.run(main())
PY

echo "OK"
