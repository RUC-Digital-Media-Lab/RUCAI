#!/usr/bin/env bash
set -euo pipefail

# Deploy RUCAI on Green VM.
# Run on Green VM as a user with sudo rights.

APP_DIR="${APP_DIR:-/home/frede/RUCAI}"
BRANCH="${BRANCH:-release/gpu-pilot}"
PORT="${PORT:-8011}"
APP_PORT="${APP_PORT:-$PORT}"
SERVICE_NAME="${SERVICE_NAME:-rucai-api}"
SERVICE_USER="${SERVICE_USER:-frede}"
SERVICE_GROUP="${SERVICE_GROUP:-frede}"
SKIP_GIT="${SKIP_GIT:-0}"
RUNNER_MODE="${RUNNER_MODE:-auto}"
TMUX_SESSION="${TMUX_SESSION:-rucai-api}"
ACCESS_MODE="${ACCESS_MODE:-none}"
ENABLE_CLOUDFLARE_TUNNEL="${ENABLE_CLOUDFLARE_TUNNEL:-0}"
ENABLE_OPS_MONITOR="${ENABLE_OPS_MONITOR:-1}"

render_systemd_unit() {
  local destination="$1"
  APP_DIR="$APP_DIR" \
  SERVICE_USER="$SERVICE_USER" \
  SERVICE_GROUP="$SERVICE_GROUP" \
  APP_PORT="$APP_PORT" \
  python3 - "$destination" <<'PY'
from pathlib import Path
import os
import sys

destination = Path(sys.argv[1])
template = Path("deploy/systemd/rucai-api.service").read_text()
app_dir = Path(os.environ["APP_DIR"])
replacements = {
    "__SERVICE_USER__": os.environ["SERVICE_USER"],
    "__SERVICE_GROUP__": os.environ["SERVICE_GROUP"],
    "__APP_DIR__": str(app_dir),
    "__ENV_FILE__": str(app_dir / ".env"),
    "__UVICORN_BIN__": str(app_dir / ".venv" / "bin" / "uvicorn"),
    "__APP_PORT__": os.environ["APP_PORT"],
}
for needle, value in replacements.items():
    template = template.replace(needle, value)
destination.write_text(template)
PY
}

validate_systemd_runtime() {
  local uvicorn_bin="$APP_DIR/.venv/bin/uvicorn"
  local env_file="$APP_DIR/.env"

  if ! getent passwd "$SERVICE_USER" >/dev/null 2>&1; then
    echo "Configured SERVICE_USER '$SERVICE_USER' does not exist."
    echo "Stop the loop with: sudo systemctl stop ${SERVICE_NAME}; sudo systemctl reset-failed ${SERVICE_NAME}"
    exit 1
  fi
  if ! getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
    echo "Configured SERVICE_GROUP '$SERVICE_GROUP' does not exist."
    echo "Stop the loop with: sudo systemctl stop ${SERVICE_NAME}; sudo systemctl reset-failed ${SERVICE_NAME}"
    exit 1
  fi
  if [[ ! -d "$APP_DIR" ]]; then
    echo "Configured APP_DIR '$APP_DIR' does not exist."
    exit 1
  fi
  if [[ ! -f "$env_file" ]]; then
    echo "Missing environment file: $env_file"
    exit 1
  fi
  if [[ ! -x "$uvicorn_bin" ]]; then
    echo "Missing executable uvicorn binary: $uvicorn_bin"
    exit 1
  fi
}

print_runtime_assumptions() {
  echo "Runtime assumptions:"
  echo "  runner_mode: ${RUNNER_MODE}"
  echo "  service_name: ${SERVICE_NAME}"
  echo "  service_user: ${SERVICE_USER}"
  echo "  service_group: ${SERVICE_GROUP}"
  echo "  app_dir: ${APP_DIR}"
  echo "  env_file: ${APP_DIR}/.env"
  echo "  exec_start: ${APP_DIR}/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT}"
  echo "  app_port: ${APP_PORT}"
}

if [[ "$SKIP_GIT" != "1" && ! -d "$APP_DIR/.git" ]]; then
  echo "Missing git repo at $APP_DIR"
  exit 1
fi

cd "$APP_DIR"

if [[ "$SKIP_GIT" == "1" ]]; then
  echo "[1/7] Skip git update (SKIP_GIT=1)"
else
  echo "[1/7] Update code"
  git fetch --all --prune
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
fi

echo "[2/7] Python venv + dependencies (uv)"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Installing with python3 -m pip --user..."
  python3 -m pip install --user uv
  export PATH="$HOME/.local/bin:$PATH"
fi
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

if [[ ! -f .env ]]; then
  echo "[3/7] No .env found. Copying template."
  cp deploy/env/.env.green.template .env
  echo "Fill secrets in $APP_DIR/.env before starting the service."
fi
# Load deploy/runtime flags from .env
set -a
source .env
set +a

# Normalize port selection so systemd, tmux, health checks, and tunnels all use the same value.
if [[ -n "${APP_PORT:-}" ]]; then
  PORT="$APP_PORT"
