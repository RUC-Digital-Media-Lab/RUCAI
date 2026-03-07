#!/usr/bin/env bash
set -euo pipefail

# Manage RUCAI reverse SSH tunnel from UCloud -> front server.
#
# Usage:
#   bash deploy/scripts/reverse_tunnel.sh install
#   bash deploy/scripts/reverse_tunnel.sh start
#   bash deploy/scripts/reverse_tunnel.sh stop
#   bash deploy/scripts/reverse_tunnel.sh status
#   bash deploy/scripts/reverse_tunnel.sh logs
#   bash deploy/scripts/reverse_tunnel.sh urltest

APP_DIR="${APP_DIR:-$(pwd)}"
PORT="${PORT:-${APP_PORT:-8011}}"
APP_PORT="${APP_PORT:-$PORT}"
SERVER_HOST="${SERVER_HOST:-front.example.com}"
SERVER_SSH_PORT="${SERVER_SSH_PORT:-2111}"
SERVER_SSH_USER="${SERVER_SSH_USER:-deploy}"
REMOTE_BIND_PORT="${REMOTE_BIND_PORT:-18011}"
REVERSE_TUNNEL_SESSION="${REVERSE_TUNNEL_SESSION:-rucai-revtunnel}"
REVERSE_TUNNEL_LOG="${REVERSE_TUNNEL_LOG:-.logs/reverse_tunnel.log}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://rucai.example.com}"

LOG_FILE="$APP_DIR/$REVERSE_TUNNEL_LOG"
mkdir -p "$APP_DIR/.logs"

install_autossh() {
  if command -v autossh >/dev/null 2>&1; then
    echo "autossh already installed: $(autossh -V 2>&1 | head -n 1)"
    return 0
  fi

  echo "Installing autossh..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y autossh
  else
    echo "apt-get not available. Install autossh manually and rerun."
    exit 1
  fi
}

ensure_dependencies() {
  if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux is required."
    exit 1
  fi
  if ! command -v autossh >/dev/null 2>&1; then
    echo "autossh not found. Run: bash deploy/scripts/reverse_tunnel.sh install"
    exit 1
  fi
}

check_local_api() {
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "RUCAI API on 127.0.0.1:${APP_PORT} not reachable. Start API first."
  exit 1
}

start_tunnel() {
  ensure_dependencies
  check_local_api

  : > "$LOG_FILE"
  if tmux has-session -t "$REVERSE_TUNNEL_SESSION" 2>/dev/null; then
    tmux kill-session -t "$REVERSE_TUNNEL_SESSION"
    sleep 1
  fi

  cmd="cd \"$APP_DIR\" && AUTOSSH_GATETIME=0 AUTOSSH_LOGFILE=\"$LOG_FILE\" autossh -M 0 -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:${REMOTE_BIND_PORT}:127.0.0.1:${APP_PORT} -p ${SERVER_SSH_PORT} ${SERVER_SSH_USER}@${SERVER_HOST} >> \"$LOG_FILE\" 2>&1"
  tmux new-session -d -s "$REVERSE_TUNNEL_SESSION" "$cmd"

  echo "Started reverse tunnel session: $REVERSE_TUNNEL_SESSION"
  echo "Server endpoint (internal): 127.0.0.1:${REMOTE_BIND_PORT}"
  echo "Logs: $LOG_FILE"
}

stop_tunnel() {
  if tmux has-session -t "$REVERSE_TUNNEL_SESSION" 2>/dev/null; then
    tmux kill-session -t "$REVERSE_TUNNEL_SESSION"
    echo "Stopped tunnel session: $REVERSE_TUNNEL_SESSION"
  else
    echo "Tunnel session not running."
  fi
}

status_tunnel() {
  echo "tmux session: $REVERSE_TUNNEL_SESSION"
  if tmux has-session -t "$REVERSE_TUNNEL_SESSION" 2>/dev/null; then
    echo "status: running"
  else
    echo "status: stopped"
  fi
  echo "server_target: ${SERVER_SSH_USER}@${SERVER_HOST}:${SERVER_SSH_PORT}"
  echo "remote_bind: 127.0.0.1:${REMOTE_BIND_PORT}"
  echo "local_api: 127.0.0.1:${APP_PORT}"
  echo "logs: $LOG_FILE"
}

show_logs() {
  tail -n 120 "$LOG_FILE" 2>/dev/null || true
}

url_test() {
  local url="${PUBLIC_BASE_URL%/}/health"
  echo "Testing: $url"
  curl -fsS "$url" && echo
}

subcmd="${1:-}"
case "$subcmd" in
  install) install_autossh ;;
  start) start_tunnel ;;
  stop) stop_tunnel ;;
  status) status_tunnel ;;
  logs) show_logs ;;
  urltest) url_test ;;
  *)
    echo "Usage: bash deploy/scripts/reverse_tunnel.sh {install|start|stop|status|logs|urltest}"
    exit 1
    ;;
esac
