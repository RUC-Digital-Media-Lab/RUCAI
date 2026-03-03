#!/usr/bin/env bash
set -euo pipefail

# Configure Nginx on the front server for RUCAI domain + TLS.
# Run this script on the FRONT SERVER (not on UCloud).
#
# Example:
#   DOMAIN=rucai-ruc.dk UPSTREAM_PORT=18011 TLS_EMAIL=you@example.com \
#   bash deploy/scripts/server_nginx_setup.sh

DOMAIN="${DOMAIN:-rucai-ruc.dk}"
UPSTREAM_HOST="${UPSTREAM_HOST:-127.0.0.1}"
UPSTREAM_PORT="${UPSTREAM_PORT:-18011}"
SITE_NAME="${SITE_NAME:-rucai}"
TLS_EMAIL="${TLS_EMAIL:-}"
ENABLE_TLS="${ENABLE_TLS:-1}"

if ! command -v nginx >/dev/null 2>&1; then
  echo "Installing nginx..."
  sudo apt-get update -y
  sudo apt-get install -y nginx
fi

if [[ "$ENABLE_TLS" == "1" ]] && [[ -z "$TLS_EMAIL" ]]; then
  echo "TLS_EMAIL must be set when ENABLE_TLS=1."
  echo "Example: TLS_EMAIL=ops@example.com bash deploy/scripts/server_nginx_setup.sh"
  exit 1
fi

conf_file="/etc/nginx/sites-available/${SITE_NAME}.conf"
tmp_conf="$(mktemp)"
tmp_http_only="$(mktemp)"

cat > "$tmp_http_only" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://${UPSTREAM_HOST}:${UPSTREAM_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 300;
        proxy_connect_timeout 30;
        proxy_send_timeout 300;
    }
}
EOF

echo "Writing nginx config: $conf_file"
sudo cp "$tmp_http_only" "$conf_file"
rm -f "$tmp_http_only"
sudo ln -sfn "$conf_file" "/etc/nginx/sites-enabled/${SITE_NAME}.conf"
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

if [[ "$ENABLE_TLS" == "1" ]]; then
  if ! command -v certbot >/dev/null 2>&1; then
    echo "Installing certbot..."
    sudo apt-get update -y
    sudo apt-get install -y certbot python3-certbot-nginx
  fi

  echo "Issuing/refreshing certificate for ${DOMAIN}..."
  sudo certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m "${TLS_EMAIL}" --redirect

  cat > "$tmp_conf" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    location / {
        proxy_pass http://${UPSTREAM_HOST}:${UPSTREAM_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 300;
        proxy_connect_timeout 30;
        proxy_send_timeout 300;
    }
}
EOF
  sudo cp "$tmp_conf" "$conf_file"
  rm -f "$tmp_conf"
fi

echo "Validating nginx config..."
sudo nginx -t
sudo systemctl reload nginx

echo "Nginx is ready for ${DOMAIN} -> ${UPSTREAM_HOST}:${UPSTREAM_PORT}"
