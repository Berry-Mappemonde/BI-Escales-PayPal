"""wind_fn(lat, lon, t) : hindcast (passé), prévision 0–7 j depuis maintenant, fondu 7–10 j, climatologie ensuite."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from climatology_atlas import atlas_wind_at, atlas_wind_cached
from forecast_cube import ForecastCube
from voyage_clock import parse_iso

FORECAST_FULL_HOURS = 7 * 24
FORECAST_BLEND_END_HOURS = 10 * 24

HindcastFn = Callable[[float, float, datetime], Optional[Dict[str, Any]]]


def _hours_since(origin: datetime, t: datetime) -> float:
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    if origin.tzinfo is None:
        origin = origin.replace(tzinfo=timezone.utc)
    return (t - origin).total_seconds() / 3600.0


def _blend_dir(a: float, b: float, w: float) -> float:
    """w = poids de b (0 = a, 1 = b). Plus courte arc."""
    d = (b - a + 540) % 360 - 180
    return (a + d * w + 360) % 360


def _as_dt(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = parse_iso(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _climo(lat: float, lon: float, t: datetime, atlas_network: bool) -> Dict[str, Any]:
    pack = atlas_wind_at(lat, lon, t.month) if atlas_network else atlas_wind_cached(lat, lon, t.month)
    pack = {**pack, "hs": pack.get("hs"), "regime": pack.get("kind") or "climatology"}
    return pack


def blended_wind(
    lat: float,
    lon: float,
    t: datetime,
    t0: datetime | str,
    cube: Optional[ForecastCube],
    *,
    atlas_network: bool = True,
    now: datetime | str | None = None,
    hindcast_fn: Optional[HindcastFn] = None,
) -> Dict[str, Any]:
    """`now` = heure du calcul. Passé = hindcast ; fondu 7→10 j relatif à maintenant.

    `t0` est conservé (départ de l'horloge) mais n'entre plus dans le fondu.
    `atlas_network=False`: cache-only climatology (hot loops prefetch first).
    """
    del t0  # fondu relatif à maintenant, plus à t0
    now_d = _as_dt(now) if now is not None else datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    t = t.astimezone(timezone.utc)

    if t < now_d:
        if hindcast_fn is not None:
            try:
                h = hindcast_fn(lat, lon, t)
            except Exception:
                h = None
            if h and h.get("speedKnots") is not None:
                return {
                    **h,
                    "kind": "hindcast",
                    "regime": "hindcast",
                    "sources": list(h.get("sources") or []),
                    "spread": h.get("spread"),
                }
        climo = _climo(lat, lon, t, atlas_network)
        return {**climo, "hs": None, "kind": "climatology", "regime": "climatology", "reason": "hindcast_empty"}

    hours = _hours_since(now_d, t)
    climo = _climo(lat, lon, t, atlas_network)

    if cube is None or hours > FORECAST_BLEND_END_HOURS:
        return {**climo, "hs": None}

    fc = cube.at(lat, lon, t)
    if fc is None:
        return {**climo, "reason": "no_forecast_cell", "hs": None}

    if hours < FORECAST_FULL_HOURS:
        return {**fc, "regime": fc.get("kind") or "forecast"}

    w = (hours - FORECAST_FULL_HOURS) / float(FORECAST_BLEND_END_HOURS - FORECAST_FULL_HOURS)
    w = max(0.0, min(1.0, w))
    kind = "forecast" if w < 1 else "climatology"
    return {
        "speedKnots": fc["speedKnots"] * (1 - w) + climo["speedKnots"] * w,
        "dirFromDeg": _blend_dir(fc["dirFromDeg"], climo["dirFromDeg"], w),
        "hs": fc.get("hs"),
        "uo": fc.get("uo"),
        "vo": fc.get("vo"),
        "kind": kind,
        "regime": kind,
        "model": fc.get("model"),
        "leadHours": fc.get("leadHours"),
        "source": "blend",
        "blend": round(w, 3),
    }


def make_wind_fn(
    t0: datetime | str,
    cube: Optional[ForecastCube],
    *,
    atlas_network: bool = True,
    now: datetime | str | None = None,
    hindcast_fn: Optional[HindcastFn] = None,
):
    t0d = parse_iso(t0) if not isinstance(t0, datetime) else t0
    now_d = _as_dt(now) if now is not None else datetime.now(timezone.utc)

    def wind_fn(lat: float, lon: float, t: datetime) -> Dict[str, Any]:
        return blended_wind(
            lat, lon, t, t0d, cube,
            atlas_network=atlas_network, now=now_d, hindcast_fn=hindcast_fn,
        )
    return wind_fn
