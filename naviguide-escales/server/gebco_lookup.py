"""Sondage GEBCO au large pour le sac `ici()`.

Pas de grille NetCDF sur le VPS (plan H5 : lookup point).
Source : OpenTopoData (GEBCO 2020). Attribution : GEBCO Compilation Group.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

COASTAL_CUTOFF_NM = 20
OPENTOPO_URL = "https://api.opentopodata.org/v1/gebco2020"
USER_AGENT = "NAVIGUIDE-simulator/0.2 (Berry-Mappemonde expedition)"
CACHE_TTL_S = 6 * 3600
CACHE_MAX = 256

_cache: dict[tuple[float, float], tuple[float, float]] = {}


def reset_gebco_cache() -> None:
    _cache.clear()


def cache_cell(lat: float, lon: float) -> tuple[float, float]:
    return (round(float(lat), 1), round(float(lon), 1))


def min_coast_nm(dossier: dict[str, Any]) -> float | None:
    """Proxy rivage : marina / capitainerie / WPI déjà dans le sac."""
    dists: list[float] = []
    nearby = dossier.get("nearby") or {}
    for key in ("marinas", "capitaineries", "wpi", "anchorages"):
        for place in nearby.get(key) or []:
            nm = place.get("nm")
            if isinstance(nm, (int, float)):
                dists.append(float(nm))
    return min(dists) if dists else None


async def fetch_gebco_elevation(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
) -> float | None:
    key = cache_cell(lat, lon)
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[0] < CACHE_TTL_S:
        return hit[1]
    try:
        resp = await client.get(
            OPENTOPO_URL,
            params={"locations": f"{lat:.5f},{lon:.5f}"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=8.0,
        )
        if resp.status_code != 200:
            return None
        rows = (resp.json() or {}).get("results") or []
        elev = rows[0].get("elevation") if rows else None
        if not isinstance(elev, (int, float)):
            return None
        value = float(elev)
    except Exception:
        return None
    if len(_cache) >= CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (now, value)
    return value


async def attach_depth_offshore(
    dossier: dict[str, Any],
    client: httpx.AsyncClient,
) -> None:
    sources = dossier.setdefault("sources", {})
    at = dossier.get("at") or {}
    lat, lon = at.get("lat"), at.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        dossier["depthOffshore"] = None
        sources["gebco"] = None
        return

    dist = min_coast_nm(dossier)
    if dist is not None and dist < COASTAL_CUTOFF_NM:
        dossier["depthOffshore"] = None
        sources["gebco"] = "coastal"
        return

    elev = await fetch_gebco_elevation(client, float(lat), float(lon))
    if elev is None:
        dossier["depthOffshore"] = None
        sources["gebco"] = "unavailable"
        return
    if elev >= 0:
        dossier["depthOffshore"] = None
        sources["gebco"] = "land"
        return
    dossier["depthOffshore"] = round(elev, 1)
    sources["gebco"] = "ok"
