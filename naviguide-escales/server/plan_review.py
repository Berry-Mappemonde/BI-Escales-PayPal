"""Revue de plan par règles (plan général §1.8) + commentaire.

Par jambe de la route officielle (d'une escale à la suivante), ce que les
données déjà collectées disent — rien d'autre :

- calendrier : départ, arrivée, jours de mer, jours à quai à l'arrivée
  (horloge officielle) ;
- formalités : ZEE traversées et leurs ports d'entrée officiels, dossier
  Gold présent ou non (perles chauffées ; une perle inconnue = trou compté,
  pas deviné) ;
- aires marines protégées à portée sur la jambe (perles).

La saison (rose des vents, cyclones IBTrACS) est lue côté client dans le
cache de l'atlas, pour le mois de la jambe.

Le commentaire « Ce que je changerais » est rédigé par
`cascade_text(tier="write")` à partir des seules lignes du tableau ; aucun
chiffre nouveau (`filter_numbers`). Cache par hash du tableau.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime, timedelta
from typing import Any

from shipping_lanes import anti_shipping_of
from voyage_clock import PARK_STOP_NAME, parse_iso, to_iso

log = logging.getLogger("naviguide-simulator.plan-review")

# Vitesse de programme : repli sans horloge (milles ÷ 8 kn ÷ 24).
# Avec une horloge, daysAtSea est l'écart départ d'escale → arrivée suivante.
PLANNED_KNOTS = 8.0
# Même plancher que voyage_clock.PLANNING_MIN_KN ; plafond « quelques jours ».
ETA_MIN_KN = 3.0
ETA_MAX_SPAN_DAYS = 7.0


def eta_span_days(p10_iso: str | None, p90_iso: str | None) -> float | None:
    """Écart p90 − p10 en jours civils. None si une date manque (jamais inventé)."""
    if not p10_iso or not p90_iso:
        return None
    try:
        a, b = parse_iso(p10_iso), parse_iso(p90_iso)
    except Exception:
        return None
    return (b - a).total_seconds() / 86400.0


def planned_sea_days(leg_nm: float, knots: float = PLANNED_KNOTS) -> float:
    """Repli sans horloge : milles ÷ nœuds planifiés ÷ 24."""
    kn = float(knots) if knots and float(knots) > 0 else PLANNED_KNOTS
    nm = max(0.0, float(leg_nm) or 0.0)
    return round(nm / kn / 24.0, 1)


def _clock_gap_days(dep: datetime, arr: datetime) -> float:
    return (arr - dep).total_seconds() / 86400.0


def sea_days_between(dep: datetime | None, arr: datetime | None, leg_nm: float, *, from_clock: bool) -> float:
    """Jours de mer affichés.

    Horloge présente et écart des dates positif (départ d'une escale →
    arrivée suivante) : cet écart, sans seuil. Repli milles ÷ 8 kn seulement
    si les dates manquent, sont égales ou dans le désordre.
    """
    planned = planned_sea_days(leg_nm)
    if not from_clock or dep is None or arr is None:
        return planned
    span = _clock_gap_days(dep, arr)
    if span <= 0:
        return planned
    return round(span, 1)

COMMENT_NS = "plan-comment"
COMMENT_TTL_S = 7 * 86400.0
COMMENT_MAX_SENTENCES = 4
COMMENT_MAX_CHARS = 800
COMMENT_SYSTEM = (
    "Tu commentes une revue de plan de voyage déjà calculée. "
    "Tu dis ce que tu changerais (repos, formalités, saison), en au plus 4 phrases. "
    "Tu ne produis aucun chiffre qui n'est pas déjà dans les faits. "
    "Thinking OFF. Pas de liste, pas de titre."
)


def _sail_nm_at(clock: dict, t_hours: float) -> float:
    """Sea miles of the clock at `t_hours` (interpolated — exact match misses quay vertices)."""
    verts = [v for v in (clock.get("vertices") or []) if v.get("tHours") is not None]
    if not verts:
        return 0.0
    t = float(t_hours)
    first, last = verts[0], verts[-1]
    t_first = float(first.get("tHours") or 0)
    t_last = float(last.get("tHours") or 0)
    if t <= t_first:
        return float(first.get("sailNm") or 0)
    if t >= t_last:
        return float(last.get("sailNm") or 0)
    for a, b in zip(verts, verts[1:]):
        ta, tb = float(a.get("tHours") or 0), float(b.get("tHours") or 0)
        if t > tb:
            continue
        span = tb - ta
        sa, sb = float(a.get("sailNm") or 0), float(b.get("sailNm") or 0)
        if span <= 1e-9:
            return sb
        frac = (t - ta) / span
        return sa + frac * (sb - sa)
    return float(last.get("sailNm") or 0)


def _norm_stop_name(name: str) -> str:
    return str(name or "").lower().split(" (")[0].strip()


def _attach_itinerary_nm(clock_marks: list[dict], voy_marks: list) -> None:
    """Copie `nm` (milles de mer de l'itinéraire) sur les marques d'horloge."""
    by = {}
    for m in voy_marks or []:
        key = _norm_stop_name(m.get("name"))
        if key and m.get("nm") is not None:
            by[key] = m
    for cm in clock_marks:
        vm = by.get(_norm_stop_name(cm.get("name")))
        if not vm:
            continue
        if cm.get("nm") is None and vm.get("nm") is not None:
            cm["nm"] = float(vm["nm"])


def _nm_apart(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> float | None:
    try:
        p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
        dphi = math.radians(float(lat2) - float(lat1))
        dlamb = math.radians(float(lon2) - float(lon1))
    except (TypeError, ValueError):
        return None
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlamb / 2.0) ** 2
    return 2.0 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))


def _nearest_mark_name(marks: list, lat: Any, lon: Any, limit_nm: float = 80.0) -> str | None:
    best, best_d = None, float(limit_nm)
    for mark in marks or []:
        name = (mark or {}).get("name") if isinstance(mark, dict) else None
        if not name:
            continue
        dist = _nm_apart(lat, lon, mark.get("lat"), mark.get("lon"))
        if dist is not None and dist < best_d:
            best_d = dist
            best = str(name)
    return best


def _marks_with_park(clock: dict) -> list[dict]:
    """Marques d'horloge + park de l'épisode (Cayenne n'est pas toujours une marque)."""
    marks = [m for m in (clock.get("marks") or []) if isinstance(m, dict)]
    for ep in clock.get("episodes") or []:
        park = ep.get("park") if isinstance(ep.get("park"), dict) else None
        if not park or park.get("lat") is None:
            continue
        marks.append({
            "name": PARK_STOP_NAME,
            "lat": park.get("lat"),
            "lon": park.get("lon"),
        })
    return marks


def _sea_origin_after(clock: dict, a: dict, b: dict) -> tuple[str, float | None, float | None]:
    """Quai / park où les milles de mer de a→b commencent vraiment (Cayenne après l'épisode)."""
    fallback = str(a.get("name") or "")
    t_a = float(a.get("tHours") or 0)
    t_b = float(b.get("tHours") or 0)
    from_nm = a["_sailNm"] if "_sailNm" in a else _sail_nm_at(clock, t_a)
    last_quay = None
    for vertex in clock.get("vertices") or []:
        if not isinstance(vertex, dict) or vertex.get("tHours") is None:
            continue
        t = float(vertex.get("tHours") or 0)
        if t < t_a - 1e-6 or t > t_b + 1e-6:
            continue
        nm = float(vertex.get("sailNm") or 0)
        if vertex.get("vehicle") in ("main", "side") and nm > from_nm + 0.5:
            break
        if vertex.get("vehicle") == "quay":
            last_quay = vertex
    if not last_quay:
        return fallback, None, None
    name = _nearest_mark_name(
        _marks_with_park(clock), last_quay.get("lat"), last_quay.get("lon"),
    ) or fallback
    t_hours = float(last_quay.get("tHours") or t_a)
    sail = float(last_quay.get("sailNm") or from_nm)
    return name, t_hours, sail


def _leg_distance_nm(a: dict, b: dict, from_nm: float, to_nm: float) -> float:
    """Mille nautiques de la jambe : horloge, sinon nm / filmNm de l'itinéraire.

    Un `sailNm` à correspondance ratée (ou un cumNm local à un tronçon geojson)
    donnait ~880 nm sur Nouméa → Dzaoudzi au lieu de ~9 150 — d'où « 4,5 j ».
    """
    span = max(0.0, float(to_nm) - float(from_nm))
    if a.get("nm") is not None and b.get("nm") is not None:
        other = float(b["nm"]) - float(a["nm"])
        if other > span + 0.5:
            span = other
    return span


# Une marque d'horloge peut porter le nom d'une escale pacifique
# et l'instant d'un sommet du retour atlantique (longitudes dépliées). On
# recale tHours / sailNm sur les milles d'itinéraire, qui sont justes.
SNAP_SAIL_NM_EXACT = 1.0
SNAP_SAIL_NM_NEAR = 50.0


def _t_hours_at_sail_nm(clock: dict, sail_nm: float) -> tuple[float, float] | None:
    """Premier (tHours, sailNm) de l'horloge où les milles de mer atteignent `sail_nm`."""
    try:
        target = float(sail_nm)
    except (TypeError, ValueError):
        return None
    verts: list[dict] = []
    for vertex in clock.get("vertices") or []:
        if not isinstance(vertex, dict) or vertex.get("tHours") is None:
            continue
        if vertex.get("sailNm") is None:
            continue
        if vertex.get("vehicle") == "plane":
            continue
        verts.append(vertex)
    if not verts:
        return None
    verts = sorted(verts, key=lambda v: (float(v.get("tHours") or 0), float(v.get("sailNm") or 0)))

    def _close(vertex: dict) -> float:
        return abs(float(vertex["sailNm"]) - target)

    best = min(verts, key=_close)
    if _close(best) <= SNAP_SAIL_NM_EXACT:
        return float(best["tHours"]), float(best["sailNm"])
    for a, b in zip(verts, verts[1:]):
        sa, sb = float(a["sailNm"]), float(b["sailNm"])
        if sa == sb:
            continue
        lo, hi = (sa, sb) if sa < sb else (sb, sa)
        if lo - 0.5 <= target <= hi + 0.5:
            frac = (target - sa) / (sb - sa)
            t = float(a["tHours"]) + frac * (float(b["tHours"]) - float(a["tHours"]))
            return t, target
    if _close(best) <= SNAP_SAIL_NM_NEAR:
        return float(best["tHours"]), float(best["sailNm"])
    return None


def _snap_mark_to_itinerary_nm(clock: dict, mark: dict) -> dict:
    """Recopie la marque ; si `nm` d'itinéraire est là, tHours suit le sommet correspondant."""
    out = dict(mark)
    if out.get("nm") is None:
        return out
    hit = _t_hours_at_sail_nm(clock, float(out["nm"]))
    if hit is None:
        return out
    t_hours, sail = hit
    out["tHours"] = t_hours
    out["_sailNm"] = sail
    return out


def _align_dates_to_sea_days(dep: datetime, arr: datetime, days_at_sea: float) -> tuple[datetime, datetime]:
    """Dates égales ou dans le désordre : l'arrivée suit le repli milles ÷ 8 kn. Sinon, dates inchangées."""
    try:
        days = float(days_at_sea)
    except (TypeError, ValueError):
        return dep, arr
    if days <= 0:
        return dep, arr
    span = (arr - dep).total_seconds() / 86400.0
    if span <= 0:
        return dep, dep + timedelta(days=days)
    return dep, arr


def legs_from_clock(clock: dict, start_name: str | None = None) -> list[dict]:
    """Consecutive stops → legs with sea-mile bounds and dates. The clock's
    marks are the arrivals; the departure is the first vertex."""
    marks = []
    for raw in clock.get("marks") or []:
        if not isinstance(raw, dict) or not raw.get("name"):
            continue
        mark = _snap_mark_to_itinerary_nm(clock, raw)
        if mark.get("tHours") is None:
            continue
        marks.append(mark)
    marks.sort(key=lambda m: float(m.get("tHours") or 0))
    verts = clock.get("vertices") or []
    if not verts:
        return []
    # The vertex from which the boat sails (the land leg before it counts
    # miles too, but on wheels): its miles and hour open the first leg.
    sea_start = verts[0]
    for a, b in zip(verts, verts[1:]):
        if b.get("vehicle") in ("main", "side"):
            sea_start = a
            break
    start = {"name": start_name or clock.get("startAt") or "Départ", "tHours": float(sea_start.get("tHours") or 0),
             "holdHours": 0, "_sailNm": float(sea_start.get("sailNm") or 0)}
    if not marks or abs(float(marks[0]["tHours"]) - start["tHours"]) > 1e-6:
        marks = [start] + marks
    t0 = parse_iso(clock["t0"])
    legs = []
    for a, b in zip(marks, marks[1:]):
        dep = t0 + timedelta(hours=float(a["tHours"]) + float(a.get("holdHours") or 0))
        arr = t0 + timedelta(hours=float(b["tHours"]))
        from_nm = a["_sailNm"] if "_sailNm" in a else (
            _sail_nm_at(clock, float(a["tHours"]) + float(a.get("holdHours") or 0)) or _sail_nm_at(clock, float(a["tHours"])))
        to_nm = b["_sailNm"] if "_sailNm" in b else _sail_nm_at(clock, float(b["tHours"]))
        itinerary_nm = 0.0
        if a.get("nm") is not None and b.get("nm") is not None:
            itinerary_nm = float(b["nm"]) - float(a["nm"])
        if to_nm <= from_nm + 0.5 and itinerary_nm <= 0.5:
            continue  # an air hop or a land leg: nothing to sail
        origin_name, origin_t, origin_nm = _sea_origin_after(clock, a, b)
        if origin_t is not None:
            dep = t0 + timedelta(hours=float(origin_t))
        if origin_nm is not None:
            from_nm = origin_nm
        leg_nm = round(_leg_distance_nm(a, b, from_nm, to_nm))
        if leg_nm <= 0:
            continue
        planned = planned_sea_days(leg_nm)
        dep, arr = _align_dates_to_sea_days(dep, arr, planned)
        days = sea_days_between(dep, arr, leg_nm, from_clock=True)
        to_nm_out = from_nm + leg_nm if to_nm <= from_nm + 0.5 else to_nm
        legs.append({
            "from": origin_name, "to": b["name"],
            "departIso": to_iso(dep), "arriveIso": to_iso(arr),
            "daysAtSea": days,
            "plannedKnots": PLANNED_KNOTS,
            "holdDays": round(float(b.get("holdHours") or 0) / 24),
            "fromNm": from_nm, "toNm": to_nm_out, "legNm": leg_nm,
            "month": arr.month,
        })
    return legs


SEASON_SAMPLES = 3
SEASON_BUDGET_S = 6.0


def _leg_sample_points(
    clock: dict, leg: dict, n: int = SEASON_SAMPLES, points: list | None = None,
) -> list[tuple[float, float]]:
    verts = [v for v in (clock.get("vertices") or [])
             if v.get("lat") is not None and _in_leg_nm(float(v.get("sailNm") or 0), leg)]
    if not verts:
        for p in points or []:
            if not isinstance(p, dict) or p.get("lat") is None or p.get("lon") is None:
                continue
            if not _sea_point(p):
                continue
            nm = _point_nm(p)
            if nm is None or not _in_leg_nm(nm, leg):
                continue
            verts.append(p)
    if not verts:
        return []
    step = max(1, len(verts) // n)
    return [(float(v["lat"]), float(v["lon"])) for v in verts[::step][:n]]


def _in_leg_nm(nm: float, leg: dict) -> bool:
    return leg["fromNm"] - 0.5 <= float(nm) <= leg["toNm"] + 0.5


def _mark_nm(mark: dict) -> float | None:
    if mark.get("nm") is not None:
        return float(mark["nm"])
    if mark.get("filmNm") is not None:
        return float(mark["filmNm"])
    return None


def _point_nm(point: dict) -> float | None:
    for key in ("sailNm", "cumNm", "filmCum"):
        if point.get(key) is not None:
            return float(point[key])
    return None


def _sea_point(point: dict) -> bool:
    return not (point.get("jump") or point.get("nonMaritime") or point.get("air"))


def _points_in_nm(points: list | None, from_nm: float, to_nm: float) -> list[dict]:
    out: list[dict] = []
    for p in points or []:
        if not isinstance(p, dict):
            continue
        nm = _point_nm(p)
        if nm is None:
            continue
        if from_nm - 0.5 <= nm <= to_nm + 0.5:
            out.append(p)
    return out


def _leg_is_sailable(from_nm: float, to_nm: float, points: list | None) -> bool:
    """Air hop (nm plat) ou terre seule → pas une jambe à revoir."""
    if to_nm <= from_nm + 0.5:
        return False
    span = _points_in_nm(points, from_nm, to_nm)
    if not span:
        return True
    return any(_sea_point(p) for p in span)


def _parse_mark_iso(mark: dict):
    raw = mark.get("iso")
    if not raw:
        return None
    try:
        return parse_iso(raw)
    except Exception:
        return None


def legs_from_voyage(voy: dict) -> list[dict]:
    """Jambes depuis marks + t0 + points — sans clock, sans build_voyage_clock.

    from/to et fromNm/toNm viennent de `nm` / `filmNm`. Sans horloge,
    daysAtSea est le repli milles ÷ 8 kn ; les dates viennent de `iso`
    ou de t0 + ce repli. Une jambe terre ou un saut avion est sautée.
    """
    marks = [m for m in (voy.get("marks") or []) if isinstance(m, dict) and m.get("name")]
    if len(marks) < 2:
        return []

    def _key(m: dict) -> tuple:
        nm = _mark_nm(m)
        idx = float(m.get("index") or 0)
        if nm is not None:
            return (0, nm, idx)
        return (1, idx, 0.0)

    marks = sorted(marks, key=_key)
    t0 = None
    if voy.get("t0"):
        try:
            t0 = parse_iso(voy["t0"])
        except Exception:
            t0 = None
    points = voy.get("points") or []
    legs: list[dict] = []
    elapsed_h = 0.0
    for a, b in zip(marks, marks[1:]):
        from_nm = _mark_nm(a)
        to_nm = _mark_nm(b)
        if from_nm is None or to_nm is None:
            continue
        if not _leg_is_sailable(from_nm, to_nm, points):
            continue
        leg_nm = round(_leg_distance_nm(a, b, from_nm, to_nm))
        if leg_nm <= 0:
            continue
        to_nm_out = from_nm + leg_nm if to_nm <= from_nm + 0.5 else to_nm
        hold_b = float(b.get("holdHours") or 0)
        dep = _parse_mark_iso(a)
        if dep is not None:
            dep = dep + timedelta(hours=float(a.get("holdHours") or 0))
        arr = _parse_mark_iso(b)
        if t0 is not None:
            if dep is None:
                dep = t0 + timedelta(hours=elapsed_h)
            if arr is None:
                arr = dep + timedelta(hours=leg_nm / PLANNED_KNOTS)
            elapsed_h = (arr - t0).total_seconds() / 3600.0 + hold_b
        if dep is None or arr is None:
            continue
        dep, arr = _align_dates_to_sea_days(dep, arr, planned_sea_days(leg_nm))
        days = sea_days_between(dep, arr, leg_nm, from_clock=True)
        legs.append({
            "from": a["name"], "to": b["name"],
            "departIso": to_iso(dep), "arriveIso": to_iso(arr),
            "daysAtSea": days,
            "plannedKnots": PLANNED_KNOTS,
            "holdDays": round(hold_b / 24),
            "fromNm": from_nm, "toNm": to_nm_out, "legNm": leg_nm,
            "month": arr.month,
        })
    return legs


def _leg_lonlat(clock: dict, leg: dict, points: list | None = None) -> list[list[float]]:
    """Sommets mer de la jambe, [lon, lat] — pour le score, pas pour redessiner."""
    coords: list[list[float]] = []
    seen: set[tuple[float, float]] = set()

    def add(lon: float, lat: float) -> None:
        key = (round(lon, 4), round(lat, 4))
        if key in seen:
            return
        seen.add(key)
        coords.append([float(lon), float(lat)])

    for v in clock.get("vertices") or []:
        if v.get("lat") is None or v.get("lon") is None:
            continue
        if _in_leg_nm(float(v.get("sailNm") or 0), leg):
            add(float(v["lon"]), float(v["lat"]))
    for p in points or []:
        if not isinstance(p, dict) or p.get("lat") is None or p.get("lon") is None:
            continue
        if not _sea_point(p):
            continue
        nm = _point_nm(p)
        if nm is None:
            continue
        if _in_leg_nm(float(nm), leg):
            add(float(p["lon"]), float(p["lat"]))
    return coords


def season_for_leg(
    clock: dict, leg: dict, *, budget_deadline: float | None = None, points: list | None = None,
) -> dict[str, Any]:
    """The month's climatology on the leg, from the BI atlas (server cache,
    zone fallback never counted as data): worst gale %, most cyclone tracks
    nearby, cells read / missing."""
    import time  # noqa: PLC0415
    from climatology_atlas import atlas_wind_at  # noqa: PLC0415

    gale = cyc = None
    cells = missing = 0
    for lat, lon in _leg_sample_points(clock, leg, points=points):
        if budget_deadline is not None and time.monotonic() > budget_deadline:
            missing += 1
            continue
        try:
            w = atlas_wind_at(lat, lon, int(leg["month"]))
        except Exception:
            w = None
        point = (w or {}).get("point") if isinstance(w, dict) else None
        if not point or (w or {}).get("source") != "atlas":
            missing += 1
            continue
        cells += 1
        rose = point.get("rose") or {}
        g = rose.get("gale_pct", (point.get("wind_atlas") or {}).get("gale_pct"))
        if isinstance(g, (int, float)):
            gale = max(gale or 0.0, float(g))
        c = (point.get("cyclone") or {}).get("nearby")
        if isinstance(c, (int, float)):
            cyc = max(cyc or 0, int(c))
    return {"galePct": gale, "cyclones": cyc, "cells": cells, "missing": missing, "month": leg["month"], "source": "atlas" if cells else None}


def review_official(voy: dict, now: datetime | None = None, *, season: bool = True) -> dict[str, Any]:
    import time  # noqa: PLC0415
    from ici_engine import thin_cache_get, thin_cache_key  # noqa: PLC0415
    from ici_warm import route_events_from_pearls, sample_route_nm  # noqa: PLC0415

    clock = voy.get("clock") or {}
    points = voy.get("points") or []
    # The sea start is the stop at the clock's first vertex (La Rochelle: the
    # Saint-Maur → La Rochelle leg is land and has no vertex at sea).
    start_name = None
    verts = clock.get("vertices") or []
    if verts:
        # Same sea-start vertex as legs_from_clock: name it from the marks.
        sea_start = verts[0]
        for a, b in zip(verts, verts[1:]):
            if b.get("vehicle") in ("main", "side"):
                sea_start = a
                break
        film0 = float(sea_start.get("filmNm") or 0)
        best = None
        for m in voy.get("marks") or []:
            if not m.get("name"):
                continue
            d = abs(float(m.get("filmNm", m.get("nm")) or 0) - film0)
            if best is None or d < best[0]:
                best = (d, m["name"])
        if best and best[0] <= 1.0:
            start_name = best[1]
    _attach_itinerary_nm(clock.get("marks") or [], voy.get("marks") or [])
    # Semis RD4/RC7 : pas de clock.t0. Les jambes viennent des marks + t0 +
    # points — jamais build_voyage_clock sur le thread HTTP.
    # Si le clock a un t0 mais pas encore de sommets, on ne reste pas à [].
    legs = legs_from_clock(clock, start_name) if clock.get("t0") else []
    if not legs:
        legs = legs_from_voyage(voy)
    pearls = sample_route_nm(points)
    events = route_events_from_pearls(points) if pearls else []

    # Pearls known / unknown per leg, and the ZEE seen on the leg (by pearl).
    for leg in legs:
        zees: dict[Any, dict] = {}
        known = unknown = 0
        for p in pearls:
            if not (leg["fromNm"] - 0.5 <= p["sailNm"] <= leg["toNm"] + 0.5):
                continue
            bag = thin_cache_get(thin_cache_key(p["lat"], p["lon"], 30.0))
            if bag is None:
                unknown += 1
                continue
            known += 1
            z = bag.get("zee") or {}
            mrgid = z.get("mrgid")
            if mrgid and not z.get("ashore"):
                cur = zees.setdefault(mrgid, {"mrgid": mrgid, "name": z.get("name"), "gold": bool(z.get("gold")), "poe": set()})
                cur["gold"] = cur["gold"] or bool(z.get("gold"))
                for poe in (bag.get("poe") or [])[:4]:
                    if isinstance(poe, dict) and poe.get("name"):
                        cur["poe"].add(poe["name"])
        amps = {e["siteId"] for e in events if e["kind"] == "amp" and leg["fromNm"] - 0.5 <= e["sailNm"] <= leg["toNm"] + 0.5}
        leg["pearls"] = {"known": known, "unknown": unknown}
        leg["zees"] = [
            {"mrgid": z["mrgid"], "name": z["name"], "gold": z["gold"], "poe": sorted(z["poe"])[:4]}
            for z in zees.values()
        ]
        leg["ampCount"] = len(amps)
        # Rules (facts only): formalities to check = a ZEE without a Gold pack
        # and without a known official port of entry.
        to_check = [z["name"] for z in leg["zees"] if not z["gold"] and not z["poe"]]
        leg["flags"] = []
        if to_check:
            leg["flags"].append({"kind": "formalities", "names": to_check[:4]})
        if unknown and not known:
            leg["flags"].append({"kind": "unknown", "count": unknown})
        if leg["holdDays"] == 0 and leg["daysAtSea"] >= 3:
            leg["flags"].append({"kind": "no-rest"})
        leg["antiShipping"] = anti_shipping_of(_leg_lonlat(clock, leg, points))
    if season:
        deadline = time.monotonic() + SEASON_BUDGET_S
        for leg in legs:
            if not leg.get("month"):
                continue
            leg["season"] = season_for_leg(clock, leg, budget_deadline=deadline, points=points)
    return {
        "voyageId": voy.get("voyageId"),
        "generatedAt": to_iso(now) if now else None,
        "legs": legs,
        "pearlsWarmed": sum(l["pearls"]["known"] for l in legs),
        "pearlsUnknown": sum(l["pearls"]["unknown"] for l in legs),
    }


def table_facts(legs: list[dict] | None) -> dict[str, Any]:
    """Lignes du tableau (faits seuls) : pas de dates ISO, pas de generatedAt."""
    rows = []
    for leg in legs or []:
        if not isinstance(leg, dict):
            continue
        pearls = leg.get("pearls") if isinstance(leg.get("pearls"), dict) else {}
        season = leg.get("season") if isinstance(leg.get("season"), dict) else None
        row: dict[str, Any] = {
            "from": leg.get("from"),
            "to": leg.get("to"),
            "legNm": leg.get("legNm"),
            "daysAtSea": leg.get("daysAtSea"),
            "holdDays": leg.get("holdDays"),
            "ampCount": leg.get("ampCount"),
            "pearls": {"known": pearls.get("known"), "unknown": pearls.get("unknown")},
            "zees": [
                {"name": z.get("name"), "gold": z.get("gold"), "poe": list(z.get("poe") or [])[:4]}
                for z in (leg.get("zees") or []) if isinstance(z, dict)
            ],
            "flags": [f for f in (leg.get("flags") or []) if isinstance(f, dict)],
        }
        pack = leg.get("antiShipping") if isinstance(leg.get("antiShipping"), dict) else None
        if pack:
            lanes = [n for n in (pack.get("lanes") or []) if isinstance(n, str) and n.strip()]
            row["antiShipping"] = {"score": pack.get("score"), "lanes": lanes}
        if season:
            row["season"] = {
                "galePct": season.get("galePct"),
                "cyclones": season.get("cyclones"),
                "cells": season.get("cells"),
                "missing": season.get("missing"),
            }
        rows.append(row)
    return {"n": len(rows), "legs": rows}


def table_hash(facts: dict[str, Any]) -> str:
    blob = json.dumps(facts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def comment_fallback(facts: dict[str, Any]) -> str:
    """≤ 4 phrases, uniquement les chiffres déjà dans `facts`."""
    legs = facts.get("legs") or []
    if not legs:
        return ""
    bits: list[str] = []
    n = facts.get("n")
    if n is not None:
        bits.append(f"Le tableau compte {n} jambe{'s' if n != 1 else ''}.")
    for leg in legs:
        if len(bits) >= COMMENT_MAX_SENTENCES:
            break
        bits.append(
            f"{leg.get('from') or '—'} → {leg.get('to') or '—'} : "
            f"{leg.get('legNm')} nm, {leg.get('daysAtSea')} jours de mer."
        )
        names: list[str] = []
        for flag in leg.get("flags") or []:
            if flag.get("kind") == "formalities":
                names.extend(str(x) for x in (flag.get("names") or []) if x)
        if names and len(bits) < COMMENT_MAX_SENTENCES:
            bits.append(f"Formalités à vérifier : {', '.join(names[:3])}.")
        unknown = (leg.get("pearls") or {}).get("unknown")
        if unknown and len(bits) < COMMENT_MAX_SENTENCES:
            bits.append(f"{unknown} perles pas encore chauffées.")
    return " ".join(bits[:COMMENT_MAX_SENTENCES])


def _cache_get(key: str) -> dict[str, Any] | None:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(COMMENT_NS, key, COMMENT_TTL_S)
    val = (hit or {}).get("value")
    if not isinstance(val, dict):
        return None
    text = val.get("text")
    source = val.get("source")
    if not isinstance(text, str) or not text.strip():
        return None
    if not isinstance(source, str) or not source.strip():
        return None
    return {"text": text, "source": source}


def _cache_put(key: str, value: dict[str, Any]) -> None:
    import pearl_store  # noqa: PLC0415

    pearl_store.kv_put(COMMENT_NS, key, {"text": value.get("text"), "source": value.get("source")})


def _clip_comment(text: str, facts: dict[str, Any], fallback: str) -> str:
    from story_cascade import filter_numbers, tidy_story  # noqa: PLC0415

    tidy = tidy_story(text or fallback, fallback, max_sentences=COMMENT_MAX_SENTENCES, max_chars=COMMENT_MAX_CHARS)
    cleaned, _ = filter_numbers(tidy, facts)
    return (cleaned or "").strip() or fallback


async def comment_plan(
    legs: list[dict] | None,
    *,
    client=None,
    cascade=None,
) -> dict[str, Any]:
    """Nemotron 3.5 Super VL (tier write) : ≤ 4 phrases. Cache par hash du tableau. Calculée en arrière-plan (revue
    du stock) : sous NAVIGUIDE_LLM_MODE=on-demand (défaut, 28 sept.) la cascade rend la phrase par règles."""
    from story_cascade import cascade_text  # noqa: PLC0415
    import llm_budget  # noqa: PLC0415
    with llm_budget.background():
        return await _comment_plan(legs, client=client, cascade=cascade, cascade_text=cascade_text)


async def _comment_plan(legs, *, client, cascade, cascade_text) -> dict[str, Any]:

    facts = table_facts(legs)
    key = table_hash(facts)
    hit = _cache_get(key)
    if hit:
        return {**hit, "cached": True}
    fallback = comment_fallback(facts)
    if not facts.get("legs"):
        return {"text": fallback, "source": "rules", "cached": False}
    fn = cascade or cascade_text
    user = (
        "Faits du tableau (ne pas inventer de chiffre) :\n"
        f"{json.dumps(facts, ensure_ascii=False, default=str)}"
    )
    try:
        text, source = await fn(
            COMMENT_SYSTEM, user, client, tier="write", fallback=fallback,
            facts=facts, max_tokens=400,
        )
    except Exception as exc:
        log.debug("commentaire revue : %s", exc)
        text, source = fallback, "rules"
    out_text = _clip_comment(text or fallback, facts, fallback)
    if not out_text:
        out_text, source = fallback, "rules"
    out = {"text": out_text, "source": source or "rules"}
    _cache_put(key, out)
    return {**out, "cached": False}
