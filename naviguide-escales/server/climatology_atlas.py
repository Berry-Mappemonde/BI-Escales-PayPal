"""Client atlas BI — GET /climatology/point (+ crossings).

kind: climatology. Zone fallback only if the API is dead / empty.
Never relabel the pack as forecast.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, Optional, Tuple

import httpx

from bi_upstream import BiDisabled, bi_base
from climatology_zones import zone_wind_at

log = logging.getLogger("naviguide-simulator.atlas")

KIND = "climatology"
TIMEOUT_S = 4.0
DEAD_S = 45.0
CELL = 0.5
MAX_WORKERS = 8
# Slow answers are treated like a dead atlas: a hot loop must never wait on
# hundreds of 2-second calls in a row.
SLOW_S = 2.5

_cache: dict[str, dict] = {}
_lock = threading.Lock()
_dead_until = 0.0


def reset_atlas_cache() -> None:
    global _dead_until
    with _lock:
        _cache.clear()
        _dead_until = 0.0


def _cell_key(lat: float, lon: float, month: int) -> str:
    la = round(round(float(lat) / CELL) * CELL, 4)
    lo = round(round(float(lon) / CELL) * CELL, 4)
    m = max(1, min(12, int(month or 1)))
    return f"{la}:{lo}:{m}"


def _mark_dead() -> None:
    global _dead_until
    _dead_until = time.time() + DEAD_S


def atlas_is_dead() -> bool:
    return time.time() < _dead_until


def _zone(lat: float, lon: float, month: int) -> Dict[str, Any]:
    pack = zone_wind_at(lat, lon, month)
    pack["source"] = "zone_fallback"
    pack["kind"] = KIND
    pack["period"] = None
    pack["doi"] = None
    return pack


def _weighted_percentile(samples: list[tuple[float, float]], q: float) -> float:
    """Percentile pondéré (q dans [0, 100]) d'une liste (valeur, poids)."""
    rows = sorted((float(v), float(w)) for v, w in samples if w > 0)
    if not rows:
        return 0.0
    total = sum(w for _v, w in rows)
    if total <= 0:
        return rows[0][0]
    target = max(0.0, min(100.0, float(q))) / 100.0 * total
    acc = 0.0
    last = rows[0][0]
    for val, weight in rows:
        acc += weight
        last = val
        if acc >= target:
            return val
    return last


def rose_speed_percentiles(rose: Optional[dict]) -> Optional[list[float]]:
    """Trois tirages p25 / p50 / p75 de la rose. None si une seule valeur."""
    if not isinstance(rose, dict):
        return None
    for keys in (("p25", "p50", "p75"), ("speed_p25", "speed_p50", "speed_p75")):
        vals = [rose.get(k) for k in keys]
        if all(v is not None for v in vals):
            try:
                return [float(v) for v in vals]
            except (TypeError, ValueError):
                pass
    samples: list[tuple[float, float]] = []
    for row in rose.get("directions_from") or []:
        if not isinstance(row, dict):
            continue
        spd, pct = row.get("speed_knots"), row.get("pct")
        if spd is None or pct is None:
            continue
        try:
            s, p = float(spd), float(pct)
        except (TypeError, ValueError):
            continue
        if p > 0:
            samples.append((s, p))
    if len(samples) < 2:
        return None
    return [
        _weighted_percentile(samples, 25),
        _weighted_percentile(samples, 50),
        _weighted_percentile(samples, 75),
    ]


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _track_sid(item: Any) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    sid = props.get("sid") or item.get("sid") or item.get("id")
    if sid:
        return str(sid)
    geom = item.get("geometry") if isinstance(item.get("geometry"), dict) else {}
    coords = item.get("coordinates") or geom.get("coordinates")
    if isinstance(coords, list) and len(coords) >= 2:
        # Une ligne = une tempête. On ne compte pas ses sommets.
        return f"line:{len(coords)}:{coords[0]}"
    return None


