"""Hindcast multi-sources — Open-Meteo + Copernicus, fusion par médiane.

Une source en panne manque ; aucune source → champ vide (jamais inventé).
Cache SQLite `pearl_store.kv` ns `hindcast`, clé (cellule ERA5 0,25°, produit, jour).
Budget Open-Meteo : ns `om-budget`, plafond NAVIGUIDE_OM_DAILY_BUDGET (défaut 3000).
Enveloppe unique partagée avec l'ensemble ETA : l'hindcast du jour
a la priorité, une part NAVIGUIDE_OM_ETA_RESERVED (défaut 24) reste pour
la prochaine escale — l'un n'épuise pas l'autre.
"""
from __future__ import annotations

import logging
import math
import os
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

from pearl_store import kv_get, kv_put
from voyage_clock import parse_iso, to_iso

log = logging.getLogger("naviguide-simulator.hindcast")

ERA5_STRONG_WIND_FACTOR = 1.05
ERA5_STRONG_WIND_MS = 15.0
MS_TO_KN = 1.943844
HINDCAST_PAD_DAYS = 2
CACHE_NS = "hindcast"
OM_BUDGET_NS = "om-budget"
FETCH_TIMEOUT_S = 20.0
ERA5_CELL_DEG = 0.25
READY_COVERAGE = 0.95
DEFAULT_OM_DAILY_BUDGET = 3000
# Prochaine escale : ≤ MAX_PROBES_PER_LEG (12) + marge, hors plafond hindcast.
DEFAULT_OM_ETA_RESERVED = 24

OM_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
OM_ERA5_URL = "https://archive-api.open-meteo.com/v1/archive"
OM_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
OM_WIND_HOURLY = "wind_speed_10m,wind_direction_10m,wind_gusts_10m"
OM_MARINE_HOURLY = (
    "wave_height,wave_direction,wave_period,"
    "ocean_current_velocity,ocean_current_direction"
)
OM_MARINE_HOURLY_WAVES = "wave_height,wave_direction,wave_period"

SRC_OM_FORECAST = "om-forecast"
SRC_OM_ERA5 = "om-era5"
SRC_OM_MARINE = "om-marine"
SRC_CMEMS_WIND = "cmems-wind"
SRC_CMEMS_WAVE = "cmems-wave"
SRC_CMEMS_PHY = "cmems-phy"

PRODUCTS = (
    SRC_OM_FORECAST,
    SRC_OM_ERA5,
    SRC_OM_MARINE,
    SRC_CMEMS_WIND,
    SRC_CMEMS_WAVE,
    SRC_CMEMS_PHY,
)
# Vent du passé pour l'horloge : ERA5 Open-Meteo, sans Copernicus.
ERA5_PRODUCTS = (SRC_OM_ERA5,)

# Tests branchent un client / des fetchers CMEMS. Jamais le réseau réel.
_http_factory: Optional[Callable[[], httpx.Client]] = None
_cmems_wind: Optional[Callable] = None
_cmems_wave: Optional[Callable] = None
_cmems_phy: Optional[Callable] = None
_fetch_blocked = False
_om_http_count = 0


class OpenMeteoQuotaExceeded(Exception):
    """429 ou plafond journalier — le remplissage s'arrête jusqu'au lendemain UTC."""


def bind_http(factory: Optional[Callable[[], httpx.Client]]) -> None:
    global _http_factory
    _http_factory = factory


def bind_cmems(*, wind=None, wave=None, phy=None) -> None:
    global _cmems_wind, _cmems_wave, _cmems_phy
    _cmems_wind, _cmems_wave, _cmems_phy = wind, wave, phy


def block_network() -> None:
    """Deuxième appel cache : tout fetch lève (test « sans réseau »)."""
    global _fetch_blocked
    _fetch_blocked = True


def unblock_network() -> None:
    global _fetch_blocked
    _fetch_blocked = False


def reset_hooks() -> None:
    global _om_http_count
    bind_http(None)
    bind_cmems(wind=None, wave=None, phy=None)
    unblock_network()
    _om_http_count = 0


def om_http_call_count() -> int:
    """Appels HTTP Open-Meteo réellement envoyés depuis `reset_hooks` (tests)."""
    return _om_http_count


def hindcast_enabled() -> bool:
    if (os.getenv("NAVIGUIDE_OFFLINE") or "").strip().lower() in ("1", "true", "yes"):
        return False
    raw = (os.getenv("NAVIGUIDE_HINDCAST") or "1").lower()
    if raw in ("0", "false", "no"):
        return False
    if (os.getenv("NAVIGUIDE_FORECAST_BACKEND") or "").lower() == "synthetic":
        return False
    return True


def cell_center(lat: float, lon: float) -> tuple[float, float]:
    """Centre de la cellule ERA5 0,25° la plus proche (arrondi)."""
    step = ERA5_CELL_DEG

    def _snap(value: float) -> float:
        return round(round(float(value) / step) * step, 2)

    return _snap(lat), _snap(lon)


