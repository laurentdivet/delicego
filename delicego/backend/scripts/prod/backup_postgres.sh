#!/usr/bin/env bash

set -euo pipefail

# Backup PostgreSQL simple (pg_dump) + rotation.
#
# Usage:
#   ./backup_postgres.sh [--output-dir DIR] [--keep N]
#
# Variables d'env optionnelles (si non passées en args):
#   PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

OUTPUT_DIR_DEFAULT="${ROOT_DIR}/backups/postgres"
KEEP_DEFAULT="14"

OUTPUT_DIR="${OUTPUT_DIR_DEFAULT}"
KEEP="${KEEP_DEFAULT}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="$2"; shift 2;;
    --keep)
      KEEP="$2"; shift 2;;
    -h|--help)
      sed -n '1,120p' "$0"; exit 0;;
    *)
      echo "Argument inconnu: $1" >&2
      exit 2;;
  esac
done

mkdir -p "${OUTPUT_DIR}"

TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
HOST="${PGHOST:-localhost}"
PORT="${PGPORT:-5433}"
USER="${PGUSER:-delicego}"
DB="${PGDATABASE:-delicego}"

OUT_FILE="${OUTPUT_DIR}/delicego_${DB}_${TIMESTAMP}.dump"
OUT_FILE_GZ="${OUT_FILE}.gz"
OUT_FILE_SHA="${OUT_FILE_GZ}.sha256"

echo "[backup] host=${HOST} port=${PORT} user=${USER} db=${DB}"
echo "[backup] output=${OUT_FILE_GZ}"

# format custom pour permettre un restore flexible
pg_dump \
  --format=custom \
  --no-owner \
  --no-privileges \
  --host "${HOST}" \
  --port "${PORT}" \
  --username "${USER}" \
  --file "${OUT_FILE}" \
  "${DB}"

gzip -f "${OUT_FILE}"

# checksum simple pour détecter corruption/transfer incomplet
(cd "${OUTPUT_DIR}" && shasum -a 256 "$(basename "${OUT_FILE_GZ}")" > "$(basename "${OUT_FILE_SHA}")")

echo "[backup] checksum=$(cat "${OUT_FILE_SHA}")"

# Rotation : conserve les N plus récents (sur les .dump.gz)
set +e
TO_DELETE=$(ls -1t "${OUTPUT_DIR}"/*.dump.gz 2>/dev/null | tail -n "+$((KEEP+1))")
set -e

if [[ -n "${TO_DELETE:-}" ]]; then
  echo "[backup] rotation: suppression des anciens backups"
  # shellcheck disable=SC2086
  rm -f ${TO_DELETE}
  # supprimer aussi les checksums associés si présents
  for f in ${TO_DELETE}; do
    rm -f "${f}.sha256" || true
  done
fi

echo "[backup] OK"