def ibtracs_track_count(payload: Optional[dict]) -> int:
    """Nombre de tempêtes, pas de sommets ni de copies monde.

    Les traces portant un ``sid`` (ou une ligne) priment sur le recensement
    ``tracks_in_month``, qui sert quand la liste n'est pas là. Les franchissements
    d'une jambe et le champ ``nearby`` ne sont pas un effectif de tempêtes.
    """
    if not isinstance(payload, dict):
        return 0
    cyclone = payload.get("cyclone") if isinstance(payload.get("cyclone"), dict) else {}
    tracks = None
    for key in ("tracks", "features"):
        if isinstance(cyclone.get(key), list):
            tracks = cyclone[key]
            break
    if tracks is None and isinstance(payload.get("features"), list):
        tracks = payload["features"]
    sids: list[str] = []
    for item in tracks or []:
        sid = _track_sid(item)
        if sid:
            sids.append(sid)
    if sids:
        return len(set(sids))
    census = _as_int(cyclone.get("tracks_in_month"))
    if census is not None and census > 0:
        return census
    return 0


def atlas_period(payload: Optional[dict]) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    if payload.get("period"):
        return str(payload["period"])
    periods = payload.get("periods") if isinstance(payload.get("periods"), dict) else {}
    for key in ("cyclone", "ibtracs", "wind"):
        if periods.get(key):
            return str(periods[key])
    return None


def wind_from_point(payload: Optional[dict]) -> Optional[Dict[str, Any]]:
    if not payload or payload.get("kind") != KIND:
        return None
    rose = payload.get("wind_atlas") or {}
    block = rose.get("most_likely") or rose.get("vector_mean")
    if not isinstance(block, dict) or block.get("speed_knots") is None:
        return None
    try:
        speed = float(block["speed_knots"])
        direction = float(block.get("dir_deg") or 0)
    except (TypeError, ValueError):
        return None
    wave = payload.get("wave") or {}
    current = payload.get("current") or {}
    cyclone = payload.get("cyclone") or {}
    draws = rose_speed_percentiles(rose)
    return {
        "speedKnots": speed,
        "dirFromDeg": direction,
        "source": "atlas",
        "kind": KIND,
        "period": payload.get("period") or (payload.get("periods") or {}).get("wind"),
        "doi": payload.get("doi"),
        "periods": payload.get("periods"),
        "provenance": payload.get("provenance"),
        "hs": wave.get("hs_p90_m") if wave.get("hs_p90_m") is not None else wave.get("hs_p50_m"),
        "hsP50": wave.get("hs_p50_m"),
        "hsP90": wave.get("hs_p90_m"),
        "currentKn": current.get("speed_knots"),
        "currentToDeg": current.get("direction_to_deg"),
        "roseKnots": draws,
        "cycloneNearby": cyclone.get("nearby"),
        "crossings": cyclone.get("crossings_if_leg"),
        "point": payload,
    }


def _get_json(url: str, params: dict, client: httpx.Client | None = None) -> Any:
    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT_S)
    try:
        r = http.get(url, params=params, headers={"Accept": "application/json"}, timeout=TIMEOUT_S)
        r.raise_for_status()
        return r.json()
    finally:
        if own:
            http.close()


def _atlas_params(lat: float, lon: float, month: int, dest_lat, dest_lon, day) -> dict:
    params: dict[str, Any] = {"lat": lat, "lon": lon, "month": int(month)}
    if dest_lat is not None and dest_lon is not None:
        params["dest_lat"] = dest_lat
        params["dest_lon"] = dest_lon
    if day is not None:
        params["day"] = day
    return params


def _read_atlas_point(params: dict, client: httpx.Client | None) -> tuple[Optional[dict], float]:
    """GET {BI}/climatology/point. Retourne (payload, durée en secondes)."""
    started = time.monotonic()
    try:
        base = bi_base()
        if not base:
            raise BiDisabled("BI disabled: BI_API_URL is not set")
        payload = _get_json(f"{base}/climatology/point", params, client)
    except Exception as exc:
        log.info("atlas point down: %s", exc)
        return None, 0.0
    return payload, time.monotonic() - started


def _finish_point(payload: Optional[dict], elapsed: float) -> Optional[dict]:
    if payload is None:
        _mark_dead()
        return None
    if elapsed > SLOW_S:
        log.info("atlas point slow (%.1fs): zone fallback for %ss", elapsed, DEAD_S)
        _mark_dead()
    return payload


def _point_provider(month: int, day, dest_lat, dest_lon) -> str:
    name = f"bi-climatology-m{int(month)}"
    if day is not None:
        name += f"-d{int(day)}"
    if dest_lat is not None and dest_lon is not None:
        name += f"-to-{float(dest_lat):.4f},{float(dest_lon):.4f}"
    return name


