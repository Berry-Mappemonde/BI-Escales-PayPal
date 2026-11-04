#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly APP_DIR
readonly API_HOST="127.0.0.1"
readonly API_PORT="8010"
readonly FRONT_HOST="127.0.0.1"
readonly FRONT_PORT="5174"
readonly STARTUP_TIMEOUT="60"

api_pid=""
front_pid=""
log_dir=""

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if [[ -n "$front_pid" ]]; then
    kill "$front_pid" 2>/dev/null || true
    wait "$front_pid" 2>/dev/null || true
  fi
  if [[ -n "$api_pid" ]]; then
    kill "$api_pid" 2>/dev/null || true
    wait "$api_pid" 2>/dev/null || true
  fi
  if [[ -n "$log_dir" ]]; then
    rm -rf -- "$log_dir"
  fi
  exit "$exit_code"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for command_name in curl env; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Commande requise introuvable: %s\n' "$command_name" >&2
    exit 1
  fi
done

if [[ -z "${NVIDIA_API_KEY_2:-}" ]]; then
  printf 'NVIDIA_API_KEY_2 doit être définie dans l’environnement pour activer NIM.\n' >&2
  exit 1
fi

log_dir="$(mktemp -d "${TMPDIR:-/tmp}/naviguide-review.XXXXXX")"

cd "$APP_DIR"
env -u NEBIUS_API_KEY -u NAVIGUIDE_OFFLINE -u NAVIGUIDE_LLM_MODE \
  PYTHON_DOTENV_DISABLED=1 NAVIGUIDE_LLM_PROVIDERS=nim \
  NVIDIA_API_KEY="$NVIDIA_API_KEY_2" \
  /workspace/nv-venv/bin/python -m uvicorn server.main:app \
  --host "$API_HOST" --port "$API_PORT" \
  >"$log_dir/api.log" 2>&1 &
api_pid=$!

env -u NEBIUS_API_KEY -u NVIDIA_API_KEY_2 -u NVIDIA_API_KEY \
  API_PROXY_TARGET="http://${API_HOST}:${API_PORT}" \
  "$APP_DIR/node_modules/.bin/vite" --configLoader native \
  --host "$FRONT_HOST" --port "$FRONT_PORT" \
  >"$log_dir/front.log" 2>&1 &
front_pid=$!

api_url="http://${API_HOST}:${API_PORT}/"
front_url="http://${FRONT_HOST}:${FRONT_PORT}/"
deadline=$((SECONDS + STARTUP_TIMEOUT))
api_ready=0
front_ready=0

while (( SECONDS < deadline )); do
  if ! kill -0 "$api_pid" 2>/dev/null; then
    printf 'Le serveur API s’est arrêté avant de répondre sur sa route de santé.\n' >&2
    exit 1
  fi
  if ! kill -0 "$front_pid" 2>/dev/null; then
    printf 'Le serveur Vite s’est arrêté avant de répondre.\n' >&2
    exit 1
  fi

  if (( api_ready == 0 )) && curl --fail --silent --show-error --output /dev/null "$api_url" 2>/dev/null; then
    api_ready=1
  fi
  if (( front_ready == 0 )) && curl --fail --silent --show-error --output /dev/null "$front_url" 2>/dev/null; then
    front_ready=1
  fi
  if (( api_ready == 1 && front_ready == 1 )); then
    break
  fi
  sleep 1
done

if (( api_ready == 0 || front_ready == 0 )); then
  printf 'Délai dépassé en attendant les vérifications HTTP (API %s, interface %s).\n' "$api_url" "$front_url" >&2
  exit 1
fi

printf 'Revue locale NIM prête. Garde ce terminal ouvert; Ctrl+C arrête les deux serveurs.\n'
printf 'URL à ouvrir: %s\n' "$front_url"
printf 'FR: Outils → FR → Suivre / expédition Berry-Mappemonde → « Revoir l’expédition » → Brut → Lecture, puis Rédigé → Lecture.\n'
printf 'EN: Outils → EN → Follow / Berry-Mappemonde expedition → « Replay the expedition » → Raw → Play, puis Edited → Play.\n'

while kill -0 "$api_pid" 2>/dev/null && kill -0 "$front_pid" 2>/dev/null; do
  sleep 1
done

printf 'Un des serveurs s’est arrêté.\n' >&2
exit 1
