#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
cd "$FRONTEND"
if [[ ! -d node_modules ]]; then
  npm install
fi
export VITE_PAYPAL_CLIENT_ID=demo-client
export VITE_DEMO_MODE=1
export VITE_PAYPAL_MOCK=1
exec npm run dev -- --host 127.0.0.1 --port 5173
