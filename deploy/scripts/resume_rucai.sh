#!/usr/bin/env bash
set -euo pipefail

# Resume RUCAI runtime after VM reboot/job restart.
# Reuses existing .env and starts app + selected access mode + monitor.
#
# Usage:
#   APP_DIR="/work/.../RUCAI" bash deploy/scripts/resume_rucai.sh

APP_DIR="${APP_DIR:-/work/FrederikMøllerHenriksen#7467/projects/RUCAI}"
BRANCH="${BRANCH:-main}"
SKIP_GIT="${SKIP_GIT:-1}"

cd "$APP_DIR"

if [[ ! -f .env ]]; then
  echo "Missing .env in $APP_DIR. Create it first."
  exit 1
fi

set -a
source .env
set +a

echo "[1/4] Deploy/start runtime"
SKIP_GIT="$SKIP_GIT" APP_DIR="$APP_DIR" BRANCH="$BRANCH" bash deploy/scripts/deploy_green.sh

echo "[2/4] Local health"
curl -fsS "http://127.0.0.1:${APP_PORT:-8011}/health" && echo

echo "[3/4] Sessions"
tmux ls || true

echo "[4/4] Access checks"
case "${ACCESS_MODE:-none}" in
  reverse_ssh)
    bash deploy/scripts/reverse_tunnel.sh status || true
    ;;
  cloudflare)
    bash deploy/scripts/cloudflare_tunnel.sh status || true
    bash deploy/scripts/cloudflare_tunnel.sh url || true
    ;;
  *)
    echo "ACCESS_MODE=${ACCESS_MODE:-none} (no public tunnel check)"
    ;;
esac

if [[ -n "${PUBLIC_BASE_URL:-}" ]]; then
  echo "PUBLIC_BASE_URL=${PUBLIC_BASE_URL}"
fi