def point_key(lat: float, lon: float) -> str:
    clat, clon = cell_center(lat, lon)
    return f"{clat:.2f}:{clon:.2f}"


def cache_key(lat: float, lon: float, product: str, day: str) -> str:
    return f"{point_key(lat, lon)}:{product}:{day}"


def om_daily_budget() -> int:
    raw = (os.getenv("NAVIGUIDE_OM_DAILY_BUDGET") or "").strip()
    if not raw:
        return DEFAULT_OM_DAILY_BUDGET
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_OM_DAILY_BUDGET


def om_eta_reserved() -> int:
    """Appels gardés pour l'ETA de la prochaine escale (ensemble)."""
    raw = (os.getenv("NAVIGUIDE_OM_ETA_RESERVED") or "").strip()
    if not raw:
        n = DEFAULT_OM_ETA_RESERVED
    else:
        try:
            n = max(0, int(raw))
        except ValueError:
            n = DEFAULT_OM_ETA_RESERVED
    return min(n, om_daily_budget())


def om_hindcast_ceiling() -> int:
    """Plafond hindcast : le budget moins la part réservée à l'ETA."""
    return max(0, om_daily_budget() - om_eta_reserved())


def om_can_spend(purpose: str = "hindcast") -> bool:
    """True s'il reste un appel pour ce rôle. 429 / plafond total → False pour tous."""
    if om_quota_blocked():
        return False
    used = om_calls_today()
    if purpose == "ensemble":
        return used < om_daily_budget()
    return used < om_hindcast_ceiling()


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _budget_key(day: Optional[str] = None) -> str:
    return f"calls:{day or _utc_day()}"


def _block_key(day: Optional[str] = None) -> str:
    return f"blocked:{day or _utc_day()}"


def om_calls_today() -> int:
    hit = kv_get(OM_BUDGET_NS, _budget_key())
    val = (hit or {}).get("value")
    if isinstance(val, dict):
        try:
            return int(val.get("n") or 0)
        except (TypeError, ValueError):
            return 0
    if isinstance(val, int):
        return val
    return 0


def om_quota_blocked() -> bool:
    hit = kv_get(OM_BUDGET_NS, _block_key())
    if hit and hit.get("value"):
        return True
    return om_calls_today() >= om_daily_budget()


def om_quota_reason() -> Optional[str]:
    hit = kv_get(OM_BUDGET_NS, _block_key())
    val = (hit or {}).get("value")
    if isinstance(val, dict) and val.get("reason"):
        raw = str(val["reason"])
        if raw in ("429", "budget", "quota Open-Meteo"):
            return "quota Open-Meteo"
        return raw
    if val:
        return "quota Open-Meteo"
    if om_calls_today() >= om_daily_budget():
        return "quota Open-Meteo"
    return None


def _mark_om_quota_blocked(reason: str) -> None:
    kv_put(OM_BUDGET_NS, _block_key(), {"reason": reason})


def om_record_call() -> None:
    """Compte un appel Open-Meteo (hindcast ou ensemble) dans l'enveloppe du jour."""
    _record_om_call()


def om_mark_quota(reason: str) -> None:
    """429 ou plafond : bloque l'enveloppe partagée jusqu'au lendemain UTC."""
    _mark_om_quota_blocked(reason)


def _record_om_call() -> None:
    global _om_http_count
    _om_http_count += 1
    n = om_calls_today() + 1
    kv_put(OM_BUDGET_NS, _budget_key(), {"n": n})
    if n >= om_daily_budget():
        _mark_om_quota_blocked("budget")


def _cached_hours(hit: Optional[dict]) -> Any:
    if not hit or not isinstance(hit.get("value"), dict):
        return None
    hours = hit["value"].get("hours")
    return hours or None


def _day_str(day: str | datetime) -> str:
    if isinstance(day, datetime):
        if day.tzinfo is None:
            day = day.replace(tzinfo=timezone.utc)
        return day.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return str(day)[:10]


def _as_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = parse_iso(str(value) if "T" in str(value) else f"{value}T00:00:00Z")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def uv_to_wind_from(u: float, v: float) -> tuple[float, float]:
    """eastward, northward (m/s) → (kn, direction « de »)."""
    speed_ms = math.sqrt(u * u + v * v)
    from_deg = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
    return speed_ms * MS_TO_KN, from_deg


def uv_to_current_to(uo: float, vo: float) -> tuple[float, float]:
    """uo, vo (m/s) → (kn, direction « vers »). uo=1, vo=0 → 90°."""
    speed_ms = math.sqrt(uo * uo + vo * vo)
    to_deg = (math.degrees(math.atan2(uo, vo)) + 360.0) % 360.0
    return speed_ms * MS_TO_KN, to_deg


