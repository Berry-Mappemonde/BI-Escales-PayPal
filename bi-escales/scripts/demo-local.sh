#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

echo "== BI Escales — démo locale =="

if [[ ! -d "$BACKEND/.venv" ]]; then
  python3 -m venv "$BACKEND/.venv"
fi
# shellcheck disable=SC1091
source "$BACKEND/.venv/bin/activate"
pip -q install -r "$BACKEND/requirements.txt"

export ESCALES_ENABLED="${ESCALES_ENABLED:-1}"
export ESCALES_STORE="${ESCALES_STORE:-memory}"
export ESCALES_ADMIN_KEY="${ESCALES_ADMIN_KEY:-demo-admin-key}"

if [[ -z "${PAYPAL_CLIENT_ID:-}" && -z "${VITE_PAYPAL_CLIENT_ID:-}" ]]; then
  echo "Attention: PAYPAL_CLIENT_ID / VITE_PAYPAL_CLIENT_ID non définis — promesses PayPal indisponibles."
fi

cd "$FRONTEND"
if [[ ! -d node_modules ]]; then
  npm install
fi

if [[ -f "$FRONTEND/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$FRONTEND/.env.local"
  set +a
fi

export VITE_PAYPAL_CLIENT_ID="${VITE_PAYPAL_CLIENT_ID:-${PAYPAL_CLIENT_ID:-}}"
export VITE_ENABLE_AG_GRID="${VITE_ENABLE_AG_GRID:-0}"

echo "Backend: http://127.0.0.1:8000 (ESCALES_ENABLED=$ESCALES_ENABLED)"
echo "Frontend: http://127.0.0.1:5173"
echo "Clé trésorier démo (x-admin-key): $ESCALES_ADMIN_KEY"

(cd "$BACKEND" && uvicorn app.main:app --host 127.0.0.1 --port 8000) &
BACK_PID=$!
trap 'kill $BACK_PID 2>/dev/null || true' EXIT

sleep 1
npm run dev -- --host 127.0.0.1 --port 5173
