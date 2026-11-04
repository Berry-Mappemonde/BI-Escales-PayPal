"""Entry / Speed ProtectedSeas → circulation plaisance.

0 autorisé, 1 interdit, 2 restreint, 3 inconnu.
Interdit = entry 1 ou speed 1 (pas de transit).
Régulé = entry 2 ou speed 2.
"""
from __future__ import annotations

from typing import Any


def as_activity(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n in (0, 1, 2, 3) else None


def traffic_kind(entry: Any, speed: Any) -> str:
    e = as_activity(entry)
    s = as_activity(speed)
    if e == 1 or s == 1:
        return "forbidden"
    if e == 2 or s == 2:
        return "regulated"
    if e == 0 and s in (None, 0, 3):
        return "allowed"
    if e is None and s == 0:
        return "allowed"
    return "unknown"


def is_forbidden_pleasure(entry: Any, speed: Any) -> bool:
    return traffic_kind(entry, speed) == "forbidden"


def is_regulated_pleasure(entry: Any, speed: Any) -> bool:
    return traffic_kind(entry, speed) == "regulated"


def _ring_bbox(ring) -> tuple[float, float, float, float] | None:
    lons, lats = [], []
    for pt in ring or []:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        try:
            lons.append(float(pt[0]))
            lats.append(float(pt[1]))
        except (TypeError, ValueError):
            continue
    if not lons:
        return None
    return min(lons), min(lats), max(lons), max(lats)


def geom_bbox(geom: dict | None) -> tuple[float, float, float, float] | None:
    if not isinstance(geom, dict):
        return None
    kind = geom.get("type")
    coords = geom.get("coordinates") or []
    boxes = []
    if kind == "Polygon" and coords:
        box = _ring_bbox(coords[0])
        if box:
            boxes.append(box)
    elif kind == "MultiPolygon":
        for poly in coords:
            if poly:
                box = _ring_bbox(poly[0])
                if box:
                    boxes.append(box)
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _in_bbox(lon: float, lat: float, box: tuple[float, float, float, float] | None) -> bool:
    if not box:
        return False
    return box[0] <= lon <= box[2] and box[1] <= lat <= box[3]


def point_in_ring(lon: float, lat: float, ring) -> bool:
    pts = []
    for pt in ring or []:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        try:
            pts.append((float(pt[0]), float(pt[1])))
        except (TypeError, ValueError):
            continue
    if len(pts) < 3:
        return False
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return False
    inside = False
    j = len(pts) - 1
    for i, (xi, yi) in enumerate(pts):
        xj, yj = pts[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def point_in_polygon(lon: float, lat: float, coords) -> bool:
    if not coords:
        return False
    if not point_in_ring(lon, lat, coords[0]):
        return False
    for hole in coords[1:]:
        if point_in_ring(lon, lat, hole):
            return False
    return True


def point_in_geom(lon: float, lat: float, geom: dict | None) -> bool:
    if not isinstance(geom, dict):
        return False
    kind = geom.get("type")
    coords = geom.get("coordinates")
    if kind == "Polygon":
        return point_in_polygon(lon, lat, coords)
    if kind == "MultiPolygon":
        return any(point_in_polygon(lon, lat, poly) for poly in (coords or []))
    return False