def apply_era5_correction(speed_kn: float) -> float:
    """Facteur 1,05 seulement au-dessus de 15 m/s, seulement ERA5."""
    speed_ms = float(speed_kn) / MS_TO_KN
    if speed_ms > ERA5_STRONG_WIND_MS:
        speed_ms *= ERA5_STRONG_WIND_FACTOR
    return speed_ms * MS_TO_KN


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return float(statistics.median(values))


def _circ_median(degs: List[float]) -> Optional[float]:
    if not degs:
        return None
    if len(degs) == 1:
        return float(degs[0]) % 360.0
    best, best_s = degs[0], float("inf")
    for cand in degs:
        s = sum(abs(((x - cand + 180.0) % 360.0) - 180.0) for x in degs)
        if s < best_s:
            best, best_s = cand, s
    return float(best) % 360.0


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN
        return None
    return n


def _client() -> httpx.Client:
    if _http_factory:
        return _http_factory()
    return httpx.Client(timeout=FETCH_TIMEOUT_S)


def _om_get(url: str, params: dict) -> Optional[dict]:
    if _fetch_blocked:
        raise RuntimeError("hindcast network blocked")
    if not om_can_spend("hindcast"):
        if om_calls_today() >= om_daily_budget() and not kv_get(OM_BUDGET_NS, _block_key()):
            _mark_om_quota_blocked("budget")
        raise OpenMeteoQuotaExceeded(om_quota_reason() or "quota Open-Meteo")
    try:
        with _client() as client:
            resp = client.get(url, params=params)
            _record_om_call()
            if resp.status_code == 429:
                _mark_om_quota_blocked("429")
                log.info("open-meteo %s: 429 quota", url.split("/")[2])
                raise OpenMeteoQuotaExceeded("quota Open-Meteo")
            resp.raise_for_status()
            return resp.json()
    except OpenMeteoQuotaExceeded:
        raise
    except Exception as exc:
        log.info("open-meteo %s: %s", url.split("/")[2], exc)
        return None


def om_get(url: str, params: dict) -> Optional[dict]:
    """Client HTTP Open-Meteo partagé (hindcast, ensembles). `None` si panne ou quota."""
    try:
        return _om_get(url, params)
    except OpenMeteoQuotaExceeded:
        return None


def hours_from_om(payload: Optional[dict]) -> Dict[str, dict]:
    return _hours_from_om(payload)


def _hours_from_om(payload: Optional[dict]) -> Dict[str, dict]:
    hourly = (payload or {}).get("hourly") or {}
    times = hourly.get("time") or []
    out: Dict[str, dict] = {}
    for i, raw in enumerate(times):
        try:
            iso = to_iso(parse_iso(raw if "Z" in raw or "+" in raw[10:] else f"{raw}:00Z" if len(raw) == 16 else f"{raw}Z"))
        except Exception:
            continue
        out[iso] = {k: (hourly[k][i] if i < len(hourly.get(k) or []) else None) for k in hourly if k != "time"}
    return out


def _fetch_om_forecast(lat: float, lon: float, day: str) -> Optional[dict]:
    data = _om_get(OM_FORECAST_URL, {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": day,
        "end_date": day,
        "hourly": OM_WIND_HOURLY,
        "wind_speed_unit": "kn",
        "timezone": "UTC",
    })
    if data is None:
        return None
    hours = {}
    for iso, row in _hours_from_om(data).items():
        hours[iso] = {
            "speedKnots": _num(row.get("wind_speed_10m")),
            "dirFromDeg": _num(row.get("wind_direction_10m")),
            "gustKnots": _num(row.get("wind_gusts_10m")),
        }
    return {"hours": hours, "source": SRC_OM_FORECAST}


def _era5_hour_row(row: dict) -> dict:
    raw = _num(row.get("wind_speed_10m"))
    return {
        "speedKnots": apply_era5_correction(raw) if raw is not None else None,
        "dirFromDeg": _num(row.get("wind_direction_10m")),
        "gustKnots": _num(row.get("wind_gusts_10m")),
    }


def _split_hours_by_day(hours: Dict[str, dict]) -> Dict[str, dict]:
    by_day: Dict[str, dict] = {}
    for iso, row in hours.items():
        day = str(iso)[:10]
        by_day.setdefault(day, {})[iso] = row
    return by_day


# ERA5 répond des null pour les jours pas encore publiés (~5 j de retard) :
# un jour avec moins de 20 heures de vent n'est PAS mis en cache — il sera
# redemandé quand l'archive l'aura publié (HC1 : le cache est immuable).
ERA5_MIN_PUBLISHED_HOURS = 20


def _era5_published_day(day_hours: dict) -> Optional[dict]:
    kept = {iso: row for iso, row in (day_hours or {}).items()
            if row.get("speedKnots") is not None}
    if len(kept) < ERA5_MIN_PUBLISHED_HOURS:
        return None
    return kept


