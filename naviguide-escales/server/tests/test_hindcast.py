"""Hindcast multi-sources, médiane, cache, conventions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from climatology_zones import boat_speed_from_wind
from forecast_blend import blended_wind
from hindcast import (
    ERA5_PRODUCTS,
    ERA5_STRONG_WIND_FACTOR,
    MS_TO_KN,
    SRC_OM_ERA5,
    apply_era5_correction,
    at,
    bind_cmems,
    bind_http,
    block_network,
    cache_key,
    cell_center,
    fill_era5_along,
    hindcast_status_fields,
    om_can_spend,
    om_eta_reserved,
    om_hindcast_ceiling,
    om_http_call_count,
    om_quota_blocked,
    past_passage_slots,
    reset_hooks,
    series,
    uncovered_era5_slots,
    uv_to_current_to,
)
from pearl_store import kv_count, kv_get, kv_put
from voyage_clock import build_voyage_clock, parse_iso, sample_clock_at_time, sog_along_route, to_iso

T0 = datetime(2026, 5, 15, 8, tzinfo=timezone.utc)
DAY0 = "2026-05-15"
DAY1 = "2026-05-16"
LAT, LON = 46.15, -1.16


@pytest.fixture(autouse=True)
def _hooks():
    reset_hooks()
    yield
    reset_hooks()


def _dates(start: str, end: str) -> list[str]:
    d = datetime.fromisoformat(start).date()
    last = datetime.fromisoformat(end).date()
    out = []
    while d <= last:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _hours(start: str, end: str) -> list[str]:
    times = []
    for day in _dates(start, end):
        times.extend(f"{day}T{h:02d}:00" for h in range(24))
    return times


def _om_json(times: list[str], *, speed: float, marine: bool = False, era5_hours: dict | None = None) -> dict:
    n = len(times)
    if marine:
        return {"hourly": {
            "time": times,
            "wave_height": [1.2] * n,
            "wave_direction": [240.0] * n,
            "wave_period": [8.0] * n,
            "ocean_current_velocity": [0.2] * n,
            "ocean_current_direction": [90.0] * n,
        }}
    speeds = []
    for iso in times:
        if era5_hours and iso[11:13] in era5_hours:
            speeds.append(era5_hours[iso[11:13]])
        else:
            speeds.append(speed)
    return {"hourly": {
        "time": times,
        "wind_speed_10m": speeds,
        "wind_direction_10m": [0.0] * n,
        "wind_gusts_10m": [s + 3 for s in speeds],
    }}


def bind_om(*, forecast_kn=20.0, era5_kn=20.0, marine_ok=True, era5_hours=None, fail_hosts=()):
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if any(h in host for h in fail_hosts):
            return httpx.Response(503, text="down")
        params = dict(request.url.params)
        start = params.get("start_date")
        end = params.get("end_date") or start
        times = _hours(start, end)
        if "marine-api" in host:
            if not marine_ok:
                return httpx.Response(400, text="unknown current vars")
            return httpx.Response(200, json=_om_json(times, speed=0, marine=True))
        if "archive-api" in host:
            return httpx.Response(200, json=_om_json(times, speed=era5_kn, era5_hours=era5_hours))
        return httpx.Response(200, json=_om_json(times, speed=forecast_kn))

    bind_http(lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def _cmems_rows(start, end, **fields):
    t = start if getattr(start, "tzinfo", None) else start.replace(tzinfo=timezone.utc)
    e = end if getattr(end, "tzinfo", None) else end.replace(tzinfo=timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    if e.tzinfo is None:
        e = e.replace(tzinfo=timezone.utc)
    rows = []
    cur = t
    while cur <= e:
        rows.append({"t": to_iso(cur), **fields})
        cur += timedelta(hours=1)
    return rows


def bind_ok_cmems(*, wind_kn=20.0, fail_wind=False):
    def wind(_la, _lo, start, end):
        if fail_wind:
            raise RuntimeError("cmems-wind down")
        return _cmems_rows(start, end, speedKnots=wind_kn, dirFromDeg=0.0)

    def wave(_la, _lo, start, end):
        return _cmems_rows(start, end, hs=1.5, waveDirFromDeg=240.0, wavePeriodS=8.0)

    def phy(_la, _lo, start, end):
        return _cmems_rows(start, end, currentKn=0.4, currentToDeg=90.0)

    bind_cmems(wind=wind, wave=wave, phy=phy)


def test_median_of_three_wind_sources():
    bind_om(forecast_kn=8.0, era5_kn=10.0)
    bind_ok_cmems(wind_kn=12.0)
    packed = series(LAT, LON, DAY0)
    hour = next(h for h in packed["hours"] if h["t"].startswith(f"{DAY0}T12"))
    assert hour["speedKnots"] == 10.0
    assert set(hour["byVar"]["speedKnots"]["sources"]) == {"om-forecast", "om-era5", "cmems-wind"}
    assert hour["spread"] == 4.0
    assert hour["regime"] == "hindcast"


def test_one_source_down_spread_from_two():
    bind_om(forecast_kn=8.0, era5_kn=12.0)
    bind_ok_cmems(fail_wind=True)
    hour = next(h for h in series(LAT, LON, DAY0)["hours"] if h["t"].startswith(f"{DAY0}T06"))
    assert hour["speedKnots"] == 10.0
    assert hour["spread"] == 4.0
    assert "cmems-wind" not in hour["sources"]
    assert "om-forecast" in hour["sources"] and "om-era5" in hour["sources"]


def test_cache_second_call_without_network():
    bind_om()
    bind_ok_cmems()
    first = series(LAT, LON, DAY0)
    assert first["hours"]
    block_network()
    second = series(LAT, LON, DAY0)
    assert len(second["hours"]) == len(first["hours"])
    assert second["hours"][0]["speedKnots"] == first["hours"][0]["speedKnots"]


def test_all_sources_down_empty_then_climatology():
    bind_http(lambda: httpx.Client(transport=httpx.MockTransport(
        lambda _r: httpx.Response(503, text="down")
    )))
    bind_cmems(
        wind=lambda *_a: (_ for _ in ()).throw(RuntimeError("down")),
        wave=lambda *_a: (_ for _ in ()).throw(RuntimeError("down")),
        phy=lambda *_a: (_ for _ in ()).throw(RuntimeError("down")),
    )
    packed = series(LAT, LON, DAY0)
    assert packed["hours"] == []
    empty = at(LAT, LON, T0)
    assert empty["speedKnots"] is None
    assert empty["sources"] == []
    climo = blended_wind(
        LAT, LON, T0 - timedelta(hours=2), T0, None,
        atlas_network=False, now=T0, hindcast_fn=lambda *_a: empty,
    )
    assert climo["kind"] == "climatology"
    assert climo["regime"] == "climatology"
    assert climo.get("reason") == "hindcast_empty"


def test_era5_correction_only_above_15ms_and_only_era5():
    strong_kn = 16.0 * MS_TO_KN
    weak_kn = 10.0 * MS_TO_KN
    bind_om(forecast_kn=strong_kn, era5_kn=strong_kn, era5_hours={"12": weak_kn})
    bind_ok_cmems(wind_kn=strong_kn)
    packed = series(LAT, LON, DAY0)
    strong = next(h for h in packed["hours"] if h["t"].startswith(f"{DAY0}T00"))
    weak = next(h for h in packed["hours"] if h["t"].startswith(f"{DAY0}T12"))
    era5_strong = strong["bySource"]["om-era5"]["speedKnots"]
    fc_strong = strong["bySource"]["om-forecast"]["speedKnots"]
    era5_weak = weak["bySource"]["om-era5"]["speedKnots"]
    assert abs(fc_strong - strong_kn) < 1e-6
    assert abs(era5_strong - apply_era5_correction(strong_kn)) < 1e-6
    assert era5_strong > strong_kn
    assert abs(era5_weak - weak_kn) < 1e-6
    assert abs(apply_era5_correction(weak_kn) - weak_kn) < 1e-6
    assert ERA5_STRONG_WIND_FACTOR == 1.05


def test_uo_east_vo_zero_current_to_90():
    kn, to_deg = uv_to_current_to(1.0, 0.0)
    assert abs(kn - MS_TO_KN) < 1e-6
    assert to_deg == 90.0


def test_two_days_known_wind_position_within_1nm():
    bind_om(forecast_kn=20.0, era5_kn=20.0)
    bind_ok_cmems(wind_kn=20.0)
    t0 = T0
    points = [
        {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False},
        {"lat": 46.15, "lon": -13.5, "cumNm": 500, "filmCum": 500, "jump": False},
    ]

    def wind_fn(lat, lon, t):
        return at(lat, lon, t)

    clock = build_voyage_clock(points, [], t0, polar_raw=None, start_at="saint-maur", wind_fn=wind_fn)
    sample = sample_clock_at_time(clock, t0 + timedelta(hours=48))
    expected_kn = boat_speed_from_wind(20.0)
    assert expected_kn == 9.0
    pack = at(LAT, LON, t0)
    # Le courant du hindcast est projeté sur la route (cap 270°).
    sog = max(0.5, sog_along_route(expected_kn, pack, 270.0))
    assert sample is not None
    assert abs(sample["sailNm"] - sog * 48.0) <= 1.0
    assert sample["regime"] == "hindcast"


def test_quay_speed_zero_keeps_hindcast_regime():
    bind_om()
    bind_ok_cmems()
    t0 = T0
    points = [
        {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False},
        {"lat": 46.0, "lon": -3.0, "cumNm": 80, "filmCum": 80, "jump": False},
    ]
    marks = [{"name": "Fort-de-France (Martinique)", "nm": 80, "filmNm": 80, "index": 1}]
    clock = build_voyage_clock(points, marks, t0, start_at="saint-maur", wind_fn=lambda la, lo, t: at(la, lo, t))
    mark = clock["marks"][0]
    sample = sample_clock_at_time(clock, parse_iso(mark["iso"]) + timedelta(hours=1))
    assert sample["atQuay"] is True
    assert sample["speedKnots"] == 0
    assert sample["regime"] == "hindcast"


def test_wx_from_hindcast_uses_duration_and_max():
    from voyage_journal import latest, record_wx_from_hindcast

    clock = {
        "t0": to_iso(T0),
        "vertices": [
            {"iso": "2026-05-16T00:00:00Z", "regime": "hindcast", "windKnots": 36.0, "hs": 2.0, "lat": 46.1, "lon": -1.2},
            {"iso": "2026-05-16T06:00:00Z", "regime": "hindcast", "windKnots": 41.0, "hs": 2.1, "lat": 46.0, "lon": -1.4},
        ],
    }
    assert record_wx_from_hindcast(clock, T0 + timedelta(days=3)) == 1
    assert record_wx_from_hindcast(clock, T0 + timedelta(days=3)) == 0
    wx = latest(5, kinds=("wx",))[0]
    assert wx["basis"] == "hindcast"
    assert wx["maxWindKnots"] == 41.0
    assert wx["hours"] >= 6.0


# ── RA8 — ERA5 le long de la route, sans Copernicus ───────────────────────

RA8_POLAR = {
    "twa_rows": [40, 60, 90, 120, 150, 180],
    "tws_cols": [8, 12, 16, 20, 24],
    "matrix": [
        [5.0, 6.5, 7.5, 8.0, 8.2],
        [6.0, 7.5, 8.5, 9.0, 9.2],
        [7.0, 8.5, 9.5, 10.0, 10.4],
        [6.5, 8.0, 9.0, 10.0, 10.2],
        [5.5, 7.0, 8.0, 9.0, 9.2],
        [4.5, 6.0, 7.0, 8.0, 8.2],
    ],
}

# Point hors des fixtures C2 pour ne pas réutiliser un blend Copernicus.
RA8_LAT, RA8_LON = 12.345, -23.456


def test_cmems_skipped_without_credentials(monkeypatch):
    monkeypatch.delenv("COPERNICUS_USERNAME", raising=False)
    monkeypatch.delenv("COPERNICUS_PASSWORD", raising=False)
    bind_om(era5_kn=14.0, forecast_kn=14.0)
    packed = series(RA8_LAT, RA8_LON, DAY0)
    assert "om-era5" in packed["products"]
    assert "cmems-wind" not in packed["products"]
    assert "cmems-wave" not in packed["products"]
    assert "cmems-phy" not in packed["products"]
    hour = next(h for h in packed["hours"] if h["t"].startswith(f"{DAY0}T08"))
    assert hour["regime"] == "hindcast"
    assert hour["speedKnots"] == 14.0
    assert "om-era5" in hour["sources"]


def test_era5_fill_raises_store_without_copernicus(monkeypatch):
    monkeypatch.delenv("COPERNICUS_USERNAME", raising=False)
    monkeypatch.delenv("COPERNICUS_PASSWORD", raising=False)
    bind_om(era5_kn=22.0)
    before = kv_count("hindcast")
    n = fill_era5_along([(RA8_LAT, RA8_LON, DAY0)])
    assert n >= 1
    assert kv_count("hindcast") > before
    hour = at(RA8_LAT, RA8_LON, T0, products=ERA5_PRODUCTS)
    assert hour["speedKnots"] == 22.0
    assert hour["regime"] == "hindcast"
    assert hour["sources"] == ["om-era5"]


def test_past_vertex_speed_from_era5_not_climatology(monkeypatch):
    """Sommet daté dans le passé : régime hindcast, vitesse = ERA5 × polaire."""
    monkeypatch.delenv("COPERNICUS_USERNAME", raising=False)
    monkeypatch.delenv("COPERNICUS_PASSWORD", raising=False)
    era5_kn = 24.0
    bind_om(era5_kn=era5_kn, forecast_kn=era5_kn)
    t0 = T0
    now = t0 + timedelta(hours=36)
    points = [
        {"lat": RA8_LAT, "lon": RA8_LON, "cumNm": 0, "filmCum": 0, "jump": False},
        {"lat": RA8_LAT, "lon": RA8_LON - 1.0, "cumNm": 30, "filmCum": 30, "jump": False},
    ]
    climo = build_voyage_clock(points, [], t0, polar_raw=RA8_POLAR, start_at="saint-maur")
    climo_sea = next(v for v in climo["vertices"] if (v.get("speedKnots") or 0) > 0)

    n = fill_era5_along([(RA8_LAT, RA8_LON, DAY0), (RA8_LAT, RA8_LON - 1.0, DAY0)])
    assert n >= 1

    def wind_fn(lat, lon, t):
        return blended_wind(
            lat, lon, t, t0, None,
            atlas_network=False, now=now,
            hindcast_fn=lambda la, lo, tt: at(la, lo, tt, products=ERA5_PRODUCTS),
        )

    clock = build_voyage_clock(
        points, [], t0, polar_raw=RA8_POLAR, start_at="saint-maur", wind_fn=wind_fn,
    )
    past = next(
        v for v in clock["vertices"]
        if parse_iso(v["iso"]) < now and (v.get("speedKnots") or 0) > 0
    )
    assert past["regime"] == "hindcast"
    assert past["sources"] == ["om-era5"]
    assert past["windKnots"] == era5_kn
    assert past["speedKnots"] != climo_sea["speedKnots"]
    from voyage_clock import polar_boat_speed, polar_efficiency
    stw = polar_boat_speed(RA8_POLAR, past["twa"], era5_kn) * polar_efficiency()
    assert abs(past["speedKnots"] - stw) < 0.3


def test_uncovered_slots_after_date_shift():
    lat, lon = 1.111, -2.222
    now = T0 + timedelta(days=3)
    clock = {
        "vertices": [
            {"lat": lat, "lon": lon, "iso": "2026-05-15T12:00:00Z", "vehicle": "main"},
            {"lat": lat, "lon": lon, "iso": "2026-05-20T12:00:00Z", "vehicle": "main"},
            {"lat": lat, "lon": lon, "iso": "2026-05-16T08:00:00Z", "vehicle": "plane"},
        ],
    }
    slots = past_passage_slots(clock, now)
    clat, clon = cell_center(lat, lon)
    assert (clat, clon, DAY0) in slots
    assert (clat, clon, "2026-05-20") not in slots
    assert all(s[2] != "2026-05-16" for s in slots)
    missing = uncovered_era5_slots(clock, now)
    assert (clat, clon, DAY0) in missing


# ── Cellule 0,25°, plage, quota, statut honnête ──────────────────

SAME_CELL_A = (46.15, -1.16)
SAME_CELL_B = (46.20, -1.20)
DAY2 = "2026-05-17"


def _put_era5_hours(lat, lon, day, kn=10.0):
    hours = {
        f"{day}T{h:02d}:00:00Z": {"speedKnots": kn, "dirFromDeg": 0.0, "gustKnots": kn + 2}
        for h in range(24)
    }
    kv_put("hindcast", cache_key(lat, lon, SRC_OM_ERA5, day), {
        "hours": hours, "source": SRC_OM_ERA5,
    })


def test_rf10_same_cell_same_day_one_call():
    assert cell_center(*SAME_CELL_A) == cell_center(*SAME_CELL_B)
    bind_om(era5_kn=12.0)
    n = fill_era5_along([(*SAME_CELL_A, DAY0), (*SAME_CELL_B, DAY0)])
    assert n == 1
    assert om_http_call_count() == 1
    a = at(*SAME_CELL_A, T0, products=ERA5_PRODUCTS, fetch=False)
    b = at(*SAME_CELL_B, T0, products=ERA5_PRODUCTS, fetch=False)
    assert a["speedKnots"] == 12.0
    assert b["speedKnots"] == 12.0


def test_rf10_three_day_range_one_call_three_cache_entries():
    bind_om(era5_kn=11.0)
    slots = [(*SAME_CELL_A, DAY0), (*SAME_CELL_A, DAY1), (*SAME_CELL_A, DAY2)]
    n = fill_era5_along(slots)
    assert n == 3
    assert om_http_call_count() == 1
    for day in (DAY0, DAY1, DAY2):
        hit = kv_get("hindcast", cache_key(*SAME_CELL_A, SRC_OM_ERA5, day))
        hours = ((hit or {}).get("value") or {}).get("hours")
        assert hours


def test_rf10_429_stops_empty_status_no_more_calls():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Daily API request limit exceeded")

    bind_http(lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    slots = [
        (10.0, -20.0, DAY0),
        (20.0, -30.0, DAY0),
        (30.0, -40.0, DAY0),
    ]
    assert fill_era5_along(slots) == 0
    assert om_http_call_count() == 1
    assert om_quota_blocked()
    assert kv_get("hindcast", cache_key(10.0, -20.0, SRC_OM_ERA5, DAY0)) is None
    assert fill_era5_along(slots) == 0
    assert om_http_call_count() == 1
    clock = {
        "vertices": [
            {"lat": 10.0, "lon": -20.0, "iso": "2026-05-15T12:00:00Z", "vehicle": "main"},
            {"lat": 20.0, "lon": -30.0, "iso": "2026-05-15T18:00:00Z", "vehicle": "main"},
        ],
    }
    fields = hindcast_status_fields(clock, T0 + timedelta(days=3), obtained=False)
    assert fields["hindcastStatus"] == "empty"
    assert fields["hindcastReason"] == "quota Open-Meteo"
    assert fields["hindcastCoverage"] == "0/2"
    assert "hindcastRefreshedAt" not in fields


def test_rf10_cached_cell_zero_calls_on_next_fill():
    bind_om(era5_kn=9.0)
    slot = (*SAME_CELL_A, DAY0)
    assert fill_era5_along([slot]) == 1
    assert om_http_call_count() == 1
    reset_hooks()
    bind_om(era5_kn=99.0)
    assert fill_era5_along([slot]) == 0
    assert om_http_call_count() == 0
    hour = at(*SAME_CELL_A, T0, products=ERA5_PRODUCTS, fetch=False)
    assert hour["speedKnots"] == 9.0


def test_rf10_status_ready_partial_empty():
    now = T0 + timedelta(days=30)
    verts = []
    for i in range(20):
        lat = 10.0 + i * 0.5
        verts.append({
            "lat": lat, "lon": -20.0,
            "iso": (T0 + timedelta(days=i)).strftime("%Y-%m-%dT12:00:00Z"),
            "vehicle": "main",
        })
    clock = {"vertices": verts}
    empty = hindcast_status_fields(clock, now, obtained=False)
    assert empty["hindcastStatus"] == "empty"
    assert empty["hindcastCoverage"] == "0/20"
    assert empty["hindcastReason"] == "panne"

    for i in range(18):
        _put_era5_hours(10.0 + i * 0.5, -20.0, (T0 + timedelta(days=i)).strftime("%Y-%m-%d"))
    partial = hindcast_status_fields(clock, now, obtained=True)
    assert partial["hindcastStatus"] == "partial"
    assert partial["hindcastCoverage"] == "18/20"
    assert "hindcastRefreshedAt" in partial

    _put_era5_hours(10.0 + 18 * 0.5, -20.0, (T0 + timedelta(days=18)).strftime("%Y-%m-%d"))
    ready = hindcast_status_fields(clock, now, obtained=True)
    assert ready["hindcastStatus"] == "ready"
    assert ready["hindcastCoverage"] == "19/20"


def test_rf10_voyage_dir_hosts_sqlite(tmp_path, monkeypatch):
    d = tmp_path / "shared-cache"
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(d))
    import voyage_store
    monkeypatch.setattr(voyage_store, "_DIR", d)
    import pearl_store
    pearl_store.reset()
    bind_om(era5_kn=8.0)
    fill_era5_along([(*SAME_CELL_A, DAY0)])
    assert (d / "naviguide.sqlite").exists()
    from pearl_store import db_path
    assert db_path() == d / "naviguide.sqlite"
    pearl_store.reset()


# ── HC1 — cache immuable par cellule, fenêtre, migration, trajet réel ────


def _bind_om_frontier(published_until: str, *, era5_kn=20.0, calls=None):
    """Archive ERA5 : vent pour les jours ≤ published_until, null ensuite
    (comme la vraie API pour les jours pas encore publiés)."""
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        start = params.get("start_date")
        end = params.get("end_date") or start
        if calls is not None:
            calls.append((start, end))
        times = _hours(start, end)
        n = len(times)
        speeds = [era5_kn if iso[:10] <= published_until else None for iso in times]
        return httpx.Response(200, json={"hourly": {
            "time": times,
            "wind_speed_10m": speeds,
            "wind_direction_10m": [0.0] * n,
            "wind_gusts_10m": [None if s is None else s + 3 for s in speeds],
        }})

    bind_http(lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def test_hc1_fill_window_one_call_never_refetches_cached_days():
    from hindcast import fill_era5_window
    calls: list = []
    _bind_om_frontier("2026-12-31", calls=calls)
    assert fill_era5_window(*SAME_CELL_A, DAY1) == 7          # [DAY1−3, DAY1+3]
    assert om_http_call_count() == 1
    assert calls[0] == ("2026-05-13", "2026-05-19")
    # Jour déjà en cache : zéro appel.
    assert fill_era5_window(*SAME_CELL_A, DAY0) == 0
    assert om_http_call_count() == 1
    # Jour au-delà de la fenêtre : l'appel suivant NE redemande pas les jours
    # cachés — la plage commence après le dernier jour en cache.
    assert fill_era5_window(*SAME_CELL_A, "2026-05-21") == 5  # 20..24 (pad +3), 19 déjà là
    assert om_http_call_count() == 2
    assert calls[1] == ("2026-05-20", "2026-05-24")


def test_hc1_unpublished_days_never_cached_then_filled_when_published():
    from hindcast import fill_era5_window
    _bind_om_frontier(DAY1)  # publié jusqu'au 16 mai seulement
    got = fill_era5_window(*SAME_CELL_A, DAY1)
    assert got == 4  # 13..16 mai ; 17..19 mai répondus null → PAS mis en cache
    assert kv_get("hindcast", cache_key(*SAME_CELL_A, SRC_OM_ERA5, DAY1)) is not None
    assert kv_get("hindcast", cache_key(*SAME_CELL_A, SRC_OM_ERA5, DAY2)) is None
    # Le lendemain, l'archive publie : le jour manquant est rempli, les jours
    # déjà téléchargés ne sont pas redemandés.
    reset_hooks()
    calls: list = []
    _bind_om_frontier("2026-12-31", era5_kn=30.0, calls=calls)
    assert fill_era5_window(*SAME_CELL_A, DAY2) >= 1
    assert calls[0][0] == DAY2  # commence après le 16 mai déjà en cache
    hit = kv_get("hindcast", cache_key(*SAME_CELL_A, SRC_OM_ERA5, DAY1))
    hour = next(iter(hit["value"]["hours"].values()))
    assert hour["speedKnots"] == 20.0  # le jour figé n'a pas bougé


def test_hc1_migration_rekeys_raw_coordinates_on_cell():
    from hindcast import migrate_orphan_cache_keys
    hours = {f"{DAY0}T{h:02d}:00:00Z": {"speedKnots": 14.0, "dirFromDeg": 0.0, "gustKnots": 17.0}
             for h in range(24)}
    raw_key = f"-0.344:-100.566:{SRC_OM_ERA5}:{DAY0}"
    kv_put("hindcast", raw_key, {"hours": hours, "source": SRC_OM_ERA5})
    # Une orpheline ambiguë : la clé cellule existe déjà → abandon, sans écraser.
    _put_era5_hours(10.07, -20.06, DAY0, kn=9.0)
    kv_put("hindcast", f"10.070:-20.060:{SRC_OM_ERA5}:{DAY0}", {"hours": hours, "source": SRC_OM_ERA5})
    out = migrate_orphan_cache_keys()
    assert out["migrated"] == 1
    assert out["abandoned"] == 1
    assert kv_get("hindcast", raw_key) is None
    moved = kv_get("hindcast", cache_key(-0.344, -100.566, SRC_OM_ERA5, DAY0))
    assert moved and moved["value"]["hours"]
    kept = kv_get("hindcast", cache_key(10.07, -20.06, SRC_OM_ERA5, DAY0))
    assert next(iter(kept["value"]["hours"].values()))["speedKnots"] == 9.0


HC1_POINTS = [
    {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False},
    {"lat": 46.15, "lon": -13.5, "cumNm": 500, "filmCum": 500, "jump": False},
    {"lat": 46.15, "lon": -38.0, "cumNm": 1520, "filmCum": 1520, "jump": False},
]


def _hc1_voy():
    return {
        "voyageId": "hc1-test", "t0": to_iso(T0), "points": [dict(p) for p in HC1_POINTS],
        "marks": [], "startAt": "saint-maur", "expedition_id": "berry-mappemonde-2026",
    }


def test_hc1_track_era5_keys_do_not_depend_on_climatology(monkeypatch):
    """Zones ou atlas pour l'avenir : les MÊMES clés ERA5 sont demandées —
    le besoin vient du trajet réel, pas de l'horloge climatologique."""
    import real_track
    from pearl_store import kv_keys
    monkeypatch.setenv("NAVIGUIDE_HINDCAST", "1")
    now = T0 + timedelta(days=10)
    _bind_om_frontier((now - timedelta(days=6)).strftime("%Y-%m-%d"))
    assert real_track.ensure_track(_hc1_voy(), now, None) is not None
    keys_a = sorted(k for k in kv_keys("hindcast") if f":{SRC_OM_ERA5}:" in k)

    import pearl_store
    pearl_store.reset()
    import climatology_zones
    real_zone = climatology_zones.zone_wind_at
    monkeypatch.setattr(climatology_zones, "zone_wind_at",
                        lambda lat, lon, m: {**real_zone(lat, lon, m), "speedKnots": 5.0})
    assert real_track.ensure_track(_hc1_voy(), now, None) is not None
    keys_b = sorted(k for k in kv_keys("hindcast") if f":{SRC_OM_ERA5}:" in k)
    assert keys_a == keys_b
    pearl_store.reset()


