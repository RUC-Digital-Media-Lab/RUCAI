#!/usr/bin/env bash
set -euo pipefail

# Bootstrap RUCAI dependencies on a fresh Ubuntu VM.
# Safe to run multiple times.
#
# Usage:
#   APP_DIR="/work/.../RUCAI" bash deploy/scripts/bootstrap_new_vm.sh

APP_DIR="${APP_DIR:-/work/FrederikMøllerHenriksen#7467/projects/RUCAI}"
INSTALL_POSTGRES="${INSTALL_POSTGRES:-1}"
INSTALL_OLLAMA="${INSTALL_OLLAMA:-0}"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This script supports apt-based Linux only."
  exit 1
fi

echo "[1/6] Base OS packages"
sudo apt-get update -y
sudo apt-get install -y \
  ca-certificates \
  curl \
  git \
  tmux \
  autossh \
  jq \
  build-essential \
  python3 \
  python3-venv \
  python3-pip

if [[ "$INSTALL_POSTGRES" == "1" ]]; then
  echo "[2/6] PostgreSQL + pgvector"
  sudo apt-get install -y postgresql-16 postgresql-client-16 postgresql-16-pgvector
  sudo pg_ctlcluster 16 main start || true
else
  echo "[2/6] PostgreSQL skipped (INSTALL_POSTGRES=0)"
fi

echo "[3/6] uv package manager"
if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --user uv
fi
export PATH="$HOME/.local/bin:$PATH"
echo "uv: $(command -v uv || true)"

if [[ "$INSTALL_OLLAMA" == "1" ]]; then
  echo "[4/6] Ollama install"
  if ! command -v ollama >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  echo "ollama: $(command -v ollama || true)"
else
  echo "[4/6] Ollama skipped (INSTALL_OLLAMA=0)"
fi

echo "[5/6] RUCAI venv + deps"
cd "$APP_DIR"
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

echo "[6/6] .env presence"
if [[ ! -f .env ]]; then
  cp deploy/env/.env.green.template .env
  echo "Created .env from template. Fill secrets before deploy."
else
  echo ".env already exists (kept as-is)."
fi

cat <<EOF

Bootstrap complete.
Next steps:
  1) Validate/edit .env in: $APP_DIR/.env
  2) Optional DB init (if local postgres):
       APP_DIR="$APP_DIR" DB_PASSWORD='__set__' bash deploy/scripts/setup_local_postgres.sh
  3) Start RUCAI:
       SKIP_GIT=1 APP_DIR="$APP_DIR" BRANCH=main bash deploy/scripts/deploy_green.sh

EOF
