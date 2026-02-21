#!/usr/bin/env bash
set -euo pipefail

# Deploy RUCAI on Green VM.
# Run on Green VM as a user with sudo rights.

APP_DIR="${APP_DIR:-/home/ucloud/RUCAI}"
BRANCH="${BRANCH:-release/gpu-pilot}"
PORT="${PORT:-8011}"
SERVICE_NAME="${SERVICE_NAME:-rucai-api}"
SKIP_GIT="${SKIP_GIT:-0}"
RUNNER_MODE="${RUNNER_MODE:-auto}"
TMUX_SESSION="${TMUX_SESSION:-rucai-api}"

if [[ ! -d "$APP_DIR/.git" ]]; then
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
  tmp_service="$(mktemp)"
  sed "s|/home/ucloud/RUCAI|$APP_DIR|g" deploy/systemd/rucai-api.service > "$tmp_service"
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

echo "[7/7] Health check"
if command -v curl >/dev/null 2>&1; then
  curl -fsS "http://127.0.0.1:${PORT}/health" && echo
else
  wget -qO- "http://127.0.0.1:${PORT}/health" && echo
fi

echo "Deploy completed."
