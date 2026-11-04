#!/usr/bin/env python3
"""Recalcule moments (ancres côte) et film officiel après déploiement RG10 / RG14.

Règle absolue : aucune perte de perles ni de lignes moments — uniquement mise à jour
des ancres (tMs, coords, marques horloge). Sauvegarde horodatée avant toute écriture.

Usage (poste de recette) :

    cd naviguide-simulator
    export NAVIGUIDE_OFFICIAL_STORE_DIR="${NAVIGUIDE_OFFICIAL_STORE_DIR:-$HOME/.cache/naviguide/voyage-store}"
    export NAVIGUIDE_VOYAGE_DIR="${NAVIGUIDE_VOYAGE_DIR:-$HOME/.cache/naviguide/voyage-data}"
    python3 scripts/reanchor_official_moments.py --dry-run
    python3 scripts/reanchor_official_moments.py

Construire un stock poste depuis le dépôt (tests `pytest -m poste`) :

    cd naviguide-simulator
    export NAVIGUIDE_OFFICIAL_STORE_DIR=/tmp/poste-stock-test
    export NAVIGUIDE_VOYAGE_DIR=/tmp/poste-voyage-data
    pip install -r server/requirements.txt
    python3 scripts/prepare_official_store.py
    cd server && uvicorn main:app --host 127.0.0.1 --port 8010
    pytest tests/test_film_discours.py -m poste

── Production OVH (utilisateur ubuntu, dépôt dans le home) ──

    ssh ubuntu@135.125.226.16
    cd ~/blue-intelligence-map/naviguide-simulator
    set -a
    [ -f /etc/naviguide-nowarm.env ] && . /etc/naviguide-nowarm.env
    [ -f "$HOME/.config/naviguide/simulator.env" ] && . "$HOME/.config/naviguide/simulator.env"
    set +a
    # Même défaut que le serveur (official_store.disk_root) : pas de ~/.cache/… sur l'OVH.
    unset NAVIGUIDE_OFFICIAL_STORE_DIR
    python3 scripts/reanchor_official_moments.py --dry-run
    python3 scripts/reanchor_official_moments.py
    sudo systemctl restart naviguide-simulator naviguide-film-front

── Production Contabo (utilisateur naviguide) ──

    sudo -u naviguide -H bash -lc '
      cd /opt/naviguide/Blue-Intelligence/naviguide-simulator
      set -a
      [ -f /etc/naviguide/simulator.env ] && . /etc/naviguide/simulator.env
      set +a
      unset NAVIGUIDE_OFFICIAL_STORE_DIR
      python3 scripts/reanchor_official_moments.py --dry-run
      python3 scripts/reanchor_official_moments.py
    '
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
sys.path.insert(0, str(SERVER))

os.environ.setdefault("NAVIGUIDE_OFFICIAL_WORKER", "0")


def main() -> int:
    parser = argparse.ArgumentParser(description="Réancrage RG10/RG14 du stock officiel.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="affiche le plan et les comptes sans écrire ni sauvegarder",
    )
    parser.add_argument(
        "--i-accept-data-risk-without-backup",
        action="store_true",
        help="désactive la sauvegarde (interdit en production ; tests uniquement)",
    )
    args = parser.parse_args()

    from ici_engine import ensure_pearl_amp_layer_sig  # noqa: PLC0415
    from reanchor_official import refuse_empty_store, run_reanchor

    ensure_pearl_amp_layer_sig("reanchor_official_moments")
    refuse_empty_store()
    return run_reanchor(
        dry_run=args.dry_run,
        skip_backup=args.i_accept_data_risk_without_backup,
    )


if __name__ == "__main__":
    raise SystemExit(main())
