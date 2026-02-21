#!/usr/bin/env bash
set -euo pipefail

# Sync RUCAI data from Blue (existing dev server) to Green (this VM).
# Run this script on Green.
#
# Required env vars:
#   BLUE_SSH          e.g. frede@212.27.13.34
#   BLUE_SSH_PORT     e.g. 2111
#   BLUE_DB_NAME      e.g. ppl_rag
#   BLUE_DB_USER      e.g. ppl
#   BLUE_UPLOAD_ROOT  e.g. /home/frede/RUCAI/data/uploads
#
# Optional env vars:
#   BLUE_DB_HOST      default: localhost
#   BLUE_DB_PORT      default: 5432
#   GREEN_DB_NAME     default: ppl_rag
#   GREEN_DB_USER     default: ppl
#   GREEN_DB_HOST     default: localhost
#   GREEN_DB_PORT     default: 5432
#   GREEN_UPLOAD_ROOT default: /home/ucloud/RUCAI/data/uploads

: "${BLUE_SSH:?Set BLUE_SSH, e.g. frede@212.27.13.34}"
: "${BLUE_SSH_PORT:?Set BLUE_SSH_PORT, e.g. 2111}"
: "${BLUE_DB_NAME:?Set BLUE_DB_NAME}"
: "${BLUE_DB_USER:?Set BLUE_DB_USER}"
: "${BLUE_UPLOAD_ROOT:?Set BLUE_UPLOAD_ROOT}"

BLUE_DB_HOST="${BLUE_DB_HOST:-localhost}"
BLUE_DB_PORT="${BLUE_DB_PORT:-5432}"
GREEN_DB_NAME="${GREEN_DB_NAME:-ppl_rag}"
GREEN_DB_USER="${GREEN_DB_USER:-ppl}"
GREEN_DB_HOST="${GREEN_DB_HOST:-localhost}"
GREEN_DB_PORT="${GREEN_DB_PORT:-5432}"
GREEN_UPLOAD_ROOT="${GREEN_UPLOAD_ROOT:-/home/ucloud/RUCAI/data/uploads}"

SSH_OPTS=("-p" "$BLUE_SSH_PORT" "-o" "StrictHostKeyChecking=accept-new")

echo "[1/3] Sync uploads from blue -> green"
mkdir -p "$GREEN_UPLOAD_ROOT"
rsync -av --delete -e "ssh ${SSH_OPTS[*]}" "$BLUE_SSH:$BLUE_UPLOAD_ROOT/" "$GREEN_UPLOAD_ROOT/"

echo "[2/3] Streaming pg_dump from blue -> pg_restore on green"
ssh "${SSH_OPTS[@]}" "$BLUE_SSH" \
  "pg_dump -Fc -h '$BLUE_DB_HOST' -p '$BLUE_DB_PORT' -U '$BLUE_DB_USER' '$BLUE_DB_NAME'" \
  | pg_restore --clean --if-exists -h "$GREEN_DB_HOST" -p "$GREEN_DB_PORT" -U "$GREEN_DB_USER" -d "$GREEN_DB_NAME"

echo "[3/3] Done. Recommended next step: restart API and run smoke checks."
