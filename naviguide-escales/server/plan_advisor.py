"""Conseil par décalage de date et corridor borné.

Candidats d ∈ {−21, −14, −7, 0, +7, +14, +21} × corridors {référence, nord, sud}.
Nord/sud = trait décalé de 150 nm puis relissé (grands cercles). Distance ≤ +20 %.
L'isochrone ne cherche qu'à l'intérieur du corridor (bande ± 300 nm du trait
de référence, cap +20 %, seuils du skipper) — jamais d'écart libre.
Score = Σ weight des alertes + 0,3 × |d| + 0,02 × extraNm.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from amp_nogo import amp_nogo_fn, load_forbidden_nogo
from isochrone import (
    combine_nogo,
    distance_to_track_nm,
    haversine,
    move_position,
    run_leg_isochrone,
    skipper_nogo,
    track_nm as iso_track_nm,
)
from plan_alerts import (
    _as_day,
    _as_dt,
    _f,
    _leg_points,
    _ready_plan,
    evaluate_plan,
    haversine_nm,
    plan_from_voyage,
)
from plan_review import PLANNED_KNOTS, _attach_itinerary_nm, legs_from_clock, legs_from_voyage
from voyage_clock import bearing_deg, to_iso

log = logging.getLogger("naviguide-simulator.plan-advisor")

SHIFT_DAYS = (-21, -14, -7, 0, 7, 14, 21)
WEIGHT_SHIFT_PER_DAY = 0.3
WEIGHT_EXTRA_NM = 0.02
WEIGHTS = {"shiftPerDay": WEIGHT_SHIFT_PER_DAY, "extraNm": WEIGHT_EXTRA_NM}
CORRIDOR_REFERENCE = "reference"
CORRIDORS = ("reference", "north", "south")
CORRIDOR_RANK = {"reference": 0, "north": 1, "south": 2}
CORRIDOR_OFFSET_NM = 150.0
CORRIDOR_MAX_NM = 300.0
DISTANCE_CAP_RATIO = 1.20
JALON_STEP_NM = 180.0
GC_STEP_NM = 30.0
CORRIDOR_LABEL_FR = {"reference": "référence", "north": "nord", "south": "sud"}
MONTHS_FR = (
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)

_JOBS: dict[str, dict] = {}
_JOB_LOCK = threading.Lock()
_JOB_THREADS: dict[str, threading.Thread] = {}


def clear_advice_jobs() -> None:
    with _JOB_LOCK:
        _JOBS.clear()
        _JOB_THREADS.clear()


def _review_start_name(voy: dict) -> str | None:
    """Même départ mer que `review_official` (plan-review), pas `voy.startAt`."""
    clock = voy.get("clock") or {}
    verts = clock.get("vertices") or []
    if not verts:
        return None
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
        return best[1]
    return None


def review_legs(voy: dict) -> list[dict]:
    """Jambes du même référentiel que GET /voyage/official/plan-review."""
    if not isinstance(voy, dict):
        return []
    clock = voy.get("clock") or {}
    start_name = _review_start_name(voy)
    _attach_itinerary_nm(clock.get("marks") or [], voy.get("marks") or [])
    legs = legs_from_clock(clock, start_name) if clock.get("t0") else []
    if not legs:
        legs = legs_from_voyage(voy)
    return legs


def _map_review_to_prepared(wanted: dict, prepared: list) -> int | None:
    wf, wt = wanted.get("from"), wanted.get("to")
    for i, lg in enumerate(prepared or []):
        if lg.get("from") == wf and lg.get("to") == wt:
            return i
    return None


def advice_unavailable(leg_idx: int, reason: str) -> dict:
    return {
        "status": "unavailable",
        "leg": int(leg_idx),
        "reason": str(reason),
        "weights": dict(WEIGHTS),
    }


def _depart_dt(leg: dict) -> datetime:
    return _as_dt(leg.get("departIso") or leg.get("depart"))


def departure_after_now(leg: dict, now: Any) -> bool:
    """La jambe n'a pas commencé : le départ proposé est strictement après maintenant."""
    try:
        return _depart_dt(leg) > _now_dt(now)
    except Exception:
        return False


def _advice_closed_indices(legs: list, now: Any) -> list[int]:
    now_dt = _now_dt(now)
    return [i for i, leg in enumerate(legs or []) if isinstance(leg, dict) and not departure_after_now(leg, now_dt)]


