"""Table d’horloge — même algo que src/engine/voyageClock.js (contrat A = B)."""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from climatology_atlas import atlas_wind_at_dt, prefetch_points
from climatology_zones import boat_speed_from_wind
# Plus court arc, résultat replié : -180 puis 179.85 ne traverse pas le globe.
from longitude import delta_lon, interp_lon_shortest as _lerp_lon, wrap_lon as _wrap_lon

_PORT_DAYS_PATH = Path(__file__).resolve().parent / "data" / "port_days.json"
_PORT_DAYS_CACHE: Optional[dict] = None

AIR_CALENDAR_HOURS = 8.0
LAND_CALENDAR_HOURS = 4.0
MIN_KNOTS = 0.5
# Paire de sauts aller / retour : le second atterrit près du départ du premier (filmCast.js).
AIR_HOP_RETURN_NM = 80.0
HUB_STOP_NAME = "Halifax (Nouvelle-Écosse)"
VIA_STOP_NAME = "Saint-Pierre (Saint-Pierre-et-Miquelon)"
PARK_STOP_NAME = "Cayenne (Guyane)"
# Port réel (route officielle), pas un sommet de mer voisin.
SAINT_PIERRE_LAT = 46.7761
SAINT_PIERRE_LON = -56.1628
WAVE_NOGO_M = 2.5
# WAVE_NOGO_DT_FACTOR (×3 dès 2,5 m) retiré C4 — voir wave_polar_factor.
MAX_STEP_NM = 30.0
MAX_STEP_H = 1.0
OFFICIAL_VOYAGE_ID = "berry-mappemonde-2026-officiel"
OFFICIAL_T0 = "2026-05-15T08:00:00Z"
DEFAULT_BMAP_PORT_DAYS = 3
PLANNING_MIN_KN = 3.0
POLAR_EFFICIENCY_DEFAULT = 0.85
MS_TO_KN = 1.943844
WAVE_POLAR_HS_FLAT_M = 1.5
WAVE_POLAR_HS_FULL_M = 4.0
WAVE_POLAR_HEAD = 0.6
WAVE_POLAR_FOLLOW = 0.85
TWA_CLOSE_HAULED_MIN = 40.0
TWA_RUNNING_MAX = 170.0

WindFn = Callable[[float, float, datetime], Dict[str, Any]]


class WindExhausted(Exception):
    """Levée par un wind_fn strict : plus de vent RÉEL à cette date.

    `build_voyage_clock` s'arrête proprement au dernier pas complet et pose
    `truncated` sur l'horloge — jamais un vent inventé à la place."""

    def __init__(self, reason: Optional[str] = None):
        super().__init__(reason or "vent réel épuisé")
        self.reason = reason


def _norm_stop(name: str) -> str:
    return re.sub(r"[\s\-]+", "-", (name or "").strip().lower())


