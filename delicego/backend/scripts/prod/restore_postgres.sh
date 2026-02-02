#!/usr/bin/env bash

set -euo pipefail

# Restore PostgreSQL simple (pg_restore) depuis un dump pg_dump --format=custom.
#
# Usage:
#   ./restore_postgres.sh --file /path/to/file.dump.gz [--drop-create] [--target-db DB]
#
# Variables d'env optionnelles:
#   PGHOST, PGPORT, PGUSER, PGPASSWORD

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

FILE=""
DROP_CREATE="0"
TARGET_DB="${PGDATABASE:-delicego}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --file)
      FILE="$2"; shift 2;;
    --target-db)
      TARGET_DB="$2"; shift 2;;
    --drop-create)
      DROP_CREATE="1"; shift 1;;
    -h|--help)
      sed -n '1,160p' "$0"; exit 0;;
    *)
      echo "Argument inconnu: $1" >&2
      exit 2;;
  esac
done

if [[ -z "${FILE}" ]]; then
  echo "--file est obligatoire" >&2
  exit 2
fi

if [[ ! -f "${FILE}" ]]; then
  echo "Fichier introuvable: ${FILE}" >&2
  exit 2
fi

HOST="${PGHOST:-localhost}"
PORT="${PGPORT:-5433}"
USER="${PGUSER:-delicego}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "[restore] host=${HOST} port=${PORT} user=${USER} db=${TARGET_DB}"
echo "[restore] file=${FILE}"

# Vérif checksum si fichier .sha256 adjacent
if [[ -f "${FILE}.sha256" ]]; then
  echo "[restore] verification checksum (.sha256 trouvé)"
  (cd "$(dirname "${FILE}")" && shasum -a 256 -c "$(basename "${FILE}.sha256")")
fi

echo "[restore] decompression"
gunzip -c "${FILE}" > "${TMP_DIR}/dump.dump"

if [[ "${DROP_CREATE}" == "1" ]]; then
  echo "[restore] mode drop+create (ATTENTION: destructive)"
  # Termine les connexions actives, drop, recreate
  psql -h "${HOST}" -p "${PORT}" -U "${USER}" -d postgres \
    -v ON_ERROR_STOP=1 \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${TARGET_DB}' AND pid <> pg_backend_pid();" \
    -c "DROP DATABASE IF EXISTS \"${TARGET_DB}\";" \
    -c "CREATE DATABASE \"${TARGET_DB}\";"
fi

echo "[restore] pg_restore"
pg_restore \
  --no-owner \
  --no-privileges \
  --host "${HOST}" \
  --port "${PORT}" \
  --username "${USER}" \
  --dbname "${TARGET_DB}" \
  --exit-on-error \
  "${TMP_DIR}/dump.dump"

echo "[restore] OK"
