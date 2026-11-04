"""ETA probabiliste par ensembles Open-Meteo.

Au-delà de 7 jours, l'arrivée n'est pas une date unique : p10 / p50 / p90
des intégrations par membre. Sans ensemble = `{members: 0}`, jamais inventé.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from climatology_atlas import atlas_wind_at_dt
from hindcast import hours_from_om, point_key
from isochrone import haversine
from pearl_store import kv_delete, kv_get, kv_put
from voyage_clock import (
    PLANNING_MIN_KN,
    build_voyage_clock,
    parse_iso,
    sample_clock_at_time,
    to_iso,
)

log = logging.getLogger("naviguide-simulator.ensemble-eta")

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_MODELS = "gfs_seamless,ecmwf_ifs025"
FORECAST_DAYS = 15
CACHE_NS = "ensemble"
CACHE_TTL_S = 6 * 3600
MAX_POINT_NM = 60.0
MAX_PROBES_PER_LEG = 12
SOURCE = "open-meteo-ensemble"
STATUS_TTL_S = 36 * 3600
ETA_BACKOFF_S = (30, 60, 120, 300, 600, 900)
REASON_UNAVAILABLE = "ensemble_unavailable"
REASON_QUOTA = "quota"
REASON_QUOTA_LABEL = "quota Open-Meteo atteint"
REASON_NETWORK = "réseau"
REASON_BEYOND_HORIZON = "beyond_horizon"
REASON_EMPTY = "empty_ensemble"
REASON_NO_STOP = "no_stop"
REASON_NO_REMAINING = "no_remaining"
REASON_INTEGRATION = "integration_empty"
# Un membre à ~0 kn faisait exploser p90 (7 mois). Même plancher
# que voyage_clock.planning_speed_for ; la fourchette affichée reste de
# quelques jours autour de p50 (jamais inventée : sans membres valides → vide).
ETA_MIN_KN = PLANNING_MIN_KN
ETA_MAX_SPAN_DAYS = 7.0
ETA_TIGHTEN_TAG = "t3"
_SPEED_KEY = re.compile(r"^(?:(?P<model>.+)_)?wind_speed_10m(?:_member(?P<n>\d+))?$")

WindFn = Callable[[float, float, datetime], Dict[str, Any]]


def empty_eta(
    now: Optional[datetime] = None,
    *,
    reason: Optional[str] = None,
    last_attempt: Optional[str] = None,
    next_retry: Optional[str] = None,
    detail: Optional[str] = None,
) -> dict:
    when = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    out = {
        "p10": None,
        "p50": None,
        "p90": None,
        "members": 0,
        "source": None,
        "computedAt": to_iso(when),
        "memberKnots": [],
    }
    if reason or last_attempt or next_retry or detail:
        out["reason"] = reason
        out["lastAttempt"] = last_attempt or to_iso(when)
        out["nextRetry"] = next_retry
        if detail:
            out["detail"] = str(detail)[:240]
    return out


def official_eta_status_key(stop: str, now: datetime) -> str:
    """État d'un warm vide (raison / prochaine relance), indépendant du clock."""
    when = _as_dt(now)
    return (
        f"eta-official-status:{_norm_stop(stop)}:{when.strftime('%Y-%m-%d')}"
        f":{when.hour // 6}:{ETA_TIGHTEN_TAG}"
    )


def compute_next_retry(
    now: datetime,
    attempt: int = 0,
    detail: Optional[str] = None,
) -> datetime:
    """Prochaine relance : quota journalier → lendemain UTC ; sinon repli 30 s → 15 min."""
    when = _as_dt(now)
    text = (detail or "").lower()
    if (
        "limit exceeded" in text
        or "try again tomorrow" in text
        or "429" in text
        or "quota" in text
    ):
        nxt = (when + timedelta(days=1)).replace(hour=0, minute=15, second=0, microsecond=0)
        if nxt <= when:
            nxt += timedelta(days=1)
        return nxt
    delay = ETA_BACKOFF_S[min(max(int(attempt), 0), len(ETA_BACKOFF_S) - 1)]
    return when + timedelta(seconds=delay)


