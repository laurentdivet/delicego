"""Validation CI reproductibilité DB (migrations + seed + checks Postgres).

Objectif:
- être appelé depuis GitHub Actions
- centraliser la logique pour éviter de dupliquer des bouts de bash dans le workflow

Contrats:
- DATABASE_URL doit être défini (asyncpg) ex:
    postgresql+asyncpg://delicego:delicego@localhost:5432/delicego
- Pas de downgrade en CI (migration zzzz non downgradable)
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class DbConn:
    # Async SQLAlchemy URL (utilisé par Alembic/env.py + scripts)
    database_url: str
    # DSN psql (sans driver sqlalchemy) pour exécuter les checks SQL via psql
    psql_url: str


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print(f"\n[ci] $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, env=env)


def _must_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _derive_psql_url(database_url: str) -> str:
    # Convertit postgresql+asyncpg:// -> postgresql://
    # (psql ne comprend pas le préfixe SQLAlchemy)
    if database_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+asyncpg://")
    if database_url.startswith("postgresql://"):
        return database_url
    # fallback: on laisse tel quel pour rendre l'erreur explicite côté psql
    return database_url


def _psql_scalar(*, psql_url: str, sql: str) -> int:
    # -X: pas de ~/.psqlrc
    # -tA: tuples only + unaligned => valeur brute
    out = subprocess.check_output(
        [
            "psql",
            "-X",
            psql_url,
            "-v",
            "ON_ERROR_STOP=1",
            "-tA",
            "-c",
            sql,
        ],
        text=True,
    ).strip()
    try:
        return int(out)
    except ValueError as e:
        raise RuntimeError(f"Expected integer output from psql. Got: {out!r} for SQL: {sql}") from e


def main() -> int:
    database_url = _must_env("DATABASE_URL")
    conn = DbConn(database_url=database_url, psql_url=_derive_psql_url(database_url))

    print("[ci] Python:")
    _run([sys.executable, "-V"])
    print("[ci] DATABASE_URL is set (redacted password in logs)")
    # éviter de logguer un secret si un jour on change la conf
    print("[ci] DATABASE_URL:", conn.database_url.replace(":delicego@", ":***@"))

    # 1) migrations
    _run(["alembic", "-c", "alembic.ini", "upgrade", "head"], env={**os.environ, "DATABASE_URL": conn.database_url})

    # Le script est prévu pour tourner en GitHub Actions (Postgres service). En local,
    # il est normal de ne pas avoir Postgres sur localhost:5432.

    # 2) checks Postgres: aucun type USER-DEFINED, aucun enum natif dans public
    user_defined = _psql_scalar(
        psql_url=conn.psql_url,
        sql=(
            "SELECT count(*) "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND data_type='USER-DEFINED';"
        ),
    )
    if user_defined != 0:
        raise RuntimeError(f"CI check failed: USER-DEFINED columns != 0 (got {user_defined})")
    print("[ci][OK] USER-DEFINED columns = 0")

    enum_count = _psql_scalar(
        psql_url=conn.psql_url,
        sql="SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE t.typtype='e' AND n.nspname='public';",
    )
    if enum_count != 0:
        raise RuntimeError(f"CI check failed: pg_enum(public) != 0 (got {enum_count})")
    print("[ci][OK] pg enum types in public = 0")

    # 3) seed minimal (sans XLSX)
    _run(
        [sys.executable, "-m", "scripts.seed_all", "--apply"],
        env={**os.environ, "DATABASE_URL": conn.database_url},
    )

    # 4) Forecast smoke (doit écrire prediction_vente)
    _run(
        [sys.executable, "scripts/run_forecast.py", "--horizon", "7"],
        env={**os.environ, "DATABASE_URL": conn.database_url},
    )
    pred_count = _psql_scalar(psql_url=conn.psql_url, sql="SELECT count(*) FROM prediction_vente;")
    if pred_count <= 0:
        raise RuntimeError(f"CI check failed: prediction_vente count must be > 0 (got {pred_count})")
    print(f"[ci][OK] prediction_vente rows = {pred_count}")

    print("\n[ci][SUCCESS] migrations + checks + seed + forecast OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