def port_days_table() -> dict:
    """Table sourcée (`server/data/port_days.json`). Valeurs = convention actuelle."""
    global _PORT_DAYS_CACHE
    if _PORT_DAYS_CACHE is not None:
        return _PORT_DAYS_CACHE
    try:
        raw = json.loads(_PORT_DAYS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        raw = {
            "default": DEFAULT_BMAP_PORT_DAYS,
            "source": "programme Berry-Mappemonde 2026",
            "stops": {"Saint-Maur": 0, "La Rochelle": 3, "Halifax": 1},
        }
    if not isinstance(raw, dict):
        raw = {"default": DEFAULT_BMAP_PORT_DAYS, "source": "", "stops": {}}
    raw.setdefault("default", DEFAULT_BMAP_PORT_DAYS)
    raw.setdefault("stops", {})
    _PORT_DAYS_CACHE = raw
    return raw


def port_days_for(name: str) -> int:
    table = port_days_table()
    n = _norm_stop(name)
    best_days: Optional[int] = None
    best_len = -1
    for key, days in (table.get("stops") or {}).items():
        k = _norm_stop(str(key))
        if k and k in n and len(k) > best_len:
            try:
                best_days = int(days)
            except (TypeError, ValueError):
                continue
            best_len = len(k)
    if best_days is not None:
        return best_days
    try:
        return int(table.get("default", DEFAULT_BMAP_PORT_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_BMAP_PORT_DAYS


def official_clock_params() -> dict:
    """Constantes d'horloge exposées par GET /voyage/official (`params`)."""
    table = port_days_table()
    try:
        port_default = int(table.get("default", DEFAULT_BMAP_PORT_DAYS))
    except (TypeError, ValueError):
        port_default = DEFAULT_BMAP_PORT_DAYS
    return {
        "landHours": LAND_CALENDAR_HOURS,
        "airHours": AIR_CALENDAR_HOURS,
        "minKnots": MIN_KNOTS,
        "portDaysDefault": port_default,
        "polarEfficiency": polar_efficiency(),
    }


def parse_iso(iso: str) -> datetime:
    raw = str(iso).replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlon = delta_lon(lon1, lon2)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(dlon)
    y = math.sin(dl) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def twa_deg(heading: float, wind_from: float) -> float:
    h = ((heading % 360) + 360) % 360
    w = ((wind_from % 360) + 360) % 360
    raw = abs(w - h)
    return 360 - raw if raw > 180 else raw


def _bracket(val: float, arr: List[float]) -> tuple[int, int]:
    if not arr:
        return 0, 0
    if val <= arr[0]:
        return 0, 0
    last = len(arr) - 1
    if val >= arr[last]:
        return last, last
    for i in range(last):
        if val <= arr[i + 1]:
            return i, i + 1
    return last, last


def polar_boat_speed(raw: Optional[dict], twa: float, tws: float) -> Optional[float]:
    if not raw:
        return None
    rows = [float(x) for x in (raw.get("twa_rows") or [])]
    cols = [float(x) for x in (raw.get("tws_cols") or [])]
    matrix = raw.get("matrix") or []
    if not rows or not cols or not matrix:
        return None
    a = abs(float(twa))
    w = float(tws)
    if w <= 0 or a <= 0:
        return 0.0
    a = min(180.0, a)
    tws_max = cols[-1]
    eff_w = min(w, tws_max)
    twa_min = rows[0]

    def bilinear(ta: float, tw: float) -> float:
        i0, i1 = _bracket(ta, rows)
        j0, j1 = _bracket(tw, cols)
        v00 = float(matrix[i0][j0])
        v10 = float(matrix[i1][j0])
        v01 = float(matrix[i0][j1])
        v11 = float(matrix[i1][j1])
        t_span = (rows[i1] - rows[i0]) or 1
        w_span = (cols[j1] - cols[j0]) or 1
        ft = 0.0 if i0 == i1 else (ta - rows[i0]) / t_span
        fw = 0.0 if j0 == j1 else (tw - cols[j0]) / w_span
        return (
            v00 * (1 - ft) * (1 - fw)
            + v10 * ft * (1 - fw)
            + v01 * (1 - ft) * fw
            + v11 * ft * fw
        )

    if a < twa_min:
        return round(bilinear(twa_min, eff_w) * (a / twa_min), 3)
    if a > rows[-1]:
        a = rows[-1]
    return round(bilinear(a, eff_w), 3)


def polar_efficiency() -> float:
    """Facteur de croisière. Variable d'environnement POLAR_EFFICIENCY."""
    raw = os.environ.get("POLAR_EFFICIENCY", str(POLAR_EFFICIENCY_DEFAULT))
    try:
        v = float(raw)
    except (TypeError, ValueError):
        v = POLAR_EFFICIENCY_DEFAULT
    if v <= 0:
        v = POLAR_EFFICIENCY_DEFAULT
    return min(1.0, v)


def wave_polar_factor(hs: Optional[float], relative_deg: float = 90.0) -> float:
    """Facteur continu Hs × angle relatif houle/cap.

    f = 1 jusqu'à 1,5 m ; linéaire jusqu'à 0,6 (mer de face) / 0,85 (mer
    arrière) à 4 m ; plafonné au-delà. Angle 0° = mer de face (houle « de »
    dans le cap), 180° = mer arrière.
    """
    if hs is None:
        return 1.0
    try:
        h = float(hs)
    except (TypeError, ValueError):
        return 1.0
    if h <= WAVE_POLAR_HS_FLAT_M:
        return 1.0
    rel = max(0.0, min(180.0, abs(float(relative_deg))))
    f_full = WAVE_POLAR_HEAD + (WAVE_POLAR_FOLLOW - WAVE_POLAR_HEAD) * (rel / 180.0)
    if h >= WAVE_POLAR_HS_FULL_M:
        return f_full
    t = (h - WAVE_POLAR_HS_FLAT_M) / (WAVE_POLAR_HS_FULL_M - WAVE_POLAR_HS_FLAT_M)
    return 1.0 + t * (f_full - 1.0)


def current_along_route_kn(w: dict, heading_deg: float) -> float:
    """Projection du vecteur courant (uo/vo ou kn « vers ») sur la route."""
    if not isinstance(w, dict):
        return 0.0
    uo, vo = w.get("uo"), w.get("vo")
    if uo is not None and vo is not None:
        try:
            east_kn = float(uo) * MS_TO_KN
            north_kn = float(vo) * MS_TO_KN
        except (TypeError, ValueError):
            return 0.0
    elif w.get("currentKn") is not None:
        try:
            kn = float(w.get("currentKn") or 0)
            to_deg = float(w.get("currentToDeg") or 0)
        except (TypeError, ValueError):
            return 0.0
        rad = math.radians(to_deg)
        east_kn = kn * math.sin(rad)
        north_kn = kn * math.cos(rad)
    else:
        return 0.0
    h = math.radians(heading_deg)
    return east_kn * math.sin(h) + north_kn * math.cos(h)


def sog_along_route(stw: float, w: dict, heading_deg: float) -> float:
    """SOG = projection sur la route de (vecteur polaire + vecteur courant)."""
    return float(stw) + current_along_route_kn(w, heading_deg)


def planning_speed_for(polar_raw: Optional[dict], tws: float, twa: float) -> Optional[float]:
    """Vitesse de planification : polaire × POLAR_EFFICIENCY, plancher 3 kn."""
    bs = polar_boat_speed(polar_raw, twa, tws)
    if bs is None:
        return None
    kn = max(PLANNING_MIN_KN, float(bs) * polar_efficiency())
    # Même arrondi que Math.round JS (demi loin de zéro), pas le banker Python.
    return math.floor(kn * 10 + 0.5) / 10.0


def _harmonic_mean(values: List[float]) -> float:
    vals = [float(v) for v in values if v is not None and float(v) > 1e-9]
    if not vals:
        return MIN_KNOTS
    return len(vals) / sum(1.0 / v for v in vals)


def _wave_relative_deg(heading: float, w: dict) -> float:
    wave_from = w.get("waveFromDeg")
    if wave_from is None:
        wave_from = w.get("waveDirDeg")
    if wave_from is None:
        return 90.0
    try:
        return twa_deg(heading, float(wave_from))
    except (TypeError, ValueError):
        return 90.0


def _stw_from_wind(polar_raw, brg: float, w: dict) -> tuple[float, float, str]:
    """Vitesse surface : polaire × efficacité × polaire de vagues (sans courant).

    `boat_speed_from_wind` n'est appelé que sans polaire (`basis`).
    """
    twa = twa_deg(brg, float(w.get("dirFromDeg") or 0))
    from_polar = polar_boat_speed(polar_raw, twa, float(w.get("speedKnots") or 0))
    if from_polar is not None:
        speed = float(from_polar) * polar_efficiency()
        basis = "polar"
    else:
        speed = boat_speed_from_wind(w.get("speedKnots") or 0)
        basis = "fallback"
    speed *= wave_polar_factor(w.get("hs"), _wave_relative_deg(brg, w))
    return float(speed), twa, basis


def _r1(n: Optional[float]) -> Optional[float]:
    if n is None:
        return None
    return round(float(n), 1)


def _r4(n: float) -> float:
    return round(float(n), 4)


def _mark_indices(marks: List[dict], points: List[dict]) -> List[dict]:
    out = []
    for m in marks or []:
        if isinstance(m.get("index"), int) and 0 <= m["index"] < len(points):
            out.append({**m, "index": m["index"]})
            continue
        target = m.get("nm", m.get("filmNm", 0))
        best, best_d = 0, float("inf")
        for i, p in enumerate(points):
            d = abs((p.get("cumNm") or 0) - (target or 0))
            if d < best_d:
                best, best_d = i, d
        out.append({**m, "index": best})
    return out


def _nm_apart(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> Optional[float]:
    try:
        p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
        dphi = math.radians(float(lat2) - float(lat1))
        dlamb = math.radians(float(lon2) - float(lon1))
    except (TypeError, ValueError):
        return None
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlamb / 2.0) ** 2
    return 2.0 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))


def _farthest_point(points: List[dict], from_idx: int, to_idx: int, origin: dict) -> tuple[dict, int]:
    best_i = from_idx
    best_d = -1.0
    for i in range(from_idx, to_idx + 1):
        d = _nm_apart(origin.get("lat"), origin.get("lon"), points[i].get("lat"), points[i].get("lon"))
        if d is not None and d > best_d:
            best_d = d
            best_i = i
    return points[best_i], best_i


def detect_air_episodes(points: Optional[List[dict]]) -> List[dict]:
    """Paire de sauts aller / retour (park = Cayenne, hub = Halifax, via = Saint-Pierre)."""
    pts = list(points or [])
    jump_idx = [i for i in range(1, len(pts)) if pts[i].get("jump")]
    episodes: List[dict] = []
    used: set[int] = set()
    for a, ja in enumerate(jump_idx):
        if ja in used or ja < 1:
            continue
        origin = pts[ja - 1]
        for jb in jump_idx[a + 1:]:
            if jb in used:
                continue
            dest = pts[jb]
            gap = _nm_apart(origin.get("lat"), origin.get("lon"), dest.get("lat"), dest.get("lon"))
            if gap is None or gap > AIR_HOP_RETURN_NM:
                continue
            hub = pts[ja]
            via_from = min(ja + 1, jb - 1)
            via_to = max(ja, jb - 1)
            if via_to >= via_from:
                via, via_idx = _farthest_point(pts, via_from, via_to, hub)
            else:
                via, via_idx = hub, ja
            park_brg = bearing_deg(
                pts[ja - 2]["lat"], pts[ja - 2]["lon"], origin["lat"], origin["lon"],
            ) if ja >= 2 else bearing_deg(origin["lat"], origin["lon"], hub["lat"], hub["lon"])
            episodes.append({
                "ja": ja,
                "jb": jb,
                "viaIdx": via_idx,
                "park": {
                    "lat": origin["lat"],
                    "lon": origin["lon"],
                    "bearing": park_brg,
                    "cumNm": origin.get("cumNm") or 0,
                    "filmCum": origin.get("filmCum", origin.get("cumNm", 0)) or 0,
                },
                "hub": {"lat": hub["lat"], "lon": hub["lon"]},
                "via": {"lat": via["lat"], "lon": via["lon"]},
            })
            used.add(ja)
            used.add(jb)
            break
    return episodes


def _nearest_mark_name(marks: List[dict], lat: Any, lon: Any, fallback: str) -> str:
    best = fallback
    best_d = 80.0
    for m in marks or []:
        name = str(m.get("name") or "").strip()
        if not name:
            continue
        d = _nm_apart(lat, lon, m.get("lat"), m.get("lon"))
        if d is not None and d < best_d:
            best_d = d
            best = name
    return best


def with_hub_marks(marks: List[dict], points: List[dict], episodes: List[dict]) -> List[dict]:
    """Halifax (hub, aller et retour) + via Saint-Pierre si absents des marques."""
    out = [dict(m) for m in (marks or []) if isinstance(m, dict)]
    have_idx = {m["index"] for m in out if isinstance(m.get("index"), int)}

    def push(index: int, name: str, point: dict, kind: str) -> None:
        if index in have_idx or not (0 <= index < len(points)):
            return
        have_idx.add(index)
        out.append({
            "name": name,
            "index": index,
            "lat": point.get("lat"),
            "lon": point.get("lon"),
            "nm": point.get("cumNm") or 0,
            "filmNm": point.get("filmCum", point.get("cumNm", 0)) or 0,
            "kind": kind,
        })

    for ep in episodes or []:
        ja, jb = int(ep["ja"]), int(ep["jb"])
        hub_name = _nearest_mark_name(out, ep["hub"]["lat"], ep["hub"]["lon"], HUB_STOP_NAME)
        via_name = _nearest_mark_name(out, ep["via"]["lat"], ep["via"]["lon"], VIA_STOP_NAME)
        push(ja, hub_name, points[ja], "hub")
        ret_hub = jb - 1
        if ret_hub != ja and ret_hub > ja:
            push(ret_hub, hub_name, points[ret_hub], "hub")
        via_idx = int(ep.get("viaIdx") or ja)
        if via_idx != ja and via_idx != jb:
            push(via_idx, via_name, points[via_idx], "via")
    return out


def vehicle_at(points: List[dict], index: int, episodes: Optional[List[dict]] = None) -> str:
    if index < 0 or index >= len(points):
        return "main"
    p = points[index]
    if p.get("jump"):
        return "plane"
    if p.get("nonMaritime"):
        return "land"
    for ep in episodes or []:
        if int(ep["ja"]) < index < int(ep["jb"]):
            return "side"
    return "main"


def _episode_covering(episodes: List[dict], index: int) -> Optional[dict]:
    for ep in episodes or []:
        if int(ep["ja"]) <= index <= int(ep["jb"]):
            return ep
    return None


def find_start_index(points: List[dict], marks: List[dict], start_at: str = "la-rochelle") -> int:
    # "seam" : la route commence déjà au bon endroit (reprise mi-parcours,
    # HC1) — ne PAS pivoter sur la marque La Rochelle (l'arrivée de la
    # boucle matcherait et sauterait tout l'avenir).
    if start_at in ("saint-maur", "seam") or not points:
        return 0
    for m in _mark_indices(marks, points):
        if re.search(r"la rochelle", str(m.get("name") or ""), re.I):
            return int(m["index"])
    return 0


def _default_wind(lat: float, lon: float, t: datetime) -> Dict[str, Any]:
    pack = atlas_wind_at_dt(lat, lon, t)
    pack.setdefault("regime", pack.get("kind") or "climatology")
    return pack


def _point_along(a: dict, b: dict, frac: float) -> dict:
    f = max(0.0, min(1.0, float(frac)))
    span = float(b.get("cumNm") or 0) - float(a.get("cumNm") or 0)
    film_span = float(b.get("filmCum", b.get("cumNm", 0)) or 0) - float(a.get("filmCum", a.get("cumNm", 0)) or 0)
    return {
        "lat": a["lat"] + f * (b["lat"] - a["lat"]),
        "lon": _lerp_lon(a["lon"], b["lon"], f),
        "cumNm": float(a.get("cumNm") or 0) + f * span,
        "filmCum": float(a.get("filmCum", a.get("cumNm", 0)) or 0) + f * film_span,
        "jump": False,
        "nonMaritime": False,
    }


def _wind_pack_from(w: dict, twa: Optional[float] = None) -> Dict[str, Any]:
    return {
        "speedKnots": w.get("speedKnots"),
        "twa": twa,
        "kind": w.get("kind") or w.get("regime") or "climatology",
        "regime": w.get("regime") or w.get("kind") or "climatology",
        "sources": list(w.get("sources") or []),
        "spread": w.get("spread"),
        "model": w.get("model"),
        "leadHours": w.get("leadHours"),
        "reason": w.get("reason"),
        "source": w.get("source"),
        "period": w.get("period"),
        "doi": w.get("doi"),
        "hs": w.get("hs"),
        "hsP50": w.get("hsP50"),
        "hsP90": w.get("hsP90"),
        "currentKn": w.get("currentKn"),
        "currentToDeg": w.get("currentToDeg"),
        "uo": w.get("uo"),
        "vo": w.get("vo"),
        "waveFromDeg": w.get("waveFromDeg", w.get("waveDirDeg")),
        "roseKnots": list(w["roseKnots"]) if isinstance(w.get("roseKnots"), (list, tuple)) else None,
    }


def _speed_from_wind(polar_raw, brg: float, w: dict) -> tuple[float, float, str]:
    """SOG sur la route. Climatologie : moyenne harmonique des 3 tirages rose."""
    draws = w.get("roseKnots") if isinstance(w, dict) else None
    kind = (w.get("kind") or w.get("regime") or "") if isinstance(w, dict) else ""
    if kind == "climatology" and isinstance(draws, (list, tuple)) and len(draws) >= 3:
        sogs: List[float] = []
        twa = 0.0
        basis = "fallback"
        for kn in list(draws)[:3]:
            pack = {**w, "speedKnots": kn}
            stw, twa, basis = _stw_from_wind(polar_raw, brg, pack)
            sogs.append(max(MIN_KNOTS, sog_along_route(stw, w, brg)))
        return _harmonic_mean(sogs), twa, basis
    stw, twa, basis = _stw_from_wind(polar_raw, brg, w)
    return max(MIN_KNOTS, sog_along_route(stw, w, brg)), twa, basis


def _clock_kind(vertices: List[dict]) -> str:
    kinds = {(v.get("regime") or v.get("kind")) for v in vertices if v.get("regime") or v.get("kind")}
    if "hindcast" in kinds or "forecast" in kinds:
        if kinds <= {"hindcast"}:
            return "hindcast"
        return "mixed"
    return "climatology"


def _emit(p: dict, t_hours: float, t0: datetime, bearing: float,
          speed_knots: Optional[float], wind: dict, vehicle: str, month: int,
          sea_hours: float = 0.0, basis: str = "fallback") -> dict:
    when = t0 + timedelta(hours=t_hours)
    veh = "main" if vehicle == "boat" else vehicle
    speed_basis = basis if basis in {"polar", "fallback"} else "fallback"
    return {
        "filmNm": _r4(p.get("filmCum", p.get("cumNm", 0)) or 0),
        "sailNm": _r4(p.get("cumNm", 0) or 0),
        "lat": p["lat"],
        "lon": _wrap_lon(p["lon"]),
        "bearing": _r1(bearing),
        "tHours": _r4(t_hours),
        "iso": to_iso(when),
        "speedKnots": _r1(speed_knots),
        "windKnots": _r1(wind.get("speedKnots")),
        "twa": _r1(wind.get("twa")),
        "month": month,
        "vehicle": veh,
        "seaHours": _r4(sea_hours),
        "basis": speed_basis,
        "kind": wind.get("kind") or wind.get("regime") or "climatology",
        "regime": wind.get("regime") or wind.get("kind") or "climatology",
        "sources": list(wind.get("sources") or []),
        "spread": wind.get("spread"),
        "model": wind.get("model"),
        "leadHours": wind.get("leadHours"),
        "reason": wind.get("reason"),
        "source": wind.get("source"),
        "period": wind.get("period"),
        "doi": wind.get("doi"),
        "hs": wind.get("hs"),
        "hsP50": wind.get("hsP50"),
        "hsP90": wind.get("hsP90"),
        "currentKn": wind.get("currentKn"),
        "currentToDeg": wind.get("currentToDeg"),
    }


def _stop_latlon(name: str, point: dict, mark: dict) -> tuple[Any, Any]:
    """Saint-Pierre reste au port réel ; les autres escales suivent le sommet."""
    if re.search(r"saint[- ]pierre", name or "", re.I):
        return SAINT_PIERRE_LAT, SAINT_PIERRE_LON
    if isinstance(point.get("lat"), (int, float)) and isinstance(point.get("lon"), (int, float)):
        return point.get("lat"), _wrap_lon(point.get("lon"))
    return mark.get("lat"), mark.get("lon")


def _cayenne_mark(marks: List[dict]) -> Optional[dict]:
    for mark in marks:
        if "cayenne" in str(mark.get("name") or "").lower():
            return mark
    return None


def _apply_park_stay(
    clock_marks: List[dict],
    park: dict,
    t_hours: float,
    quay_hours: float,
    t0d: datetime,
    brg: float,
    sail_nm: float,
    vertices: List[dict],
    sea_hours: float,
    basis: str,
) -> tuple[float, float]:
    """Séjour à Cayenne (3 j, table des ports) au retour de l'épisode, une fois."""
    hold = float(port_days_for(PARK_STOP_NAME) * 24)
    if hold <= 0:
        return t_hours, quay_hours
    existing = _cayenne_mark(clock_marks)
    if existing is not None and float(existing.get("holdHours") or 0) >= hold - 1e-6:
        return t_hours, quay_hours
    if existing is None:
        clock_marks.append({
            "name": PARK_STOP_NAME,
            "filmNm": _r4(park.get("filmCum") or 0),
            "tHours": _r4(t_hours),
            "iso": to_iso(t0d + timedelta(hours=t_hours)),
            "holdHours": hold,
            "lat": park.get("lat"),
            "lon": _wrap_lon(park.get("lon")) if isinstance(park.get("lon"), (int, float)) else park.get("lon"),
            "vehicle": "quay",
        })
    else:
        existing["holdHours"] = hold
    t_hours += hold
    quay_hours += hold
    vertices.append(_emit(
        {**park, "cumNm": sail_nm, "filmCum": park.get("filmCum") or 0},
        t_hours, t0d, float(park.get("bearing") or brg), 0.0,
        {"kind": "climatology"}, "quay",
        (t0d + timedelta(hours=t_hours)).month,
        sea_hours,
        basis=basis,
    ))
    return t_hours, quay_hours


def _dedupe_cayenne_marks(marks: List[dict]) -> List[dict]:
    """Une seule Cayenne : la réinsertion HUD ne compte pas une seconde escale."""
    out: List[dict] = []
    kept = False
    for mark in marks:
        if "cayenne" in str((mark or {}).get("name") or "").lower():
            if kept:
                continue
            kept = True
        out.append(mark)
    return out


def build_voyage_clock(
    points: List[dict],
    marks: Optional[List[dict]] = None,
    t0: str | datetime = "",
    polar_raw: Optional[dict] = None,
    start_at: str = "la-rochelle",
    wind_fn: Optional[WindFn] = None,
) -> Dict[str, Any]:
    pts = list(points or [])
    t0d = parse_iso(t0) if not isinstance(t0, datetime) else t0
    if t0d.tzinfo is None:
        t0d = t0d.replace(tzinfo=timezone.utc)
    if wind_fn is None:
        months = {t0d.month, (t0d.month % 12) + 1, ((t0d.month + 1) % 12) + 1}
        prefetch_points(pts, months)
    wind_at = wind_fn or _default_wind
    marks = marks or []
    episodes = detect_air_episodes(pts)
    marks = with_hub_marks(marks, pts, episodes)
    start_idx = find_start_index(pts, marks, start_at)
    tagged = _mark_indices(marks, pts)
    mark_by_index = {m["index"]: m for m in tagged}

    vertices: List[dict] = []
    clock_marks: List[dict] = []
    t_hours = 0.0
    sea_hours = 0.0
    quay_hours = 0.0

    if not pts:
        iso = to_iso(t0d)
        return {
            "t0": iso,
            "kind": "climatology",
            "vertices": [],
            "marks": [],
            "seaHours": 0,
            "quayHours": 0,
            "arrivalIso": iso,
        }

    clock_basis = "polar" if polar_raw else "fallback"
    last_speed_basis = clock_basis

    for i in range(start_idx):
        nxt = pts[i + 1] if i + 1 < len(pts) else pts[i]
        vertices.append(_emit(
            pts[i], 0.0, t0d,
            bearing_deg(pts[i]["lat"], pts[i]["lon"], nxt["lat"], nxt["lon"]),
            None, {"kind": "climatology"}, "land", t0d.month, 0.0,
            basis=clock_basis,
        ))

    start = pts[start_idx]
    start_next = pts[start_idx + 1] if start_idx + 1 < len(pts) else start
    vertices.append(_emit(
        start, 0.0, t0d,
        bearing_deg(start["lat"], start["lon"], start_next["lat"], start_next["lon"]),
        None, {"kind": "climatology"},
        "land" if start.get("nonMaritime") else "main",
        t0d.month, 0.0,
        basis=clock_basis,
    ))

    land_end_idx = -1
    if start_at == "saint-maur":
        for m in tagged:
            if re.search(r"la rochelle", str(m.get("name") or ""), re.I):
                land_end_idx = int(m["index"])
                break

    # Départ La Rochelle : après la jambe terrestre, pas à t0.
    # (saint-maur ajoute ces heures à l'arrivée sur le dernier tronçon terre.)
    if start_at != "saint-maur" and any(
        isinstance(pts[i], dict) and pts[i].get("nonMaritime") for i in range(start_idx)
    ):
        t_hours = LAND_CALENDAR_HOURS
        vertices[-1]["tHours"] = _r4(t_hours)
        vertices[-1]["iso"] = to_iso(t0d + timedelta(hours=t_hours))

    sail_nm = float(start.get("cumNm") or 0)
    truncated: Optional[dict] = None
    a = b = start
    span_nm = pos_nm = 0.0

    try:
        for i in range(start_idx, len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            brg = bearing_deg(a["lat"], a["lon"], b["lat"], b["lon"])
            span_nm = max(0.0, float(b.get("cumNm") or 0) - float(a.get("cumNm") or 0))
            pos_nm = 0.0
            dest_vehicle = vehicle_at(pts, i + 1, episodes)
            vehicle = dest_vehicle
            speed_knots: Optional[float] = None
            wind_pack: Dict[str, Any] = {"kind": "climatology"}
            air_edge = bool(b.get("jump") or dest_vehicle == "plane")
            if not air_edge and b.get("air") and dest_vehicle != "plane":
                continue

            if air_edge:
                t_hours += AIR_CALENDAR_HOURS
                vehicle = "plane"
                vertices.append(_emit(
                    {**b, "cumNm": sail_nm}, t_hours, t0d, brg, speed_knots, wind_pack, vehicle,
                    (t0d + timedelta(hours=t_hours)).month,
                    sea_hours,
                    basis=clock_basis,
                ))
                ep_land = _episode_covering(episodes, i + 1)
                if ep_land and i + 1 == int(ep_land["jb"]):
                    park = ep_land["park"]
                    vertices.append(_emit(
                        {**park, "cumNm": sail_nm, "filmCum": park.get("filmCum") or 0},
                        t_hours, t0d, float(park.get("bearing") or brg), 0.0,
                        {"kind": "climatology"}, "quay",
                        (t0d + timedelta(hours=t_hours)).month,
                        sea_hours,
                        basis=last_speed_basis,
                    ))
                    t_hours, quay_hours = _apply_park_stay(
                        clock_marks, park, t_hours, quay_hours, t0d, brg, sail_nm,
                        vertices, sea_hours, last_speed_basis,
                    )
            elif a.get("nonMaritime") and b.get("nonMaritime"):
                vehicle = "land"
                if start_at == "saint-maur" and land_end_idx >= 0 and i + 1 == land_end_idx:
                    t_hours += LAND_CALENDAR_HOURS
                sail_nm = float(b.get("cumNm") or sail_nm)
                vertices.append(_emit(
                    b, t_hours, t0d, brg, speed_knots, wind_pack, vehicle,
                    (t0d + timedelta(hours=t_hours)).month,
                    sea_hours,
                    basis=clock_basis,
                ))
            else:
                while pos_nm < span_nm - 1e-9:
                    rem = span_nm - pos_nm
                    guess = min(MAX_STEP_NM, rem)
                    mid_frac = (pos_nm + guess / 2.0) / span_nm if span_nm else 0.5
                    mid = _point_along(a, b, mid_frac)
                    w0 = wind_at(mid["lat"], mid["lon"], t0d + timedelta(hours=t_hours))
                    speed0, _twa0, _basis0 = _speed_from_wind(polar_raw, brg, w0)
                    dt0 = guess / speed0
                    if dt0 > MAX_STEP_H:
                        guess = speed0 * MAX_STEP_H
                        dt0 = MAX_STEP_H
                        mid_frac = (pos_nm + guess / 2.0) / span_nm if span_nm else 0.5
                        mid = _point_along(a, b, mid_frac)
                    when_mid = t0d + timedelta(hours=t_hours + dt0 / 2.0)
                    w = wind_at(mid["lat"], mid["lon"], when_mid)
                    speed_knots, twa, last_speed_basis = _speed_from_wind(polar_raw, brg, w)
                    dt = guess / speed_knots
                    if dt > MAX_STEP_H + 1e-6:
                        guess = speed_knots * MAX_STEP_H
                        dt = MAX_STEP_H
                    t_hours += dt
                    sea_hours += dt
                    pos_nm += guess
                    sail_nm += guess
                    wind_pack = _wind_pack_from(w, twa)
                    pt = b if pos_nm >= span_nm - 1e-6 else _point_along(a, b, pos_nm / span_nm)
                    vertices.append(_emit(
                        {**pt, "cumNm": sail_nm}, t_hours, t0d, brg, speed_knots, wind_pack,
                        dest_vehicle if dest_vehicle in {"main", "side"} else "main",
                        (t0d + timedelta(hours=t_hours)).month,
                        sea_hours,
                        basis=last_speed_basis,
                    ))

            arrived = mark_by_index.get(i + 1)
            hub_hold = bool(arrived and arrived.get("kind") == "hub")
            # La Rochelle après la terre : on part, on ne compte pas le séjour
            # du retour (3 j) avant la première mise à la voile.
            outbound_departure = (
                start_at == "saint-maur"
                and land_end_idx >= 0
                and i + 1 == land_end_idx
                and bool(a.get("nonMaritime"))
                and bool(b.get("nonMaritime"))
            )
            if arrived and i + 1 != start_idx and (vehicle != "plane" or hub_hold):
                hold = 0 if outbound_departure else port_days_for(str(arrived.get("name") or "")) * 24
                lat, lon = _stop_latlon(str(arrived.get("name") or ""), b, arrived)
                clock_marks.append({
                    "name": arrived.get("name"),
                    "filmNm": _r4(b.get("filmCum", b.get("cumNm", 0)) or 0),
                    "tHours": _r4(t_hours),
                    "iso": to_iso(t0d + timedelta(hours=t_hours)),
                    "holdHours": hold,
                    "lat": lat,
                    "lon": lon,
                    "kind": arrived.get("kind"),
                    "vehicle": "quay" if hold > 0 else vehicle,
                })
                if hold > 0:
                    t_hours += hold
                    quay_hours += hold
                    vertices.append(_emit(
                        {**b, "cumNm": sail_nm}, t_hours, t0d, brg, 0.0,
                        {"kind": wind_pack.get("kind") or "climatology",
                         "regime": wind_pack.get("regime") or wind_pack.get("kind") or "climatology",
                         "sources": list(wind_pack.get("sources") or []),
                         "spread": wind_pack.get("spread"),
                         "speedKnots": wind_pack.get("speedKnots")},
                        "quay",
                        (t0d + timedelta(hours=t_hours)).month,
                        sea_hours,
                        basis=last_speed_basis,
                    ))
    except WindExhausted as exc:
        # Fin du vent RÉEL : on garde le dernier pas complet, on dit
        # où et pourquoi — jamais un vent de remplacement non étiqueté.
        frac = (pos_nm / span_nm) if span_nm else 0.0
        seam = _point_along(a, b, frac)
        truncated = {
            "reason": exc.reason,
            "iso": to_iso(t0d + timedelta(hours=t_hours)),
            "pointIndex": i,
            "pointCumNm": _r4(seam.get("cumNm") or 0),
            "pointFilmCum": _r4(seam.get("filmCum") or 0),
        }

    last = vertices[-1]
    out = {
        "t0": to_iso(t0d),
        "kind": _clock_kind(vertices),
        "vertices": vertices,
        "marks": _dedupe_cayenne_marks(clock_marks),
        "episodes": episodes,
        "seaHours": _r4(sea_hours),
        "quayHours": _r4(quay_hours),
        "arrivalIso": last.get("iso") or to_iso(t0d),
        "startAt": start_at,
    }
    if truncated is not None:
        out["truncated"] = truncated
    return out


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def sample_clock_at_hours(clock: dict, t_hours: float) -> Optional[dict]:
    verts = clock.get("vertices") or []
    if not verts:
        return None
    x = float(t_hours)
    if x <= verts[0]["tHours"]:
        return {**verts[0], "atQuay": False, "status": "waiting" if x < 0 else "live"}
    last = verts[-1]
    if x >= last["tHours"]:
        at_quay = last.get("vehicle") == "quay"
        out = {**last, "atQuay": at_quay, "status": "arrived"}
        if at_quay:
            out["speedKnots"] = 0
            out["vehicle"] = "quay"
            if out.get("plannedKnots") is None:
                out["plannedKnots"] = last.get("speedKnots")
        return out
    for i in range(len(verts) - 1):
        a, b = verts[i], verts[i + 1]
        if x > b["tHours"]:
            continue
        span = (b["tHours"] - a["tHours"]) or 1
        t = (x - a["tHours"]) / span
        if abs((b.get("filmNm") or 0) - (a.get("filmNm") or 0)) < 1e-6:
            hold = 0.0
            for m in clock.get("marks") or []:
                if abs((m.get("filmNm") or 0) - (a.get("filmNm") or 0)) < 1e-4:
                    hold = float(m.get("holdHours") or 0)
                    break
            park = _park_at_hours(clock, x)
            veh = "side" if park else "quay"
            out_hold = {
                **a,
                "tHours": x,
                "atQuay": True,
                "status": "live",
                "vehicle": veh,
                "speedKnots": 0,
                "plannedKnots": a.get("speedKnots"),
                "holdHours": hold,
            }
            if park:
                out_hold["parkLat"] = park.get("lat")
                out_hold["parkLon"] = park.get("lon")
            return out_hold
        t0 = parse_iso(clock["t0"])
        veh = a.get("vehicle")
        if b.get("vehicle") == "plane":
            veh = "plane"
        elif a.get("vehicle") == "side" or b.get("vehicle") == "side":
            veh = "side"
        out = {
            **a,
            "lat": _lerp(a["lat"], b["lat"], t),
            "lon": _lerp_lon(a["lon"], b["lon"], t),
            "filmNm": _lerp(a["filmNm"], b["filmNm"], t),
            "sailNm": _lerp(a["sailNm"], b["sailNm"], t),
            "tHours": x,
            "iso": to_iso(t0 + timedelta(hours=x)),
            "atQuay": False,
            "status": "live",
            "vehicle": veh,
            "kind": a["kind"] if t < 0.5 else b["kind"],
            "regime": (a.get("regime") or a.get("kind")) if t < 0.5 else (b.get("regime") or b.get("kind")),
            "sources": (a.get("sources") if t < 0.5 else b.get("sources")) or [],
            "spread": a.get("spread") if t < 0.5 else b.get("spread"),
            "speedKnots": b.get("speedKnots") if b.get("speedKnots") is not None else a.get("speedKnots"),
            "windKnots": b.get("windKnots") if b.get("windKnots") is not None else a.get("windKnots"),
            "model": b.get("model") or a.get("model"),
            "leadHours": b.get("leadHours") if b.get("leadHours") is not None else a.get("leadHours"),
            "seaHours": _lerp(float(a.get("seaHours") or 0), float(b.get("seaHours") or 0), t),
        }
        park = _park_at_hours(clock, x)
        if park and veh in {"plane", "side"}:
            out["parkLat"] = park.get("lat")
            out["parkLon"] = park.get("lon")
        return out
    return {**last, "atQuay": False, "status": "arrived"}


def _park_at_hours(clock: dict, t_hours: float) -> Optional[dict]:
    """Position du catamaran (Cayenne) pendant l'épisode — le sample suit l'équipage."""
    verts = clock.get("vertices") or []
    for ep in clock.get("episodes") or []:
        park = ep.get("park") if isinstance(ep.get("park"), dict) else None
        if not park:
            continue
        hub = ep.get("hub") or {}
        out_t = None
        back_t = None
        for v in verts:
            if not isinstance(v, dict) or v.get("vehicle") != "plane":
                continue
            d_hub = _nm_apart(v.get("lat"), v.get("lon"), hub.get("lat"), hub.get("lon"))
            d_park = _nm_apart(v.get("lat"), v.get("lon"), park.get("lat"), park.get("lon"))
            if out_t is None and d_hub is not None and d_hub <= 80:
                out_t = float(v.get("tHours") or 0)
            elif out_t is not None and d_park is not None and d_park <= 80:
                back_t = float(v.get("tHours") or 0)
                break
        if out_t is None:
            continue
        end = back_t if back_t is not None else out_t + 24 * 14
        if out_t - AIR_CALENDAR_HOURS <= float(t_hours) <= end:
            return park
    return None


def sample_clock_at_time(clock: dict, when: datetime | str) -> Optional[dict]:
    t0 = parse_iso(clock["t0"])
    w = parse_iso(when) if not isinstance(when, datetime) else when
    if w.tzinfo is None:
        w = w.replace(tzinfo=timezone.utc)
    hours = (w - t0).total_seconds() / 3600.0
    if hours < 0:
        v = (clock.get("vertices") or [{}])[0]
        return {
            **v,
            "atQuay": True,
            "status": "waiting",
            "countdownHours": -hours,
            "speedKnots": 0,
            "vehicle": "quay",
            "plannedKnots": v.get("speedKnots"),
        }
    return sample_clock_at_hours(clock, hours)
