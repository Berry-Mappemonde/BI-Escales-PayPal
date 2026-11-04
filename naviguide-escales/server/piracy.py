"""Zones de piraterie (boîtes IMB / UKMTO) — N4.

Table versionnée : pas de score composite, pas de CYCLONE_BASINS.
Boîtes reprises de naviguide/naviguide_workspace/naviguide_agent3/risk_engine.py
``PIRACY_ZONES`` (l. 22-33). Le brief N4 citait l. 42-49 : ce sont
``CYCLONE_BASINS`` dans le fichier actuel — on ne les copie pas.
CRITICAL de l'ancien moteur est ramené à HIGH (R10a : 3 / 2 / 1).
Les océans LOW de fond (Atlantique nord, Méditerranée, Pacifique sud,
Caraïbes « rare ») sont exclus : Aden → HIGH, Atlantique nord → rien.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from longitude import wrap_lon as _wrap_lon

_DATA = Path(__file__).resolve().parent / "data" / "piracy_zones.json"
_LEVEL_RANK = {"HIGH": 3, "MEDIUM": 2, "MED": 2, "LOW": 1}


@lru_cache(maxsize=1)
def load_table() -> dict:
    with _DATA.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def zones() -> list[dict]:
    raw = load_table().get("zones") or []
    return [z for z in raw if isinstance(z, dict) and z.get("name")]


def _in_box(lat: float, lon: float, zone: dict) -> bool:
    try:
        return (
            float(zone["lat_min"]) <= lat <= float(zone["lat_max"])
            and float(zone["lon_min"]) <= lon <= float(zone["lon_max"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def _area(zone: dict) -> float:
    try:
        return abs(float(zone["lat_max"]) - float(zone["lat_min"])) * abs(
            float(zone["lon_max"]) - float(zone["lon_min"])
        )
    except (KeyError, TypeError, ValueError):
        return float("inf")


def _norm_level(raw: object) -> str:
    token = str(raw or "LOW").strip().upper()
    if token in {"CRITICAL", "CRIT"}:
        return "HIGH"
    if token in {"MODERATE", "MED", "MEDIUM"}:
        return "MEDIUM"
    if token == "HIGH":
        return "HIGH"
    return "LOW"


def zone_at(lat: float, lon: float, when=None) -> dict | None:
    """Zone unique au point, ou None. Forme ``{name, level, source}`` (sac + R10a)."""
    del when  # accepté pour plan_alerts._hook(lat, lon, when)
    try:
        la, lo = float(lat), _wrap_lon(lon)
    except (TypeError, ValueError):
        return None
    if not -90.0 <= la <= 90.0:
        return None
    hits = [z for z in zones() if _in_box(la, lo, z)]
    if not hits:
        return None
    hits.sort(key=lambda z: (-_LEVEL_RANK.get(_norm_level(z.get("level")), 1), _area(z)))
    chosen = hits[0]
    table_src = load_table().get("source") or "IMB/UKMTO"
    return {
        "name": str(chosen["name"]),
        "level": _norm_level(chosen.get("level")),
        "source": str(chosen.get("source") or table_src),
    }


def attach_piracy(bag: dict | None, lat: float | None = None, lon: float | None = None) -> dict | None:
    """Pose ``piracy: {name, level, source}`` ou ``None``. Ne touche pas le reste."""
    if not isinstance(bag, dict):
        return bag
    at = bag.get("at") if isinstance(bag.get("at"), dict) else {}
    la = lat if lat is not None else at.get("lat")
    lo = lon if lon is not None else at.get("lon")
    if la is None or lo is None:
        bag["piracy"] = None
        return bag
    bag["piracy"] = zone_at(la, lo)
    return bag
