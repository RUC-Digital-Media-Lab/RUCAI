#!/usr/bin/env bash
set -euo pipefail

# Sync RUCAI from UCloud (source) -> server (destination).
# Run this script on SERVER.
#
# Required env:
#   UCLOUD_SSH            e.g. ucloud@example-host
#   UCLOUD_SSH_PORT       e.g. 22
#   UCLOUD_APP_DIR        e.g. /work/project/RUCAI
#   UCLOUD_UPLOAD_ROOT    e.g. /work/.../RUCAI/data/uploads
#
# Optional source DB env:
#   UCLOUD_DB_HOST        default: localhost
#   UCLOUD_DB_PORT        default: 5432
#   UCLOUD_DB_NAME        default: ppl_rag
#   UCLOUD_DB_USER        default: ppl
#   UCLOUD_DB_PASSWORD    optional; prefer .pgpass on source
#
# Optional destination env (server local):
#   SERVER_APP_DIR        default: /srv/rucai
#   SERVER_UPLOAD_ROOT    default: /srv/rucai/data/uploads
#   SERVER_DB_HOST        default: localhost
#   SERVER_DB_PORT        default: 5432
#   SERVER_DB_NAME        default: ppl_rag
#   SERVER_DB_USER        default: ppl
#   SERVER_DB_PASSWORD    optional; prefer .pgpass on destination
#
# Optional behavior:
#   SYNC_CODE             default: 1
#   SYNC_UPLOADS          default: 1
#   SYNC_DB               default: 1
#   USE_SOURCE_SUDO_DUMP_FALLBACK default: 1
#   USE_DEST_SUDO_RESTORE_FALLBACK default: 1

: "${UCLOUD_SSH:?Set UCLOUD_SSH, e.g. ucloud@example-host}"
: "${UCLOUD_SSH_PORT:?Set UCLOUD_SSH_PORT, e.g. 22}"
: "${UCLOUD_APP_DIR:?Set UCLOUD_APP_DIR}"
: "${UCLOUD_UPLOAD_ROOT:?Set UCLOUD_UPLOAD_ROOT}"

UCLOUD_DB_HOST="${UCLOUD_DB_HOST:-localhost}"
UCLOUD_DB_PORT="${UCLOUD_DB_PORT:-5432}"
UCLOUD_DB_NAME="${UCLOUD_DB_NAME:-ppl_rag}"
UCLOUD_DB_USER="${UCLOUD_DB_USER:-ppl}"

SERVER_APP_DIR="${SERVER_APP_DIR:-/srv/rucai}"
SERVER_UPLOAD_ROOT="${SERVER_UPLOAD_ROOT:-/srv/rucai/data/uploads}"
SERVER_DB_HOST="${SERVER_DB_HOST:-localhost}"
SERVER_DB_PORT="${SERVER_DB_PORT:-5432}"
SERVER_DB_NAME="${SERVER_DB_NAME:-ppl_rag}"
SERVER_DB_USER="${SERVER_DB_USER:-ppl}"

SYNC_CODE="${SYNC_CODE:-1}"
SYNC_UPLOADS="${SYNC_UPLOADS:-1}"
SYNC_DB="${SYNC_DB:-1}"
USE_SOURCE_SUDO_DUMP_FALLBACK="${USE_SOURCE_SUDO_DUMP_FALLBACK:-1}"
USE_DEST_SUDO_RESTORE_FALLBACK="${USE_DEST_SUDO_RESTORE_FALLBACK:-1}"

ssh_opts=("-p" "$UCLOUD_SSH_PORT" "-o" "StrictHostKeyChecking=accept-new")
rsync_ssh="ssh ${ssh_opts[*]}"

escape_sq() {
  printf "%s" "$1" | sed "s/'/'\"'\"'/g"
}

echo "[sync_ucloud_to_server] Source: ${UCLOUD_SSH}:${UCLOUD_APP_DIR}"
echo "[sync_ucloud_to_server] Target: ${SERVER_APP_DIR}"

