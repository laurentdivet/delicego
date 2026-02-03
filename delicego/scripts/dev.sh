#!/usr/bin/env bash
set -euo pipefail

# One-command dev launcher for DéliceGo
# - starts Postgres via docker compose
# - waits for readiness (pg_isready inside container)
# - resets DB (terminate connections + drop/create)
# - runs alembic migrations + seeds
# - launches backend + frontend in parallel with clean shutdown

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
POSTGRES_SERVICE="postgres"
DB_NAME="delicego"
DB_USER="delicego"
DB_PASSWORD="delicego"
DB_HOST="localhost"
DB_PORT="5433"

BACKEND_PORT="8001"
FRONTEND_PORT="5173"

TOTAL_STEPS=8
STEP=0

log_step() {
  STEP=$((STEP + 1))
  printf '\n[%s/%s] %s\n' "$STEP" "$TOTAL_STEPS" "$*"
}

die() {
  printf '\n[ERROR] %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Commande requise introuvable: $1"
}

check_docker() {
  log_step "Vérification Docker (docker + compose)"

  need_cmd docker

  if ! docker info >/dev/null 2>&1; then
    die "Docker ne semble pas démarré ou accessible (docker info a échoué)."
  fi

  # Prefer the v2 plugin (`docker compose`). Fallback to v1 (`docker-compose`) if present.
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    die "Docker Compose introuvable. Installe Docker Desktop (compose v2) ou docker-compose."
  fi

  if [[ ! -f "$COMPOSE_FILE" ]]; then
    die "docker-compose.yml introuvable à la racine: $COMPOSE_FILE"
  fi
}

warn_node_version() {
  # Bonus: warn only (non-blocking) if node < 20.19
  if ! command -v node >/dev/null 2>&1; then
    printf "[WARN] Node.js non trouvé. Le frontend ne pourra pas démarrer (prérequis: Node).\n" >&2
    return 0
  fi

  local v major minor
  v="$(node -v 2>/dev/null || true)"
  v="${v#v}"
  major="${v%%.*}"
  minor="${v#*.}"; minor="${minor%%.*}"

  # numeric guard
  if [[ "$major" =~ ^[0-9]+$ ]] && [[ "$minor" =~ ^[0-9]+$ ]]; then
    if (( major < 20 )) || { (( major == 20 )) && (( minor < 19 )); }; then
      printf "[WARN] Version Node détectée: v%s (recommandé: >= 20.19).\n" "$v" >&2
    fi
  fi
}

compose_up_postgres() {
  log_step "Démarrage Postgres (docker compose up -d ${POSTGRES_SERVICE})"
  (cd "$ROOT_DIR" && "${COMPOSE[@]}" up -d "$POSTGRES_SERVICE")
}

postgres_container_id() {
  (cd "$ROOT_DIR" && "${COMPOSE[@]}" ps -q "$POSTGRES_SERVICE")
}

wait_postgres_ready() {
  log_step "Attente Postgres prêt (timeout 30s via pg_isready dans le container)"

  local cid start now
  cid="$(postgres_container_id)"
  [[ -n "$cid" ]] || die "Impossible de trouver le container du service '${POSTGRES_SERVICE}'."

  start="$(date +%s)"
  while true; do
    if docker exec "$cid" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
      printf "Postgres est prêt.\n"
      return 0
    fi

    now="$(date +%s)"
    if (( now - start >= 30 )); then
      die "Timeout: Postgres n'est pas prêt après 30s."
    fi
    sleep 1
  done
}

reset_database() {
  log_step "Reset DB '${DB_NAME}' (terminate connexions + drop/create) via psql dans le container"

  local cid
  cid="$(postgres_container_id)"
  [[ -n "$cid" ]] || die "Impossible de trouver le container du service '${POSTGRES_SERVICE}'."

  # Everything is executed inside the container: no local psql required.
  docker exec -i "$cid" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d postgres <<SQL
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS "${DB_NAME}";
CREATE DATABASE "${DB_NAME}" OWNER "${DB_USER}";
SQL
}

run_migrations_and_seed() {
  log_step "Migrations Alembic + seed (DATABASE_URL requis par Alembic)"

  export DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

  (cd "$ROOT_DIR/backend" && alembic -c alembic.ini upgrade head)
  (cd "$ROOT_DIR/backend" && python -m scripts.seed_all --apply)
  (cd "$ROOT_DIR/backend" && python -m scripts.seed_demo)
}

export_dev_env() {
  log_step "Export variables dev"
  export IMPACT_DASHBOARD_PUBLIC_DEV=1
  printf "IMPACT_DASHBOARD_PUBLIC_DEV=1\n"
}

install_frontend_deps_if_needed() {
  if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
    printf "frontend/node_modules absent → npm install\n"
    (cd "$ROOT_DIR/frontend" && npm install)
  fi
}

start_servers() {
  log_step "Lancement backend + frontend (Ctrl+C pour arrêter proprement)"

  warn_node_version

  # Backend
  (cd "$ROOT_DIR/backend" && uvicorn app.main:app --reload --port "$BACKEND_PORT") &
  BACKEND_PID=$!

  # Frontend
  install_frontend_deps_if_needed
  (cd "$ROOT_DIR/frontend" && npm run dev -- --port "$FRONTEND_PORT") &
  FRONTEND_PID=$!

  cleanup() {
    printf "\nArrêt (SIGINT/SIGTERM) → kill backend(%s) frontend(%s)\n" "$BACKEND_PID" "$FRONTEND_PID" >&2
    kill "$BACKEND_PID" "$FRONTEND_PID" >/dev/null 2>&1 || true
    wait "$BACKEND_PID" "$FRONTEND_PID" >/dev/null 2>&1 || true
  }
  trap cleanup INT TERM

  printf "\nServices en cours:\n- backend  : http://localhost:%s\n- frontend : http://localhost:%s\n- postgres : localhost:%s\n" \
    "$BACKEND_PORT" "$FRONTEND_PORT" "$DB_PORT"

  # Wait until one exits (then cleanup will trigger on signals; otherwise we just wait both)
  wait "$BACKEND_PID" "$FRONTEND_PID"
}

main() {
  check_docker
  compose_up_postgres
  wait_postgres_ready
  reset_database
  run_migrations_and_seed
  export_dev_env
  start_servers
}

main "$@"