def resolve_advice_leg(plan: dict, leg_idx: int, *, now: Any = None) -> tuple[dict, int | None, str | None]:
    """Indice de la revue → plan préparé. `reason` si la jambe n'est pas calculable.

    Choix RF1 : l'indice client est celui de plan-review. On le traduit vers
    le plan de `prepare_plan` par (from, to). Pas d'invention de jambe.
    Une date proposée doit être après maintenant, et seulement pour une jambe
    pas encore commencée. Sinon aucun conseil.
    """
    src = prepare_plan(plan, now=now)
    prepared = src.get("legs") or []
    review = review_legs(plan) if isinstance(plan, dict) else []
    idx = int(leg_idx)
    closed = set(src.get("_adviceClosed") or [])

    def _gate(mapped: int) -> tuple[dict, int | None, str | None]:
        if mapped in closed or not (0 <= mapped < len(prepared)) or not departure_after_now(prepared[mapped], now):
            return src, None, "past"
        return src, mapped, None

    if review:
        if not (0 <= idx < len(review)):
            return src, None, "unknown_leg"
        mapped = _map_review_to_prepared(review[idx], prepared)
        if mapped is not None:
            return _gate(mapped)
        if not prepared:
            return src, None, "no_clock"
        return src, None, "not_computable"
    if not (0 <= idx < len(prepared)):
        return src, None, "no_clock" if not prepared else "unknown_leg"
    return _gate(idx)


def prepare_plan(plan: dict, *, now: Any = None) -> dict:
    if not isinstance(plan, dict):
        return {"legs": [], "skipper_thresholds": {}}
    if _ready_plan(plan):
        src = plan
    elif plan.get("clock") or plan.get("voyageId") or plan.get("pearls"):
        src = plan_from_voyage(plan, now=now, thresholds=plan.get("skipper_thresholds"))
    else:
        src = plan
    if now is None or not isinstance(src, dict):
        return src
    closed = _advice_closed_indices(src.get("legs") or [], now)
    if not closed:
        return src
    out = dict(src)
    out["_adviceClosed"] = closed
    return out


def _now_dt(raw: Any) -> datetime:
    return raw if isinstance(raw, datetime) else _as_dt(raw or datetime.now(timezone.utc))


def _arrive_dt(leg: dict) -> datetime:
    raw = leg.get("arriveIso") or leg.get("arrive")
    if raw:
        return _as_dt(raw)
    depart = _as_dt(leg.get("departIso") or leg.get("depart"))
    kn = _f(leg.get("kn") or leg.get("plannedKnots")) or PLANNED_KNOTS
    kn = kn if kn > 0 else PLANNED_KNOTS
    pts = [p for p in _leg_points(leg) if p.get("lat") is not None and p.get("lon") is not None]
    nm = 0.0
    if pts:
        last, first = pts[-1], pts[0]
        if last.get("sailNm") is not None:
            nm = max(0.0, float(last["sailNm"]) - float(first.get("sailNm") or 0))
        else:
            for i in range(1, len(pts)):
                nm += haversine_nm(
                    float(pts[i - 1]["lat"]), float(pts[i - 1]["lon"]),
                    float(pts[i]["lat"]), float(pts[i]["lon"]),
                )
    return depart + timedelta(hours=nm / kn)


def _is_frozen(leg: dict, now: datetime) -> bool:
    return _arrive_dt(leg) <= now


def shift_plan(plan: dict, leg_idx: int, days: int) -> dict:
    """Décale le départ de `leg_idx` et toutes les jambes suivantes ; holdDays inchangé."""
    out = copy.deepcopy(plan)
    delta = timedelta(days=int(days))
    for i, leg in enumerate(out.get("legs") or []):
        if i < leg_idx:
            continue
        dep = _as_dt(leg.get("departIso") or leg.get("depart"))
        arr = _arrive_dt(leg)
        new_dep, new_arr = dep + delta, arr + delta
        leg["depart"] = new_dep.strftime("%Y-%m-%d")
        leg["arrive"] = new_arr.strftime("%Y-%m-%d")
        leg["departIso"] = to_iso(new_dep)
        leg["arriveIso"] = to_iso(new_arr)
    return out


