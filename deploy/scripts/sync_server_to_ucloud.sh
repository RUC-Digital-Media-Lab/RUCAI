#!/usr/bin/env bash
set -euo pipefail

# Sync RUCAI from server (source) -> UCloud (destination).
# Run this script on UCLOUD.
#
# Required env:
#   SERVER_SSH            e.g. frede@212.27.13.34
#   SERVER_SSH_PORT       e.g. 2111
#   SERVER_APP_DIR        e.g. /home/frede/RUCAI
#   SERVER_UPLOAD_ROOT    e.g. /home/frede/RUCAI/data/uploads
#
# Optional source DB env:
#   SERVER_DB_HOST        default: localhost
#   SERVER_DB_PORT        default: 5432
#   SERVER_DB_NAME        default: ppl_rag
#   SERVER_DB_USER        default: ppl
#   SERVER_DB_PASSWORD    optional; prefer .pgpass on source
#
# Optional destination env (ucloud local):
#   UCLOUD_APP_DIR        default: /work/FrederikMøllerHenriksen#7467/projects/RUCAI
#   UCLOUD_UPLOAD_ROOT    default: /work/FrederikMøllerHenriksen#7467/projects/RUCAI/data/uploads
#   UCLOUD_DB_HOST        default: localhost
#   UCLOUD_DB_PORT        default: 5432
#   UCLOUD_DB_NAME        default: ppl_rag
#   UCLOUD_DB_USER        default: ppl
#   UCLOUD_DB_PASSWORD    optional; prefer .pgpass on destination
#
# Optional behavior:
#   SYNC_CODE             default: 1
#   SYNC_UPLOADS          default: 1
#   SYNC_DB               default: 1
#   USE_DEST_SUDO_RESTORE_FALLBACK default: 1

: "${SERVER_SSH:?Set SERVER_SSH, e.g. frede@212.27.13.34}"
: "${SERVER_SSH_PORT:?Set SERVER_SSH_PORT, e.g. 2111}"
: "${SERVER_APP_DIR:?Set SERVER_APP_DIR}"
: "${SERVER_UPLOAD_ROOT:?Set SERVER_UPLOAD_ROOT}"

SERVER_DB_HOST="${SERVER_DB_HOST:-localhost}"
SERVER_DB_PORT="${SERVER_DB_PORT:-5432}"
SERVER_DB_NAME="${SERVER_DB_NAME:-ppl_rag}"
SERVER_DB_USER="${SERVER_DB_USER:-ppl}"

UCLOUD_APP_DIR="${UCLOUD_APP_DIR:-/work/FrederikMøllerHenriksen#7467/projects/RUCAI}"
UCLOUD_UPLOAD_ROOT="${UCLOUD_UPLOAD_ROOT:-/work/FrederikMøllerHenriksen#7467/projects/RUCAI/data/uploads}"
UCLOUD_DB_HOST="${UCLOUD_DB_HOST:-localhost}"
UCLOUD_DB_PORT="${UCLOUD_DB_PORT:-5432}"
UCLOUD_DB_NAME="${UCLOUD_DB_NAME:-ppl_rag}"
UCLOUD_DB_USER="${UCLOUD_DB_USER:-ppl}"

SYNC_CODE="${SYNC_CODE:-1}"
SYNC_UPLOADS="${SYNC_UPLOADS:-1}"
SYNC_DB="${SYNC_DB:-1}"
USE_DEST_SUDO_RESTORE_FALLBACK="${USE_DEST_SUDO_RESTORE_FALLBACK:-1}"

ssh_opts=("-p" "$SERVER_SSH_PORT" "-o" "StrictHostKeyChecking=accept-new")
rsync_ssh="ssh ${ssh_opts[*]}"

escape_sq() {
  printf "%s" "$1" | sed "s/'/'\"'\"'/g"
}

echo "[sync_server_to_ucloud] Source: ${SERVER_SSH}:${SERVER_APP_DIR}"
echo "[sync_server_to_ucloud] Target: ${UCLOUD_APP_DIR}"

if [[ "$SYNC_CODE" == "1" ]]; then
  echo "[1/3] Sync project code (excluding env/data/runtime artifacts)"
  mkdir -p "$UCLOUD_APP_DIR"
  rsync -av --delete -e "$rsync_ssh" \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '.logs/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '.env' \
    --exclude 'data/uploads/' \
    "${SERVER_SSH}:${SERVER_APP_DIR}/" \
    "${UCLOUD_APP_DIR}/"
else
  echo "[1/3] Skip code sync (SYNC_CODE=0)"
fi

if [[ "$SYNC_UPLOADS" == "1" ]]; then
  echo "[2/3] Sync uploads"
  mkdir -p "$UCLOUD_UPLOAD_ROOT"
  rsync -av --delete -e "$rsync_ssh" \
    "${SERVER_SSH}:${SERVER_UPLOAD_ROOT}/" \
    "${UCLOUD_UPLOAD_ROOT}/"
else
  echo "[2/3] Skip upload sync (SYNC_UPLOADS=0)"
fi

if [[ "$SYNC_DB" == "1" ]]; then
  echo "[3/3] Sync DB via pg_dump -> pg_restore"
  src_pw_prefix=""
  if [[ -n "${SERVER_DB_PASSWORD:-}" ]]; then
    src_pw_prefix="PGPASSWORD='$(escape_sq "$SERVER_DB_PASSWORD")' "
  fi
  dst_pw_prefix=""
  if [[ -n "${UCLOUD_DB_PASSWORD:-}" ]]; then
    dst_pw_prefix="PGPASSWORD='$(escape_sq "$UCLOUD_DB_PASSWORD")' "
  fi

  src_cmd="${src_pw_prefix}pg_dump -Fc -h '$(escape_sq "$SERVER_DB_HOST")' -p '$(escape_sq "$SERVER_DB_PORT")' -U '$(escape_sq "$SERVER_DB_USER")' '$(escape_sq "$SERVER_DB_NAME")'"
  dst_cmd="${dst_pw_prefix}pg_restore --clean --if-exists -h '$(escape_sq "$UCLOUD_DB_HOST")' -p '$(escape_sq "$UCLOUD_DB_PORT")' -U '$(escape_sq "$UCLOUD_DB_USER")' -d '$(escape_sq "$UCLOUD_DB_NAME")'"

  set +e
  ssh "${ssh_opts[@]}" "$SERVER_SSH" "$src_cmd" | bash -lc "$dst_cmd"
  rc=$?
  set -e

  if [[ "$rc" -ne 0 ]]; then
    if [[ "$USE_DEST_SUDO_RESTORE_FALLBACK" == "1" ]]; then
      echo "Primary DB sync failed. Retrying destination restore via sudo -u postgres..."
      sudo_dst_cmd="sudo -n -u postgres pg_restore --clean --if-exists -d '$(escape_sq "$UCLOUD_DB_NAME")'"
      ssh "${ssh_opts[@]}" "$SERVER_SSH" "$src_cmd" | bash -lc "$sudo_dst_cmd"
    else
      echo "DB sync failed and fallback disabled (USE_DEST_SUDO_RESTORE_FALLBACK=0)."
      exit 1
    fi
  fi
else
  echo "[3/3] Skip DB sync (SYNC_DB=0)"
fi

echo "Done."