def _via_pipeline(provider: str, lat: float, lon: float, loader) -> Optional[dict]:
    """Une panne de BI n'est jamais mise en cache : la pause `_mark_dead` suffit,
    et l'appel suivant après la pause retente vraiment l'API."""
    from weather_pipeline import forget_failed_layer, get_async_weather_queue, route_snapshot

    forget_failed_layer(provider, float(lat), float(lon))
    route_snapshot(provider, float(lat), float(lon), loader)
    view = get_async_weather_queue().wait_layer(
        provider, float(lat), float(lon), timeout=TIMEOUT_S + 0.5,
    )
    if not view or view.get("status") != "ready":
        forget_failed_layer(provider, float(lat), float(lon))
    return view


def fetch_atlas_point(
    lat: float,
    lon: float,
    month: int,
    dest_lat: float | None = None,
    dest_lon: float | None = None,
    day: int | None = None,
    client: httpx.Client | None = None,
) -> Optional[dict]:
    if atlas_is_dead():
        return None
    params = _atlas_params(lat, lon, month, dest_lat, dest_lon, day)

    def loader():
        payload, elapsed = _read_atlas_point(params, client)
        if payload is None:
            raise RuntimeError("atlas_down")
        # Pause de lenteur au vrai appel seulement : une relecture en cache ne la relance pas.
        return {"payload": _finish_point(payload, elapsed)}

    view = _via_pipeline(_point_provider(month, day, dest_lat, dest_lon), lat, lon, loader)
    if not view or view.get("status") != "ready" or not isinstance(view.get("payload"), dict):
        _mark_dead()
        return None
    return view["payload"]


def fetch_atlas_crossings(
    lat1: float, lon1: float, lat2: float, lon2: float, month: int,
    day: int | None = None,
    client: httpx.Client | None = None,
) -> Optional[dict]:
    if atlas_is_dead():
        return None
    params: dict[str, Any] = {
        "lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2, "month": int(month),
    }
    if day is not None:
        params["day"] = day
    provider = f"bi-climatology-crossings-m{int(month)}"
    if day is not None:
        provider += f"-d{int(day)}"

    def loader():
        try:
            base = bi_base()
            if not base:
                raise BiDisabled("BI disabled: BI_API_URL is not set")
            payload = _get_json(f"{base}/climatology/crossings", params, client)
        except Exception as exc:
            log.info("atlas crossings down: %s", exc)
            raise
        if not isinstance(payload, dict):
            raise RuntimeError("atlas_down")
        return {"payload": payload}

    view = _via_pipeline(provider, lat1, lon1, loader)
    if not view or view.get("status") != "ready" or not isinstance(view.get("payload"), dict):
        return None
    return view["payload"]


def atlas_wind_at(
    lat: float,
    lon: float,
    month: int,
    client: httpx.Client | None = None,
) -> Dict[str, Any]:
    key = _cell_key(lat, lon, month)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit["wind"] if hit.get("wind") else _zone(lat, lon, month)
    payload = fetch_atlas_point(lat, lon, month, client=client)
    wind = wind_from_point(payload)
    with _lock:
        _cache[key] = {"point": payload, "wind": wind}
    return wind if wind else _zone(lat, lon, month)


def atlas_wind_at_dt(lat: float, lon: float, t) -> Dict[str, Any]:
    return atlas_wind_at(lat, lon, t.month)


def atlas_wind_cached(lat: float, lon: float, month: int) -> Dict[str, Any]:
    """Cache only — never touches the network. For hot loops (isochrone).

    A cell that was not prefetched falls back to the zone climatology, still
    labelled `kind: climatology`, `source: zone_fallback`.
    """
    key = _cell_key(lat, lon, month)
    with _lock:
        hit = _cache.get(key)
    if hit is not None and hit.get("wind"):
        return hit["wind"]
    return _zone(lat, lon, month)


def corridor_cells(
    coords: Iterable[Tuple[float, float]],
    months: Iterable[int],
    pad: int = 1,
) -> list[Tuple[float, float, int]]:
    """Atlas cells around a leg: each (lat, lon) plus `pad` cells on every side."""
    months = sorted({max(1, min(12, int(m))) for m in months})
    cells: list[Tuple[float, float, int]] = []
    seen: set[str] = set()
    for lat, lon in coords:
        base_lat = round(float(lat) / CELL) * CELL
        base_lon = round(float(lon) / CELL) * CELL
        for di in range(-pad, pad + 1):
            for dj in range(-pad, pad + 1):
                la = round(base_lat + di * CELL, 4)
                lo = round(base_lon + dj * CELL, 4)
                if la < -90 or la > 90:
                    continue
                for m in months:
                    key = _cell_key(la, lo, m)
                    if key in seen:
                        continue
                    seen.add(key)
                    cells.append((la, lo, m))
    return cells