def eta_retry_due(peeked: Optional[dict], now: datetime) -> bool:
    """True s'il faut relancer le warm (pas de membres, backoff expiré ou absent)."""
    if _positive_members((peeked or {}).get("members")) > 0:
        return False
    raw = (peeked or {}).get("nextRetry")
    if not raw:
        return True
    try:
        return _as_dt(raw) <= _as_dt(now)
    except Exception:
        return True


def explain_eta_reason(raw: Optional[dict]) -> str:
    """Raison honnête pour le stock / l'écran — jamais une date inventée."""
    if not raw:
        return REASON_UNAVAILABLE
    reason = str(raw.get("reason") or "")
    detail = str(raw.get("detail") or "")
    blob = f"{reason} {detail}".lower()
    if (
        reason in (REASON_QUOTA, REASON_QUOTA_LABEL)
        or "quota" in blob
        or "429" in blob
        or "limit exceeded" in blob
        or "try again tomorrow" in blob
    ):
        return REASON_QUOTA_LABEL
    if "network" in blob or "blocked" in blob or "réseau" in blob:
        return REASON_NETWORK
    return reason or REASON_UNAVAILABLE


def eta_store_retry_due(
    payload: Optional[dict],
    now: datetime,
    next_stop: str = "",
) -> bool:
    """True si le remplisseur doit recalculer la famille eta."""
    stops = (payload or {}).get("stops") or {}
    if not stops:
        return True
    if next_stop:
        for name, stop in stops.items():
            if match_stop(str(name), next_stop) or name == next_stop:
                return eta_retry_due(stop, now)
    if any(_positive_members((s or {}).get("members")) > 0 for s in stops.values()):
        return False
    return any(eta_retry_due(s, now) for s in stops.values())


def remember_eta_failure(
    stop: str,
    now: datetime,
    reason: str,
    detail: Optional[str] = None,
) -> dict:
    """Enregistre un warm vide : raison lue, dernière tentative, prochaine relance."""
    when = _as_dt(now)
    prev = kv_get(CACHE_NS, official_eta_status_key(stop, when), max_age_s=STATUS_TTL_S)
    raw = prev.get("value") if prev else None
    try:
        attempt = int((raw or {}).get("attempt") or 0)
    except (TypeError, ValueError):
        attempt = 0
    nxt = compute_next_retry(when, attempt, detail)
    payload = {
        "reason": reason,
        "lastAttempt": to_iso(when),
        "nextRetry": to_iso(nxt),
        "detail": (str(detail)[:240] if detail else None),
        "attempt": attempt + 1,
        "members": 0,
    }
    kv_put(CACHE_NS, official_eta_status_key(stop, when), payload)
    return empty_eta(
        when,
        reason=reason,
        last_attempt=payload["lastAttempt"],
        next_retry=payload["nextRetry"],
        detail=payload["detail"],
    )


def _empty_for(
    stop: str,
    now: datetime,
    reason: str,
    detail: Optional[str] = None,
) -> dict:
    if (stop or "").strip():
        return remember_eta_failure(stop, now, reason, detail)
    return empty_eta(now, reason=reason, detail=detail)


