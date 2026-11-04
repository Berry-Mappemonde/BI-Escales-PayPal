#!/usr/bin/env bash
# Arrête les processus lancés par ensure-dev.sh (PIDs dans .dev/).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

kill_pid_file() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  local pid
  pid="$(cat "$f" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  rm -f "$f"
}

kill_pid_file .dev/vite.pid
kill_pid_file .dev/api.pid
echo "Simulateur arrêté (si les ports étaient gérés par ensure-dev)."
