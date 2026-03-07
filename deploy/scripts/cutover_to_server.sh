#!/usr/bin/env bash
set -euo pipefail

# Cut over domain traffic to SERVER-hosted RUCAI runtime.
# Run on SERVER.
#
# Optional env:
#   APP_DIR                default: /srv/rucai
#   RUN_SYNC               default: 1 (UCloud -> server)
#   RUN_DEPLOY             default: 1
#   RUN_SWITCH             default: 1
#   RUN_DOMAIN_CHECK       default: 1
#   DOMAIN_HEALTH_URL      default: https://rucai.example.com/health
#
# Sync env forwarded to sync_ucloud_to_server.sh:
#   UCLOUD_SSH, UCLOUD_SSH_PORT, UCLOUD_APP_DIR, UCLOUD_UPLOAD_ROOT, ...

APP_DIR="${APP_DIR:-/srv/rucai}"
RUN_SYNC="${RUN_SYNC:-1}"
RUN_DEPLOY="${RUN_DEPLOY:-1}"
RUN_SWITCH="${RUN_SWITCH:-1}"
RUN_DOMAIN_CHECK="${RUN_DOMAIN_CHECK:-1}"
DOMAIN_HEALTH_URL="${DOMAIN_HEALTH_URL:-https://rucai.example.com/health}"
MAINTENANCE_WINDOW="${MAINTENANCE_WINDOW:-0}"

cd "$APP_DIR"

echo "[cutover_to_server] app_dir=$APP_DIR"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

# Default destination DB params from local app env when not explicitly provided.
export SERVER_DB_HOST="${SERVER_DB_HOST:-${DB_HOST:-localhost}}"
export SERVER_DB_PORT="${SERVER_DB_PORT:-${DB_PORT:-5432}}"
export SERVER_DB_NAME="${SERVER_DB_NAME:-${DB_NAME:-ppl_rag}}"
export SERVER_DB_USER="${SERVER_DB_USER:-${DB_USER:-ppl}}"
export SERVER_DB_PASSWORD="${SERVER_DB_PASSWORD:-${DB_PASSWORD:-}}"

if [[ "$MAINTENANCE_WINDOW" == "1" ]]; then
  echo "[prep] Enable maintenance window"
  ACTION=install_hook bash deploy/scripts/maintenance_banner.sh
  ACTION=enable bash deploy/scripts/maintenance_banner.sh
  trap 'ACTION=disable bash deploy/scripts/maintenance_banner.sh || true' EXIT
fi

if [[ "$RUN_SYNC" == "1" ]]; then
  echo "[1/4] Sync UCloud -> server"
  : "${UCLOUD_SSH:=ucloud@example-host}"
  : "${UCLOUD_SSH_PORT:=22}"
  : "${UCLOUD_APP_DIR:=/work/project/RUCAI}"
  : "${UCLOUD_UPLOAD_ROOT:=/work/project/RUCAI/data/uploads}"
  export UCLOUD_SSH UCLOUD_SSH_PORT UCLOUD_APP_DIR UCLOUD_UPLOAD_ROOT
  export SERVER_APP_DIR="${SERVER_APP_DIR:-$APP_DIR}"
  export SERVER_UPLOAD_ROOT="${SERVER_UPLOAD_ROOT:-$APP_DIR/data/uploads}"
  bash deploy/scripts/sync_ucloud_to_server.sh
else
  echo "[1/4] Skip sync (RUN_SYNC=0)"
fi

if [[ "$RUN_DEPLOY" == "1" ]]; then
  echo "[2/4] Start/refresh server runtime"
  SKIP_GIT=1 APP_DIR="$APP_DIR" BRANCH="${BRANCH:-main}" bash deploy/scripts/deploy_green.sh
else
  echo "[2/4] Skip deploy (RUN_DEPLOY=0)"
fi

if [[ "$RUN_SWITCH" == "1" ]]; then
  echo "[3/4] Switch nginx upstream to server app"
  MODE=server bash deploy/scripts/switch_domain_upstream.sh
else
  echo "[3/4] Skip upstream switch (RUN_SWITCH=0)"
fi

echo "[4/4] Health checks"
curl -fsS -m 8 http://127.0.0.1:8011/health && echo
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

echo "Cutover-to-server completed."