def prefetch_atlas_cells(
    cells: Iterable[Tuple[float, float, int]],
    budget_s: float | None = None,
) -> int:
    """Warm the cache in parallel. Returns how many atlas hits landed.

    With `budget_s`, stops waiting once the budget is spent: the cells still
    missing will be served by the zone fallback (`atlas_wind_cached`).
    """
    todo = []
    seen = set()
    for lat, lon, month in cells:
        key = _cell_key(lat, lon, month)
        if key in seen:
            continue
        seen.add(key)
        with _lock:
            if key in _cache:
                continue
        todo.append((lat, lon, month, key))
    if not todo or atlas_is_dead():
        return 0
    hits = 0
    deadline = None if budget_s is None else time.monotonic() + max(0.0, float(budget_s))

    def one(item):
        la, lo, m, key = item
        if atlas_is_dead():
            return 0
        payload = fetch_atlas_point(la, lo, m)
        wind = wind_from_point(payload)
        with _lock:
            _cache[key] = {"point": payload, "wind": wind}
        return 1 if wind else 0

    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    futs = [pool.submit(one, item) for item in todo]
    try:
        remaining = None if deadline is None else max(0.01, deadline - time.monotonic())
        for fut in as_completed(futs, timeout=remaining):
            try:
                hits += int(fut.result())
            except Exception:
                pass
    except TimeoutError:
        log.info("atlas prefetch: budget %.1fs spent, %s cells left to zone fallback",
                 budget_s, sum(1 for f in futs if not f.done()))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return hits


def prefetch_points(points: list, months: Iterable[int]) -> int:
    cells = []
    seen = set()
    for p in points or []:
        if p.get("jump") or p.get("nonMaritime"):
            continue
        key = (round(float(p["lat"]) * 2) / 2, round(float(p["lon"]) * 2) / 2)
        if key in seen:
            continue
        seen.add(key)
        for m in months:
            cells.append((p["lat"], p["lon"], int(m)))
    return prefetch_atlas_cells(cells)


def climatology_block(
    lat: float,
    lon: float,
    month: int,
    dest_lat: float | None = None,
    dest_lon: float | None = None,
    client: httpx.Client | None = None,
) -> dict:
    """Full /point (+ crossings) for ICI / later analysis."""
    point = fetch_atlas_point(lat, lon, month, dest_lat, dest_lon, client=client)
    crossings = None
    if dest_lat is not None and dest_lon is not None:
        crossings = fetch_atlas_crossings(lat, lon, dest_lat, dest_lon, month, client=client)
    wind = wind_from_point(point)
    traces = ibtracs_track_count(point if isinstance(point, dict) else None)
    period = atlas_period(point if isinstance(point, dict) else None)
    if wind or traces:
        if crossings and isinstance(point, dict):
            cyc = dict(point.get("cyclone") or {})
            cyc["crossings_if_leg"] = crossings
            point = {**point, "cyclone": cyc, "crossings": crossings}
            traces = ibtracs_track_count(point)
        source = "atlas" if wind else "ibtracs"
        return {
            "kind": KIND,
            "status": "ready",
            "source": source,
            "month": month,
            "period": period,
            "ibtracsCount": traces,
            "doi": point.get("doi") if isinstance(point, dict) else None,
            "periods": point.get("periods") if isinstance(point, dict) else None,
            "provenance": point.get("provenance") if isinstance(point, dict) else None,
            "point": point,
            "crossings": crossings or ((point.get("cyclone") or {}).get("crossings_if_leg") if isinstance(point, dict) else None),
            "wind": {
                "speedKnots": wind["speedKnots"],
                "dirFromDeg": wind["dirFromDeg"],
                "kind": KIND,
                "source": "atlas",
            } if wind else _zone(lat, lon, month),
        }
    zone = _zone(lat, lon, month)
    empty = point is not None
    return {
        "kind": KIND,
        "status": "atlas_empty" if empty else "zone_fallback",
        "source": "empty" if empty else "zone_fallback",
        "month": month,
        "period": None,
        "ibtracsCount": 0,
        "doi": None,
        "point": point,
        "crossings": crossings,
        "wind": zone,
    }
