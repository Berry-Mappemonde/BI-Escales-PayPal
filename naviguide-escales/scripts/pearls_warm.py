#!/usr/bin/env python3
"""Passage unique des perles du voyage officiel.

  python3 scripts/pearls_warm.py --estimate
  python3 scripts/pearls_warm.py --run

L'estimation n'écrit pas. Le passage reprend après un arrêt et refuse
un second lancement simultané. Aucun --force.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent / "server"
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

from pearls_warm import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
