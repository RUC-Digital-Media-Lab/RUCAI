#!/usr/bin/env bash
set -euo pipefail

# RUCAI ops monitor (UCloud):
# - periodic GPU metrics from nvidia-smi
# - API health status
# - tunnel session presence
# - optional active Ollama models
#
# Usage:
#   bash deploy/scripts/ops_monitor.sh start
#   bash deploy/scripts/ops_monitor.sh stop
#   bash deploy/scripts/ops_monitor.sh status
#   bash deploy/scripts/ops_monitor.sh logs
#   bash deploy/scripts/ops_monitor.sh snapshot

APP_DIR="${APP_DIR:-$(pwd)}"
APP_PORT="${APP_PORT:-8011}"
OPS_MONITOR_INTERVAL="${OPS_MONITOR_INTERVAL:-15}"
OPS_MONITOR_SESSION="${OPS_MONITOR_SESSION:-rucai-monitor}"
OPS_MONITOR_LOG="${OPS_MONITOR_LOG:-.logs/ops_monitor.csv}"

LOG_FILE="$APP_DIR/$OPS_MONITOR_LOG"
mkdir -p "$APP_DIR/.logs"

ensure_header() {
  if [[ ! -f "$LOG_FILE" ]]; then
    echo "ts,api_ok,cf_tunnel,rev_tunnel,gpu_name,gpu_util_pct,mem_util_pct,mem_used_mib,mem_total_mib,temp_c,power_w,compute_apps,ollama_models" > "$LOG_FILE"
  fi
}

session_flag() {
  local name="$1"
  if tmux has-session -t "$name" 2>/dev/null; then
    echo "1"
  else
    echo "0"
  fi
}

collect_line() {
  local ts api_ok cf_tunnel rev_tunnel gpu_line gpu_name gpu_util mem_util mem_used mem_total temp power apps models
  ts="$(date -Iseconds)"

  if curl -fsS -m 3 "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1; then
    api_ok="1"
  else
    api_ok="0"
  fi

  cf_tunnel="$(session_flag rucai-cloudflare)"
  rev_tunnel="$(session_flag rucai-revtunnel)"

  if command -v nvidia-smi >/dev/null 2>&1; then
    gpu_line="$(nvidia-smi --query-gpu=name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits | head -n 1 || true)"
  else
    gpu_line=""
  fi

  if [[ -n "$gpu_line" ]]; then
    IFS=',' read -r gpu_name gpu_util mem_util mem_used mem_total temp power <<< "$gpu_line"
    gpu_name="$(echo "$gpu_name" | xargs)"
    gpu_util="$(echo "$gpu_util" | xargs)"
    mem_util="$(echo "$mem_util" | xargs)"
    mem_used="$(echo "$mem_used" | xargs)"
    mem_total="$(echo "$mem_total" | xargs)"
    temp="$(echo "$temp" | xargs)"
    power="$(echo "$power" | xargs)"
  else
    gpu_name="na"; gpu_util="na"; mem_util="na"; mem_used="na"; mem_total="na"; temp="na"; power="na"
  fi

  if command -v nvidia-smi >/dev/null 2>&1; then
    apps="$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader,nounits 2>/dev/null | tr '\n' ';' | sed 's/"/\"\"/g')"
  else
    apps=""
  fi

  if command -v ollama >/dev/null 2>&1; then
    models="$(ollama ps 2>/dev/null | tail -n +2 | awk '{print $1}' | paste -sd ';' - | sed 's/"/\"\"/g')"
  else
    models=""
  fi

  printf '%s,%s,%s,%s,"%s",%s,%s,%s,%s,%s,%s,"%s","%s"\n' \
    "$ts" "$api_ok" "$cf_tunnel" "$rev_tunnel" "$gpu_name" "$gpu_util" "$mem_util" "$mem_used" "$mem_total" "$temp" "$power" "$apps" "$models"
}

start_monitor() {
  if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux is required."
    exit 1
  fi
  ensure_header
  if tmux has-session -t "$OPS_MONITOR_SESSION" 2>/dev/null; then
    tmux kill-session -t "$OPS_MONITOR_SESSION"
    sleep 1
  fi
  tmux new-session -d -s "$OPS_MONITOR_SESSION" "cd \"$APP_DIR\"; while true; do bash deploy/scripts/ops_monitor.sh snapshot >> \"$LOG_FILE\"; sleep \"$OPS_MONITOR_INTERVAL\"; done"
  echo "Started monitor session: $OPS_MONITOR_SESSION"
  echo "Log file: $LOG_FILE"
}

stop_monitor() {
  if tmux has-session -t "$OPS_MONITOR_SESSION" 2>/dev/null; then
    tmux kill-session -t "$OPS_MONITOR_SESSION"
    echo "Stopped monitor session: $OPS_MONITOR_SESSION"
  else
    echo "Monitor session not running."
  fi
}

status_monitor() {
  echo "tmux session: $OPS_MONITOR_SESSION"
  if tmux has-session -t "$OPS_MONITOR_SESSION" 2>/dev/null; then
    echo "status: running"
  else
    echo "status: stopped"
  fi
  echo "log: $LOG_FILE"
}

show_logs() {
  tail -n 80 "$LOG_FILE" 2>/dev/null || true
}

subcmd="${1:-}"
case "$subcmd" in
  start) start_monitor ;;
  stop) stop_monitor ;;
  status) status_monitor ;;
  logs) show_logs ;;
  snapshot) collect_line ;;
  *)
    echo "Usage: bash deploy/scripts/ops_monitor.sh {start|stop|status|logs|snapshot}"
    exit 1
    ;;
esac