def _fetch_om_era5(lat: float, lon: float, day: str, end_date: Optional[str] = None) -> Optional[dict]:
    clat, clon = cell_center(lat, lon)
    start = _day_str(day)
    end = _day_str(end_date or day)
    data = _om_get(OM_ERA5_URL, {
        "latitude": f"{clat:.4f}",
        "longitude": f"{clon:.4f}",
        "start_date": start,
        "end_date": end,
        "hourly": OM_WIND_HOURLY,
        "wind_speed_unit": "kn",
        "timezone": "UTC",
    })
    if data is None:
        return None
    hours = {}
    for iso, row in _hours_from_om(data).items():
        hours[iso] = _era5_hour_row(row)
    extra = {}
    for d, pack in _split_hours_by_day(hours).items():
        kept = _era5_published_day(pack)
        if kept:
            extra[d] = {"hours": kept}
    packed = extra.get(start) or {"hours": {}}
    return {"hours": packed.get("hours") or {}, "source": SRC_OM_ERA5, "extraDays": extra}


def _fetch_om_marine(lat: float, lon: float, day: str) -> Optional[dict]:
    data = _om_get(OM_MARINE_URL, {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": day,
        "end_date": day,
        "hourly": OM_MARINE_HOURLY,
        "timezone": "UTC",
    })
    if data is None:
        data = _om_get(OM_MARINE_URL, {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "start_date": day,
            "end_date": day,
            "hourly": OM_MARINE_HOURLY_WAVES,
            "timezone": "UTC",
        })
    if data is None:
        return None
    hours = {}
    for iso, row in _hours_from_om(data).items():
        current_ms = _num(row.get("ocean_current_velocity"))
        hours[iso] = {
            "hs": _num(row.get("wave_height")),
            "waveDirFromDeg": _num(row.get("wave_direction")),
            "wavePeriodS": _num(row.get("wave_period")),
            "currentKn": None if current_ms is None else current_ms * MS_TO_KN,
            "currentToDeg": _num(row.get("ocean_current_direction")),
        }
    return {"hours": hours, "source": SRC_OM_MARINE}


def _cmems_creds() -> tuple[Optional[str], Optional[str]]:
    return os.getenv("COPERNICUS_USERNAME"), os.getenv("COPERNICUS_PASSWORD")


def _cmems_hook(product: str):
    if product == SRC_CMEMS_WIND:
        return _cmems_wind
    if product == SRC_CMEMS_WAVE:
        return _cmems_wave
    if product == SRC_CMEMS_PHY:
        return _cmems_phy
    return None


def _product_enabled(product: str) -> bool:
    """CMEMS : seulement si un hook de test ou des identifiants sont là.

    Sans ça, RA8 ne tente même pas Copernicus — le vent du passé vient d'ERA5.
    """
    if product not in (SRC_CMEMS_WIND, SRC_CMEMS_WAVE, SRC_CMEMS_PHY):
        return True
    if _cmems_hook(product) is not None:
        return True
    user, password = _cmems_creds()
    return bool(user and password)


def _window_for_day(day: str) -> tuple[datetime, datetime]:
    d0 = parse_iso(f"{day}T00:00:00Z")
    start = d0 - timedelta(days=HINDCAST_PAD_DAYS)
    end = d0 + timedelta(days=HINDCAST_PAD_DAYS, hours=23)
    return start, end


def _split_cmems_by_day(rows: List[dict]) -> Dict[str, dict]:
    by_day: Dict[str, dict] = {}
    for row in rows or []:
        t = row.get("t")
        if not t:
            continue
        day = str(t)[:10]
        by_day.setdefault(day, {"hours": {}})
        by_day[day]["hours"][t] = {k: v for k, v in row.items() if k != "t"}
    return by_day


def _fetch_cmems_wind(lat: float, lon: float, day: str) -> Optional[dict]:
    if _fetch_blocked:
        raise RuntimeError("hindcast network blocked")
    start, end = _window_for_day(day)
    hook = _cmems_wind
    if hook is None:
        try:
            from copernicus.getWind import get_wind_series
            user, password = _cmems_creds()
            hook = lambda la, lo, s, e: get_wind_series(la, lo, start=s, end=e, username=user, password=password)
        except Exception as exc:
            log.info("cmems-wind import: %s", exc)
            return None
    try:
        rows = hook(lat, lon, start, end) or []
    except Exception as exc:
        log.info("cmems-wind: %s", exc)
        return None
    by_day = _split_cmems_by_day(rows)
    packed = by_day.get(day)
    return {"hours": (packed or {}).get("hours") or {}, "source": SRC_CMEMS_WIND, "extraDays": by_day}


