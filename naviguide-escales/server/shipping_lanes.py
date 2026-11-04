"""Couloirs cargos (boîtes AIS simplifiées) et score anti-trafic.

Source : naviguide/naviguide-api/routing_ab/cargo.py (SHIPPING_LANES,
point_lane_weight, anti_shipping_score, lane_hits). 1,0 = hors des
couloirs, 0,0 = dedans. Métadonnée seulement — le trait n'est pas décalé.
"""

from __future__ import annotations

from typing import Iterable, Sequence

# (lon_min, lat_min, lon_max, lat_max, weight, name)
ShippingBox = tuple[float, float, float, float, float, str]

SHIPPING_LANES: tuple[ShippingBox, ...] = (
    (-1.0, 50.0, 3.0, 52.0, 0.95, "Dover Strait"),
    (0.0, 52.0, 10.0, 57.0, 0.75, "North Sea"),
    (-10.0, 43.0, 0.0, 48.0, 0.50, "Bay of Biscay"),
    (-7.0, 35.0, -4.0, 37.0, 0.90, "Gibraltar"),
    (0.0, 37.0, 15.0, 43.0, 0.65, "Western Med"),
    (30.0, 12.0, 45.0, 30.0, 0.85, "Red Sea"),
    (42.0, 10.0, 57.0, 16.0, 0.80, "Gulf of Aden"),
    (50.0, -10.0, 80.0, 10.0, 0.50, "Indian Ocean W"),
    (98.0, 1.0, 110.0, 7.0, 0.95, "Malacca"),
    (105.0, 5.0, 122.0, 22.0, 0.70, "South China Sea"),
    (15.0, -36.0, 30.0, -28.0, 0.55, "Cape approaches"),
    (-85.0, 7.0, -76.0, 12.0, 0.70, "Caribbean W"),
    (-70.0, 38.0, -10.0, 50.0, 0.65, "N Atlantic main"),
    (145.0, -20.0, 160.0, -10.0, 0.55, "Coral Sea lane"),
    (141.0, -12.0, 144.0, -9.0, 0.40, "Torres commercial"),
)


def _in_box(lon: float, lat: float, box: ShippingBox) -> bool:
    lon_min, lat_min, lon_max, lat_max, _weight, _name = box
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def point_lane_weight(lon: float, lat: float) -> float:
    """Poids max du couloir cargo qui contient le point (0 si aucun)."""
    weight = 0.0
    for box in SHIPPING_LANES:
        if _in_box(lon, lat, box):
            weight = max(weight, box[4])
    return weight


def anti_shipping_score(coords: Sequence[Sequence[float]]) -> float:
    """1.0 = hors couloirs, 0.0 = entièrement dans un couloir dense."""
    flat = [c[:2] for c in coords if len(c) >= 2]
    if not flat:
        return 1.0
    step = max(1, len(flat) // 50)
    sampled = flat[::step]
    total = 0.0
    for lon, lat in sampled:
        total += point_lane_weight(lon, lat)
    avg = total / len(sampled)
    return round(max(0.0, 1.0 - avg), 4)


def lane_hits(coords: Iterable[Sequence[float]]) -> list[str]:
    names: set[str] = set()
    for pt in coords:
        if len(pt) < 2:
            continue
        lon, lat = pt[0], pt[1]
        for box in SHIPPING_LANES:
            if _in_box(lon, lat, box):
                names.add(box[5])
    return sorted(names)


def anti_shipping_of(coords: Sequence[Sequence[float]] | None) -> dict:
    """Métadonnée d'une jambe : {score, lanes[]} — pas de géométrie."""
    seq = coords or []
    return {"score": anti_shipping_score(seq), "lanes": lane_hits(seq)}


def anti_shipping_at(lat: float, lon: float, when=None) -> dict | None:
    """Point unique pour l'évaluateur (R10a, alerte traffic poids 1)."""
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    lanes = lane_hits(((lo, la),))
    if not lanes:
        return None
    return {"score": round(max(0.0, 1.0 - point_lane_weight(lo, la)), 4), "lanes": lanes}


def attach_anti_shipping(route: dict | None) -> dict | None:
    """Pose properties.antiShipping. Ne touche pas geometry.coordinates."""
    if not isinstance(route, dict):
        return route
    geom = route.get("geometry") if isinstance(route.get("geometry"), dict) else {}
    coords = geom.get("coordinates") if isinstance(geom.get("coordinates"), list) else []
    props = route.get("properties")
    if not isinstance(props, dict):
        props = {}
        route["properties"] = props
    props["antiShipping"] = anti_shipping_of(coords)
    return route