def cascade_stops(base: dict, shifted: dict, leg_idx: int) -> list[dict]:
    out = []
    for i, (was, now) in enumerate(zip(base.get("legs") or [], shifted.get("legs") or [])):
        if i < leg_idx:
            continue
        out.append({
            "stop": now.get("to"),
            "was": _as_day(was.get("arriveIso") or was.get("arrive") or _arrive_dt(was)),
            "now": _as_day(now.get("arriveIso") or now.get("arrive") or _arrive_dt(now)),
        })
    return out


def score_of(total_weight: float, days: int, extra_nm: float) -> float:
    return float(total_weight) + WEIGHT_SHIFT_PER_DAY * abs(int(days)) + WEIGHT_EXTRA_NM * float(extra_nm)


def _as_coords(points: Any) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in points or []:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            out.append((float(p[0]), float(p[1])))
        elif isinstance(p, dict) and p.get("lat") is not None and p.get("lon") is not None:
            out.append((float(p["lat"]), float(p["lon"])))
    return out


def track_nm(points: Any) -> float:
    coords = _as_coords(points)
    return iso_track_nm(coords) if coords else 0.0


def _jalons(coords: list[tuple[float, float]], step_nm: float = JALON_STEP_NM) -> list[tuple[float, float]]:
    if len(coords) < 2:
        return list(coords)
    out = [coords[0]]
    acc = 0.0
    last = coords[0]
    for p in coords[1:]:
        acc += haversine(last[0], last[1], p[0], p[1])
        if acc >= step_nm:
            out.append(p)
            acc = 0.0
        last = p
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return out


def great_circle_resample(
    a: tuple[float, float], b: tuple[float, float], step_nm: float = GC_STEP_NM,
) -> list[tuple[float, float]]:
    dist = haversine(a[0], a[1], b[0], b[1])
    if dist <= step_nm:
        return [a, b]
    n = max(1, int(math.ceil(dist / step_nm)))
    brg = bearing_deg(a[0], a[1], b[0], b[1])
    pts = [a]
    for i in range(1, n):
        pts.append(move_position(a[0], a[1], brg, dist * i / n))
    pts.append(b)
    return pts


