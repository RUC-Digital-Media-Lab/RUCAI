#!/usr/bin/env bash
set -euo pipefail

# Toggle short maintenance mode in nginx for RUCAI.
# Run on SERVER.
#
# Usage:
#   ACTION=install_hook bash deploy/scripts/maintenance_banner.sh
#   ACTION=enable bash deploy/scripts/maintenance_banner.sh
#   ACTION=disable bash deploy/scripts/maintenance_banner.sh
#   ACTION=status bash deploy/scripts/maintenance_banner.sh
#
# Optional env:
#   SITE_CONF             default: /etc/nginx/sites-available/rucai.conf
#   FLAG_FILE             default: /etc/nginx/rucai_maintenance.on

ACTION="${ACTION:-status}"
SITE_CONF="${SITE_CONF:-/etc/nginx/sites-available/rucai.conf}"
FLAG_FILE="${FLAG_FILE:-/etc/nginx/rucai_maintenance.on}"
HOOK_MARKER="rucai-maintenance-hook"

install_hook() {
  if sudo grep -q "$HOOK_MARKER" "$SITE_CONF"; then
    echo "Hook already present."
    return 0
  fi

  tmp_file="$(mktemp)"
  sudo awk -v marker="$HOOK_MARKER" -v flag="$FLAG_FILE" '
    BEGIN { inserted=0 }
    {
      print $0
      if (!inserted && $0 ~ /^[[:space:]]*location[[:space:]]+\/[[:space:]]*\{[[:space:]]*$/) {
        print "        if (-f " flag ") { return 503; } # " marker
        inserted=1
      }
    }
    END {
      if (!inserted) {
        print "ERROR: could not find \"location / {\" block for maintenance hook." > "/dev/stderr"
        exit 1
      }
    }
  ' "$SITE_CONF" > "$tmp_file"

  sudo cp "$tmp_file" "$SITE_CONF"
  rm -f "$tmp_file"
  sudo nginx -t
  sudo systemctl reload nginx
  echo "Maintenance hook installed."
}

enable_maintenance() {
  sudo touch "$FLAG_FILE"
  sudo nginx -t
  sudo systemctl reload nginx
  echo "Maintenance enabled."
}

disable_maintenance() {
  sudo rm -f "$FLAG_FILE"
  sudo nginx -t
  sudo systemctl reload nginx
  echo "Maintenance disabled."
}

status_maintenance() {
  if sudo test -f "$FLAG_FILE"; then
    echo "status: enabled"
  else
    echo "status: disabled"
  fi
  if sudo grep -q "$HOOK_MARKER" "$SITE_CONF"; then
    echo "hook: installed"
  else
    echo "hook: missing (run ACTION=install_hook)"
  fi
}

case "$ACTION" in
  install_hook) install_hook ;;
  enable) enable_maintenance ;;
  disable) disable_maintenance ;;
  status) status_maintenance ;;
  *)
    echo "Invalid ACTION='$ACTION'. Use: install_hook|enable|disable|status"
    exit 1
    ;;
esac
