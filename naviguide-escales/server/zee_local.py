"""ZEE locale — point-dans-polygone sur les ZEE VLIZ v12.

Le gazetteer MarineRegions « par point » est bruité le long des côtes
(« Spanish EEZ » à La Rochelle, allers-retours ZEE / haute mer). Blue
Intelligence sert déjà à la carte la couche complète des 285 ZEE
(`GET /api/poe/zones/geojson`, Marine Regions v12, CC-BY 4.0, ~18 Mo).
Ce module la télécharge **une fois** (cache 30 j sur disque), la charge
dans un STRtree shapely et répond en local :

- `zee_at(lat, lon)` → la ZEE qui contient le point, `None` en haute mer,
  ou `UNKNOWN` tant que l'index n'est pas chargé (le gazetteer reste alors
  le repli, `sources.zee = "marineregions"`) ;
- un point à terre (global_land_mask) est « À terre (Pays) » — le pays de
  la ZEE la plus proche — sauf s'il touche une ZEE à ~12 nm (bateau à quai).

Rien d'inventé : la source est nommée (`vliz-local`), la géométrie est
celle de VLIZ, et sans fichier on garde MarineRegions.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from longitude import wrap_lon as _wrap

log = logging.getLogger("naviguide-simulator.zee-local")

UNKNOWN = object()  # index not loaded yet
CACHE_TTL_S = 30 * 86400.0
QUAY_PROBE_DEG = 0.2    # ~12 nm: a boat alongside is in its country's EEZ
COASTAL_GAP_DEG = 0.15  # ~9 nm: a bay the simplified layer cut across
COAST_PROBE_DEG = 0.25  # "near a coast" = land within ~15 nm

_LOCK = threading.RLock()
_index: dict[str, Any] = {"tree": None, "geoms": None, "props": None, "loaded": False, "features": 0, "loadedAt": None}
_loading = False


def geojson_url() -> str | None:
    from ici_engine import bi_base  # noqa: PLC0415
    base = bi_base()
    if not base:
        return None
    return f"{base}/poe/zones/geojson"


def cache_path() -> Path:
    from voyage_store import voyage_dir  # noqa: PLC0415
    return voyage_dir() / "eez_vliz_v12.geojson"


def enabled() -> bool:
    return (os.environ.get("NAVIGUIDE_ZEE_LOCAL") or "1").strip() not in ("0", "false", "no")


def status() -> dict[str, Any]:
    p = cache_path()
    return {
        "loaded": bool(_index["loaded"]),
        "features": int(_index["features"] or 0),
        "file": str(p) if p.exists() else None,
        "fileAgeDays": round((time.time() - p.stat().st_mtime) / 86400, 1) if p.exists() else None,
        "loadedAt": _index["loadedAt"],
    }


def reset() -> None:
    with _LOCK:
        _index.update({"tree": None, "geoms": None, "props": None, "loaded": False, "features": 0, "loadedAt": None})


# ── loading ─────────────────────────────────────────────────────────────────

def _props_of(feat: dict) -> dict:
    p = feat.get("properties") or {}
    try:
        mrgid = int(p.get("mrgid") or 0) or None
    except (TypeError, ValueError):
        mrgid = None
    return {
        "mrgid": mrgid,
        "name": p.get("geoname") or p.get("name") or "ZEE",
        "country": p.get("name") or p.get("sovereign") or None,
        "sovereign": p.get("sovereign") or None,
        "iso2": p.get("iso2") or None,
        "polType": p.get("pol_type") or None,
    }


def load_from_file(path: Optional[Path] = None) -> int:
    """Build the index from the cached GeoJSON. Returns the feature count (0 = nothing)."""
    import shapely  # noqa: PLC0415
    from shapely.geometry import shape  # noqa: PLC0415
    from shapely.strtree import STRtree  # noqa: PLC0415

    path = path or cache_path()
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("ZEE locale : fichier illisible (%s)", exc)
        return 0
    geoms, props = [], []
    for feat in data.get("features") or []:
        try:
            g = shape(feat["geometry"])
        except Exception:
            continue
        if g.is_empty:
            continue
        shapely.prepare(g)
        geoms.append(g)
        props.append(_props_of(feat))
    if not geoms:
        return 0
    tree = STRtree(geoms)
    with _LOCK:
        _index.update({"tree": tree, "geoms": geoms, "props": props, "loaded": True,
                       "features": len(geoms), "loadedAt": time.time()})
    log.info("ZEE locale : %d polygones VLIZ chargés", len(geoms))
    return len(geoms)


async def ensure_loaded(client=None, force_download: bool = False) -> bool:
    """Download the layer if missing or stale (30 d), then load it. Never raises."""
    global _loading
    if not enabled():
        return False
    if _index["loaded"] and not force_download:
        return True
    import asyncio  # noqa: PLC0415
    # Another task is already loading: wait for it instead of racing it.
    waited = 0.0
    while _loading and waited < 300.0:
        await asyncio.sleep(0.5)
        waited += 0.5
    if _index["loaded"] and not force_download:
        return True
    with _LOCK:
        if _loading:
            return False
        _loading = True
    try:
        path = cache_path()
        stale = (not path.exists()) or (time.time() - path.stat().st_mtime > CACHE_TTL_S)
        if stale or force_download:
            try:
                url = geojson_url()
                if not url:
                    raise RuntimeError("BI disabled: BI_API_URL is not set")
                import httpx  # noqa: PLC0415
                own = client is None
                http = client or httpx.AsyncClient()
                try:
                    r = await http.get(url, timeout=120.0, headers={"Accept": "application/geo+json"})
                    r.raise_for_status()
                    body = r.content
                    if len(body) < 10_000 or b'"features"' not in body[:200_000] and b'"features"' not in body:
                        raise ValueError("réponse sans features")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(".tmp")
                    tmp.write_bytes(body)
                    tmp.replace(path)
                    log.info("ZEE locale : couche VLIZ téléchargée (%.1f Mo)", len(body) / 1e6)
                finally:
                    if own:
                        await http.aclose()
            except Exception as exc:
                log.warning("ZEE locale : téléchargement impossible (%s) — MarineRegions en repli", exc)
        # Parsing 18 MB of GeoJSON and preparing 285 polygons takes seconds:
        # off the event loop, the API keeps answering meanwhile.
        import asyncio  # noqa: PLC0415
        n = await asyncio.to_thread(load_from_file, path)
        return n > 0
    finally:
        with _LOCK:
            _loading = False


def start_background(loop=None) -> bool:
    """Server startup: load (or download) the layer in the background — never
    on the event loop, never blocking the first requests."""
    if not enabled():
        return False
    try:
        import asyncio  # noqa: PLC0415
        loop = loop or asyncio.get_event_loop()
        loop.create_task(ensure_loaded())
        return True
    except Exception as exc:
        log.warning("ZEE locale : tâche de fond non lancée : %s", exc)
        return False


# ── lookup ──────────────────────────────────────────────────────────────────

def _zee_dict(p: dict) -> dict:
    from ici_engine import FRENCH_EEZ_MRGID  # noqa: PLC0415
    mrgid = p.get("mrgid")
    return {
        "name": p.get("name") or "ZEE",
        "mrgid": mrgid,
        "territory": FRENCH_EEZ_MRGID.get(mrgid) if mrgid is not None else None,
        "gold": False,
        "country": p.get("country"),
    }


def _containing(lon: float, lat: float) -> Optional[dict]:
    """EEZ that contains the point. When several polygons overlap (a huge
    neighbour spilling over a smaller one — Adelaide over Nouméa), the
    smallest polygon is the one the point is actually in."""
    from shapely.geometry import Point  # noqa: PLC0415
    tree, geoms, props = _index["tree"], _index["geoms"], _index["props"]
    pt = Point(lon, lat)
    hits = []
    for i in tree.query(pt):
        if geoms[i].contains(pt) or geoms[i].intersects(pt):
            hits.append(int(i))
    if not hits:
        return None
    best = min(hits, key=lambda i: float(geoms[i].area))
    return props[best]


def _nearest(lon: float, lat: float) -> Optional[dict]:
    from shapely.geometry import Point  # noqa: PLC0415
    tree, props = _index["tree"], _index["props"]
    try:
        i = tree.nearest(Point(lon, lat))
    except Exception:
        return None
    return props[int(i)] if i is not None else None


def _nearest_within(lon: float, lat: float, max_deg: float) -> Optional[dict]:
    from shapely.geometry import Point  # noqa: PLC0415
    tree, geoms, props = _index["tree"], _index["geoms"], _index["props"]
    pt = Point(lon, lat)
    try:
        i = tree.nearest(pt)
    except Exception:
        return None
    if i is None:
        return None
    i = int(i)
    return props[i] if geoms[i].distance(pt) <= max_deg else None


def _near_coast(lat: float, lon: float, is_land, step: float = COAST_PROBE_DEG) -> bool:
    for dlat, dlon in ((0, -step), (0, step), (-step, 0), (step, 0), (-step, -step), (-step, step), (step, -step), (step, step)):
        try:
            if is_land(lat + dlat, _wrap(lon + dlon)):
                return True
        except Exception:
            continue
    return False


def zee_at(lat: float, lon: float):
    """The EEZ containing the point (dict), None for high seas, an « À terre »
    dict on land, or UNKNOWN while the index is not loaded."""
    if not _index["loaded"]:
        return UNKNOWN
    lon = _wrap(float(lon))
    lat = float(lat)
    hit = _containing(lon, lat)
    if hit is not None:
        return _zee_dict(hit)
    try:
        from isochrone import is_land  # noqa: PLC0415
        land = is_land(lat, lon)
    except Exception:
        def is_land(_lat, _lon):  # noqa: E306
            return False
        land = False
    if not land:
        # The layer served to the map is simplified: a bay or a harbour can
        # fall just outside its own EEZ. Water near a coast that sits within
        # ~9 nm of an EEZ polygon belongs to it — the true 200 nm limit is
        # never that close to land.
        near = _nearest_within(lon, lat, COASTAL_GAP_DEG)
        if near is not None and _near_coast(lat, lon, is_land):
            return _zee_dict(near)
    if land:
        # A boat alongside sits on the land mask: probe ~12 nm around.
        s = QUAY_PROBE_DEG
        for dlat, dlon in ((0, -s), (0, s), (-s, 0), (s, 0), (-s, -s), (-s, s), (s, -s), (s, s)):
            near = _containing(_wrap(lon + dlon), lat + dlat)
            if near is not None and not is_land(lat + dlat, _wrap(lon + dlon)):
                return _zee_dict(near)
        p = _nearest(lon, lat)
        country = (p or {}).get("country") or (p or {}).get("sovereign")
        return {
            "name": f"À terre ({country})" if country else "À terre",
            "mrgid": None,
            "territory": None,
            "gold": False,
            "ashore": True,
        }
    return None


def zee_at_payload(lat: float, lon: float) -> dict:
    """JSON for the film timestep: the EEZ at the replayed position.
    UNKNOWN stays unknown — never rewritten as high seas."""
    hit = zee_at(lat, lon)
    if hit is UNKNOWN:
        return {"unknown": True, "name": None, "mrgid": None, "territory": None, "gold": False}
    if hit is None:
        return {"name": "Haute mer", "mrgid": None, "territory": None, "gold": False}
    return hit


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