def _fetch_cmems_wave(lat: float, lon: float, day: str) -> Optional[dict]:
    if _fetch_blocked:
        raise RuntimeError("hindcast network blocked")
    start, end = _window_for_day(day)
    hook = _cmems_wave
    if hook is None:
        try:
            from copernicus.getWave import get_wave_series
            user, password = _cmems_creds()
            hook = lambda la, lo, s, e: get_wave_series(la, lo, start=s, end=e, username=user, password=password)
        except Exception as exc:
            log.info("cmems-wave import: %s", exc)
            return None
    try:
        rows = hook(lat, lon, start, end) or []
    except Exception as exc:
        log.info("cmems-wave: %s", exc)
        return None
    by_day = _split_cmems_by_day(rows)
    packed = by_day.get(day)
    return {"hours": (packed or {}).get("hours") or {}, "source": SRC_CMEMS_WAVE, "extraDays": by_day}


def _fetch_cmems_phy(lat: float, lon: float, day: str) -> Optional[dict]:
    if _fetch_blocked:
        raise RuntimeError("hindcast network blocked")
    start, end = _window_for_day(day)
    hook = _cmems_phy
    if hook is None:
        try:
            from copernicus.getCurrent import get_current_series
            user, password = _cmems_creds()
            hook = lambda la, lo, s, e: get_current_series(la, lo, start=s, end=e, username=user, password=password)
        except Exception as exc:
            log.info("cmems-phy import: %s", exc)
            return None
    try:
        rows = hook(lat, lon, start, end) or []
    except Exception as exc:
        log.info("cmems-phy: %s", exc)
        return None
    by_day = _split_cmems_by_day(rows)
    packed = by_day.get(day)
    return {"hours": (packed or {}).get("hours") or {}, "source": SRC_CMEMS_PHY, "extraDays": by_day}


_FETCHERS = {
    SRC_OM_FORECAST: _fetch_om_forecast,
    SRC_OM_ERA5: _fetch_om_era5,
    SRC_OM_MARINE: _fetch_om_marine,
    SRC_CMEMS_WIND: _fetch_cmems_wind,
    SRC_CMEMS_WAVE: _fetch_cmems_wave,
    SRC_CMEMS_PHY: _fetch_cmems_phy,
}


def _blend_cache_id(products: tuple) -> str:
    wanted = tuple(products)
    if wanted == PRODUCTS:
        return "blend"
    return "blend:" + "+".join(wanted)


def _store_product_day(lat: float, lon: float, product: str, day: str, hours: dict) -> Optional[dict]:
    """Écrit une journée seulement si elle a des heures — un échec n'est pas un résultat."""
    if not hours:
        return None
    stored = {"hours": hours, "source": product}
    kv_put(CACHE_NS, cache_key(lat, lon, product, day), stored)
    return stored


def _load_product(lat: float, lon: float, product: str, day: str, *, fetch: bool = True) -> Optional[dict]:
    key = cache_key(lat, lon, product, day)
    hit = kv_get(CACHE_NS, key)
    hours = _cached_hours(hit)
    if hours:
        return hit["value"]
    if _fetch_blocked:
        raise RuntimeError("hindcast network blocked")
    if not fetch:
        return None
    fetcher = _FETCHERS[product]
    raw = fetcher(lat, lon, day)
    if raw is None:
        return None
    extra = raw.pop("extraDays", None)
    stored = _store_product_day(lat, lon, product, day, raw.get("hours") or {})
    if extra:
        for extra_day, pack in extra.items():
            if extra_day == day:
                continue
            _store_product_day(lat, lon, product, extra_day, pack.get("hours") or {})
    return stored


def _fuse_scalar(samples: List[tuple[str, float]], circular: bool = False) -> dict:
    if not samples:
        return {"value": None, "sources": [], "spread": None, "values": {}}
    values = {src: val for src, val in samples}
    nums = list(values.values())
    if circular:
        value = _circ_median(nums)
        arcs = [abs(((x - y + 180.0) % 360.0) - 180.0) for x in nums for y in nums]
        spread = max(arcs) if arcs else 0.0
    else:
        value = _median(nums)
        spread = (max(nums) - min(nums)) if nums else None
    return {
        "value": None if value is None else round(float(value), 3),
        "sources": [src for src, _ in samples],
        "spread": None if spread is None else round(float(spread), 3),
        "values": values,
    }


