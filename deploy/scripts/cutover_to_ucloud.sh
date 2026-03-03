#!/usr/bin/env bash
set -euo pipefail

# Cut over domain traffic back to UCLOUD-hosted RUCAI runtime via reverse tunnel.
# Run on SERVER.
#
# Optional env:
#   APP_DIR                default: /home/frede/RUCAI
#   UCLOUD_SSH             default: ucloud@ssh.cloud.sdu.dk
#   UCLOUD_SSH_PORT        default: 2485
#   UCLOUD_APP_DIR         default: /work/FrederikMøllerHenriksen#7467/projects/RUCAI
#   RUN_SYNC               default: 1 (server -> ucloud)
#   RUN_RESUME             default: 1
#   RUN_SWITCH             default: 1
#   RUN_DOMAIN_CHECK       default: 1
#   DOMAIN_HEALTH_URL      default: https://www.rucai.dk/health
#
# Notes:
# - Supports changed UCloud SSH port by setting UCLOUD_SSH_PORT.
# - Requires key/auth from UCloud to server for reverse tunnel startup.

APP_DIR="${APP_DIR:-/home/frede/RUCAI}"
UCLOUD_SSH="${UCLOUD_SSH:-ucloud@ssh.cloud.sdu.dk}"
UCLOUD_SSH_PORT="${UCLOUD_SSH_PORT:-2485}"
UCLOUD_APP_DIR="${UCLOUD_APP_DIR:-/work/FrederikMøllerHenriksen#7467/projects/RUCAI}"

RUN_SYNC="${RUN_SYNC:-1}"
RUN_RESUME="${RUN_RESUME:-1}"
RUN_SWITCH="${RUN_SWITCH:-1}"
RUN_DOMAIN_CHECK="${RUN_DOMAIN_CHECK:-1}"
DOMAIN_HEALTH_URL="${DOMAIN_HEALTH_URL:-https://www.rucai.dk/health}"
MAINTENANCE_WINDOW="${MAINTENANCE_WINDOW:-0}"

cd "$APP_DIR"

echo "[cutover_to_ucloud] app_dir=$APP_DIR"
echo "[cutover_to_ucloud] ucloud=${UCLOUD_SSH}:${UCLOUD_SSH_PORT} app_dir=${UCLOUD_APP_DIR}"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

# Default source DB params from local server app env when not explicitly provided.
SERVER_DB_HOST="${SERVER_DB_HOST:-${DB_HOST:-localhost}}"
SERVER_DB_PORT="${SERVER_DB_PORT:-${DB_PORT:-5432}}"
SERVER_DB_NAME="${SERVER_DB_NAME:-${DB_NAME:-ppl_rag}}"
SERVER_DB_USER="${SERVER_DB_USER:-${DB_USER:-ppl}}"
SERVER_DB_PASSWORD="${SERVER_DB_PASSWORD:-${DB_PASSWORD:-}}"

if [[ "$MAINTENANCE_WINDOW" == "1" ]]; then
  echo "[prep] Enable maintenance window"
  ACTION=install_hook bash deploy/scripts/maintenance_banner.sh
  ACTION=enable bash deploy/scripts/maintenance_banner.sh
  trap 'ACTION=disable bash deploy/scripts/maintenance_banner.sh || true' EXIT
fi

if [[ "$RUN_SYNC" == "1" ]]; then
  echo "[1/4] Sync server -> ucloud"
  esc_server_db_password="$(printf %q "${SERVER_DB_PASSWORD}")"
  ssh -p "$UCLOUD_SSH_PORT" "$UCLOUD_SSH" "
    set -e
    cd '$UCLOUD_APP_DIR'
    export SERVER_SSH='${SERVER_SSH:-frede@212.27.13.34}'
    export SERVER_SSH_PORT='${SERVER_SSH_PORT:-2111}'
    export SERVER_APP_DIR='${SERVER_APP_DIR:-/home/frede/RUCAI}'
    export SERVER_UPLOAD_ROOT='${SERVER_UPLOAD_ROOT:-/home/frede/RUCAI/data/uploads}'
    export SERVER_DB_HOST='${SERVER_DB_HOST}'
    export SERVER_DB_PORT='${SERVER_DB_PORT}'
    export SERVER_DB_NAME='${SERVER_DB_NAME}'
    export SERVER_DB_USER='${SERVER_DB_USER}'
    export SERVER_DB_PASSWORD=${esc_server_db_password}
    export UCLOUD_APP_DIR='${UCLOUD_APP_DIR}'
    export UCLOUD_UPLOAD_ROOT='${UCLOUD_UPLOAD_ROOT:-$UCLOUD_APP_DIR/data/uploads}'
    bash deploy/scripts/sync_server_to_ucloud.sh
  "
else
  echo "[1/4] Skip sync (RUN_SYNC=0)"
fi

if [[ "$RUN_RESUME" == "1" ]]; then
  echo "[2/4] Resume ucloud runtime + tunnel"
  ssh -p "$UCLOUD_SSH_PORT" "$UCLOUD_SSH" "
    set -e
    cd '$UCLOUD_APP_DIR'
    bash deploy/scripts/resume_rucai.sh
  "
else
  echo "[2/4] Skip ucloud resume (RUN_RESUME=0)"
fi

if [[ "$RUN_SWITCH" == "1" ]]; then
  echo "[3/4] Switch nginx upstream to ucloud tunnel"
  MODE=ucloud bash deploy/scripts/switch_domain_upstream.sh
else
  echo "[3/4] Skip upstream switch (RUN_SWITCH=0)"
fi

echo "[4/4] Health checks"
curl -fsS -m 8 http://127.0.0.1:18011/health && echo
if [[ "$RUN_DOMAIN_CHECK" == "1" ]]; then
  if [[ "$MAINTENANCE_WINDOW" == "1" ]]; then
    echo "Domain check deferred until maintenance is disabled."
  else
    curl -fsS -m 12 "$DOMAIN_HEALTH_URL" && echo
  fi
fi

if [[ "$MAINTENANCE_WINDOW" == "1" ]]; then
  ACTION=disable bash deploy/scripts/maintenance_banner.sh
  trap - EXIT
  if [[ "$RUN_DOMAIN_CHECK" == "1" ]]; then
    curl -fsS -m 12 "$DOMAIN_HEALTH_URL" && echo
  fi
fi

echo "Cutover-to-ucloud completed."
