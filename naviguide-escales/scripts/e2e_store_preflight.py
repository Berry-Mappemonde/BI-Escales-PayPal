#!/usr/bin/env python3
"""Recette hors ligne : le stock figé et sa route vont ensemble.

Lancé par scripts/e2e-store-api.sh avant l'API, et par la CI (job simulateur). Sort en 1 si aucune clé de
l'archive ne porte l'empreinte de la route de recette (l'API ne servirait
rien : ni bateau, ni horloge, ni film). Avertit, sans bloquer, quand la route
publiée a changé depuis le gel : le stock reste à recalculer sur la nouvelle.
"""
from __future__ import annotations

import json
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import official_store  # noqa: E402
import voyage_api  # noqa: E402


def fingerprint(route: Path) -> str:
    voyage_api._ROUTE_GEOJSON = route
    voyage_api._OFFICIAL_BODY_CACHE = None
    body = voyage_api.official_itinerary_body()
    if body is None:
        raise SystemExit(f"route illisible : {route}")
    return voyage_api._route_fp(body.points, body.marks, voyage_api.OFFICIAL_T0)


def archive_keys(archive: Path) -> set[str]:
    keys = set()
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            if member.isfile() and member.name.endswith(".json"):
                doc = json.load(tf.extractfile(member))
                if doc.get("key"):
                    keys.add(str(doc["key"]))
    return keys


def main() -> int:
    archive, route = Path(sys.argv[1]), Path(sys.argv[2])
    snapshot = fingerprint(route)
    keys = archive_keys(archive)
    if not any(k.startswith(f"{snapshot}:") for k in keys):
        print(
            f"stock figé et route de recette désaccordés : route {snapshot}, "
            f"clés {sorted({k.split(':', 1)[0] for k in keys})}. "
            "Regeler les deux ensemble (scripts/freeze_official_store.py).",
            file=sys.stderr,
        )
        return 1
    published = fingerprint(ROOT / "public" / "route.geojson")
    if published != snapshot:
        print(
            f"::warning::Stock figé calculé sur la route {snapshot} ; la route publiée est {published}. "
            "La recette tourne sur la route du gel. Recalculer puis regeler le stock sur la route publiée "
            "(voir server/tests/fixtures/official_store.README.md)."
        )
    print(f"stock figé apparié : route {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