if [[ "$SYNC_CODE" == "1" ]]; then
  echo "[1/3] Sync project code (excluding env/data/runtime artifacts)"
  mkdir -p "$SERVER_APP_DIR"
  rsync -av --delete -e "$rsync_ssh" \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '.logs/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '.env' \
    --exclude 'data/uploads/' \
    "${UCLOUD_SSH}:${UCLOUD_APP_DIR}/" \
    "${SERVER_APP_DIR}/"
else
  echo "[1/3] Skip code sync (SYNC_CODE=0)"
fi

if [[ "$SYNC_UPLOADS" == "1" ]]; then
  echo "[2/3] Sync uploads"
  mkdir -p "$SERVER_UPLOAD_ROOT"
  rsync -av --delete -e "$rsync_ssh" \
    "${UCLOUD_SSH}:${UCLOUD_UPLOAD_ROOT}/" \
    "${SERVER_UPLOAD_ROOT}/"
else
  echo "[2/3] Skip upload sync (SYNC_UPLOADS=0)"
fi

if [[ "$SYNC_DB" == "1" ]]; then
  echo "[3/3] Sync DB via pg_dump -> pg_restore"
  src_pw_prefix=""
  if [[ -n "${UCLOUD_DB_PASSWORD:-}" ]]; then
    src_pw_prefix="PGPASSWORD='$(escape_sq "$UCLOUD_DB_PASSWORD")' "
  fi
  dst_pw_prefix=""
  if [[ -n "${SERVER_DB_PASSWORD:-}" ]]; then
    dst_pw_prefix="PGPASSWORD='$(escape_sq "$SERVER_DB_PASSWORD")' "
  fi

  src_cmd="${src_pw_prefix}pg_dump -w -Fc -h '$(escape_sq "$UCLOUD_DB_HOST")' -p '$(escape_sq "$UCLOUD_DB_PORT")' -U '$(escape_sq "$UCLOUD_DB_USER")' '$(escape_sq "$UCLOUD_DB_NAME")'"
  dst_cmd="${dst_pw_prefix}pg_restore --exit-on-error --clean --if-exists -h '$(escape_sq "$SERVER_DB_HOST")' -p '$(escape_sq "$SERVER_DB_PORT")' -U '$(escape_sq "$SERVER_DB_USER")' -d '$(escape_sq "$SERVER_DB_NAME")'"

  active_src_cmd="$src_cmd"

  set +e
  ssh "${ssh_opts[@]}" "$UCLOUD_SSH" "$active_src_cmd" | bash -lc "$dst_cmd"
  rc=$?
  set -e

  if [[ "$rc" -ne 0 ]]; then
    if [[ "$USE_SOURCE_SUDO_DUMP_FALLBACK" == "1" ]]; then
      echo "Primary DB sync failed. Retrying source dump via sudo -u postgres..."
      sudo_src_cmd="sudo -n -u postgres pg_dump -Fc -d '$(escape_sq "$UCLOUD_DB_NAME")'"
      active_src_cmd="$sudo_src_cmd"
      set +e
      ssh "${ssh_opts[@]}" "$UCLOUD_SSH" "$active_src_cmd" | bash -lc "$dst_cmd"
      rc=$?
      set -e
    else
      echo "DB sync failed and fallback disabled (USE_SOURCE_SUDO_DUMP_FALLBACK=0)."
      exit 1
    fi
  fi

  if [[ "$rc" -ne 0 ]]; then
    if [[ "$USE_DEST_SUDO_RESTORE_FALLBACK" == "1" ]]; then
      echo "Restore failed. Retrying destination restore via sudo -u postgres..."
      sudo_dst_cmd="sudo -u postgres pg_restore --exit-on-error --clean --if-exists -d '$(escape_sq "$SERVER_DB_NAME")'"
      ssh "${ssh_opts[@]}" "$UCLOUD_SSH" "$active_src_cmd" | bash -lc "$sudo_dst_cmd"
    else
      echo "DB restore failed and fallback disabled (USE_DEST_SUDO_RESTORE_FALLBACK=0)."
      exit 1
    fi
  fi
else
  echo "[3/3] Skip DB sync (SYNC_DB=0)"
fi

echo "Done."