def test_hc1_quota_stops_track_cleanly_then_resumes(monkeypatch):
    import real_track
    monkeypatch.setenv("NAVIGUIDE_HINDCAST", "1")
    monkeypatch.setenv("NAVIGUIDE_OM_DAILY_BUDGET", "3")
    monkeypatch.setenv("NAVIGUIDE_OM_ETA_RESERVED", "0")
    now = T0 + timedelta(days=10)
    _bind_om_frontier("2026-12-31")
    track = real_track.ensure_track(_hc1_voy(), now, None)
    assert track is not None
    trunc = track["clock"].get("truncated")
    assert trunc and trunc["reason"] == "quota Open-Meteo"
    n_before = len(track["clock"]["vertices"])
    assert om_http_call_count() == 3  # arrêt propre au plafond

    # « Le lendemain » : budget rendu, la reprise AJOUTE des sommets sans
    # toucher aux anciens ni redemander un jour en cache.
    monkeypatch.setenv("NAVIGUIDE_OM_DAILY_BUDGET", "3000")
    import pearl_store
    from hindcast import OM_BUDGET_NS, _block_key, _budget_key
    pearl_store.kv_delete(OM_BUDGET_NS, _block_key())
    pearl_store.kv_delete(OM_BUDGET_NS, _budget_key())
    again = real_track.ensure_track(_hc1_voy(), now, None)
    verts = again["clock"]["vertices"]
    assert verts[:n_before] == track["clock"]["vertices"]
    assert len(verts) > n_before
    assert again["appended"] == len(verts) - n_before
    assert again["recomputed"] is False


def test_rg17_hindcast_leaves_reserved_slice_for_eta(monkeypatch):
    import pearl_store

    pearl_store.reset()
    reset_hooks()
    monkeypatch.setenv("NAVIGUIDE_OM_DAILY_BUDGET", "5")
    monkeypatch.setenv("NAVIGUIDE_OM_ETA_RESERVED", "2")
    assert om_eta_reserved() == 2
    assert om_hindcast_ceiling() == 3
    bind_om(era5_kn=10.0)
    slots = [(10.0 + i, -20.0 - i, DAY0) for i in range(6)]
    fill_era5_along(slots)
    assert om_http_call_count() == 3
    assert not om_quota_blocked()
    assert om_can_spend("ensemble")
    assert not om_can_spend("hindcast")
    pearl_store.reset()
    reset_hooks()
