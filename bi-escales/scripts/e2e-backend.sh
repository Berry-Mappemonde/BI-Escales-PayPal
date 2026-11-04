#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
cd "$BACKEND"
if ! python3 -c "import fastapi" 2>/dev/null; then
  pip3 install -q -r requirements.txt --break-system-packages
fi
export ESCALES_ENABLED=1
export ESCALES_STORE=memory
export ESCALES_ADMIN_KEY="${ESCALES_ADMIN_KEY:-demo-admin-key}"
export ESCALES_PAYPAL_MOCK=1
export ESCALES_WEBHOOKS_ENABLED=1
export PAYPAL_WEBHOOK_ID=WH-DEMO
export ESCALES_VAULT_ENABLED=1
export PAYPAL_CLIENT_ID=demo-client
export PAYPAL_CLIENT_SECRET=demo-secret
export PAYPAL_ENV=sandbox
export PYTHONPATH="$BACKEND${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