def _fuse_hour(by_source: Dict[str, dict]) -> dict:
    wind_speed, wind_dir, gust = [], [], []
    hs, wave_dir, period = [], [], []
    cur_kn, cur_to = [], []
    for src, row in by_source.items():
        if row.get("speedKnots") is not None:
            wind_speed.append((src, float(row["speedKnots"])))
        if row.get("dirFromDeg") is not None:
            wind_dir.append((src, float(row["dirFromDeg"])))
        if row.get("gustKnots") is not None:
            gust.append((src, float(row["gustKnots"])))
        if row.get("hs") is not None:
            hs.append((src, float(row["hs"])))
        if row.get("waveDirFromDeg") is not None:
            wave_dir.append((src, float(row["waveDirFromDeg"])))
        if row.get("wavePeriodS") is not None:
            period.append((src, float(row["wavePeriodS"])))
        if row.get("currentKn") is not None:
            cur_kn.append((src, float(row["currentKn"])))
        if row.get("currentToDeg") is not None:
            cur_to.append((src, float(row["currentToDeg"])))
    fused = {
        "speedKnots": _fuse_scalar(wind_speed),
        "dirFromDeg": _fuse_scalar(wind_dir, circular=True),
        "gustKnots": _fuse_scalar(gust),
        "hs": _fuse_scalar(hs),
        "waveDirFromDeg": _fuse_scalar(wave_dir, circular=True),
        "wavePeriodS": _fuse_scalar(period),
        "currentKn": _fuse_scalar(cur_kn),
        "currentToDeg": _fuse_scalar(cur_to, circular=True),
    }
    sources = []
    for src in PRODUCTS:
        if src in by_source:
            sources.append(src)
    return {
        "speedKnots": fused["speedKnots"]["value"],
        "dirFromDeg": fused["dirFromDeg"]["value"],
        "gustKnots": fused["gustKnots"]["value"],
        "hs": fused["hs"]["value"],
        "waveDirFromDeg": fused["waveDirFromDeg"]["value"],
        "wavePeriodS": fused["wavePeriodS"]["value"],
        "currentKn": fused["currentKn"]["value"],
        "currentToDeg": fused["currentToDeg"]["value"],
        "sources": sources,
        "spread": fused["speedKnots"]["spread"],
        "byVar": fused,
        "bySource": by_source,
        "kind": "hindcast",
        "regime": "hindcast",
    }


def series(
    lat: float,
    lon: float,
    day: str | datetime,
    *,
    products: Optional[tuple] = None,
    fetch: bool = True,
) -> dict:
    """Vent / houle / courant horaires du `day` (UTC), sources demandées, médiane.

    `products=ERA5_PRODUCTS` : archive Open-Meteo seulement.
    `fetch=False` : cache uniquement, aucun appel réseau.
    """
    day = _day_str(day)
    wanted = tuple(products) if products else PRODUCTS
    blend_key = cache_key(lat, lon, _blend_cache_id(wanted), day)
    hit = kv_get(CACHE_NS, blend_key)
    if hit and isinstance(hit.get("value"), dict) and hit["value"].get("hours"):
        return hit["value"]

    loaded: Dict[str, dict] = {}
    for product in wanted:
        if not _product_enabled(product):
            continue
        try:
            pack = _load_product(lat, lon, product, day, fetch=fetch)
        except OpenMeteoQuotaExceeded:
            raise
        except RuntimeError:
            raise
        except Exception as exc:
            log.info("hindcast %s: %s", product, exc)
            pack = None
        if pack and pack.get("hours"):
            loaded[product] = pack

    times: set[str] = set()
    for pack in loaded.values():
        times.update(pack.get("hours") or {})
    hours = []
    for iso in sorted(times):
        by_source = {}
        for src, pack in loaded.items():
            row = (pack.get("hours") or {}).get(iso)
            if row:
                by_source[src] = row
        fused = _fuse_hour(by_source)
        fused["t"] = iso
        hours.append(fused)
    out = {
        "day": day,
        "lat": round(float(lat), 4),
        "lon": round(float(lon), 4),
        "hours": hours,
        "products": sorted(loaded.keys()),
    }
    if fetch and hours:
        kv_put(CACHE_NS, blend_key, out)
    return out


def at(
    lat: float,
    lon: float,
    t: datetime | str,
    *,
    products: Optional[tuple] = None,
    fetch: bool = True,
) -> dict:
    """Heure la plus proche ; champs vides si rien n'a répondu."""
    when = _as_dt(t)
    day = when.strftime("%Y-%m-%d")
    try:
        packed = series(lat, lon, day, products=products, fetch=fetch)
    except OpenMeteoQuotaExceeded:
        packed = {"hours": []}
    except Exception:
        packed = {"hours": []}
    hours = packed.get("hours") or []
    if not hours:
        return {
            "speedKnots": None,
            "dirFromDeg": None,
            "gustKnots": None,
            "hs": None,
            "currentKn": None,
            "currentToDeg": None,
            "sources": [],
            "spread": None,
            "kind": "hindcast",
            "regime": "hindcast",
            "reason": "hindcast_empty",
        }
    target = to_iso(when)
    best = min(hours, key=lambda h: abs((parse_iso(h["t"]) - when).total_seconds()))
    return {**best, "kind": "hindcast", "regime": "hindcast", "t": best.get("t") or target}


def empty_pack() -> dict:
    return {
        "speedKnots": None,
        "dirFromDeg": None,
        "sources": [],
        "spread": None,
        "kind": "hindcast",
        "regime": "hindcast",
        "reason": "hindcast_empty",
    }