def _as_dt(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = parse_iso(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _norm_stop(name: str) -> str:
    return re.sub(r"[\s\-]+", "-", (name or "").strip().lower())


def match_stop(name: str, query: str) -> bool:
    n, q = _norm_stop(name), _norm_stop(query)
    if not n or not q:
        return False
    return q == n or q in n or n in q


def empirical_quantile(sorted_vals: List[float], q: float) -> Optional[float]:
    """Quantile empirique : interpolation linéaire d'indice (n−1)·q."""
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    q = min(1.0, max(0.0, float(q)))
    idx = (n - 1) * q
    lo = int(math.floor(idx))
    hi = min(lo + 1, n - 1)
    w = idx - lo
    return float(sorted_vals[lo]) * (1.0 - w) + float(sorted_vals[hi]) * w


def arrival_quantiles(arrivals: List[datetime]) -> tuple[Optional[datetime], Optional[datetime], Optional[datetime]]:
    if not arrivals:
        return None, None, None
    stamps = sorted(a.timestamp() for a in arrivals)
    out = []
    for q in (0.10, 0.50, 0.90):
        sec = empirical_quantile(stamps, q)
        out.append(None if sec is None else datetime.fromtimestamp(sec, tz=timezone.utc))
    return out[0], out[1], out[2]


def implied_speed_kn(remaining_nm: float, start: datetime, arrival: datetime) -> float:
    """Vitesse moyenne implicite (nm / heures) d'un membre, 0 si dégénéré."""
    hours = (arrival - start).total_seconds() / 3600.0
    if hours <= 0 or remaining_nm <= 0:
        return 0.0
    return float(remaining_nm) / hours


def tighten_eta_arrivals(
    arrivals: List[datetime],
    *,
    remaining_nm: float,
    now: datetime,
    min_kn: float = ETA_MIN_KN,
) -> List[datetime]:
    """Écarte les membres plus lents que le plancher de planification (3 kn)."""
    kept: List[datetime] = []
    for arr in arrivals or []:
        if implied_speed_kn(remaining_nm, now, arr) + 1e-9 >= float(min_kn):
            kept.append(arr)
    return kept


def bound_eta_quantiles(
    p10: Optional[datetime],
    p50: Optional[datetime],
    p90: Optional[datetime],
    max_span_days: float = ETA_MAX_SPAN_DAYS,
) -> tuple[Optional[datetime], Optional[datetime], Optional[datetime]]:
    """Borne p10–p90 à une fenêtre de quelques jours autour de p50."""
    if not p10 or not p50 or not p90:
        return p10, p50, p90
    span = (p90 - p10).total_seconds() / 86400.0
    if span <= float(max_span_days) + 1e-9:
        return p10, p50, p90
    half = timedelta(days=float(max_span_days) / 2.0)
    lo = max(p10, p50 - half)
    hi = min(p90, p50 + half)
    if hi < lo:
        lo = hi = p50
    return lo, p50, hi


def tighten_eta_payload(eta: dict, now: Optional[datetime] = None) -> dict:
    """Filet : fourchette déjà calculée (cache ancien) → resserrée ou vide."""
    if not eta or _positive_members(eta.get("members")) <= 0:
        return empty_eta(
            now,
            reason=eta.get("reason") if eta else None,
            last_attempt=eta.get("lastAttempt") if eta else None,
            next_retry=eta.get("nextRetry") if eta else None,
            detail=eta.get("detail") if eta else None,
        )
    knots = eta.get("memberKnots") or []
    if knots and not any(_as_kn(k) >= ETA_MIN_KN for k in knots):
        return empty_eta(now)
    try:
        p10 = _as_dt(eta["p10"]) if eta.get("p10") else None
        p50 = _as_dt(eta["p50"]) if eta.get("p50") else None
        p90 = _as_dt(eta["p90"]) if eta.get("p90") else None
    except Exception:
        return empty_eta(now)
    if not p10 or not p50 or not p90:
        return empty_eta(now)
    p10, p50, p90 = bound_eta_quantiles(p10, p50, p90)
    out = dict(eta)
    out["p10"] = to_iso(p10) if p10 else None
    out["p50"] = to_iso(p50) if p50 else None
    out["p90"] = to_iso(p90) if p90 else None
    if knots:
        out["memberKnots"] = [round(_as_kn(k), 2) for k in knots if _as_kn(k) >= ETA_MIN_KN]
    return out


def _positive_members(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _as_kn(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_members(payload: Optional[dict]) -> Dict[str, List[dict]]:
    """Colonnes `wind_speed_10m` / `wind_speed_10m_member01` (+ préfixe modèle)."""
    hourly = (payload or {}).get("hourly") or {}
    times = hourly.get("time") or []
    speed_keys = []
    for key in hourly:
        if key == "time":
            continue
        m = _SPEED_KEY.match(key)
        if m:
            speed_keys.append((key, m.group("model") or "", m.group("n")))
    members: Dict[str, List[dict]] = {}
    rows = hours_from_om(payload)
    if not rows and times:
        return {}
    isos = sorted(rows.keys())
    for key, model, num in speed_keys:
        mid = f"{model + ':' if model else ''}{('member' + num) if num else 'control'}"
        series = []
        dir_key = key.replace("wind_speed_10m", "wind_direction_10m")
        for iso in isos:
            row = rows[iso]
            spd = row.get(key)
            if spd is None:
                continue
            try:
                series.append({
                    "t": iso,
                    "speedKnots": float(spd),
                    "dirFromDeg": None if row.get(dir_key) is None else float(row[dir_key]),
                })
            except (TypeError, ValueError):
                continue
        if series:
            members[mid] = series
    return members


def _cache_key(lat: float, lon: float) -> str:
    return f"{point_key(lat, lon)}:{ENSEMBLE_MODELS}:{FORECAST_DAYS}"


_fetch_note: Dict[str, Any] = {"reason": None, "detail": None, "ok": 0, "fail": 0}


def _reset_fetch_note() -> None:
    _fetch_note["reason"] = None
    _fetch_note["detail"] = None
    _fetch_note["ok"] = 0
    _fetch_note["fail"] = 0


def _note_fetch(reason: Optional[str] = None, detail: Optional[str] = None, *, ok: bool = False) -> None:
    if ok:
        _fetch_note["ok"] = int(_fetch_note.get("ok") or 0) + 1
        return
    _fetch_note["fail"] = int(_fetch_note.get("fail") or 0) + 1
    if reason and not _fetch_note.get("reason"):
        _fetch_note["reason"] = reason
        _fetch_note["detail"] = detail


def _http_detail(resp: Any) -> str:
    text = ""
    try:
        text = (resp.text or "").strip()
    except Exception:
        text = ""
    if text:
        try:
            body = resp.json()
            if isinstance(body, dict):
                text = str(body.get("reason") or body.get("error") or text)
        except Exception:
            pass
    return text[:240]


def _fetch_ensemble_json(lat: float, lon: float) -> tuple[Optional[dict], Optional[str], Optional[str]]:
    """(payload, raison, détail). La raison n'est posée que si le payload manque.

    On lit le statut HTTP ici (429 quota) au lieu de l'avaler dans
    ``om_get`` (hindcast.py:195-197 → None). Cache par point inchangé.
    """
    from hindcast import (  # noqa: PLC0415
        _client,
        _fetch_blocked,
        om_can_spend,
        om_mark_quota,
        om_quota_reason,
        om_record_call,
    )

    if _fetch_blocked:
        return None, REASON_UNAVAILABLE, "hindcast network blocked"
    if not om_can_spend("ensemble"):
        return None, REASON_QUOTA, om_quota_reason() or REASON_QUOTA_LABEL
    params = {
        "latitude": f"{float(lat):.4f}",
        "longitude": f"{float(lon):.4f}",
        "models": ENSEMBLE_MODELS,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "kn",
        "forecast_days": FORECAST_DAYS,
        "timezone": "UTC",
        "cell_selection": "sea",
    }
    try:
        with _client() as client:
            resp = client.get(ENSEMBLE_URL, params=params)
        om_record_call()
    except Exception as exc:
        log.info("ensemble %s: %s", point_key(lat, lon), exc)
        return None, REASON_UNAVAILABLE, str(exc)[:240]
    if resp.status_code == 429:
        detail = _http_detail(resp) or "Daily API request limit exceeded"
        om_mark_quota("429")
        log.info("ensemble %s: HTTP 429 %s", point_key(lat, lon), detail)
        return None, REASON_QUOTA, detail
    if resp.status_code >= 400:
        detail = _http_detail(resp) or f"HTTP {resp.status_code}"
        log.info("ensemble %s: HTTP %s %s", point_key(lat, lon), resp.status_code, detail)
        return None, REASON_UNAVAILABLE, detail
    try:
        return resp.json(), None, None
    except Exception as exc:
        log.info("ensemble %s: %s", point_key(lat, lon), exc)
        return None, REASON_UNAVAILABLE, str(exc)[:240]


def fetch_point_members(lat: float, lon: float) -> Dict[str, List[dict]]:
    """Une requête Ensemble API, cache 6 h. Vide si panne (jamais inventé)."""
    key = _cache_key(lat, lon)
    hit = kv_get(CACHE_NS, key, max_age_s=CACHE_TTL_S)
    if hit and isinstance(hit.get("value"), dict):
        raw = hit["value"].get("members")
        if isinstance(raw, dict) and raw:
            _note_fetch(ok=True)
            return raw
    try:
        data, reason, detail = _fetch_ensemble_json(lat, lon)
    except RuntimeError as exc:
        _note_fetch(REASON_UNAVAILABLE, str(exc)[:240])
        return {}
    if reason or data is None:
        _note_fetch(reason or REASON_UNAVAILABLE, detail)
        return {}
    members = parse_members(data)
    if members:
        kv_put(CACHE_NS, key, {"members": members, "source": SOURCE})
        _note_fetch(ok=True)
        return members
    _note_fetch(REASON_EMPTY, "ensemble payload without members")
    return {}


def _cap_probes(points: List[dict], max_probes: int) -> List[dict]:
    """Garde premier et dernier, répartit le reste. L'intégration n'est pas échantillonnée."""
    if max_probes < 2 or len(points) <= max_probes:
        return points
    out: List[dict] = []
    last_idx = -1
    span = len(points) - 1
    for i in range(max_probes):
        idx = int(round(i * span / (max_probes - 1)))
        if idx <= last_idx:
            idx = last_idx + 1
        if idx > span:
            break
        out.append(points[idx])
        last_idx = idx
    if out and out[-1] is not points[-1]:
        out[-1] = points[-1]
    return out


def sample_leg_points(
    points: List[dict],
    max_nm: float = MAX_POINT_NM,
    max_probes: int = MAX_PROBES_PER_LEG,
) -> List[dict]:
    """Sommets de la jambe, pas ≤ 60 nm, puis plafond (≤ 12 sondes)."""
    if not points:
        return []
    out = [points[0]]
    last_nm = float(points[0].get("cumNm") or 0)
    last = points[0]
    for p in points[1:]:
        nm = float(p.get("cumNm") or 0)
        gap = nm - last_nm
        if gap > max_nm + 1e-6:
            steps = max(2, int(math.ceil(gap / max_nm)))
            for i in range(1, steps):
                frac = i / steps
                out.append({
                    "lat": last["lat"] + frac * (p["lat"] - last["lat"]),
                    "lon": last["lon"] + frac * (p["lon"] - last["lon"]),
                    "cumNm": last_nm + frac * gap,
                    "filmCum": float(last.get("filmCum") or last_nm) + frac * (
                        float(p.get("filmCum") or nm) - float(last.get("filmCum") or last_nm)
                    ),
                })
            out.append(p)
            last_nm, last = nm, p
        elif gap >= max_nm - 1e-6 or p is points[-1]:
            if p is not out[-1]:
                out.append(p)
            last_nm, last = nm, p
    if points[-1] is not out[-1]:
        out.append(points[-1])
    return _cap_probes(out, max_probes)


def _nearest_hour(series: List[dict], when: datetime) -> Optional[dict]:
    if not series:
        return None
    return min(series, key=lambda h: abs((_as_dt(h["t"]) - when).total_seconds()))


def _nearest_point(points: List[dict], lat: float, lon: float) -> Optional[dict]:
    if not points:
        return None
    return min(points, key=lambda p: haversine(lat, lon, float(p["lat"]), float(p["lon"])))


def _climo_pack(lat: float, lon: float, t: datetime) -> dict:
    try:
        pack = atlas_wind_at_dt(lat, lon, t)
    except Exception:
        pack = {}
    pack = dict(pack or {})
    pack.setdefault("kind", "climatology")
    pack.setdefault("regime", "climatology")
    return pack


def _member_at(
    member_id: str,
    fields: List[dict],
    lat: float,
    lon: float,
    t: datetime,
    now: datetime,
) -> dict:
    """Vent du membre si t ≤ now+15 j ; sinon climatologie médiane. Mer / courant = climato."""
    climo = _climo_pack(lat, lon, t)
    horizon = now + timedelta(days=FORECAST_DAYS)
    if t > horizon:
        return climo
    pt = _nearest_point(fields, lat, lon)
    series = (pt or {}).get("members", {}).get(member_id) or []
    hour = _nearest_hour(series, t)
    if not hour or hour.get("speedKnots") is None:
        return climo
    return {
        **climo,
        "speedKnots": hour["speedKnots"],
        "dirFromDeg": hour.get("dirFromDeg") if hour.get("dirFromDeg") is not None else climo.get("dirFromDeg"),
        "kind": "ensemble",
        "regime": "ensemble",
        "source": SOURCE,
        "roseKnots": None,
    }


def _remaining_points(points: List[dict], sample: dict, end_nm: float) -> List[dict]:
    start_nm = float(sample.get("sailNm") or sample.get("filmNm") or 0)
    out = [{
        "lat": float(sample["lat"]),
        "lon": float(sample["lon"]),
        "cumNm": start_nm,
        "filmCum": float(sample.get("filmNm") or start_nm),
        "jump": False,
        "nonMaritime": False,
    }]
    for p in points or []:
        nm = float(p.get("cumNm") or 0)
        if nm <= start_nm + 0.01:
            continue
        if nm > end_nm + 0.5:
            break
        out.append(p)
    return out


def _find_stop(marks: List[dict], stop: str) -> Optional[dict]:
    for m in marks or []:
        if match_stop(str(m.get("name") or ""), stop):
            return m
    return None


def _integrate_member(
    points: List[dict],
    stop_name: str,
    now: datetime,
    polar_raw: Optional[dict],
    wind_fn: WindFn,
) -> Optional[datetime]:
    if len(points) < 2:
        return None
    end = points[-1]
    marks = [{
        "name": stop_name,
        "index": len(points) - 1,
        "nm": float(end.get("cumNm") or 0),
        "filmNm": float(end.get("filmCum") or end.get("cumNm") or 0),
        "lat": end.get("lat"),
        "lon": end.get("lon"),
    }]
    clock = build_voyage_clock(
        points, marks, now, polar_raw=polar_raw,
        start_at="saint-maur", wind_fn=wind_fn,
    )
    for m in clock.get("marks") or []:
        if match_stop(str(m.get("name") or ""), stop_name) and m.get("iso"):
            return _as_dt(m["iso"])
    iso = clock.get("arrivalIso")
    return _as_dt(iso) if iso else None


def official_eta_alias_key(stop: str, now: datetime) -> str:
    """Clé cache stable par escale + cycle 6 h — lisible sans clock."""
    when = _as_dt(now)
    return (
        f"eta-official:{_norm_stop(stop)}:{when.strftime('%Y-%m-%d')}"
        f":{when.hour // 6}:{ETA_TIGHTEN_TAG}"
    )


def peek_official_eta(voy: dict, stop: str, now: datetime) -> dict:
    """Lecture cache uniquement. Jamais de clock ni de fetch."""
    when = _as_dt(now)
    empty = empty_eta(when)
    if not isinstance(voy, dict) or not (stop or "").strip():
        return empty
    clock = voy.get("clock")
    if clock:
        sample = sample_clock_at_time(clock, when)
        if sample and sample.get("lat") is not None:
            marks = voy.get("marks") or clock.get("marks") or []
            if _find_stop(marks, stop):
                result_key = (
                    f"eta:{_norm_stop(stop)}:{point_key(sample['lat'], sample['lon'])}"
                    f":{when.strftime('%Y-%m-%d')}:{when.hour // 6}:{ETA_TIGHTEN_TAG}"
                )
                cached = kv_get(CACHE_NS, result_key, max_age_s=CACHE_TTL_S)
                raw = cached.get("value") if cached else None
                if isinstance(raw, dict) and raw.get("members"):
                    return dict(raw)
    alias = kv_get(CACHE_NS, official_eta_alias_key(stop, when), max_age_s=CACHE_TTL_S)
    raw = alias.get("value") if alias else None
    if isinstance(raw, dict) and raw.get("members"):
        return dict(raw)
    status = kv_get(CACHE_NS, official_eta_status_key(stop, when), max_age_s=STATUS_TTL_S)
    raw = status.get("value") if status else None
    if isinstance(raw, dict) and (raw.get("reason") or raw.get("lastAttempt")):
        return empty_eta(
            when,
            reason=raw.get("reason"),
            last_attempt=raw.get("lastAttempt"),
            next_retry=raw.get("nextRetry"),
            detail=raw.get("detail"),
        )
    return empty


def compute_eta(
    *,
    points: List[dict],
    marks: List[dict],
    stop: str,
    now: datetime,
    polar_raw: Optional[dict] = None,
    sample: Optional[dict] = None,
    clock: Optional[dict] = None,
) -> dict:
    """Intègre la jambe restante pour chaque membre → p10 / p50 / p90.

    `sample` = position actuelle (sinon échantillon d'horloge à `now`).
    """
    now = _as_dt(now)
    stop_mark = _find_stop(marks, stop)
    if not stop_mark or not points:
        return _empty_for(stop, now, REASON_NO_STOP)
    if sample is None and clock:
        sample = sample_clock_at_time(clock, now)
    if not sample or sample.get("lat") is None:
        return _empty_for(stop, now, REASON_NO_STOP)
    result_key = (
        f"eta:{_norm_stop(stop)}:{point_key(sample['lat'], sample['lon'])}"
        f":{now.strftime('%Y-%m-%d')}:{now.hour // 6}:{ETA_TIGHTEN_TAG}"
    )
    cached = kv_get(CACHE_NS, result_key, max_age_s=CACHE_TTL_S)
    if cached and isinstance(cached.get("value"), dict) and cached["value"].get("members"):
        return tighten_eta_payload(cached["value"], now)
    status_hit = kv_get(CACHE_NS, official_eta_status_key(stop, now), max_age_s=STATUS_TTL_S)
    raw_status = status_hit.get("value") if status_hit else None
    if isinstance(raw_status, dict) and not eta_retry_due(raw_status, now):
        return empty_eta(
            now,
            reason=raw_status.get("reason"),
            last_attempt=raw_status.get("lastAttempt"),
            next_retry=raw_status.get("nextRetry"),
            detail=raw_status.get("detail"),
        )
    end_nm = float(stop_mark.get("nm") or stop_mark.get("filmNm") or 0)
    start_nm = float(sample.get("sailNm") or sample.get("filmNm") or 0)
    if end_nm <= start_nm + 0.5:
        return _empty_for(stop, now, REASON_NO_REMAINING)
    remaining = _remaining_points(points, sample, end_nm)
    if len(remaining) < 2:
        return _empty_for(stop, now, REASON_NO_REMAINING)
    remaining_nm = max(0.0, end_nm - start_nm)
    probes = sample_leg_points(remaining, MAX_POINT_NM)
    fields: List[dict] = []
    member_ids: set[str] = set()
    _reset_fetch_note()
    for p in probes:
        try:
            members = fetch_point_members(float(p["lat"]), float(p["lon"]))
        except RuntimeError as exc:
            _note_fetch(REASON_UNAVAILABLE, str(exc)[:240])
            members = {}
        except Exception as exc:
            log.info("ensemble %s: %s", point_key(p["lat"], p["lon"]), exc)
            _note_fetch(REASON_UNAVAILABLE, str(exc)[:240])
            members = {}
        if members:
            fields.append({"lat": p["lat"], "lon": p["lon"], "members": members})
            member_ids.update(members)
    if not fields or not member_ids:
        reason = _fetch_note.get("reason") or REASON_UNAVAILABLE
        hours_left = remaining_nm / max(ETA_MIN_KN, 1e-6)
        if reason == REASON_EMPTY and hours_left > FORECAST_DAYS * 24.0:
            reason = REASON_BEYOND_HORIZON
        return _empty_for(stop, now, reason, _fetch_note.get("detail"))
    arrivals: List[datetime] = []
    for mid in sorted(member_ids):
        def wind_fn(lat, lon, t, _mid=mid):
            return _member_at(_mid, fields, lat, lon, t, now)
        try:
            arrived = _integrate_member(remaining, str(stop_mark.get("name") or stop), now, polar_raw, wind_fn)
        except Exception as exc:
            log.info("ensemble integrate %s: %s", mid, exc)
            arrived = None
        if arrived is not None:
            arrivals.append(arrived)
    if not arrivals:
        return _empty_for(stop, now, REASON_INTEGRATION)
    kept = tighten_eta_arrivals(arrivals, remaining_nm=remaining_nm, now=now)
    if not kept:
        return _empty_for(stop, now, REASON_INTEGRATION)
    member_knots = [round(implied_speed_kn(remaining_nm, now, arr), 2) for arr in kept]
    p10, p50, p90 = arrival_quantiles(kept)
    p10, p50, p90 = bound_eta_quantiles(p10, p50, p90)
    if not p10 or not p50 or not p90:
        return _empty_for(stop, now, REASON_INTEGRATION)
    out = {
        "p10": to_iso(p10),
        "p50": to_iso(p50),
        "p90": to_iso(p90),
        "members": len(kept),
        "source": SOURCE,
        "computedAt": to_iso(now),
        "memberKnots": member_knots,
    }
    kv_put(CACHE_NS, result_key, out)
    kv_put(CACHE_NS, official_eta_alias_key(stop, now), out)
    kv_delete(CACHE_NS, official_eta_status_key(stop, now))
    return out


def official_eta(voy: dict, stop: str, now: datetime, polar_raw: Optional[dict] = None) -> dict:
    clock = voy.get("clock")
    if not clock:
        clock = build_voyage_clock(
            voy.get("points") or [],
            voy.get("marks") or [],
            voy.get("t0") or now,
            polar_raw=polar_raw,
            start_at=voy.get("startAt") or "la-rochelle",
        )
    return tighten_eta_payload(compute_eta(
        points=voy.get("points") or [],
        marks=voy.get("marks") or clock.get("marks") or [],
        stop=stop,
        now=now,
        polar_raw=polar_raw,
        clock=clock,
    ), now)


def next_official_stop(voy: dict, now: datetime) -> str:
    """Prochaine escale (iso > now) du voyage officiel. Vide si aucune."""
    now = _as_dt(now)
    clock = voy.get("clock") or {}
    marks = clock.get("marks") or voy.get("marks") or []
    for m in marks:
        iso = m.get("iso")
        name = str(m.get("name") or "").strip()
        if not name or not iso:
            continue
        try:
            if _as_dt(iso) > now:
                return name
        except Exception:
            continue
    return ""


def preheat_official_eta(
    voy: dict,
    now: datetime,
    polar_raw: Optional[dict] = None,
    stop: Optional[str] = None,
) -> dict:
    """Chauffe l'ensemble de la prochaine escale (ou `stop`). Sans membres → vide."""
    now = _as_dt(now)
    target = (stop or "").strip() or next_official_stop(voy, now)
    if not target:
        return empty_eta(now)
    peeked = peek_official_eta(voy, target, now)
    if not eta_retry_due(peeked, now):
        return tighten_eta_payload(peeked, now)
    return official_eta(voy, target, now, polar_raw=polar_raw)
