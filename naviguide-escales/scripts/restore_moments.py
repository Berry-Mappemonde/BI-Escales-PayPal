#!/usr/bin/env python3
"""Restaure le journal moments officiel depuis un backup sqlite (fusion, sans écraser le live).

Usage poste / OVH :

    cd naviguide-simulator
    set -a && [ -f "$HOME/.config/naviguide/simulator.env" ] && . "$HOME/.config/naviguide/simulator.env"
    set +a
    unset NAVIGUIDE_OFFICIAL_STORE_DIR   # OVH : défaut server/voyage_data/official-store

    python3 scripts/restore_moments.py --dry-run \\
        --source-sqlite server/voyage_data/naviguide.sqlite.bak-rekey-20261015

    python3 scripts/restore_moments.py \\
        --source-sqlite server/voyage_data/naviguide.sqlite.bak-rekey-20261015

Voir le corps de la PR pour les commandes OVH complètes (dry-run puis réel + restart service).
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


def _default_source() -> Path:
    return ROOT / "server" / "voyage_data" / "naviguide.sqlite.bak-rekey-20261015"


def main() -> int:
    parser = argparse.ArgumentParser(description="Restauration fusionnée du journal moments.")
    parser.add_argument(
        "--source-sqlite",
        type=Path,
        default=_default_source(),
        help="backup sqlite (ex. naviguide.sqlite.bak-rekey-20261015)",
    )
    parser.add_argument(
        "--moments-json",
        type=Path,
        action="append",
        default=[],
        help="moments.json additionnels (dossiers store plus anciens)",
    )
    parser.add_argument("--dry-run", action="store_true", help="comptes seulement, aucune écriture")
    parser.add_argument(
        "--i-accept-data-risk-without-backup",
        action="store_true",
        help="tests uniquement : pas de backup live avant écriture",
    )
    args = parser.parse_args()

    from ici_engine import ensure_pearl_amp_layer_sig  # noqa: PLC0415
    from restore_moments import run_restore, validate_source_sqlite  # noqa: PLC0415

    ensure_pearl_amp_layer_sig("restore_moments")
    src = validate_source_sqlite(args.source_sqlite)
    print(f"source : {src}", flush=True)
    json_paths = list(args.moments_json or [])
    run_restore(
        source_sqlite=src,
        json_paths=json_paths,
        dry_run=args.dry_run,
        skip_backup=args.i_accept_data_risk_without_backup,
        refresh_store=not args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
