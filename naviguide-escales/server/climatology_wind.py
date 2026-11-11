"""Roses de vent climatologiques (archives float16, relues en float32).

Les fichiers ``wind-MM.npz`` vivent sous ``NAVIGUIDE_WIND_ROSE_DIR`` (défaut :
``tests/fixtures/wind_roses`` pour la suite pytest, ou ``server/wind_roses``).
"""
from __future__ import annotations

import functools
import math
import os
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np

_FLOAT_KEYS = (
    "lats",
    "lons",
    "sector_pct",
    "sector_spd",
    "calm_pct",
    "gale_pct",
    "u_mean",
    "v_mean",
)
_SECTOR_FROM_DEG = (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0)
CellRef = Union[tuple[str, int, int], tuple[str, int]]


def _rose_dir() -> Path:
    raw = (os.environ.get("NAVIGUIDE_WIND_ROSE_DIR") or "").strip()
    if raw:
        return Path(raw)
    here = Path(__file__).resolve().parent
    test_fix = here / "tests" / "fixtures" / "wind_roses"
    if test_fix.is_dir():
        return test_fix
    return here / "wind_roses"


def wind_npz_path(month: int) -> Path:
    m = max(1, min(12, int(month or 1)))
    return _rose_dir() / f"wind-{m:02d}.npz"


def _widen(arr: np.ndarray) -> np.ndarray:
    if np.issubdtype(arr.dtype, np.floating):
        return np.asarray(arr, dtype=np.float32)
    return arr


def _pub_speed(value: float) -> float:
    return round(float(value), 1)


def _norm360(deg: float) -> float:
    x = math.fmod(float(deg), 360.0)
    if x < 0.0:
        x = math.fmod(x + 360.0, 360.0)
    return x


def _pub_dir(value: float) -> float:
    return round(_norm360(value), 1)


@functools.lru_cache(maxsize=16)
def _load_month(month: int) -> dict[str, Any]:
    path = wind_npz_path(month)
    raw = np.load(path, allow_pickle=False)
    out: dict[str, Any] = {}
    for key in raw.files:
        val = raw[key]
        if key in _FLOAT_KEYS:
            out[key] = _widen(val)
        else:
            out[key] = val
    out["stat"] = raw.get("stat", np.array(["rose"]))
    return out


def _cell_index(lat: float, lon: float, bundle: dict[str, Any]) -> Optional[CellRef]:
    lats = np.asarray(bundle["lats"], dtype=np.float32).reshape(-1)
    lons = np.asarray(bundle["lons"], dtype=np.float32).reshape(-1)
    if lats.size == 0:
        return None
    pct = np.asarray(bundle["sector_pct"], dtype=np.float32)
    if pct.ndim == 3 and pct.shape[0] == lats.size and pct.shape[1] == lons.size:
        cell = 0.5
        la = round(round(float(lat) / cell) * cell, 4)
        lo = round(round(float(lon) / cell) * cell, 4)
        lat_hit = np.where(np.isclose(lats, la, atol=1e-3))[0]
        lon_hit = np.where(np.isclose(lons, lo, atol=1e-3))[0]
        if lat_hit.size and lon_hit.size:
            return ("grid", int(lat_hit[0]), int(lon_hit[0]))
        i = int(np.argmin(np.abs(lats - la)))
        j = int(np.argmin(np.abs(lons - lo)))
        if abs(float(lats[i]) - la) > 0.26 or abs(float(lons[j]) - lo) > 0.26:
            return None
        return ("grid", i, j)
    d2 = (lats - float(lat)) ** 2 + (lons - float(lon)) ** 2
    idx = int(np.argmin(d2))
    if float(d2[idx]) > 0.26:
        return None
    return ("flat", idx)


def _vector_from_uv(u: float, v: float) -> tuple[float, float]:
    speed_kn = math.hypot(u, v) * 1.94384
    toward = math.degrees(math.atan2(u, v))
    from_deg = _norm360(toward + 180.0)
    return _pub_speed(speed_kn), _pub_dir(from_deg)


def _most_likely(pct: np.ndarray, spd: np.ndarray) -> tuple[float, float]:
    p = np.asarray(pct, dtype=np.float64).reshape(-1)
    s = np.asarray(spd, dtype=np.float64).reshape(-1)
    if p.size < 8:
        return 0.0, 0.0
    idx = int(np.argmax(p))
    return _pub_speed(s[idx]), _pub_dir(_SECTOR_FROM_DEG[idx])


def _sea_ok(bundle: dict[str, Any], ref: CellRef) -> bool:
    mask = np.asarray(bundle["sea_mask"], dtype=bool)
    if ref[0] == "grid":
        return bool(mask[ref[1], ref[2]])
    return bool(mask.reshape(-1)[ref[1]])


def _at_cell(bundle: dict[str, Any], ref: CellRef) -> dict[str, Any]:
    pct = np.asarray(bundle["sector_pct"], dtype=np.float32)
    spd = np.asarray(bundle["sector_spd"], dtype=np.float32)
    if ref[0] == "grid":
        _, i, j = ref
        pct_row = pct[i, j]
        spd_row = spd[i, j]
        u = float(np.asarray(bundle["u_mean"], dtype=np.float32)[i, j])
        v = float(np.asarray(bundle["v_mean"], dtype=np.float32)[i, j])
        calm = float(np.asarray(bundle["calm_pct"], dtype=np.float32)[i, j])
        gale = float(np.asarray(bundle["gale_pct"], dtype=np.float32)[i, j])
    else:
        _, idx = ref
        pct_row = pct[idx]
        spd_row = spd[idx]
        u = float(np.asarray(bundle["u_mean"], dtype=np.float32).reshape(-1)[idx])
        v = float(np.asarray(bundle["v_mean"], dtype=np.float32).reshape(-1)[idx])
        calm = float(np.asarray(bundle["calm_pct"], dtype=np.float32).reshape(-1)[idx])
        gale = float(np.asarray(bundle["gale_pct"], dtype=np.float32).reshape(-1)[idx])
    vm_speed, vm_dir = _vector_from_uv(u, v)
    ml_speed, ml_dir = _most_likely(pct_row, spd_row)
    return {
        "vector_mean": {"speed_knots": vm_speed, "dir_deg": vm_dir},
        "most_likely": {"speed_knots": ml_speed, "dir_deg": ml_dir},
        "calm_pct": calm,
        "gale_pct": gale,
        "stat": "rose",
    }


def atlas_at(lat: float, lon: float, month: int) -> Optional[dict[str, Any]]:
    bundle = _load_month(max(1, min(12, int(month or 1))))
    ref = _cell_index(lat, lon, bundle)
    if ref is None or not _sea_ok(bundle, ref):
        return None
    return _at_cell(bundle, ref)


def wind_at(
    lat: float,
    lon: float,
    month: int,
    *,
    mode: str = "average",
) -> Optional[tuple[float, float]]:
    rose = atlas_at(lat, lon, month)
    if not rose:
        return None
    block = rose["most_likely"] if mode == "most_likely" else rose["vector_mean"]
    return block["speed_knots"], block["dir_deg"]
