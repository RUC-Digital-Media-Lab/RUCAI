#!/usr/bin/env bash
set -euo pipefail

# Manage RUCAI Cloudflare tunnel (TryCloudflare) on UCloud.
#
# Usage:
#   bash deploy/scripts/cloudflare_tunnel.sh install
#   bash deploy/scripts/cloudflare_tunnel.sh start
#   bash deploy/scripts/cloudflare_tunnel.sh status
#   bash deploy/scripts/cloudflare_tunnel.sh stop
#   bash deploy/scripts/cloudflare_tunnel.sh url

APP_DIR="${APP_DIR:-$(pwd)}"
PORT="${PORT:-${APP_PORT:-8011}}"
CLOUDFLARE_TUNNEL_SESSION="${CLOUDFLARE_TUNNEL_SESSION:-rucai-cloudflare}"
CLOUDFLARE_TUNNEL_LOG="${CLOUDFLARE_TUNNEL_LOG:-.logs/cloudflared.log}"
CLOUDFLARE_PUBLIC_URL_FILE="${CLOUDFLARE_PUBLIC_URL_FILE:-.logs/cloudflare_url.txt}"
CLOUDFLARE_TUNNEL_MODE="${CLOUDFLARE_TUNNEL_MODE:-trycloudflare}"

LOG_FILE="$APP_DIR/$CLOUDFLARE_TUNNEL_LOG"
URL_FILE="$APP_DIR/$CLOUDFLARE_PUBLIC_URL_FILE"

mkdir -p "$APP_DIR/.logs"

extract_url() {
  grep -Eo "https://[a-zA-Z0-9.-]+\\.trycloudflare\\.com" "$LOG_FILE" 2>/dev/null | tail -n 1 || true
}

install_cloudflared() {
  if command -v cloudflared >/dev/null 2>&1; then
    echo "cloudflared already installed: $(cloudflared --version | head -n 1)"
    return 0
  fi

  echo "Installing cloudflared..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    candidate="$(sudo apt-cache policy cloudflared 2>/dev/null | awk '/Candidate:/ {print $2; exit}')"
    if [[ -n "$candidate" && "$candidate" != "(none)" ]]; then
      sudo apt-get install -y cloudflared && cloudflared --version | head -n 1 && return 0
    fi
  fi

  # Fallback if package is unavailable in apt sources.
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64|amd64) BIN="cloudflared-linux-amd64" ;;
    aarch64|arm64) BIN="cloudflared-linux-arm64" ;;
    *)
      echo "Unsupported arch for fallback binary: $ARCH"
      exit 1
      ;;
  esac
  tmp_bin="$(mktemp)"
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/${BIN}" -o "$tmp_bin"
  chmod +x "$tmp_bin"
  sudo mv "$tmp_bin" /usr/local/bin/cloudflared
  cloudflared --version | head -n 1
}

start_tunnel() {
  if [[ "$CLOUDFLARE_TUNNEL_MODE" != "trycloudflare" ]]; then
    echo "Unsupported CLOUDFLARE_TUNNEL_MODE='$CLOUDFLARE_TUNNEL_MODE' for this script."
    exit 1
  fi

  if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux is required to run cloudflared in background."
    exit 1
  fi

  if ! command -v cloudflared >/dev/null 2>&1; then
    echo "cloudflared not found. Run: bash deploy/scripts/cloudflare_tunnel.sh install"
    exit 1
  fi

  # Wait briefly for API.
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if ! curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "RUCAI API on 127.0.0.1:${PORT} not reachable. Start API first."
    exit 1
  fi

  : > "$LOG_FILE"
  rm -f "$URL_FILE"

  if tmux has-session -t "$CLOUDFLARE_TUNNEL_SESSION" 2>/dev/null; then
    tmux kill-session -t "$CLOUDFLARE_TUNNEL_SESSION"
    sleep 1
  fi

  cmd="cd \"$APP_DIR\" && cloudflared tunnel --url \"http://127.0.0.1:${PORT}\" --no-autoupdate 2>&1 | tee -a \"$LOG_FILE\""
  tmux new-session -d -s "$CLOUDFLARE_TUNNEL_SESSION" "$cmd"

  for _ in $(seq 1 45); do
    url="$(extract_url)"
    if [[ -n "$url" ]]; then
      echo "$url" > "$URL_FILE"
      echo "Cloudflare public URL: $url"
      return 0
    fi
    sleep 1
  done

  echo "Could not discover trycloudflare URL within timeout."
  echo "Check logs: tail -n 120 \"$LOG_FILE\""
  exit 1
}

status_tunnel() {
  echo "tmux session: $CLOUDFLARE_TUNNEL_SESSION"
  if tmux has-session -t "$CLOUDFLARE_TUNNEL_SESSION" 2>/dev/null; then
    echo "status: running"
  else
    echo "status: stopped"
  fi
  if [[ -f "$URL_FILE" ]]; then
    echo "public_url: $(cat "$URL_FILE")"
  else
    echo "public_url: (none)"
  fi
  echo "logs: $LOG_FILE"
}

stop_tunnel() {
  if tmux has-session -t "$CLOUDFLARE_TUNNEL_SESSION" 2>/dev/null; then
    tmux kill-session -t "$CLOUDFLARE_TUNNEL_SESSION"
    echo "Stopped tunnel session: $CLOUDFLARE_TUNNEL_SESSION"
  else
    echo "Tunnel session not running."
  fi
}

print_url() {
  if [[ -f "$URL_FILE" ]]; then
    cat "$URL_FILE"
  else
    extract_url
  fi
}

subcmd="${1:-}"
case "$subcmd" in
  install) install_cloudflared ;;
  start) start_tunnel ;;
  status) status_tunnel ;;
  stop) stop_tunnel ;;
  url) print_url ;;
  *)
    echo "Usage: bash deploy/scripts/cloudflare_tunnel.sh {install|start|status|stop|url}"
    exit 1
    ;;
esac
