#!/usr/bin/env bash
# Terminal interactif : API en arrière-plan + Vite au premier plan.
exec bash "$(dirname "$0")/ensure-dev.sh" --foreground --open