def past_passage_slots(clock: dict, now: datetime | str) -> List[tuple[float, float, str]]:
    """(lat, lon, jour) des sommets déjà parcourus, hors avion — un créneau par cellule."""
    now_d = _as_dt(now)
    slots: List[tuple[float, float, str]] = []
    seen: set[tuple[str, str]] = set()
    for v in (clock or {}).get("vertices") or []:
        if v.get("vehicle") in ("plane", "side"):
            continue
        iso = v.get("iso")
        if not iso or v.get("lat") is None or v.get("lon") is None:
            continue
        try:
            t = parse_iso(iso)
        except Exception:
            continue
        if t >= now_d:
            continue
        day = t.strftime("%Y-%m-%d")
        clat, clon = cell_center(v["lat"], v["lon"])
        key = (point_key(clat, clon), day)
        if key in seen:
            continue
        seen.add(key)
        slots.append((clat, clon, day))
    return slots


def uncovered_era5_slots(clock: dict, now: datetime | str) -> List[tuple[float, float, str]]:
    """Cellules du passé sans série ERA5 en cache — à compléter en fond."""
    missing: List[tuple[float, float, str]] = []
    for lat, lon, day in past_passage_slots(clock, now):
        hit = kv_get(CACHE_NS, cache_key(lat, lon, SRC_OM_ERA5, day))
        if not _cached_hours(hit):
            missing.append((lat, lon, day))
    return missing