else
  APP_PORT="$PORT"
fi

# Keep explicit env value as override if provided at runtime.
ACCESS_MODE="${ACCESS_MODE:-none}"

SYSTEMD_OK=0
if [[ "$RUNNER_MODE" == "systemd" ]]; then
  SYSTEMD_OK=1
elif [[ "$RUNNER_MODE" == "tmux" ]]; then
  SYSTEMD_OK=0
elif command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
  SYSTEMD_OK=1
fi

if [[ "$SYSTEMD_OK" == "1" ]]; then
  echo "[4/7] Install/refresh systemd unit"
  validate_systemd_runtime
  tmp_service="$(mktemp)"
  render_systemd_unit "$tmp_service"
  print_runtime_assumptions
  sudo cp "$tmp_service" /etc/systemd/system/${SERVICE_NAME}.service
  rm -f "$tmp_service"
  sudo systemctl daemon-reload
  sudo systemctl enable ${SERVICE_NAME}.service

  echo "[5/7] Restart service"
  sudo systemctl restart ${SERVICE_NAME}.service

  echo "[6/7] Service status"
  sudo systemctl --no-pager --full status ${SERVICE_NAME}.service || true
else
  echo "[4/7] systemd unavailable -> using tmux runner"
  if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux is required in non-systemd mode. Please install tmux and rerun."
    exit 1
  fi
  print_runtime_assumptions
  mkdir -p "$APP_DIR/.logs"
  log_file="$APP_DIR/.logs/rucai.log"
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux kill-session -t "$TMUX_SESSION"
    sleep 1
  fi
  tmux new-session -d -s "$TMUX_SESSION" "cd \"$APP_DIR\" && ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\" >> \"$log_file\" 2>&1"
  echo "[5/7] Started tmux session: $TMUX_SESSION"
  echo "[6/7] tmux ls:"
  tmux ls || true
  echo "       Logs: tail -n 80 $log_file"
  echo "       Attach: tmux attach -t $TMUX_SESSION"
fi

echo "[7/8] Health check"
health_ok=0
for _ in $(seq 1 30); do
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      health_ok=1
      break
    fi
  else
    if wget -qO- "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      health_ok=1
      break
    fi
  fi
  sleep 1
done
if [[ "$health_ok" != "1" ]]; then
  echo "Health check failed for http://127.0.0.1:${PORT}/health"
  exit 1
fi
if command -v curl >/dev/null 2>&1; then
  curl -fsS "http://127.0.0.1:${PORT}/health" && echo
else
  wget -qO- "http://127.0.0.1:${PORT}/health" && echo
fi

echo "[8/8] Access mode: $ACCESS_MODE"
case "$ACCESS_MODE" in
  reverse_ssh)
    APP_DIR="$APP_DIR" APP_PORT="$APP_PORT" PORT="$PORT" bash deploy/scripts/reverse_tunnel.sh install
    APP_DIR="$APP_DIR" APP_PORT="$APP_PORT" PORT="$PORT" bash deploy/scripts/reverse_tunnel.sh start
    APP_DIR="$APP_DIR" bash deploy/scripts/reverse_tunnel.sh status || true
    ;;
  cloudflare)
    bash deploy/scripts/cloudflare_tunnel.sh install
    APP_DIR="$APP_DIR" APP_PORT="$APP_PORT" PORT="$PORT" bash deploy/scripts/cloudflare_tunnel.sh start
    public_url="$(APP_DIR="$APP_DIR" bash deploy/scripts/cloudflare_tunnel.sh url || true)"
    if [[ -n "$public_url" ]]; then
      echo "Public URL: $public_url"
    fi
    ;;
  none)
    # Backward compatibility: old env-based cloudflare toggle.
    if [[ "$ENABLE_CLOUDFLARE_TUNNEL" == "1" ]]; then
      bash deploy/scripts/cloudflare_tunnel.sh install
      APP_DIR="$APP_DIR" APP_PORT="$APP_PORT" PORT="$PORT" bash deploy/scripts/cloudflare_tunnel.sh start
      public_url="$(APP_DIR="$APP_DIR" bash deploy/scripts/cloudflare_tunnel.sh url || true)"
      if [[ -n "$public_url" ]]; then
        echo "Public URL: $public_url"
      fi
    else
      echo "No public tunnel started (ACCESS_MODE=none)."
    fi
    ;;
  *)
    echo "Unknown ACCESS_MODE='$ACCESS_MODE'. Use one of: reverse_ssh, cloudflare, none."
    exit 1
    ;;
esac

echo "[9/9] Ops monitor"
if [[ "$ENABLE_OPS_MONITOR" == "1" ]]; then
  APP_DIR="$APP_DIR" APP_PORT="$APP_PORT" bash deploy/scripts/ops_monitor.sh start
  APP_DIR="$APP_DIR" APP_PORT="$APP_PORT" bash deploy/scripts/ops_monitor.sh status || true
else
  echo "Ops monitor disabled (ENABLE_OPS_MONITOR=0)."
fi

echo "Deploy completed."
