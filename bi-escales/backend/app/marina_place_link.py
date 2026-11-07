"""Google Maps /place/ guard for stopover marinas.

Adapted from Blue-Intelligence-V3 ``marina_maps_place.py`` (place URL parsing,
``NON_MARINA_RE``, ``haversine_m``). Escales uses a 1 km cap (Clément 19:43).
"""
from __future__ import annotations

import re
from math import asin, cos, radians, sin, sqrt
from urllib.parse import unquote, urlparse

MAX_PLACE_DISTANCE_M = 1000.0

PLACE_PATH_RE = re.compile(r"/maps/place/", re.I)
SEARCH_PATH_RE = re.compile(r"/maps/search/", re.I)
COORDS_RE = re.compile(r"/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
DATA_COORDS_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
SUSPICIOUS_PLACE_RE = re.compile(
    r"\b("
    r"auto[\s-]?[ée]coles?|"
    r"bateaux?[\s-]?[ée]coles?|"
    r"driving\s+school|restaurant|hotel|hôtel|pizzeria|café|cafe|"
    r"brasserie|nightclub|bar"
    r")\b",
    re.I,
)


def google_maps_search_url(lat: float, lon: float) -> str:
    return (
        f"https://www.google.com/maps/search/?api=1&query={float(lat):.5f}%2C{float(lon):.5f}"
    )


def is_google_place_url(url: str | None) -> bool:
    raw = (url or "").strip()
    if not raw.startswith("http"):
        return False
    if SEARCH_PATH_RE.search(raw):
        return False
    host = (urlparse(raw).hostname or "").lower()
    if "google." not in host:
        return False
    return bool(PLACE_PATH_RE.search(raw))


def place_coords_from_url(url: str | None) -> tuple[float, float] | None:
    raw = unquote(url or "")
    match = COORDS_RE.search(raw) or DATA_COORDS_RE.search(raw)
    if not match:
        return None
    try:
        return float(match.group(1)), float(match.group(2))
    except (TypeError, ValueError):
        return None


def place_slug_from_url(url: str | None) -> str:
    path = unquote(urlparse(url or "").path or "")
    parts = [p for p in path.split("/") if p]
    try:
        idx = next(i for i, p in enumerate(parts) if p.lower() == "place")
        slug = parts[idx + 1] if idx + 1 < len(parts) else ""
    except StopIteration:
        slug = ""
    return slug.replace("+", " ")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlon1, rlat2, rlon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = sin(dlat / 2) ** 2 + cos(rlat1) * cos(rlat2) * sin(dlon / 2) ** 2
    return 2 * 6371000 * asin(sqrt(a))


def evaluate_google_place_link(marina: dict) -> dict:
    lat = marina.get("lat")
    lon = marina.get("lon")
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        lat_f = lon_f = float("nan")

    if lat_f == lat_f and lon_f == lon_f:
        search = google_maps_search_url(lat_f, lon_f)
    else:
        search = None

    candidate = marina.get("maps_place_url") or marina.get("maps_url")
    if candidate and not is_google_place_url(str(candidate)):
        candidate = None

    if not candidate:
        return {"safe_place": False, "maps_link": search, "rejected_reason": None}

    blob = f"{place_slug_from_url(str(candidate))} {unquote(str(candidate))}"
    if SUSPICIOUS_PLACE_RE.search(blob):
        return {
            "safe_place": False,
            "maps_link": search,
            "rejected_reason": "suspicious_name",
        }

    coords = place_coords_from_url(str(candidate))
    if coords and lat_f == lat_f and lon_f == lon_f:
        if haversine_m(lat_f, lon_f, coords[0], coords[1]) > MAX_PLACE_DISTANCE_M:
            return {
                "safe_place": False,
                "maps_link": search,
                "rejected_reason": "distance",
            }

    return {"safe_place": True, "maps_link": str(candidate), "rejected_reason": None}


def apply_maps_place_policy(row: dict) -> dict:
    out = dict(row)
    ev = evaluate_google_place_link(out)
    if ev.get("maps_link"):
        out["maps_url"] = ev["maps_link"]
    if ev.get("safe_place"):
        out["safe_google_place"] = True
    else:
        out.pop("safe_google_place", None)
        if ev.get("rejected_reason"):
            out["maps_place_rejected"] = ev["rejected_reason"]
        else:
            out.pop("maps_place_rejected", None)
    return out