def _shift_day(day: str, n: int) -> str:
    return (datetime.strptime(_day_str(day), "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


def _contiguous_ranges(days: List[str]) -> List[tuple[str, str]]:
    if not days:
        return []
    ordered = sorted(set(days))
    ranges: List[tuple[str, str]] = []
    start = prev = ordered[0]
    for d in ordered[1:]:
        if d == _shift_day(prev, 1):
            prev = d
        else:
            ranges.append((start, prev))
            start = prev = d
    ranges.append((start, prev))
    return ranges


def _load_era5_range(lat: float, lon: float, start: str, end: str) -> int:
    """Un appel Open-Meteo pour une plage ; chaque jour non vide est mis en cache."""
    raw = _fetch_om_era5(lat, lon, start, end_date=end)
    if raw is None:
        return 0
    extra = raw.get("extraDays") or {}
    stored = 0
    if raw.get("hours"):
        extra = {**extra, start: {"hours": raw["hours"]}}
    for day, pack in extra.items():
        if _store_product_day(lat, lon, SRC_OM_ERA5, day, pack.get("hours") or {}):
            stored += 1
    return stored


def fill_era5_along(slots, *, fetch: bool = True) -> int:
    """Archive ERA5 Open-Meteo le long du trait, sans Copernicus.

    Un appel par (cellule 0,25°, plage de jours contigus). Un échec n'est pas
    mis en cache. Au premier 429 ou plafond, on s'arrête jusqu'au lendemain UTC.
    """
    if om_quota_blocked():
        return 0
    needed: List[tuple[float, float, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in slots or []:
        if not item or len(item) < 3:
            continue
        try:
            lat, lon, day = float(item[0]), float(item[1]), _day_str(item[2])
        except (TypeError, ValueError):
            continue
        clat, clon = cell_center(lat, lon)
        key = (point_key(clat, clon), day)
        if key in seen:
            continue
        seen.add(key)
        hit = kv_get(CACHE_NS, cache_key(clat, clon, SRC_OM_ERA5, day))
        if _cached_hours(hit):
            continue
        needed.append((clat, clon, day))
    if not fetch or not needed:
        return 0
    by_cell: Dict[str, List[tuple[float, float, str]]] = {}
    for lat, lon, day in needed:
        by_cell.setdefault(point_key(lat, lon), []).append((lat, lon, day))
    n = 0
    for items in by_cell.values():
        if om_quota_blocked():
            break
        lat, lon = items[0][0], items[0][1]
        for start, end in _contiguous_ranges([it[2] for it in items]):
            if om_quota_blocked() or om_calls_today() >= om_hindcast_ceiling():
                if om_calls_today() >= om_daily_budget():
                    _mark_om_quota_blocked("budget")
                break
            try:
                n += _load_era5_range(lat, lon, start, end)
            except OpenMeteoQuotaExceeded:
                log.info("era5 fill stop: quota Open-Meteo")
                return n
            except Exception as exc:
                log.info("era5 fill %s %s–%s: %s", point_key(lat, lon), start, end, exc)
                continue
        if om_quota_blocked():
            break
    return n


ERA5_WINDOW_PAD_DAYS = 3
_MIGRATION_KEY = "migration:v1"


def era5_day_cached(lat: float, lon: float, day: str | datetime) -> bool:
    """Vrai si la série ERA5 de (cellule, jour) est en cache — jamais de réseau."""
    hit = kv_get(CACHE_NS, cache_key(lat, lon, SRC_OM_ERA5, _day_str(day)))
    return bool(_cached_hours(hit))


def fill_era5_window(lat: float, lon: float, day: str | datetime,
                     *, pad_days: int = ERA5_WINDOW_PAD_DAYS) -> Optional[int]:
    """UN appel archive pour la cellule : la plage contiguë de jours NON cachés
    autour de `day` dans [jour−pad, jour+pad] (le besoin vient du
    trajet réel intégré, jamais de l'horloge climatologique).

    Un jour déjà en cache n'est JAMAIS redemandé. Retourne le nombre de jours
    stockés, `None` si l'appel a échoué (panne — rien n'est mis en cache).
    Lève `OpenMeteoQuotaExceeded` au 429 / plafond.
    """
    clat, clon = cell_center(lat, lon)
    target = _day_str(day)
    if era5_day_cached(clat, clon, target):
        return 0
    lo = target
    while _shift_day(lo, -1) >= _shift_day(target, -pad_days) and not era5_day_cached(clat, clon, _shift_day(lo, -1)):
        lo = _shift_day(lo, -1)
    hi = target
    while _shift_day(hi, 1) <= _shift_day(target, pad_days) and not era5_day_cached(clat, clon, _shift_day(hi, 1)):
        hi = _shift_day(hi, 1)
    raw = _fetch_om_era5(clat, clon, lo, end_date=hi)
    if raw is None:
        return None
    extra = raw.get("extraDays") or {}
    if raw.get("hours"):
        extra = {**extra, lo: {"hours": raw["hours"]}}
    stored = 0
    for d, pack in extra.items():
        if _store_product_day(clat, clon, SRC_OM_ERA5, d, pack.get("hours") or {}):
            stored += 1
    return stored


def migrate_orphan_cache_keys() -> dict:
    """Re-clé les séries d'avant RF10 (coordonnées brutes) sur leur cellule 0,25°.

    Sans ambiguïté seulement : si la clé cellule existe déjà, l'orpheline est
    abandonnée (on ne remplace jamais une série immuable). Les clés composites
    (blend) sont laissées telles quelles.
    """
    from pearl_store import kv_delete, kv_keys  # noqa: PLC0415

    out = {"scanned": 0, "migrated": 0, "abandoned": 0}
    for key in kv_keys(CACHE_NS):
        parts = str(key).split(":")
        if len(parts) != 4:
            continue
        lat_s, lon_s, product, day = parts
        if product not in PRODUCTS:
            continue
        try:
            lat, lon = float(lat_s), float(lon_s)
        except ValueError:
            continue
        canonical = cache_key(lat, lon, product, day)
        if canonical == key:
            continue
        out["scanned"] += 1
        hit = kv_get(CACHE_NS, key)
        if not _cached_hours(hit) or kv_get(CACHE_NS, canonical) is not None:
            out["abandoned"] += 1
            continue
        kv_put(CACHE_NS, canonical, hit["value"])
        kv_delete(CACHE_NS, key)
        out["migrated"] += 1
    return out


def migrate_orphans_once() -> Optional[dict]:
    """Migration une seule fois par store (marqueur dans le cache)."""
    if kv_get(CACHE_NS, _MIGRATION_KEY):
        return None
    out = migrate_orphan_cache_keys()
    kv_put(CACHE_NS, _MIGRATION_KEY, out)
    if out["scanned"]:
        log.info("hindcast: migration des clés orphelines — %(migrated)s re-clées, "
                 "%(abandoned)s abandonnées sur %(scanned)s", out)
    return out


def era5_coverage(clock: dict, now: datetime | str) -> tuple[int, int]:
    """(remplis, total) des créneaux passés ayant des heures ERA5."""
    slots = past_passage_slots(clock, now)
    filled = 0
    for lat, lon, day in slots:
        hit = kv_get(CACHE_NS, cache_key(lat, lon, SRC_OM_ERA5, day))
        if _cached_hours(hit):
            filled += 1
    return filled, len(slots)


def hindcast_status_fields(clock: dict, now: datetime | str, *, obtained: bool) -> dict:
    """Statut honnête : ready ≥ 95 %, sinon partial n/total, sinon empty + raison."""
    filled, total = era5_coverage(clock, now)
    coverage = f"{filled}/{total}"
    reason = None
    if total == 0 or filled == 0:
        status = "empty"
        if om_quota_blocked() or om_quota_reason():
            reason = "quota Open-Meteo"
        elif total > 0:
            reason = "panne"
    elif filled / total >= READY_COVERAGE:
        status = "ready"
    else:
        status = "partial"
        if om_quota_blocked():
            reason = "quota Open-Meteo"
    out = {
        "hindcastStatus": status,
        "hindcastCoverage": coverage,
        "hindcastReason": reason,
    }
    if obtained:
        out["hindcastRefreshedAt"] = to_iso(_as_dt(now))
    return out
