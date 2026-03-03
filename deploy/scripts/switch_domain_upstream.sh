#!/usr/bin/env bash
set -euo pipefail

# Switch nginx RUCAI upstream between local server app and UCloud tunnel.
# Run on SERVER.
#
# Usage:
#   MODE=server bash deploy/scripts/switch_domain_upstream.sh
#   MODE=ucloud bash deploy/scripts/switch_domain_upstream.sh
#
# Optional env:
#   SITE_CONF              default: /etc/nginx/sites-available/rucai.conf
#   SERVER_UPSTREAM        default: http://127.0.0.1:8011
#   UCLOUD_UPSTREAM        default: http://127.0.0.1:18011
#   SKIP_HEALTH_CHECK      default: 0

: "${MODE:?Set MODE=server or MODE=ucloud}"

SITE_CONF="${SITE_CONF:-/etc/nginx/sites-available/rucai.conf}"
SERVER_UPSTREAM="${SERVER_UPSTREAM:-http://127.0.0.1:8011}"
UCLOUD_UPSTREAM="${UCLOUD_UPSTREAM:-http://127.0.0.1:18011}"
SKIP_HEALTH_CHECK="${SKIP_HEALTH_CHECK:-0}"

case "$MODE" in
  server)
    TARGET_UPSTREAM="$SERVER_UPSTREAM"
    TARGET_HEALTH="${SERVER_UPSTREAM}/health"
    ;;
  ucloud)
    TARGET_UPSTREAM="$UCLOUD_UPSTREAM"
    TARGET_HEALTH="${UCLOUD_UPSTREAM}/health"
    ;;
  *)
    echo "Invalid MODE='$MODE' (expected server|ucloud)."
    exit 1
    ;;
esac

if [[ "$SKIP_HEALTH_CHECK" != "1" ]]; then
  echo "[1/4] Verify target upstream health: $TARGET_HEALTH"
  curl -fsS -m 8 "$TARGET_HEALTH" >/dev/null
else
  echo "[1/4] Skip upstream health check (SKIP_HEALTH_CHECK=1)"
fi

echo "[2/4] Update proxy_pass in $SITE_CONF -> $TARGET_UPSTREAM"
tmp_file="$(mktemp)"
sudo cp "$SITE_CONF" "${tmp_file}.orig"
sudo sed -E \
  "s#proxy_pass[[:space:]]+http://127\\.0\\.0\\.1:[0-9]+;#        proxy_pass ${TARGET_UPSTREAM};#g" \
  "$SITE_CONF" | tee "$tmp_file" >/dev/null

if ! grep -Eq "proxy_pass[[:space:]]+${TARGET_UPSTREAM};" "$tmp_file"; then
  echo "Failed to apply target upstream in config."
  rm -f "$tmp_file"
  exit 1
fi

sudo cp "$tmp_file" "$SITE_CONF"
rm -f "$tmp_file"

echo "[3/4] Validate and reload nginx"
sudo nginx -t
sudo systemctl reload nginx

echo "[4/4] Active proxy_pass lines:"
sudo grep -n "proxy_pass" "$SITE_CONF" || true

echo "Switched MODE=$MODE"
