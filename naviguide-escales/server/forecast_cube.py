"""Cube de prévision sur un couloir (pas un GRIB globe).

Vent : Open-Meteo GFS nommé. Vague / courant : CMEMS ANFC si identifiants,
sinon Hs/courant absents (repli climatologie, kind honnête).
Le backend `synthetic` n’existe que pour les tests (NAVIGUIDE_FORECAST_BACKEND).
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from climatology_zones import zone_wind_at
from voyage_clock import parse_iso, to_iso

FORECAST_HOURS = 10 * 24
CORRIDOR_AHEAD_NM = 1500.0
CORRIDOR_BUFFER_NM = 200.0
SAMPLE_STEP_NM = 100.0
MAX_SAMPLES = 16
CACHE_TTL_H = 12.0
CUBE_MAX_BYTES = 80 * 1024 * 1024
GFS_MODEL_NAME = "GFS 0.25° (Open-Meteo)"
CMEMS_WAVE_NAME = "CMEMS ANFC 0.083°"
R_NM = 3440.065

CACHE_DIR = Path(os.environ.get(
    "NAVIGUIDE_FORECAST_CACHE",
    str(Path(__file__).resolve().parent / "forecast_cache"),
))


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * R_NM * math.asin(math.sqrt(min(1.0, a)))


def corridor_points(points: List[dict], from_sail_nm: float = 0.0,
                    ahead_nm: float = CORRIDOR_AHEAD_NM,
                    step_nm: float = SAMPLE_STEP_NM) -> List[dict]:
    pts = [p for p in (points or []) if not p.get("jump")]
    if not pts:
        return []
    start = 0
    for i, p in enumerate(pts):
        if float(p.get("cumNm") or 0) >= from_sail_nm:
            start = i
            break
    picked = [pts[start]]
    last_nm = float(pts[start].get("cumNm") or 0)
    end_nm = last_nm + ahead_nm
    for p in pts[start + 1:]:
        nm = float(p.get("cumNm") or 0)
        if nm > end_nm:
            picked.append(p)
            break
        if nm - last_nm >= step_nm:
            picked.append(p)
            last_nm = nm
        if len(picked) >= MAX_SAMPLES:
            break
    if picked[-1] is not pts[-1] and float(pts[-1].get("cumNm") or 0) <= end_nm + 1:
        if len(picked) < MAX_SAMPLES:
            picked.append(pts[-1])
    return picked


def corridor_bboxes(samples: List[dict], buffer_nm: float = CORRIDOR_BUFFER_NM) -> List[Tuple[float, float, float, float]]:
    """Un ou deux rectangles (antiméridien). (min_lat, max_lat, min_lon, max_lon)."""
    if not samples:
        return []
    pad = buffer_nm / 60.0
    lats = [p["lat"] for p in samples]
    lons = [p["lon"] for p in samples]
    min_lat, max_lat = min(lats) - pad, max(lats) + pad
    span = max(lons) - min(lons)
    if span <= 180:
        return [(min_lat, max_lat, min(lons) - pad, max(lons) + pad)]
    west = [ln for ln in lons if ln < 0]
    east = [ln for ln in lons if ln >= 0]
    boxes = []
    if west:
        boxes.append((min_lat, max_lat, min(west) - pad, max(west) + pad))
    if east:
        boxes.append((min_lat, max_lat, min(east) - pad, max(east) + pad))
    return boxes


@dataclass
class ForecastCube:
    model: str
    wave_model: Optional[str]
    issued_at: str
    times: List[str]
    samples: List[dict] = field(default_factory=list)

    def estimate_bytes(self) -> int:
        n_t = max(1, len(self.times))
        n_s = max(1, len(self.samples))
        # 6 float64 per step (u, v, hs, uo, vo, unused)
        return n_t * n_s * 6 * 8 + 4096

    def _parsed_times(self) -> List[datetime]:
        """Lead times parsed once — at() runs ~100k times per isochrone."""
        cache = self.__dict__.get("_times_cache")
        if cache is None or cache[0] is not self.times or len(cache[1]) != len(self.times):
            cache = (self.times, [parse_iso(x) for x in self.times], parse_iso(self.issued_at))
            self.__dict__["_times_cache"] = cache
        return cache[1]

    def _issued_dt(self) -> datetime:
        self._parsed_times()
        return self.__dict__["_times_cache"][2]

    def at(self, lat: float, lon: float, t: datetime) -> Optional[Dict[str, Any]]:
        if not self.samples or not self.times:
            return None
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        t_iso = to_iso(t)
        # time index: linear between two lead times
        times = self._parsed_times()
        if t <= times[0]:
            ti, tw = 0, 0.0
        elif t >= times[-1]:
            if (t - times[-1]).total_seconds() > 3 * 3600:
                return None
            ti, tw = len(times) - 2, 1.0
        else:
            ti, tw = 0, 0.0
            for i in range(len(times) - 1):
                if times[i] <= t <= times[i + 1]:
                    span = (times[i + 1] - times[i]).total_seconds() or 1
                    ti, tw = i, (t - times[i]).total_seconds() / span
                    break

        best = None
        best_d = float("inf")
        for s in self.samples:
            d = _haversine_nm(lat, lon, s["lat"], s["lon"])
            if d < best_d:
                best_d = d
                best = s
        if best is None:
            return None

        def series(key: str) -> Optional[float]:
            arr = best.get(key) or []
            if not arr or ti >= len(arr):
                return None
            a = arr[ti]
            b = arr[min(ti + 1, len(arr) - 1)]
            if a is None or b is None:
                return None
            return float(a) + (float(b) - float(a)) * tw

        u = series("u")
        v = series("v")
        if u is None or v is None:
            spd = series("speedKnots")
            direc = series("dirFromDeg")
            if spd is None or direc is None:
                return None
        else:
            spd = math.hypot(u, v) * 1.943844
            direc = (math.degrees(math.atan2(-u, -v)) + 360) % 360

        lead = (t - self._issued_dt()).total_seconds() / 3600.0
        return {
            "speedKnots": round(spd, 2),
            "dirFromDeg": round(direc, 1),
            "hs": series("hs"),
            "uo": series("uo"),
            "vo": series("vo"),
            "kind": "forecast",
            "model": self.model,
            "waveModel": self.wave_model,
            "leadHours": round(lead, 1),
            "source": "forecast_cube",
        }

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "wave_model": self.wave_model,
            "issued_at": self.issued_at,
            "times": self.times,
            "samples": self.samples,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ForecastCube":
        return cls(
            model=data["model"],
            wave_model=data.get("wave_model"),
            issued_at=data["issued_at"],
            times=data["times"],
            samples=data.get("samples") or [],
        )


def build_synthetic_cube(
    points: List[dict],
    t0: datetime,
    speed_knots: float = 22.0,
    dir_from_deg: float = 90.0,
    hours: int = FORECAST_HOURS,
    step_h: int = 3,
) -> ForecastCube:
    """Cube déterministe pour les tests — ne jamais l’étiqueter GFS."""
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    times = [to_iso(t0 + timedelta(hours=h)) for h in range(0, hours + 1, step_h)]
    n = len(times)
    samples = []
    for p in corridor_points(points, 0.0):
        samples.append({
            "lat": p["lat"],
            "lon": p["lon"],
            "speedKnots": [speed_knots] * n,
            "dirFromDeg": [dir_from_deg] * n,
            "u": None,
            "v": None,
            "hs": [1.2] * n,
            "uo": [0.0] * n,
            "vo": [0.0] * n,
        })
    return ForecastCube(
        model="synthetic-test",
        wave_model="synthetic-test",
        issued_at=to_iso(t0),
        times=times,
        samples=samples,
    )


def _fetch_open_meteo_point(lat: float, lon: float, t0: datetime, now: datetime) -> Optional[dict]:
    past_days = max(0, min(8, math.ceil((now - t0).total_seconds() / 86400) + 1)) if now > t0 else 0
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "hourly": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "kn",
        "models": "gfs_global",
        "forecast_days": 10,
        "past_days": past_days,
        "timezone": "UTC",
    }
    with httpx.Client(timeout=20.0) as client:
        resp = client.get("https://api.open-meteo.com/v1/forecast", params=params)
        resp.raise_for_status()
        data = resp.json()
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    spd = hourly.get("wind_speed_10m") or []
    direc = hourly.get("wind_direction_10m") or []
    if not times or not spd:
        return None
    return {
        "lat": lat,
        "lon": lon,
        "times": [t if t.endswith("Z") else f"{t}:00Z" if len(t) == 16 else f"{t}Z" for t in times],
        "speedKnots": spd,
        "dirFromDeg": direc,
    }


def fetch_open_meteo_cube(points: List[dict], t0: datetime,
                          from_sail_nm: float = 0.0) -> ForecastCube:
    now = datetime.now(timezone.utc)
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    samples_src = corridor_points(points, from_sail_nm)
    raws = []
    errors = 0
    for p in samples_src:
        try:
            raw = _fetch_open_meteo_point(p["lat"], p["lon"], t0, now)
            if raw:
                raws.append(raw)
        except Exception:
            errors += 1
    if not raws:
        raise RuntimeError(f"Open-Meteo GFS indisponible ({errors} erreurs)")

    # Grille temporelle commune = premier point, 3 h
    base_times = raws[0]["times"]
    picked = []
    for i, iso in enumerate(base_times):
        try:
            dt = parse_iso(iso if "Z" in iso or "+" in iso else iso + "Z")
        except Exception:
            continue
        if dt < t0 - timedelta(hours=1):
            continue
        if dt > t0 + timedelta(hours=FORECAST_HOURS) + timedelta(hours=3):
            break
        if not picked or (dt - parse_iso(picked[-1])).total_seconds() >= 2.5 * 3600:
            picked.append(to_iso(dt))
        if len(picked) > 90:
            break

    def align(raw: dict, key: str) -> List[Optional[float]]:
        index = {to_iso(parse_iso(t if "Z" in t or "+" in t else t + "Z")): i
                 for i, t in enumerate(raw["times"])}
        # also try without seconds normalisation
        out = []
        for t in picked:
            i = index.get(t)
            if i is None:
                # nearest hour key
                i = index.get(t.replace("Z", ""))
            if i is None or i >= len(raw[key]):
                out.append(None)
            else:
                out.append(raw[key][i])
        return out

    samples = []
    for raw in raws:
        samples.append({
            "lat": raw["lat"],
            "lon": raw["lon"],
            "speedKnots": align(raw, "speedKnots"),
            "dirFromDeg": align(raw, "dirFromDeg"),
            "hs": [None] * len(picked),
            "uo": [None] * len(picked),
            "vo": [None] * len(picked),
        })

    cube = ForecastCube(
        model=GFS_MODEL_NAME,
        wave_model=None,
        issued_at=to_iso(now.replace(minute=0, second=0, microsecond=0)),
        times=picked,
        samples=samples,
    )
    if cube.estimate_bytes() > CUBE_MAX_BYTES:
        cube.samples = cube.samples[: max(4, len(cube.samples) // 2)]
    return cube


def cache_path(voyage_id: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / voyage_id / "cube.json"


def save_cube(voyage_id: str, cube: ForecastCube) -> None:
    dest = cache_path(voyage_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(cube.to_dict()), encoding="utf-8")
    tmp.replace(dest)


def load_cube(voyage_id: str, max_age_h: float = CACHE_TTL_H) -> Optional[ForecastCube]:
    dest = cache_path(voyage_id)
    if not dest.exists():
        return None
    age_h = (time.time() - dest.stat().st_mtime) / 3600.0
    if age_h > max_age_h:
        return None
    try:
        return ForecastCube.from_dict(json.loads(dest.read_text(encoding="utf-8")))
    except Exception:
        return None


def build_voyage_cube(
    points: List[dict],
    t0: datetime,
    from_sail_nm: float = 0.0,
    backend: Optional[str] = None,
) -> ForecastCube:
    mode = (backend or os.environ.get("NAVIGUIDE_FORECAST_BACKEND") or "openmeteo").lower()
    if mode == "synthetic":
        return build_synthetic_cube(points, t0)
    return fetch_open_meteo_cube(points, t0, from_sail_nm)


def wind_differs_from_zone(sample: dict, lat: float, lon: float, month: int) -> bool:
    zone = zone_wind_at(lat, lon, month)
    ds = abs(float(sample.get("speedKnots") or 0) - float(zone["speedKnots"]))
    dd = abs(float(sample.get("dirFromDeg") or 0) - float(zone["dirFromDeg"]))
    dd = min(dd, 360 - dd)
    return ds > 1.0 or dd > 10.0
