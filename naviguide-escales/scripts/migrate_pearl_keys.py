#!/usr/bin/env python3
"""Copie ajout-seule des perles anciennes vers la clé canonique.

    cd naviguide-simulator
    python3 scripts/migrate_pearl_keys.py --dry-run
    python3 scripts/migrate_pearl_keys.py

Refuse de tourner si le service naviguide-simulator est actif.
Sauvegarde le sqlite avant toute écriture réelle.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
os.environ.setdefault("NAVIGUIDE_OFFICIAL_WORKER", "0")


def main() -> int:
    parser = argparse.ArgumentParser(description="Migration ajout-seule des clés de perles.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--i-accept-data-risk-without-backup", action="store_true")
    args = parser.parse_args()
    from ici_engine import ensure_pearl_amp_layer_sig  # noqa: PLC0415
    from migrate_pearl_keys import run_pearl_alias_migration  # noqa: PLC0415

    ensure_pearl_amp_layer_sig("migrate_pearl_keys")
    run_pearl_alias_migration(
        dry_run=args.dry_run,
        skip_backup=args.i_accept_data_risk_without_backup,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
