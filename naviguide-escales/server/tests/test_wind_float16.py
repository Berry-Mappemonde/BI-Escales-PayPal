"""Vent climatologique float16 — requêtes, route, ETA.

Les roses ``wind-MM.npz`` sont stockées en float16 et relues en float32.
Le demi-ulp float16, sur les grandeurs réellement présentes (composantes
≤ 11 m/s, vitesses de secteur ≤ 34 kn), vaut au plus 0,016 kn et 0,03°.
``wind_at`` / ``atlas_at`` arrondissent déjà au dixième : l'écart publié
du vecteur moyen tient donc dans un quantum, 0,1 kn et 0,1°.

Mesure sur les 12 mois × 258 480 cellules de mer, avant conversion :
vitesse du vecteur ≤ 0,0157 kn, direction du vecteur ≤ 0,027°.
Le secteur dominant ne change que lorsque les deux premiers secteurs sont
à moins de 0,12 point de pourcentage (égalité sous la résolution publiée
de 0,1 %). 1 173 cellules sur 3 101 760, soit 0,038 %.

Route officielle Berry (44 339 nm, polaire Leopard 46, départ 2026-05-15) :
Δ ETA 0,25 h sur 8 224 h de mer (15 minutes, 0,003 %). Jambes
représentatives ci-dessous : écart de route ≤ 0,13 nm, Δ ETA ≤ 0,02 h.
Un seuil de 0,5 nm et 0,05 h reste sous ce qu'une ETA climatologique
affiche comme un autre plan.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "bi_test_wind_float16")

BACKEND = Path(__file__).resolve().parents[3] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import climatology_wind as wind_mod  # noqa: E402

from climatology_atlas import rose_speed_percentiles  # noqa: E402
from isochrone import haversine, run_leg_isochrone  # noqa: E402
from voyage_clock import build_voyage_clock  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "wind_float32_ref.npz"
# One published quantum of wind_at (0.1), plus binary dust on the rounded value.
_SPEED_KN = 0.101
_DIR_DEG = 0.101
# Above the largest raw margin observed on a sector flip (0.119 point).
_TIE_MARGIN = 0.15
_ROUTE_NM = 0.5
_ISO_H = 0.05
_ETA_H = 0.05
_FLOAT_KEYS = (
    "lats", "lons", "sector_pct", "sector_spd",
    "calm_pct", "gale_pct", "u_mean", "v_mean",
)


def _ang(a: float, b: float) -> float:
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def _as_stored(arr, quantize: bool):
    arr = np.asarray(arr)
    if quantize and np.issubdtype(arr.dtype, np.floating):
        return np.asarray(arr, dtype=np.float16).astype(np.float32)
    return arr


def _leader_margin(pct) -> float:
    valid = np.asarray(pct, dtype=np.float64)
    valid = valid[valid >= 2.5]
    if valid.size < 2:
        return 100.0
    valid.sort()
    return float(valid[-1] - valid[-2])


def _cell_bundle(fix, index: int, quantize: bool) -> dict:
    pct = fix["point_pct"][index]
    spd = fix["point_spd"][index]
    lat = np.float32(fix["point_lat"][index])
    lon = np.float32(fix["point_lon"][index])
    return {
        "lats": _as_stored(np.array([lat], dtype=np.float32), quantize),
        "lons": _as_stored(np.array([lon], dtype=np.float32), quantize),
        "sector_pct": _as_stored(np.asarray(pct, dtype=np.float32).reshape(1, 1, 8), quantize),
        "sector_spd": _as_stored(np.asarray(spd, dtype=np.float32).reshape(1, 1, 8), quantize),
        "calm_pct": _as_stored(np.array([[fix["point_calm"][index]]], dtype=np.float32), quantize),
        "gale_pct": _as_stored(np.array([[fix["point_gale"][index]]], dtype=np.float32), quantize),
        "u_mean": _as_stored(np.array([[fix["point_u"][index]]], dtype=np.float32), quantize),
        "v_mean": _as_stored(np.array([[fix["point_v"][index]]], dtype=np.float32), quantize),
        "sample_count": np.array([[int(fix["point_count"][index])]], dtype=np.int32),
        "sea_mask": np.array([[bool(fix["point_sea"][index])]]),
        "stat": np.array(["rose"]),
    }


def _leg_bundle(fix, index: int, quantize: bool) -> dict:
    prefix = f"leg{index}_"
    bundle = {"stat": np.array(["rose"])}
    for key in (
        "lats", "lons", "sector_pct", "sector_spd", "calm_pct", "gale_pct",
        "u_mean", "v_mean", "sample_count", "sea_mask",
    ):
        bundle[key] = _as_stored(fix[prefix + key], quantize and key in _FLOAT_KEYS)
    return bundle


def _use(bundle):
    wind_mod._load_month = lambda month, _b=bundle: _b


def _queries(lat: float, lon: float, month: int):
    return (
        wind_mod.wind_at(lat, lon, month, mode="average"),
        wind_mod.wind_at(lat, lon, month, mode="most_likely"),
        wind_mod.atlas_at(lat, lon, month),
    )


def _leopard_polar() -> dict:
    path = Path(__file__).resolve().parents[2] / "public" / "Leopard46_Standard_Sails.csv"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    header = lines[0].split(";")
    tws = [float(item) for item in header[1:]]
    twa, matrix = [], []
    for line in lines[1:]:
        parts = line.split(";")
        twa.append(float(parts[0]))
        matrix.append([float(item) for item in parts[1:]])
    return {"twa_rows": twa, "tws_cols": tws, "matrix": matrix}


def _wind_pack(month: int):
    def fn(lat, lon, _t):
        rose = wind_mod.atlas_at(lat, lon, month)
        if not rose:
            return {"speedKnots": 0.0, "dirFromDeg": 0.0, "kind": "climatology", "hs": 1.0}
        block = rose.get("most_likely") or rose["vector_mean"]
        return {
            "speedKnots": float(block["speed_knots"]),
            "dirFromDeg": float(block["dir_deg"]),
            "kind": "climatology",
            "hs": 1.0,
            "roseKnots": rose_speed_percentiles(rose),
        }
    return fn


def _gc(lat1, lon1, lat2, lon2, n=12):
    points = []
    dist = 0.0
    prev = None
    for i in range(n + 1):
        t = i / n
        lat = lat1 + (lat2 - lat1) * t
        lon = lon1 + (lon2 - lon1) * t
        if prev is not None:
            dist += haversine(prev[0], prev[1], lat, lon)
        prev = (lat, lon)
        points.append({"lat": lat, "lon": lon, "cumNm": dist, "filmCum": dist})
    return points


def _hausdorff_nm(route_a, route_b) -> float:
    left = route_a["draft_geojson"]["geometry"]["coordinates"]
    right = route_b["draft_geojson"]["geometry"]["coordinates"]

    def _max_to(src, dst) -> float:
        worst = 0.0
        for lon, lat in src:
            worst = max(worst, min(haversine(lat, lon, lat2, lon2) for lon2, lat2 in dst))
        return worst

    return max(_max_to(left, right), _max_to(right, left))


def test_float16_wind_queries_stay_within_one_published_quantum():
    """float32 d'origine contre float16, via wind_at et atlas_at."""
    fix = np.load(FIXTURE, allow_pickle=False)
    months = {int(m) for m in fix["point_month"]}
    assert months == set(range(1, 13))
    assert len(fix["point_month"]) >= 300

    for month in range(1, 13):
        raw = np.load(wind_mod.wind_npz_path(month), allow_pickle=False)
        for key in _FLOAT_KEYS:
            assert raw[key].dtype == np.float16, (month, key, raw[key].dtype)
        assert raw["sample_count"].dtype == np.int32
        assert raw["sea_mask"].dtype == np.bool_

    wind_mod._load_month.cache_clear()
    widened = wind_mod._load_month(1)
    assert widened["u_mean"].dtype == np.float32
    assert widened["sector_spd"].dtype == np.float32

    n = len(fix["point_month"])
    prod = []
    for i in range(n):
        prod.append(_queries(
            float(fix["point_lat"][i]), float(fix["point_lon"][i]), int(fix["point_month"][i]),
        ))

    orig = wind_mod._load_month
    try:
        for i in range(n):
            lat = float(fix["point_lat"][i])
            lon = float(fix["point_lon"][i])
            month = int(fix["point_month"][i])
            where = (month, lat, lon)
            _use(_cell_bundle(fix, i, quantize=False))
            avg32, ml32, rose32 = _queries(lat, lon, month)
            _use(_cell_bundle(fix, i, quantize=True))
            avg16, ml16, rose16 = _queries(lat, lon, month)

            assert avg32 is not None and avg16 is not None, where
            assert abs(avg32[0] - avg16[0]) <= _SPEED_KN, (where, avg32, avg16)
            assert _ang(avg32[1], avg16[1]) <= _DIR_DEG, (where, avg32, avg16)
            vm32, vm16 = rose32["vector_mean"], rose16["vector_mean"]
            assert abs(vm32["speed_knots"] - vm16["speed_knots"]) <= _SPEED_KN, where
            assert _ang(vm32["dir_deg"], vm16["dir_deg"]) <= _DIR_DEG, where

            margin = _leader_margin(fix["point_pct"][i])
            if margin > _TIE_MARGIN:
                assert ml32 is not None and ml16 is not None, where
                assert ml32[1] == ml16[1], (where, ml32, ml16, margin)
                assert abs(ml32[0] - ml16[0]) <= _SPEED_KN, (where, ml32, ml16)
                assert rose32["most_likely"]["dir_deg"] == rose16["most_likely"]["dir_deg"], where

            # The shipped archive is this float16 quantization, read back widened.
            pavg, pml, _prose = prod[i]
            assert pavg == avg16, (where, pavg, avg16)
            assert pml == ml16, (where, pml, ml16)
    finally:
        wind_mod._load_month = orig
        orig.cache_clear()


