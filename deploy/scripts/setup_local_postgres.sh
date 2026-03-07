#!/usr/bin/env bash
set -euo pipefail

# Install and configure local PostgreSQL + pgvector on Ubuntu (UCloud-friendly).
# Usage:
#   APP_DIR=/work/.../RUCAI DB_PASSWORD='...' bash deploy/scripts/setup_local_postgres.sh

APP_DIR="${APP_DIR:-/work/project/RUCAI}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-ppl_rag}"
DB_USER="${DB_USER:-ppl}"
DB_PASSWORD="${DB_PASSWORD:-}"

if [[ -z "$DB_PASSWORD" ]]; then
  echo "Set DB_PASSWORD before running, e.g.:"
  echo "  DB_PASSWORD='strong-password' bash deploy/scripts/setup_local_postgres.sh"
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This script currently supports apt-based systems only."
  exit 1
fi

echo "[1/6] Install PostgreSQL 16 + pgvector"
sudo apt-get update -y >/dev/null
sudo apt-get install -y postgresql-16 postgresql-client-16 postgresql-16-pgvector >/tmp/rucai-pg-install.log 2>&1 || {
  tail -n 120 /tmp/rucai-pg-install.log
  exit 1
}

echo "[2/6] Start PostgreSQL cluster"
sudo pg_ctlcluster 16 main start || true

echo "[3/6] Create/update role and database"
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';"
else
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';"
fi
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"
fi

sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS vector;"

echo "[4/6] Validate DB login"
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "select 1 as db_ok;"

echo "[5/6] Write .env DB and path values"
cd "$APP_DIR"
if [[ ! -f .env ]]; then
  cp deploy/env/.env.green.template .env
fi
sed -i "s|^DATA_ROOT=.*|DATA_ROOT=${APP_DIR}/data|" .env
sed -i "s|^UPLOAD_ROOT=.*|UPLOAD_ROOT=${APP_DIR}/data/uploads|" .env
sed -i "s|^DB_HOST=.*|DB_HOST=${DB_HOST}|" .env
sed -i "s|^DB_PORT=.*|DB_PORT=${DB_PORT}|" .env
sed -i "s|^DB_NAME=.*|DB_NAME=${DB_NAME}|" .env
sed -i "s|^DB_USER=.*|DB_USER=${DB_USER}|" .env
sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=${DB_PASSWORD}|" .env
sed -i "s|^AUTH_USERS_FILE=.*|AUTH_USERS_FILE=${APP_DIR}/data/auth_users.json|" .env

echo "[6/6] Done"
echo "Next: RUNNER_MODE=tmux SKIP_GIT=1 APP_DIR=\"$APP_DIR\" BRANCH=main bash ./deploy/scripts/deploy_green.sh"
