#!/usr/bin/env bash
# Recette hors ligne (PW_WITH_API=1) : sert le build avec la route du stock figé.
# Copie dist/ dans un dossier temporaire, remplace route.geojson par
# server/tests/fixtures/official_store.route.geojson, puis vite preview.
# Le build lui-même (dist/) n'est pas modifié.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:?port}"
ROUTE="$ROOT/server/tests/fixtures/official_store.route.geojson"
if [[ ! -f "$ROOT/dist/index.html" ]]; then
  echo "build absent : $ROOT/dist" >&2
  exit 1
fi
if [[ ! -f "$ROUTE" ]]; then
  echo "route du stock figé absente : $ROUTE" >&2
  exit 1
fi
# Un dossier par port, vidé à chaque lancement (exec ne laisse pas nettoyer après).
OUT="${TMPDIR:-/tmp}/naviguide-e2e-dist-$PORT"
rm -rf "$OUT"
mkdir -p "$OUT"
cp -R "$ROOT/dist/." "$OUT/"
cp "$ROUTE" "$OUT/route.geojson"
cd "$ROOT"
exec npx vite preview --host 127.0.0.1 --port "$PORT" --strictPort --outDir "$OUT"
