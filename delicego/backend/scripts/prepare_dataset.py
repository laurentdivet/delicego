import asyncio
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.configuration import parametres_application

SQL = """
SELECT
  jour,
  magasin_id,
  magasin,
  menu_id,
  menu,
  qte
FROM v_ventes_jour_menu
ORDER BY jour, magasin, menu;
"""

async def load_dataset() -> pd.DataFrame:
    engine = create_async_engine(parametres_application.url_base_donnees, pool_pre_ping=True)
    async with engine.connect() as conn:
        res = await conn.execute(text(SQL))
        rows = res.mappings().all()
    await engine.dispose()
    return pd.DataFrame(rows)

async def main() -> None:
    df = await load_dataset()

    # features de base (sans météo)
    df["jour"] = pd.to_datetime(df["jour"])
    df["dow"] = df["jour"].dt.dayofweek
    df["weekend"] = (df["dow"] >= 5).astype(int)
    df["day"] = df["jour"].dt.day
    df["month"] = df["jour"].dt.month
    df["magasin_cat"] = df["magasin"].astype("category").cat.codes
    df["menu_cat"] = df["menu"].astype("category").cat.codes

    # lags (utile)
    df = df.sort_values(["magasin_id", "menu_id", "jour"])
    df["lag_1"] = df.groupby(["magasin_id", "menu_id"])["qte"].shift(1).fillna(0)
    df["lag_7"] = df.groupby(["magasin_id", "menu_id"])["qte"].shift(7).fillna(0)

    # debug
    print(df.head(20))
    print("rows=", len(df))

if __name__ == "__main__":
    asyncio.run(main())