def test_float16_wind_does_not_move_route_or_eta():
    """Isochrone et horloge du simulateur, polaire Leopard 46, via atlas_at."""
    fix = np.load(FIXTURE, allow_pickle=False)
    names = [str(item) for item in fix["leg_names"]]
    assert names == ["biscay", "azores", "agulhas"]
    polar = _leopard_polar()
    orig = wind_mod._load_month
    try:
        for index, name in enumerate(names):
            month = int(fix[f"leg{index}_month"])
            dep = fix[f"leg{index}_dep"]
            dst = fix[f"leg{index}_dst"]
            la1, lo1 = float(dep[0]), float(dep[1])
            la2, lo2 = float(dst[0]), float(dst[1])
            t0 = datetime(2026, month, 15, 8, tzinfo=timezone.utc)
            packed = _wind_pack(month)

            def _iso(bundle):
                _use(bundle)
                return run_leg_isochrone(
                    la1, lo1, la2, lo2, t0,
                    wind_fn=packed, polar_raw=polar,
                    time_step_h=6, heading_step_deg=15,
                    max_steps=36, arrival_radius_nm=40,
                )

            def _eta(bundle):
                _use(bundle)
                return build_voyage_clock(
                    _gc(la1, lo1, la2, lo2), marks=[], t0=t0,
                    polar_raw=polar, start_at="seam", wind_fn=packed,
                )

            route32 = _iso(_leg_bundle(fix, index, quantize=False))
            route16 = _iso(_leg_bundle(fix, index, quantize=True))
            assert route32["status"] == "arrived", name
            assert route16["status"] == "arrived", name
            assert _hausdorff_nm(route32, route16) <= _ROUTE_NM, (
                name, _hausdorff_nm(route32, route16),
            )
            assert abs(route32["hours"] - route16["hours"]) <= _ISO_H, (
                name, route32["hours"], route16["hours"],
            )
            eta32 = _eta(_leg_bundle(fix, index, quantize=False))
            eta16 = _eta(_leg_bundle(fix, index, quantize=True))
            assert abs(eta32["seaHours"] - eta16["seaHours"]) <= _ETA_H, (
                name, eta32["seaHours"], eta16["seaHours"],
            )
    finally:
        wind_mod._load_month = orig
        orig.cache_clear()
