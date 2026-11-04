#!/usr/bin/env python3
"""Passage unique : estimation sans appel, puis exécution sous empreinte.

  python3 scripts/one_shot.py --job fixture --estimate
  python3 scripts/one_shot.py --job fixture --run --i-have-read-the-estimate <empreinte>

Aucun --force. Pour relancer un job réussi, supprimer à la main son fichier .done.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent / "server"
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

from one_shot import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