def _smooth_gc(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(coords) < 2:
        return list(coords)
    out = [coords[0]]
    for a, b in zip(coords, coords[1:]):
        out.extend(great_circle_resample(a, b)[1:])
    return out


_CORRIDOR_MEMO: dict[tuple, list[tuple[float, float]] | None] = {}
_CORRIDOR_MEMO_MAX = 256


def corridor_track(points: Any, name: str) -> list[tuple[float, float]] | None:
    """Trait de corridor. None si distance > +20 % ou un point > 300 nm du référence.
    Mémoïsé par (jambe, couloir) : le calcul (distance de chaque point du trait au trait de référence) coûtait
    des secondes de CPU à chaque /advice, pour des jambes qui ne changent pas (RC18, 27 sept.)."""
    raw = _as_coords(points)
    if len(raw) < 2:
        return raw or None
    memo_key = (tuple(raw), str(name or ""))
    if memo_key in _CORRIDOR_MEMO:
        hit = _CORRIDOR_MEMO[memo_key]
        return list(hit) if hit is not None else None
    out = _corridor_track_uncached(raw, name)
    if len(_CORRIDOR_MEMO) >= _CORRIDOR_MEMO_MAX:
        _CORRIDOR_MEMO.clear()
    _CORRIDOR_MEMO[memo_key] = list(out) if out is not None else None
    return out


def _corridor_track_uncached(raw: list[tuple[float, float]], name: str) -> list[tuple[float, float]] | None:
    ref = _smooth_gc(_jalons(raw)) if len(raw) < 4 else raw
    if name in (CORRIDOR_REFERENCE, "", None):
        return ref
    if name not in ("north", "south"):
        return None
    brg = 0.0 if name == "north" else 180.0
    jalons = _jalons(ref)
    if len(jalons) < 3:
        d = haversine(ref[0][0], ref[0][1], ref[-1][0], ref[-1][1])
        mid_brg = bearing_deg(ref[0][0], ref[0][1], ref[-1][0], ref[-1][1])
        jalons = [ref[0], move_position(ref[0][0], ref[0][1], mid_brg, d / 2.0), ref[-1]]
    offset = [jalons[0]]
    for j in jalons[1:-1]:
        offset.append(move_position(j[0], j[1], brg, CORRIDOR_OFFSET_NM))
    offset.append(jalons[-1])
    track = _smooth_gc(offset)
    ref_nm = iso_track_nm(ref)
    if ref_nm > 0 and iso_track_nm(track) > ref_nm * DISTANCE_CAP_RATIO + 1e-6:
        return None
    if any(distance_to_track_nm(la, lo, ref) > CORRIDOR_MAX_NM + 1e-6 for la, lo in track):
        return None
    return track


def apply_corridor(plan: dict, leg_idx: int, name: str) -> tuple[dict, float, list[tuple[float, float]]] | None:
    """Copie du plan dont la jambe `leg_idx` suit le corridor. None si hors cap."""
    src = copy.deepcopy(plan)
    legs = src.get("legs") or []
    if not (0 <= int(leg_idx) < len(legs)):
        return None
    leg = legs[int(leg_idx)]
    ref = _as_coords(_leg_points(leg))
    track = corridor_track(ref, name)
    if track is None:
        return None
    extra = max(0.0, iso_track_nm(track) - iso_track_nm(ref))
    if iso_track_nm(ref) > 0 and extra > iso_track_nm(ref) * (DISTANCE_CAP_RATIO - 1.0) + 1e-6:
        return None
    leg["points"] = [{"lat": la, "lon": lo} for la, lo in track]
    return src, extra, track


def plan_from_current_leg(
    points: Any,
    *,
    frm: str,
    to: str,
    depart: Any,
    thresholds: dict | None = None,
    kn: float | None = None,
) -> dict:
    coords = _as_coords(points)
    speed = float(kn) if kn and kn > 0 else PLANNED_KNOTS
    nm = iso_track_nm(coords)
    dep = _as_dt(depart)
    arr = dep + timedelta(hours=nm / speed if speed else 0)
    return {
        "legs": [{
            "idx": 0, "from": frm, "to": to,
            "depart": dep.strftime("%Y-%m-%d"), "arrive": arr.strftime("%Y-%m-%d"),
            "departIso": to_iso(dep), "arriveIso": to_iso(arr),
            "holdDays": 0, "kn": speed,
            "points": [{"lat": la, "lon": lo} for la, lo in coords],
        }],
        "skipper_thresholds": thresholds or {},
    }


def _has_wind_alert(evaluated: dict, idx: int) -> bool:
    for leg in evaluated.get("legs") or []:
        if int(leg.get("idx") if leg.get("idx") is not None else -1) == idx:
            return any(a.get("kind") == "wind" for a in (leg.get("alerts") or []))
    if 0 <= idx < len(evaluated.get("legs") or []):
        return any(a.get("kind") == "wind" for a in (evaluated["legs"][idx].get("alerts") or []))
    return False


def bounded_isochrone(
    *,
    dep_lat: float,
    dep_lon: float,
    dst_lat: float,
    dst_lon: float,
    departure_time: datetime,
    wind_fn: Callable,
    reference: Any,
    corridor: Any | None = None,
    polar_raw: dict | None = None,
    wind_max_kt: float | None = None,
    hs_max_m: float | None = None,
    **iso_kw: Any,
) -> dict:
    """Isochrone bridée : bande ± 300 nm du référence, cap +20 %, seuils skipper."""
    ref = _as_coords(reference)
    chosen = _as_coords(corridor) if corridor is not None else ref
    ref_nm = iso_track_nm(ref)
    cap = ref_nm * DISTANCE_CAP_RATIO if ref_nm > 0 else None
    return run_leg_isochrone(
        dep_lat, dep_lon, dst_lat, dst_lon, departure_time,
        wind_fn=wind_fn,
        polar_raw=polar_raw,
        wave_nogo_fn=combine_nogo(
            skipper_nogo(wind_fn, wind_max_kt=wind_max_kt, hs_max_m=hs_max_m),
            amp_nogo_fn(
                load_forbidden_nogo(),
                escape_points=[(dep_lat, dep_lon), (dst_lat, dst_lon)],
            ),
        ),
        searoute_coords=chosen or ref,
        corridor_coords=ref or chosen,
        corridor_max_nm=CORRIDOR_MAX_NM,
        max_distance_nm=cap,
        **iso_kw,
    )


def _day_fr(iso: str) -> str:
    d = date.fromisoformat(str(iso)[:10])
    label = "1er" if d.day == 1 else str(d.day)
    return f"{label} {MONTHS_FR[d.month]}"


def _parts(iso: str) -> tuple[int, int, int]:
    d = date.fromisoformat(str(iso)[:10])
    return d.day, d.month, d.year


def advice_facts(
    *,
    frm: str,
    to: str,
    days: int,
    depart_was: str,
    depart_now: str,
    alerts_before: int,
    alerts_after: int,
    total_before: int,
    total_after: int,
    extra_nm: float,
    cascade: list[dict],
    corridor: str = CORRIDOR_REFERENCE,
) -> list[str]:
    """Faits textuels : chaque nombre de la phrase gabarit y figure."""
    was_d, was_m, was_y = _parts(depart_was)
    now_d, now_m, now_y = _parts(depart_now)
    facts = [
        f"jambe {frm} → {to}",
        f"décalage {int(days)} jours (absolu {abs(int(days))})",
        f"départ {depart_was} → {depart_now}",
        f"jour {was_d} → {now_d}",
        f"mois {was_m} → {now_m}",
        f"année {was_y} → {now_y}",
        f"alertes {int(alerts_before)} → {int(alerts_after)}",
        f"total {int(total_before)} → {int(total_after)}",
        f"extraNm {int(round(float(extra_nm)))}",
        f"corridor {corridor} ({CORRIDOR_LABEL_FR.get(corridor, corridor)})",
        f"poids {WEIGHT_SHIFT_PER_DAY} par jour, {WEIGHT_EXTRA_NM} par nm",
    ]
    for row in cascade:
        facts.append(f"{row.get('stop')} {row.get('was')} → {row.get('now')}")
    return facts


def advice_sentence(
    *,
    frm: str,
    days: int,
    depart_was: str,
    depart_now: str,
    alerts_before: int,
    alerts_after: int,
    extra_nm: float,
    corridor: str = CORRIDOR_REFERENCE,
) -> str:
    """Phrase gabarit : jambe, décalage, corridor, alertes avant/après, cascade. Nombres ⊂ facts."""
    via = ""
    if corridor in ("north", "south"):
        via = f" par le corridor {CORRIDOR_LABEL_FR[corridor]}"
    if int(days) == 0:
        head = f"Rester au départ de {frm} le {_day_fr(depart_was)}{via}"
    else:
        head = f"Partir de {frm} le {_day_fr(depart_now)} plutôt que le {_day_fr(depart_was)}{via}"
    if int(alerts_before) == int(alerts_after):
        mid = f"{int(alerts_after)} alertes sur cette jambe"
    else:
        mid = f"{int(alerts_after)} alertes au lieu de {int(alerts_before)} sur cette jambe"
    extra = int(round(float(extra_nm)))
    if extra:
        mid += f" (+{extra} nm)"
    abs_d = abs(int(days))
    if int(days) > 0:
        tail = f"toutes les escales suivantes reculent de {abs_d} jours"
    elif int(days) < 0:
        tail = f"toutes les escales suivantes avancent de {abs_d} jours"
    else:
        tail = "aucun décalage des escales suivantes"
    return f"{head} : {mid} ; {tail}."


def _leg_alert_count(evaluated: dict, idx: int) -> int:
    for leg in evaluated.get("legs") or []:
        if int(leg.get("idx") if leg.get("idx") is not None else -1) == idx:
            return len(leg.get("alerts") or [])
    if 0 <= idx < len(evaluated.get("legs") or []):
        return len(evaluated["legs"][idx].get("alerts") or [])
    return 0


def _pack_candidate(
    *,
    src: dict,
    shifted: dict,
    evaluated: dict,
    baseline: dict,
    leg_idx: int,
    days: int,
    extra_nm: float,
    corridor: str = CORRIDOR_REFERENCE,
) -> dict:
    legs = src.get("legs") or []
    chosen = legs[leg_idx]
    frm, to = chosen.get("from"), chosen.get("to")
    depart_was = _as_day(chosen.get("departIso") or chosen.get("depart"))
    shifted_leg = (shifted.get("legs") or [])[leg_idx]
    depart_now = _as_day(shifted_leg.get("departIso") or shifted_leg.get("depart"))
    alerts_before = _leg_alert_count(baseline, leg_idx)
    alerts_after = _leg_alert_count(evaluated, leg_idx)
    total_before = int(baseline.get("total") or 0)
    total_after = int(evaluated.get("total") or 0)
    cascade = cascade_stops(src, shifted, leg_idx)
    facts = advice_facts(
        frm=frm, to=to, days=days, depart_was=depart_was, depart_now=depart_now,
        alerts_before=alerts_before, alerts_after=alerts_after,
        total_before=total_before, total_after=total_after,
        extra_nm=extra_nm, cascade=cascade, corridor=corridor,
    )
    sentence = advice_sentence(
        frm=frm, days=days, depart_was=depart_was, depart_now=depart_now,
        alerts_before=alerts_before, alerts_after=alerts_after, extra_nm=extra_nm,
        corridor=corridor,
    )
    return {
        "shiftDays": int(days),
        "corridor": corridor,
        "extraNm": int(round(float(extra_nm))),
        "alertsBefore": alerts_before,
        "alertsAfter": alerts_after,
        "totalBefore": total_before,
        "totalAfter": total_after,
        "score": score_of(total_after, days, int(round(float(extra_nm)))),
        "cascade": cascade,
        "facts": facts,
        "sentence": sentence,
        "sentenceSource": "rules",
    }


def advise(
    plan: dict,
    leg_idx: int,
    *,
    now: Any = None,
    climatology: dict | None = None,
    wind_fn: Callable | None = None,
    polar_raw: dict | None = None,
    wind_max_kt: float | None = None,
    hs_max_m: float | None = None,
) -> dict:
    """Meilleur décalage × corridor + 3 alternatives. Déterministe, sans LLM."""
    src = prepare_plan(plan, now=now)
    legs = src.get("legs") or []
    if not (0 <= int(leg_idx) < len(legs)):
        raise ValueError(f"jambe {leg_idx} absente ({len(legs)} jambes)")
    now_dt = _now_dt(now)
    chosen_leg = legs[int(leg_idx)]
    frozen = _is_frozen(chosen_leg, now_dt)
    if frozen or not departure_after_now(chosen_leg, now_dt):
        shifts = (0,)
        corridors = (CORRIDOR_REFERENCE,)
    else:
        shifts = tuple(
            d for d in SHIFT_DAYS
            if _depart_dt(chosen_leg) + timedelta(days=int(d)) > now_dt
        ) or (0,)
        corridors = CORRIDORS
    th = src.get("skipper_thresholds") or {}
    gale = _f(th.get("galeKt") if isinstance(th, dict) else None) or _f(wind_max_kt)
    hs = _f(th.get("hsAlertM") if isinstance(th, dict) else None) or _f(hs_max_m)
    baseline = evaluate_plan(src, now=now_dt, climatology=climatology)
    packed = []
    eval_by_key: dict[tuple[int, str], dict] = {}
    for days in shifts:
        shifted = src if days == 0 else shift_plan(src, int(leg_idx), days)
        for corridor in corridors:
            applied = apply_corridor(shifted, int(leg_idx), corridor)
            if applied is None:
                continue
            shifted_c, extra_nm, _track = applied
            if days == 0 and corridor == CORRIDOR_REFERENCE:
                evaluated = baseline
            else:
                evaluated = evaluate_plan(shifted_c, now=now_dt, climatology=climatology)
            eval_by_key[(int(days), corridor)] = evaluated
            packed.append(_pack_candidate(
                src=src, shifted=shifted_c, evaluated=evaluated, baseline=baseline,
                leg_idx=int(leg_idx), days=int(days), extra_nm=extra_nm, corridor=corridor,
            ))
    if not packed:
        packed.append(_pack_candidate(
            src=src, shifted=src, evaluated=baseline, baseline=baseline,
            leg_idx=int(leg_idx), days=0, extra_nm=0.0, corridor=CORRIDOR_REFERENCE,
        ))
    packed.sort(key=lambda c: (
        c["score"], abs(c["shiftDays"]), c["extraNm"],
        CORRIDOR_RANK.get(c["corridor"], 9), c["shiftDays"],
    ))
    best = packed[0]
    evaluated_best = eval_by_key.get((best["shiftDays"], best["corridor"]), baseline)
    if wind_fn is not None and _has_wind_alert(evaluated_best, int(leg_idx)):
        ref = _as_coords(_leg_points((src.get("legs") or [])[int(leg_idx)]))
        chosen = corridor_track(ref, best["corridor"]) or ref
        if len(ref) >= 2:
            iso = bounded_isochrone(
                dep_lat=ref[0][0], dep_lon=ref[0][1],
                dst_lat=ref[-1][0], dst_lon=ref[-1][1],
                departure_time=_as_dt(
                    (src.get("legs") or [])[int(leg_idx)].get("departIso")
                    or (src.get("legs") or [])[int(leg_idx)].get("depart")
                ) + timedelta(days=int(best["shiftDays"])),
                wind_fn=wind_fn, reference=ref, corridor=chosen,
                polar_raw=polar_raw, wind_max_kt=gale, hs_max_m=hs,
            )
            extra = max(0.0, float(iso.get("distance_nm") or 0) - iso_track_nm(ref))
            extra_i = int(round(extra))
            best["extraNm"] = extra_i
            best["score"] = score_of(best["totalAfter"], best["shiftDays"], extra_i)
            best["routeNm"] = float(iso.get("distance_nm") or 0)
    alternatives = packed[1:4]
    return {
        "leg": int(leg_idx),
        "weights": dict(WEIGHTS),
        "best": best,
        "alternatives": alternatives,
    }


def _job_key(plan: dict, leg_idx: int, now: datetime) -> str:
    src = prepare_plan(plan, now=now)
    legs = []
    for leg in src.get("legs") or []:
        pts = [
            [round(float(p["lat"]), 3), round(float(p["lon"]), 3)]
            for p in _leg_points(leg) if p.get("lat") is not None and p.get("lon") is not None
        ]
        legs.append({
            "from": leg.get("from"), "to": leg.get("to"),
            "depart": _as_day(leg.get("departIso") or leg.get("depart")),
            "holdDays": leg.get("holdDays"), "points": pts,
        })
    payload = {"legs": legs, "leg": int(leg_idx), "now": now.strftime("%Y-%m-%d")}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def request_advice(
    plan: dict,
    leg_idx: int,
    *,
    now: Any = None,
    climatology: dict | None = None,
    rewrite: Callable[[dict], dict] | None = None,
) -> dict:
    """Réponse immédiate : pending, done, ou unavailable (jamais d'exception d'indice)."""
    src, resolved, reason = resolve_advice_leg(plan, int(leg_idx), now=now)
    if reason or resolved is None:
        return advice_unavailable(int(leg_idx), reason or "not_computable")
    now_dt = _now_dt(now)
    key = _job_key(src, int(resolved), now_dt)
    with _JOB_LOCK:
        hit = _JOBS.get(key)
        if hit and hit.get("status") == "done":
            out = copy.deepcopy(hit)
            out["leg"] = int(leg_idx)
            return out
        running = _JOB_THREADS.get(key)
        if hit and hit.get("status") == "pending" and running and running.is_alive():
            return {"status": "pending", "leg": int(leg_idx), "weights": dict(WEIGHTS)}
        _JOBS[key] = {"status": "pending", "leg": int(leg_idx), "weights": dict(WEIGHTS)}

        def _run() -> None:
            try:
                out = advise(src, int(resolved), now=now_dt, climatology=climatology)
                if rewrite:
                    out = rewrite(out)
                out["status"] = "done"
                out["leg"] = int(leg_idx)
            except Exception as exc:
                log.warning("conseil dates : %s", exc)
                try:
                    out = advise(src, int(resolved), now=now_dt, climatology=climatology)
                    out["status"] = "done"
                    out["leg"] = int(leg_idx)
                except Exception as exc2:
                    out = {"status": "done", "leg": int(leg_idx), "weights": dict(WEIGHTS), "error": str(exc2)}
            with _JOB_LOCK:
                _JOBS[key] = out

        thread = threading.Thread(target=_run, name=f"plan-advice-{leg_idx}", daemon=True)
        _JOB_THREADS[key] = thread
        thread.start()
    return {"status": "pending", "leg": int(leg_idx), "weights": dict(WEIGHTS)}
