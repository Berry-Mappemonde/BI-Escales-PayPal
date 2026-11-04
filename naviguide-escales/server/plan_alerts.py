"""Évaluateur de plan. Échantillon 60 nm, cyclone daté ± 15 j."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plan_review import PLANNED_KNOTS, _attach_itinerary_nm, legs_from_clock
from voyage_clock import parse_iso, port_days_for

SAMPLE_NM = 60.0
FORECAST_DAYS = 10
CYCLONE_WINDOW_DAYS = 15
NEAR_NM = 90.0
DEFAULT_GALE_KT = 34.0
DEFAULT_HS_M = 3.0

_CLIMO: dict | None = None
_CACHE: dict[str, dict] = {}
_CACHE_HITS = 0
_CACHE_MISSES = 0


def load_climatology_mini() -> dict:
    global _CLIMO
    if _CLIMO is None:
        path = Path(__file__).resolve().parent / "tests" / "fixtures" / "climatology_mini.json"
        _CLIMO = json.loads(path.read_text(encoding="utf-8"))
    return _CLIMO


def clear_plan_cache() -> None:
    global _CACHE_HITS, _CACHE_MISSES
    _CACHE.clear()
    _CACHE_HITS = _CACHE_MISSES = 0


def cache_info() -> dict[str, int]:
    return {"hits": _CACHE_HITS, "misses": _CACHE_MISSES, "size": len(_CACHE)}


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))


def _as_dt(raw: Any) -> datetime:
    dt = raw if isinstance(raw, datetime) else parse_iso(str(raw))
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).astimezone(timezone.utc)


def _as_day(raw: Any) -> str:
    return raw.astimezone(timezone.utc).strftime("%Y-%m-%d") if isinstance(raw, datetime) else str(raw or "")[:10]


def _f(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _threshold(th: dict | None, *keys: str, default: float) -> float:
    src = th if isinstance(th, dict) else {}
    return next((v for k in keys if (v := _f(src.get(k))) is not None), default)


def _leg_points(leg: dict) -> list[dict]:
    return [p for p in (leg.get("points") or leg.get("track") or []) if isinstance(p, dict)]


def _ready_plan(plan: dict) -> bool:
    legs = plan.get("legs") or []
    return bool(legs) and all((lg.get("depart") or lg.get("departIso")) and _leg_points(lg) for lg in legs)


def plan_from_voyage(voy: dict, *, now: Any = None, thresholds: dict | None = None) -> dict:
    clock = voy.get("clock") or {}
    _attach_itinerary_nm(clock.get("marks") or [], voy.get("marks") or [])
    raw = legs_from_clock(clock, voy.get("startAt")) if clock.get("t0") else []
    verts = [v for v in (clock.get("vertices") or []) if v.get("lat") is not None and v.get("lon") is not None]
    pearls = [p for p in (voy.get("pearls") or []) if isinstance(p, dict)]
    legs = []
    for idx, lg in enumerate(raw):
        lo, hi = float(lg.get("fromNm") or 0) - 0.5, float(lg.get("toNm") or 0) + 0.5
        pts = [v for v in verts if lo <= float(v.get("sailNm") or 0) <= hi] or list(verts)
        hold = lg.get("holdDays") if lg.get("holdDays") is not None else port_days_for(str(lg.get("to") or ""))
        legs.append({
            "idx": idx, "from": lg.get("from"), "to": lg.get("to"),
            "depart": _as_day(lg.get("departIso")), "arrive": _as_day(lg.get("arriveIso")),
            "departIso": lg.get("departIso"), "arriveIso": lg.get("arriveIso"),
            "holdDays": hold, "kn": lg.get("plannedKnots") or PLANNED_KNOTS, "points": pts,
            "pearls": [p for p in pearls if lo <= float(p.get("sailNm") or 0) <= hi],
        })
    return {"legs": legs, "skipper_thresholds": thresholds or voy.get("skipper_thresholds") or {},
            "now": now, "clock": clock}


def sample_track(points: list[dict], step_nm: float = SAMPLE_NM) -> list[dict]:
    usable = [p for p in points if p.get("lat") is not None and p.get("lon") is not None]
    if not usable:
        return []
    nms: list[float] = []
    for i, p in enumerate(usable):
        raw = p.get("sailNm")
        if raw is None:
            raw = p.get("cumNm")
        if raw is None:
            nms.append(0.0 if i == 0 else nms[-1] + haversine_nm(
                float(usable[i - 1]["lat"]), float(usable[i - 1]["lon"]), float(p["lat"]), float(p["lon"])))
        else:
            nms.append(float(raw))
    nms = [n - nms[0] for n in nms]
    out, target, last = [], 0.0, nms[-1]
    i = 0
    while target <= last + 1e-9:
        while i + 1 < len(nms) and nms[i + 1] < target:
            i += 1
        if i + 1 >= len(nms) or abs(nms[i + 1] - nms[i]) <= 1e-9:
            lat, lon = float(usable[i]["lat"]), float(usable[i]["lon"])
        else:
            frac = (target - nms[i]) / (nms[i + 1] - nms[i])
            lat = float(usable[i]["lat"]) + frac * (float(usable[i + 1]["lat"]) - float(usable[i]["lat"]))
            lon = float(usable[i]["lon"]) + frac * (float(usable[i + 1]["lon"]) - float(usable[i]["lon"]))
        out.append({"lat": lat, "lon": lon, "nm": round(target, 2)})
        target += step_nm
    end = {"lat": float(usable[-1]["lat"]), "lon": float(usable[-1]["lon"]), "nm": round(last, 2)}
    if not out or haversine_nm(out[-1]["lat"], out[-1]["lon"], end["lat"], end["lon"]) > 1.0:
        out.append(end)
    return out


def _nearest(items: list[dict], lat: float, lon: float, radius_nm: float) -> dict | None:
    best = None
    for item in items:
        ilat, ilon = _f(item.get("lat")), _f(item.get("lon"))
        at = item.get("at") if isinstance(item.get("at"), dict) else {}
        ilat = ilat if ilat is not None else _f(at.get("lat"))
        ilon = ilon if ilon is not None else _f(at.get("lon"))
        if ilat is None or ilon is None:
            continue
        dist = haversine_nm(lat, lon, ilat, ilon)
        if dist <= radius_nm and (best is None or dist < best[0]):
            best = (dist, item)
    return best[1] if best else None


def _cell_at(lat: float, lon: float, month: int, climo: dict | None = None) -> dict:
    cells = [c for c in ((climo or load_climatology_mini()).get("cells") or []) if isinstance(c, dict)]
    cell = _nearest(cells, lat, lon, 4000.0) or {}
    seq_w, seq_h = cell.get("wind_p90_kn"), cell.get("hs_p90_m")
    wind = seq_w[month - 1] if isinstance(seq_w, list) and 1 <= month <= len(seq_w) else None
    hs = seq_h[month - 1] if isinstance(seq_h, list) and 1 <= month <= len(seq_h) else None
    try:
        from climatology_atlas import atlas_wind_cached  # noqa: PLC0415
        pack = atlas_wind_cached(lat, lon, month)
        if isinstance(pack, dict) and pack.get("source") == "atlas":
            hs = pack["hsP90"] if pack.get("hsP90") is not None else hs
            rose = pack.get("roseKnots")
            wind = rose[-1] if isinstance(rose, (list, tuple)) and rose else wind
    except Exception:
        pass
    return {"season_months": [int(m) for m in (cell.get("season_months") or [])],
            "cyclones": list(cell.get("cyclones") or []),
            "wind_p90_kn": _f(wind), "hs_p90_m": _f(hs)}


def _parse_md(raw: Any) -> tuple[int, int] | None:
    parts = str(raw or "").strip().split("-")
    try:
        return (int(parts[-2]), int(parts[-1])) if len(parts) >= 2 else None
    except (TypeError, ValueError):
        return None


def _in_window(when: datetime, month: int, day: int) -> bool:
    deltas = []
    for year in (when.year - 1, when.year, when.year + 1):
        try:
            hist = date(year, month, day)
        except ValueError:
            hist = date(year, month, 28)
        deltas.append(abs((when.date() - hist).days))
    return min(deltas) <= CYCLONE_WINDOW_DAYS


def _crosses_track(lat: float, lon: float, track: list) -> bool:
    pts = []
    for raw in track or []:
        pair = (raw[0], raw[1]) if isinstance(raw, (list, tuple)) and len(raw) >= 2 else (
            raw.get("lat"), raw.get("lon")) if isinstance(raw, dict) else (None, None)
        la, lo = _f(pair[0]), _f(pair[1])
        if la is not None and lo is not None:
            pts.append((la, lo))
    for i, (la, lo) in enumerate(pts):
        if haversine_nm(lat, lon, la, lo) <= NEAR_NM:
            return True
        if i + 1 >= len(pts):
            continue
        la2, lo2 = pts[i + 1]
        steps = max(1, int(haversine_nm(la, lo, la2, lo2) / 15.0))
        if any(haversine_nm(lat, lon, la + s / steps * (la2 - la), lo + s / steps * (lo2 - lo)) <= NEAR_NM
               for s in range(1, steps)):
            return True
    return False


def _alert(kind: str, severity: str, when: datetime, lat: float, lon: float, fact: str, weight: int) -> dict:
    return {"kind": kind, "severity": severity, "when": when.strftime("%Y-%m-%d"),
            "where": {"lat": round(lat, 3), "lon": round(lon, 3)}, "fact": fact, "weight": int(weight)}


def _fmt(value: float, digits: int = 0, lang: str = "fr") -> str:
    rendered = f"{value:.{digits}f}" if digits else str(int(round(value)))
    return rendered if str(lang).lower().startswith("en") else rendered.replace(".", ",")

def _cyclone_alert(lat: float, lon: float, when: datetime, cell: dict) -> dict | None:
    dated = False
    for cyc in cell.get("cyclones") or []:
        if not isinstance(cyc, dict):
            continue
        track = list(cyc.get("track") or [])
        if cyc.get("lat") is not None and cyc.get("lon") is not None:
            track = track or [[cyc["lat"], cyc["lon"]]]
        if not track or not _crosses_track(lat, lon, track):
            continue
        hist = _parse_md(cyc.get("date"))
        name = cyc.get("name") or "cyclone"
        if hist is None:
            if when.month in (cell.get("season_months") or []):
                return _alert("cyclone", "alert", when, lat, lon, f"Saison cyclonique ({name}) : mois {when.month}", 3)
            continue
        dated = True
        if _in_window(when, hist[0], hist[1]):
            return _alert("cyclone", "alert", when, lat, lon,
                          f"Cyclone {name} (date historique {hist[1]:02d}/{hist[0]:02d}) : passage le {when.strftime('%d/%m')}", 3)
    if dated or when.month not in (cell.get("season_months") or []):
        return None
    return _alert("cyclone", "alert", when, lat, lon, f"Saison cyclonique de la zone : mois {when.month}", 3)


def _hook(module: str, names: tuple[str, ...], lat: float, lon: float, when: datetime):
    try:
        mod = __import__(module)
    except ImportError:
        return None
    for name in names:
        fn = getattr(mod, name, None)
        if not callable(fn):
            continue
        try:
            return fn(lat, lon)
        except TypeError:
            try:
                return fn(lat, lon, when)
            except Exception:
                return None
        except Exception:
            return None
    return None


def _optional_extras(lat: float, lon: float, when: datetime, lang: str = "fr") -> list[dict]:
    out, zone = [], _hook("piracy_zones", ("zone_at", "piracy_at"), lat, lon, when)
    if isinstance(zone, dict) and (zone.get("name") or zone.get("zone")):
        level = str(zone.get("level") or "LOW").upper()
        w = {"HIGH": 3, "MEDIUM": 2, "MED": 2}.get(level, 1)
        out.append(_alert("piracy", "alert" if w >= 3 else "decision", when, lat, lon,
                          f"Piraterie — {zone.get('name') or zone.get('zone')} · {level} · {zone.get('source') or 'IMB/UKMTO'}", w))
    pack = _hook("shipping_lanes", ("anti_shipping_at", "zone_at", "lanes_at"), lat, lon, when)
    if isinstance(pack, dict) and (pack.get("lanes") or pack.get("name") or pack.get("score") is not None):
        lanes = pack.get("lanes") or pack.get("name") or "couloir"
        fact = f"Couloir {lanes[0] if isinstance(lanes, list) and lanes else lanes}"
        if pack.get("score") is not None:
            fact += f" · score {_fmt(float(pack['score']), 2, lang)}"
        out.append(_alert("traffic", "decision", when, lat, lon, fact, 1))
    return out


def _amp_restriction(amp: dict) -> str | None:
    from amp_traffic import traffic_kind
    kind = amp.get("traffic") or traffic_kind(amp.get("entry"), amp.get("speed"))
    if kind == "forbidden":
        return "circulation interdite"
    if kind == "regulated":
        return "circulation régulée"
    if amp.get("restricted") is True or amp.get("restriction") is True:
        return str(amp["restriction"] if isinstance(amp.get("restriction"), str) else "restriction")
    if isinstance(amp.get("restriction"), str) and amp["restriction"].strip():
        return amp["restriction"].strip()
    if amp.get("iucn_cat") or amp.get("iucn"):
        return f"IUCN {amp.get('iucn_cat') or amp.get('iucn')}"
    des = amp.get("designation")
    return des.strip() if isinstance(des, str) and des.strip() else None


def _sample_alerts(lat, lon, when, now, thresholds, *, nm, clock, pearls, climo, lang="fr") -> list[dict]:
    gale = _threshold(thresholds, "galeKt", "windKt", "wind_max_kt", default=DEFAULT_GALE_KT)
    hs_lim = _threshold(thresholds, "hsAlertM", "hsM", "hs_max_m", default=DEFAULT_HS_M)
    past = when <= now
    near = when <= now + timedelta(days=FORECAST_DAYS)
    cell = _cell_at(lat, lon, when.month, climo)
    verts = [v for v in ((clock or {}).get("vertices") or []) if isinstance(v, dict)]
    clock_pt = min(verts, key=lambda v: abs(float(v.get("sailNm") or 0) - nm)) if verts else None
    pearl = _nearest(pearls, lat, lon, NEAR_NM)
    weather = pearl.get("weather") if isinstance(pearl, dict) and isinstance(pearl.get("weather"), dict) else {}
    wind = weather.get("wind") if isinstance(weather.get("wind"), dict) else {}
    wave = weather.get("wave") if isinstance(weather.get("wave"), dict) else {}
    obs_kn = _f((clock_pt or {}).get("windKnots")) or _f(wind.get("speedKnots"))
    obs_hs = _f((clock_pt or {}).get("hs")) or _f(wave.get("hs") if wave else weather.get("hs"))
    if not past and not near:
        kn, hs, wsrc, hsrc = cell.get("wind_p90_kn"), cell.get("hs_p90_m"), "P90", "P90"
    else:
        kn = obs_kn if obs_kn is not None else cell.get("wind_p90_kn")
        hs = obs_hs if obs_hs is not None else cell.get("hs_p90_m")
        wsrc, hsrc = ("observé" if obs_kn is not None else "P90"), ("observé" if obs_hs is not None else "P90")
    out, seen = [], set()

    def add(alert):
        if alert and alert["kind"] not in seen and str(alert.get("fact") or "").strip() and alert.get("when"):
            seen.add(alert["kind"])
            out.append(alert)

    if kn is not None and kn >= gale:
        add(_alert("wind", "alert", when, lat, lon, f"Vent {wsrc} {_fmt(kn, lang=lang)} kn ≥ {_fmt(gale, lang=lang)} kn (mois {when.month})", 3 if kn >= gale + 6 else 2))
    if hs is not None and hs >= hs_lim:
        add(_alert("sea", "alert", when, lat, lon, f"Hs {hsrc} {_fmt(hs, 1, lang)} m ≥ {_fmt(hs_lim, 1, lang)} m (mois {when.month})", 3 if hs >= hs_lim + 1 else 2))
    add(_cyclone_alert(lat, lon, when, cell))
    zee = pearl.get("zee") if isinstance(pearl, dict) and isinstance(pearl.get("zee"), dict) else {}
    poe = [p for p in (pearl.get("poe") or []) if isinstance(p, dict) and p.get("name")] if pearl else []
    if zee.get("mrgid") and not zee.get("ashore") and not zee.get("gold") and not poe:
        add(_alert("entry", "decision", when, lat, lon, f"Aucun port d'entrée officiel n'est connu pour {zee.get('name') or 'ZEE ' + str(zee.get('mrgid'))}", 2))
    amps = (pearl.get("amp") or []) if pearl else []
    if isinstance(amps, dict):
        amps = amps.get("nearby") or []
    for amp in (a for a in amps if isinstance(a, dict) and _amp_restriction(a)):
        add(_alert("mpa", "decision", when, lat, lon, f"{amp.get('name') or 'AMP'} — {_amp_restriction(amp)}", 1))
        break
    for extra in _optional_extras(lat, lon, when, lang):
        add(extra)
    return out


def _cache_key(plan: dict, now: datetime) -> str:
    legs = []
    for leg in plan.get("legs") or []:
        pts = [[round(float(p["lat"]), 3), round(float(p["lon"]), 3)]
               for p in _leg_points(leg) if p.get("lat") is not None and p.get("lon") is not None]
        legs.append({"from": leg.get("from"), "to": leg.get("to"),
                     "depart": _as_day(leg.get("departIso") or leg.get("depart")),
                     "kn": _f(leg.get("kn") or leg.get("plannedKnots")) or PLANNED_KNOTS, "points": pts})
    th = plan.get("skipper_thresholds") or {}
    payload = {"legs": legs, "now": now.strftime("%Y-%m-%d"),
               "thresholds": {k: th[k] for k in ("galeKt", "hsAlertM", "windKt", "hsM") if k in th}}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _evaluate_leg(leg: dict, idx: int, now: datetime, thresholds: dict, clock: dict | None, climo: dict | None, lang: str = "fr") -> dict:
    depart = _as_dt(leg.get("departIso") or leg.get("depart"))
    kn = _f(leg.get("kn") or leg.get("plannedKnots")) or PLANNED_KNOTS
    kn = kn if kn > 0 else PLANNED_KNOTS
    samples = sample_track(_leg_points(leg))
    last_nm = samples[-1]["nm"] if samples else 0.0
    arrive = _as_dt(leg.get("arriveIso") or leg.get("arrive")) if (leg.get("arriveIso") or leg.get("arrive")) else depart + timedelta(hours=last_nm / kn)
    pearls = [p for p in (leg.get("pearls") or []) if isinstance(p, dict)]
    alerts = []
    for sample in samples:
        when = depart + timedelta(hours=float(sample["nm"]) / kn)
        alerts.extend(_sample_alerts(float(sample["lat"]), float(sample["lon"]), when, now, thresholds,
                                    nm=float(sample["nm"]), clock=clock, pearls=pearls, climo=climo, lang=lang))
    return {"idx": int(leg["idx"] if leg.get("idx") is not None else idx), "from": leg.get("from"), "to": leg.get("to"),
            "depart": depart.strftime("%Y-%m-%d"), "arrive": arrive.strftime("%Y-%m-%d"),
            "alerts": alerts, "score": sum(int(a.get("weight") or 0) for a in alerts), "frozen": arrive <= now}


def evaluate_plan(plan: dict, *, now: Any = None, climatology: dict | None = None, lang: str = "fr") -> dict:
    global _CACHE_HITS, _CACHE_MISSES
    if not isinstance(plan, dict):
        return {"legs": [], "total": 0}
    src = plan
    if (plan.get("clock") or plan.get("voyageId") or plan.get("pearls")) and not _ready_plan(plan):
        src = plan_from_voyage(plan, now=now, thresholds=plan.get("skipper_thresholds"))
        have = {(lg.get("from"), lg.get("to")) for lg in src.get("legs") or []}
        src["legs"].extend(
            lg for lg in plan.get("legs") or []
            if (lg.get("depart") or lg.get("departIso")) and _leg_points(lg) and (lg.get("from"), lg.get("to")) not in have
        )
    now_dt = _as_dt(now or src.get("now") or datetime.now(timezone.utc))
    key = f"{_cache_key(src, now_dt)}:{str(lang).lower()}"
    if key in _CACHE:
        _CACHE_HITS += 1
        return copy.deepcopy(_CACHE[key])
    _CACHE_MISSES += 1
    thresholds = src.get("skipper_thresholds") or plan.get("skipper_thresholds") or {}
    clock = src.get("clock") if isinstance(src.get("clock"), dict) else None
    climo = climatology or load_climatology_mini()
    legs = [_evaluate_leg(leg, i, now_dt, thresholds, clock, climo, lang) for i, leg in enumerate(src.get("legs") or [])]
    out = {"legs": legs, "total": int(sum(lg["score"] for lg in legs))}
    _CACHE[key] = out
    return copy.deepcopy(out)
