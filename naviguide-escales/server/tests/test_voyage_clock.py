"""B0 — contrat JSON table A = table serveur + tests mars / juillet."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from climatology_zones import zone_wind_at
from voyage_clock import (
    AIR_CALENDAR_HOURS,
    DEFAULT_BMAP_PORT_DAYS,
    LAND_CALENDAR_HOURS,
    MIN_KNOTS,
    OFFICIAL_T0,
    OFFICIAL_VOYAGE_ID,
    PLANNING_MIN_KN,
    build_voyage_clock,
    detect_air_episodes,
    find_start_index,
    official_clock_params,
    planning_speed_for,
    polar_boat_speed,
    polar_efficiency,
    port_days_for,
    port_days_table,
    sample_clock_at_hours,
    sample_clock_at_time,
    sog_along_route,
    wave_polar_factor,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "clock_golden_route.json"
GOLDEN = json.loads(FIXTURE.read_text(encoding="utf-8"))

VERTEX_KEYS = {
    "filmNm", "sailNm", "lat", "lon", "bearing", "tHours", "iso",
    "speedKnots", "windKnots", "twa", "month", "vehicle", "kind", "seaHours",
    "basis",
}
TABLE_KEYS = {"t0", "kind", "vertices", "marks", "seaHours", "quayHours", "arrivalIso"}


def _clock(t0: str, **extra):
    return build_voyage_clock(
        GOLDEN["points"],
        GOLDEN["marks"],
        t0,
        polar_raw=None,
        start_at="la-rochelle",
        **extra,
    )


def test_schema_golden():
    c = _clock("2026-06-15T08:00:00Z")
    assert TABLE_KEYS <= set(c)
    assert c["kind"] == "climatology"
    v = c["vertices"][-1]
    assert VERTEX_KEYS <= set(v)
    assert c["vertices"][0]["tHours"] == 0
    hours = [x["tHours"] for x in c["vertices"]]
    assert hours == sorted(hours)


def test_june_fdf_after_t0():
    c = _clock("2026-06-15T08:00:00Z")
    fdf = next(m for m in c["marks"] if "Fort-de-France" in m["name"])
    assert datetime.fromisoformat(fdf["iso"].replace("Z", "+00:00")) > datetime(
        2026, 6, 15, 8, tzinfo=timezone.utc
    )


def test_march_vs_july_fdf():
    mar = _clock("2026-03-15T08:00:00Z")
    jul = _clock("2026-07-15T08:00:00Z")
    a = next(m for m in mar["marks"] if "Fort-de-France" in m["name"])
    b = next(m for m in jul["marks"] if "Fort-de-France" in m["name"])
    da = datetime.fromisoformat(a["iso"].replace("Z", "+00:00"))
    db = datetime.fromisoformat(b["iso"].replace("Z", "+00:00"))
    assert abs((da - db).total_seconds()) > 24 * 3600


def test_official_t0_and_bmap_3_days():
    assert OFFICIAL_T0.startswith("2026-05-15")
    assert OFFICIAL_VOYAGE_ID == "berry-mappemonde-2026-officiel"
    assert DEFAULT_BMAP_PORT_DAYS == 3
    assert port_days_for("Ajaccio") == 3
    assert port_days_for("Cayenne") == 3
    assert port_days_for("Papeete") == 3
    assert port_days_for("Halifax") == 1


def test_quay_72h_same_filmn():
    c = _clock("2026-06-15T08:00:00Z")
    fdf = next(m for m in c["marks"] if "Fort-de-France" in m["name"])
    assert fdf["holdHours"] == 72
    same = [v for v in c["vertices"] if abs(v["filmNm"] - fdf["filmNm"]) < 1e-6]
    assert len(same) >= 2
    assert same[-1]["tHours"] - same[0]["tHours"] >= 71.9


def test_air_hop():
    points = [
        {"lat": 4.9, "lon": -52.3, "cumNm": 0, "filmCum": 0, "jump": False},
        {"lat": 44.6, "lon": -63.6, "cumNm": 0, "filmCum": 80, "jump": True},
    ]
    c = build_voyage_clock(points, [], "2026-06-15T08:00:00Z", start_at="saint-maur")
    assert c["vertices"][-1]["tHours"] == AIR_CALENDAR_HOURS
    assert c["vertices"][-1]["speedKnots"] is None
    assert c["vertices"][-1]["vehicle"] == "plane"


def test_no_polar_climatology():
    c = _clock("2026-06-15T08:00:00Z")
    assert any(v["kind"] == "climatology" and (v["speedKnots"] or 0) > 0 for v in c["vertices"])


def test_antimeridian_monotone():
    points = [
        {"lat": -20, "lon": 170, "cumNm": 0, "filmCum": 0, "jump": False},
        {"lat": -20, "lon": 176, "cumNm": 300, "filmCum": 300, "jump": False},
        {"lat": -20, "lon": -178, "cumNm": 600, "filmCum": 600, "jump": False},
        {"lat": -20, "lon": -170, "cumNm": 900, "filmCum": 900, "jump": False},
    ]
    c = build_voyage_clock(points, [], "2026-06-15T08:00:00Z", start_at="saint-maur")
    hours = [v["tHours"] for v in c["vertices"]]
    assert hours == sorted(hours)


def test_la_rochelle_departure_is_t0_plus_land_and_cayenne_stays_three_days():
    """Départ de La Rochelle = t0 + jambe terrestre ; Cayenne reste 3 jours."""

    def wind_fn(lat, lon, t):
        return {"speedKnots": 10.0, "dirFromDeg": 90.0, "kind": "climatology"}

    t0 = "2026-05-15T08:00:00Z"
    t0d = datetime(2026, 5, 15, 8, tzinfo=timezone.utc)
    points = [
        {"lat": 46.8, "lon": 1.63, "cumNm": 0, "filmCum": 0, "jump": False, "nonMaritime": True},
        {"lat": 46.15, "lon": -1.16, "cumNm": 200, "filmCum": 200, "jump": False, "nonMaritime": True},
        {"lat": 14.6, "lon": -61.0, "cumNm": 3400, "filmCum": 3400, "jump": False},
        {"lat": 4.93, "lon": -52.35, "cumNm": 4000, "filmCum": 4000, "jump": False},
        {"lat": 44.65, "lon": -63.57, "cumNm": 4000, "filmCum": 4080, "jump": True},
        {"lat": 46.78, "lon": -56.16, "cumNm": 4400, "filmCum": 4480, "jump": False},
        {"lat": 44.65, "lon": -63.57, "cumNm": 4800, "filmCum": 4880, "jump": False},
        {"lat": 4.93, "lon": -52.35, "cumNm": 4800, "filmCum": 4960, "jump": True},
        {"lat": -17.54, "lon": -149.57, "cumNm": 8000, "filmCum": 8200, "jump": False},
    ]
    marks = [
        {"name": "La Rochelle", "nm": 200, "filmNm": 200, "index": 1},
        {"name": "Cayenne (Guyane)", "nm": 4000, "filmNm": 4000, "lat": 4.93, "lon": -52.35, "index": 3},
        {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "nm": 4400, "filmNm": 4480,
         "lat": 10.0, "lon": 10.0, "index": 5},
        {"name": "Papeete (Polynésie française)", "nm": 8000, "filmNm": 8200, "index": 8},
    ]
    c = build_voyage_clock(points, marks, t0, start_at="saint-maur", wind_fn=wind_fn)
    lr = next(m for m in c["marks"] if m["name"] == "La Rochelle")
    depart = datetime.fromisoformat(lr["iso"].replace("Z", "+00:00"))
    assert lr["holdHours"] == 0
    assert abs((depart - t0d).total_seconds() - LAND_CALENDAR_HOURS * 3600) < 1

    cayennes = [m for m in c["marks"] if "Cayenne" in (m.get("name") or "")]
    assert len(cayennes) == 1
    assert cayennes[0]["holdHours"] == port_days_for("Cayenne (Guyane)") * 24 == 72

    spm = next(m for m in c["marks"] if "Saint-Pierre" in (m.get("name") or ""))
    assert abs(spm["lat"] - 46.7761) < 1e-3
    assert abs(spm["lon"] - (-56.1628)) < 1e-3

    by_lr = build_voyage_clock(points, marks, t0, start_at="la-rochelle", wind_fn=wind_fn)
    at_lr = next(v for v in by_lr["vertices"] if abs(v["sailNm"] - 200) < 1e-6 and v["vehicle"] != "quay")
    assert at_lr["tHours"] == LAND_CALENDAR_HOURS


def test_start_saint_maur_land_dt():
    points = [
        {"lat": 46.8, "lon": 1.63, "cumNm": 0, "filmCum": 0, "jump": False, "nonMaritime": True},
        {"lat": 46.15, "lon": -1.16, "cumNm": 200, "filmCum": 200, "jump": False, "nonMaritime": True},
        {"lat": 45.0, "lon": -5.0, "cumNm": 400, "filmCum": 400, "jump": False, "nonMaritime": False},
    ]
    marks = [{"name": "La Rochelle", "nm": 200, "filmNm": 200, "index": 1}]
    assert find_start_index(points, marks, "saint-maur") == 0
    c = build_voyage_clock(points, marks, "2026-06-15T08:00:00Z", start_at="saint-maur")
    at_lr = next(v for v in c["vertices"] if abs(v["sailNm"] - 200) < 1e-6 and v["vehicle"] != "quay")
    assert at_lr["tHours"] == 4


def test_sample_waiting_and_live():
    c = _clock("2026-06-15T08:00:00Z")
    waiting = sample_clock_at_time(c, "2026-06-14T08:00:00Z")
    assert waiting["status"] == "waiting"
    live = sample_clock_at_hours(c, 12)
    assert live["status"] == "live"
    assert live["iso"] == "2026-06-15T20:00:00Z"


def test_atlas_wind_fn_keeps_kind_and_hs():
    def wind_fn(lat, lon, t):
        return {
            "speedKnots": 22.0,
            "dirFromDeg": 80.0,
            "kind": "climatology",
            "source": "atlas",
            "period": "1980-2020",
            "doi": {"wind": "10.48670/moi-00183"},
            "hsP50": 1.2,
            "hsP90": 2.6,
            "currentKn": 0.3,
        }

    c = _clock("2026-06-15T08:00:00Z", wind_fn=wind_fn)
    sea = next(v for v in c["vertices"] if (v.get("speedKnots") or 0) > 0)
    assert sea["kind"] == "climatology"
    assert sea["source"] == "atlas"
    assert sea["hsP90"] == 2.6
    assert sea["period"] == "1980-2020"


def test_sample_at_quay_speed_zero():
    c = _clock("2026-06-15T08:00:00Z")
    fdf = next(m for m in c["marks"] if "Fort-de-France" in m["name"])
    s = sample_clock_at_hours(c, float(fdf["tHours"]) + 1)
    assert s["atQuay"] is True
    assert s["speedKnots"] == 0
    assert s["vehicle"] == "quay"


def test_c2_steps_cap_30nm_or_1h_and_mid_step_wind():
    calls = []

    def wind_fn(lat, lon, t):
        calls.append((lat, lon, t))
        return {"speedKnots": 20.0, "dirFromDeg": 0.0, "kind": "hindcast", "regime": "hindcast", "sources": ["om-era5"], "spread": 1.0}

    points = [
        {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False},
        {"lat": 46.15, "lon": -3.5, "cumNm": 90, "filmCum": 90, "jump": False},
    ]
    t0 = datetime(2026, 5, 15, 8, tzinfo=timezone.utc)
    c = build_voyage_clock(points, [], t0, start_at="saint-maur", wind_fn=wind_fn)
    sea = [v for v in c["vertices"] if v.get("vehicle") == "main" and (v.get("speedKnots") or 0) > 0]
    assert len(sea) >= 2
    for a, b in zip(sea, sea[1:]):
        assert (b["sailNm"] - a["sailNm"]) <= 30.0 + 1e-6
        assert (b["tHours"] - a["tHours"]) <= 1.0 + 1e-6
    assert sea[0]["regime"] == "hindcast"
    assert sea[0]["sources"] == ["om-era5"]
    assert calls, "vent lu à mi-pas"


def test_c2_regime_flips_at_now():
    now = datetime(2026, 5, 17, 8, tzinfo=timezone.utc)

    def wind_fn(lat, lon, t):
        if t < now:
            return {"speedKnots": 14.0, "dirFromDeg": 80.0, "kind": "hindcast", "regime": "hindcast", "sources": ["om-forecast"], "spread": 0.5}
        return {"speedKnots": 16.0, "dirFromDeg": 90.0, "kind": "forecast", "regime": "forecast"}

    points = [
        {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False},
        {"lat": 40.0, "lon": -15.0, "cumNm": 650, "filmCum": 650, "jump": False},
    ]
    c = build_voyage_clock(points, [], "2026-05-15T08:00:00Z", start_at="saint-maur", wind_fn=wind_fn)
    before = sample_clock_at_time(c, now - timedelta(hours=2))
    after = sample_clock_at_time(c, now + timedelta(hours=2))
    assert before["regime"] == "hindcast"
    assert after["regime"] == "forecast"


def test_js_py_same_schema_keys():
    """Le golden partagé impose les mêmes clés des deux côtés."""
    c = _clock(GOLDEN["t0"])
    assert TABLE_KEYS <= set(c)
    assert VERTEX_KEYS <= set(c["vertices"][0])
    # La Rochelle juin : vent de zone ≠ 0
    z = zone_wind_at(46.15, -1.16, 6)
    assert z["kind"] == "climatology"
    assert z["speedKnots"] > 0


# ── C4 — courant, vagues, efficacité, climatologie ────────────────────────

C4_POLAR = {
    "twa_rows": [40, 60, 90, 120, 150, 180],
    "tws_cols": [8, 12, 16, 20],
    "matrix": [
        [5.0, 6.5, 7.5, 8.0],
        [6.0, 7.5, 8.5, 9.0],
        [7.0, 8.5, 9.5, 10.0],
        [6.5, 8.0, 9.0, 10.0],
        [5.5, 7.0, 8.0, 9.0],
        [4.5, 6.0, 7.0, 8.0],
    ],
}

# Même table que skipperOrders.test.js (parité JS/Python).
C4_PLANNING_POLAR = {
    "twa_rows": [60, 90, 120, 150],
    "tws_cols": [6, 10, 14, 20],
    "matrix": [[4, 6, 7, 8], [5, 7, 8.5, 10], [4.5, 6.5, 8, 10], [3.5, 5, 7, 9]],
}


def _c4_leg(wind):
    points = [
        {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False},
        {"lat": 46.15, "lon": -2.16, "cumNm": 30, "filmCum": 30, "jump": False},
    ]
    return build_voyage_clock(
        points, [], "2026-06-15T08:00:00Z",
        polar_raw=C4_POLAR, start_at="saint-maur",
        wind_fn=lambda lat, lon, t: dict(wind),
    )


def test_c4_current_along_and_against():
    polar = polar_boat_speed(C4_POLAR, 90, 16)
    assert polar == 9.5
    assert abs(polar_efficiency() - 0.85) < 1e-9
    expected = polar * 0.85 + 2.0
    along = {"speedKnots": 16.0, "dirFromDeg": 0.0, "kind": "hindcast",
             "currentKn": 2.0, "currentToDeg": 270.0, "hs": 1.0}
    # cap 270° (ouest) : lon diminue, courant vers l'ouest = dans l'axe
    c = _c4_leg(along)
    sea = next(v for v in c["vertices"] if (v.get("speedKnots") or 0) > 0)
    assert abs(sea["speedKnots"] - expected) < 0.15
    against = {**along, "currentToDeg": 90.0}
    c2 = _c4_leg(against)
    sea2 = next(v for v in c2["vertices"] if (v.get("speedKnots") or 0) > 0)
    assert abs(sea2["speedKnots"] - (polar * 0.85 - 2.0)) < 0.15
    # uo/vo : 2 kn vers l'ouest = uo < 0
    uo = -2.0 / 1.943844
    vec = sog_along_route(polar * 0.85, {"uo": uo, "vo": 0.0}, 270.0)
    assert abs(vec - expected) < 1e-3


def test_c4_wave_polar_continuous_and_head_worse_than_follow():
    f24 = wave_polar_factor(2.4, 0.0)
    f26 = wave_polar_factor(2.6, 0.0)
    assert abs(f26 - f24) < 0.08
    assert f24 > f26
    assert wave_polar_factor(1.5, 0.0) == 1.0
    assert abs(wave_polar_factor(4.0, 0.0) - 0.6) < 1e-9
    assert abs(wave_polar_factor(4.0, 180.0) - 0.85) < 1e-9
    assert wave_polar_factor(5.0, 0.0) == wave_polar_factor(4.0, 0.0)
    head = wave_polar_factor(3.0, 0.0)
    follow = wave_polar_factor(3.0, 180.0)
    assert head < follow
    # L'horloge : mer de face plus lente que mer arrière, même Hs.
    base = {"speedKnots": 16.0, "dirFromDeg": 0.0, "kind": "hindcast", "hs": 3.0}
    face = _c4_leg({**base, "waveFromDeg": 270.0})
    back = _c4_leg({**base, "waveFromDeg": 90.0})
    sf = next(v for v in face["vertices"] if (v.get("speedKnots") or 0) > 0)["speedKnots"]
    sb = next(v for v in back["vertices"] if (v.get("speedKnots") or 0) > 0)["speedKnots"]
    assert sf < sb


def test_c4_climatology_jensen_mean_of_times():
    """Temps aux p25/p50/p75 moyenné ≥ temps à la moyenne (inégalité de Jensen)."""
    mean_kn = 12.0
    draws = [6.0, 12.0, 20.0]
    heading = 90.0
    wind_from = 0.0  # TWA 90°
    speeds = []
    for kn in draws:
        twa = 90.0
        stw = polar_boat_speed(C4_POLAR, twa, kn) * polar_efficiency()
        speeds.append(max(0.5, stw))
    t_avg = sum(1.0 / s for s in speeds) / 3.0
    t_mean = 1.0 / (polar_boat_speed(C4_POLAR, 90.0, mean_kn) * polar_efficiency())
    assert t_avg >= t_mean - 1e-9
    rose = {
        "speedKnots": mean_kn, "dirFromDeg": wind_from, "kind": "climatology",
        "roseKnots": draws, "hs": 1.0,
    }
    mean_only = {
        "speedKnots": mean_kn, "dirFromDeg": wind_from, "kind": "climatology", "hs": 1.0,
    }
    c_rose = _c4_leg(rose)
    c_mean = _c4_leg(mean_only)
    assert c_rose["seaHours"] >= c_mean["seaHours"] - 1e-6


def test_c7_port_days_table_default_and_saint_maur():
    table = port_days_table()
    assert table["default"] == 3
    assert table.get("source") == "programme Berry-Mappemonde 2026"
    assert DEFAULT_BMAP_PORT_DAYS == 3
    assert port_days_for("Saint-Maur") == 0
    assert port_days_for("Saint-Maur (Berry, Indre)") == 0
    assert port_days_for("Ajaccio") == 3
    assert port_days_for("Cayenne (Guyane)") == 3
    assert port_days_for("Halifax (Nouvelle-Écosse)") == 1
    assert port_days_for("Port-inconnu-xyz") == 3


def test_c7_basis_fallback_without_polar():
    c = _clock("2026-06-15T08:00:00Z")
    assert c["vertices"]
    assert all(v.get("basis") in {"polar", "fallback"} for v in c["vertices"])
    sea = [v for v in c["vertices"] if v.get("vehicle") == "main" and (v.get("speedKnots") or 0) > 0]
    assert sea
    assert all(v["basis"] == "fallback" for v in sea)


def test_c7_basis_polar_when_polar():
    c = _c4_leg({
        "speedKnots": 16.0, "dirFromDeg": 0.0, "kind": "hindcast", "hs": 1.0,
    })
    sea = next(v for v in c["vertices"] if (v.get("speedKnots") or 0) > 0)
    assert sea["basis"] == "polar"


def test_c7_official_params():
    p = official_clock_params()
    assert p["landHours"] == LAND_CALENDAR_HOURS
    assert p["airHours"] == AIR_CALENDAR_HOURS
    assert p["minKnots"] == MIN_KNOTS
    assert p["portDaysDefault"] == 3
    assert p["polarEfficiency"] == polar_efficiency()


def test_sail_nm_excludes_air_miles():
    """Le vol prend AIR_CALENDAR_HOURS, il n'ajoute pas de milles à la voile."""
    points = [
        {"lat": 4.9, "lon": -52.3, "cumNm": 1000, "filmCum": 1000, "jump": False},
        {"lat": 44.6, "lon": -63.6, "cumNm": 2500, "filmCum": 2580, "jump": True},
        {"lat": 44.7, "lon": -63.8, "cumNm": 2530, "filmCum": 2610, "jump": False},
    ]
    c = build_voyage_clock(points, [], "2026-06-15T08:00:00Z", start_at="saint-maur")
    plane = next(v for v in c["vertices"] if v.get("vehicle") == "plane")
    assert plane["sailNm"] == 1000
    assert plane["tHours"] == AIR_CALENDAR_HOURS
    sea_after = [v for v in c["vertices"] if v.get("vehicle") == "main" and v["sailNm"] > 1000]
    assert sea_after
    assert max(v["sailNm"] for v in sea_after) == 1030


def test_sail_nm_includes_halifax_spm_excludes_cayenne_halifax():
    """Halifax ↔ SPM compte à la voile ; seules Cayenne ↔ Halifax restent avion."""

    def wind_fn(lat, lon, t):
        return {"speedKnots": 10.0, "dirFromDeg": 90.0, "kind": "climatology"}

    points = [
        {"lat": 4.93, "lon": -52.35, "cumNm": 1000, "filmCum": 1000, "jump": False},
        {"lat": 44.65, "lon": -63.57, "cumNm": 1000, "filmCum": 1080, "jump": True},
        {"lat": 46.78, "lon": -56.16, "cumNm": 1400, "filmCum": 1480, "jump": False},
        {"lat": 44.65, "lon": -63.57, "cumNm": 1800, "filmCum": 1880, "jump": False},
        {"lat": 4.93, "lon": -52.35, "cumNm": 1800, "filmCum": 1960, "jump": True},
        {"lat": 4.80, "lon": -52.50, "cumNm": 1830, "filmCum": 1990, "jump": False},
    ]
    c = build_voyage_clock(
        points, [], "2026-06-15T08:00:00Z", start_at="saint-maur", wind_fn=wind_fn,
    )
    planes = [v for v in c["vertices"] if v.get("vehicle") == "plane"]
    assert len(planes) == 2
    assert planes[0]["sailNm"] == 1000
    assert planes[0]["tHours"] == AIR_CALENDAR_HOURS
    assert planes[1]["sailNm"] == 1800
    assert planes[1]["tHours"] > planes[0]["tHours"] + AIR_CALENDAR_HOURS - 1e-6
    side = [v for v in c["vertices"] if v.get("vehicle") == "side"]
    assert side
    assert any(abs(v["lat"] - 46.78) < 0.05 for v in side)
    sea = [v for v in c["vertices"] if v.get("vehicle") in {"main", "side"} and v["sailNm"] > 1000]
    assert sea
    assert max(v["sailNm"] for v in sea) == 1830
    assert c["seaHours"] > 0


def test_live_position_deterministic_same_date():
    c = _clock("2026-05-15T08:00:00Z")
    when = "2026-05-20T12:00:00Z"
    a = sample_clock_at_time(c, when)
    b = sample_clock_at_time(c, when)
    assert a["status"] == "live"
    assert a["lat"] == b["lat"]
    assert a["lon"] == b["lon"]
    assert a["sailNm"] == b["sailNm"]
    assert a["status"] == b["status"]


def test_c4_planning_speed_parity_with_js():
    assert abs(polar_efficiency() - 0.85) < 1e-9
    assert planning_speed_for(C4_PLANNING_POLAR, 10, 90) == 6.0
    assert planning_speed_for(C4_PLANNING_POLAR, 20, 150) == 7.7
    assert planning_speed_for(C4_PLANNING_POLAR, 0, 90) == PLANNING_MIN_KN


def test_ra8_past_vertex_hindcast_era5_speed_not_climatology():
    """Un sommet passé a regime=hindcast et une vitesse ERA5 × polaire."""
    era5 = {
        "speedKnots": 24.0, "dirFromDeg": 0.0,
        "kind": "hindcast", "regime": "hindcast", "sources": ["om-era5"],
    }
    points = [
        {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False},
        {"lat": 46.15, "lon": -2.16, "cumNm": 30, "filmCum": 30, "jump": False},
    ]
    t0 = datetime(2026, 5, 15, 8, tzinfo=timezone.utc)
    climo = build_voyage_clock(points, [], t0, polar_raw=C4_POLAR, start_at="saint-maur")
    clock = build_voyage_clock(
        points, [], t0, polar_raw=C4_POLAR, start_at="saint-maur",
        wind_fn=lambda lat, lon, t: dict(era5),
    )
    climo_sea = next(v for v in climo["vertices"] if (v.get("speedKnots") or 0) > 0)
    sea = next(v for v in clock["vertices"] if (v.get("speedKnots") or 0) > 0)
    assert sea["regime"] == "hindcast"
    assert sea["kind"] == "hindcast"
    assert sea["sources"] == ["om-era5"]
    assert sea["windKnots"] == 24.0
    assert sea["speedKnots"] != climo_sea["speedKnots"]
    assert clock["kind"] in {"hindcast", "mixed"}
    stw = polar_boat_speed(C4_POLAR, sea["twa"], 24.0) * polar_efficiency()
    assert abs(sea["speedKnots"] - stw) < 0.3


# ── HC1 — troncature propre quand le vent RÉEL s'épuise ──────────────────


def test_hc1_wind_exhausted_truncates_cleanly():
    """Plus de vent réel → l'horloge s'arrête au dernier pas complet, dit où
    et pourquoi — aucun sommet au vent inventé après la frontière."""
    from voyage_clock import WindExhausted

    era5 = {
        "speedKnots": 20.0, "dirFromDeg": 0.0,
        "kind": "hindcast", "regime": "hindcast", "sources": ["om-era5"],
    }
    t0 = datetime(2026, 5, 15, 8, tzinfo=timezone.utc)
    frontier = t0 + timedelta(hours=24)

    def wind_fn(lat, lon, t):
        if t >= frontier:
            raise WindExhausted("pas encore publié")
        return dict(era5)

    points = [
        {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False},
        {"lat": 46.15, "lon": -13.5, "cumNm": 500, "filmCum": 500, "jump": False},
    ]
    clock = build_voyage_clock(points, [], t0, polar_raw=None,
                               start_at="saint-maur", wind_fn=wind_fn)
    trunc = clock.get("truncated")
    assert trunc is not None
    assert trunc["reason"] == "pas encore publié"
    assert trunc["pointIndex"] == 0
    last = clock["vertices"][-1]
    assert last["regime"] == "hindcast"
    # ~24 h à 9 kn : la troncature tombe au pas en cours, pas plus loin.
    assert last["tHours"] <= 24.0 + 1e-6
    assert last["tHours"] >= 23.0
    assert abs(trunc["pointCumNm"] - last["sailNm"]) < 1e-6
    sea = [v for v in clock["vertices"] if (v.get("speedKnots") or 0) > 0]
    assert all(v["regime"] == "hindcast" for v in sea)

    # Sans troncature : pas de clé `truncated` (contrat d'hier inchangé).
    full = build_voyage_clock(points, [], t0, polar_raw=None,
                              start_at="saint-maur", wind_fn=lambda *a: dict(era5))
    assert "truncated" not in full


def test_rc31_episode_side_halifax_quay():
    """Véhicule side entre les vols, marques Halifax, quay Cayenne."""

    def wind_fn(lat, lon, t):
        return {"speedKnots": 10.0, "dirFromDeg": 90.0, "kind": "climatology"}

    points = [
        {"lat": 4.93, "lon": -52.35, "cumNm": 1000, "filmCum": 1000, "jump": False},
        {"lat": 44.65, "lon": -63.57, "cumNm": 1000, "filmCum": 1080, "jump": True},
        {"lat": 46.78, "lon": -56.16, "cumNm": 1400, "filmCum": 1480, "jump": False},
        {"lat": 44.65, "lon": -63.57, "cumNm": 1800, "filmCum": 1880, "jump": False},
        {"lat": 4.93, "lon": -52.35, "cumNm": 1800, "filmCum": 1960, "jump": True},
        {"lat": 4.80, "lon": -52.50, "cumNm": 1830, "filmCum": 1990, "jump": False},
    ]
    marks = [
        {"name": "Cayenne (Guyane)", "nm": 1000, "filmNm": 1000, "lat": 4.93, "lon": -52.35},
        {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "nm": 1400, "filmNm": 1480,
         "lat": 46.78, "lon": -56.16},
    ]
    eps = detect_air_episodes(points)
    assert len(eps) == 1
    assert abs(eps[0]["park"]["lat"] - 4.93) < 0.05
    assert abs(eps[0]["hub"]["lat"] - 44.65) < 0.05
    assert abs(eps[0]["via"]["lat"] - 46.78) < 0.05
    c = build_voyage_clock(
        points, marks, "2026-07-19T08:00:00Z", start_at="saint-maur", wind_fn=wind_fn,
    )
    planes = [v for v in c["vertices"] if v.get("vehicle") == "plane"]
    assert len(planes) == 2
    side = [v for v in c["vertices"] if v.get("vehicle") == "side"]
    assert side
    assert min(v["tHours"] for v in side) > planes[0]["tHours"] - 1e-6
    assert max(v["tHours"] for v in side) < planes[1]["tHours"] + 1e-6
    halifax = [m for m in c["marks"] if "Halifax" in (m.get("name") or "")]
    assert len(halifax) >= 2
    assert all(abs(float(m.get("holdHours") or 0) - 24) < 1e-6 for m in halifax)
    quay_cay = [
        v for v in c["vertices"]
        if v.get("vehicle") == "quay" and abs(float(v.get("lat") or 0) - 4.93) < 0.2
    ]
    assert quay_cay
    mid = (min(v["tHours"] for v in side) + max(v["tHours"] for v in side)) / 2
    sample = sample_clock_at_hours(c, mid)
    assert sample["vehicle"] == "side"
    assert sample["lat"] > 43
    assert sample.get("parkLat") is None or abs(sample["parkLat"] - 4.93) < 0.2


def _v(lon, t_hours, film, lat=-20.0):
    return {
        "filmNm": film, "sailNm": film, "lat": lat, "lon": lon, "bearing": 270.0,
        "tHours": t_hours, "iso": None, "speedKnots": 8.0, "windKnots": 15.0,
        "twa": 120.0, "month": 10, "vehicle": "main", "kind": "climatology",
        "regime": "climatology", "seaHours": t_hours, "basis": "polar",
    }


def test_sample_crosses_antimeridian_by_short_arc():
    """18/10 : -180 à 06:34 puis 179.85 à 07:34 ; à 07:17 le marqueur était à +77."""
    clock = {
        "t0": "2026-10-18T06:34:06Z",
        "vertices": [_v(-180.0, 0.0, 0.0), _v(179.8506921644703, 1.0, 8.7)],
        "marks": [],
    }
    for t in (0.1, 0.5, 43 / 60, 0.9):
        s = sample_clock_at_hours(clock, t)
        assert -180.0 <= s["lon"] <= 180.0
        assert abs(abs(s["lon"]) - 180.0) < 0.2, (t, s["lon"])
    eastward = {
        "t0": "2026-10-18T00:00:00Z",
        "vertices": [_v(179.9, 0.0, 0.0), _v(-179.9, 1.0, 11.3)],
        "marks": [],
    }
    mid = sample_clock_at_hours(eastward, 0.5)["lon"]
    assert abs(abs(mid) - 180.0) < 1e-6


def test_clock_marks_lon_in_range_after_antimeridian():
    """Route dépliée (Wallis → Nouméa → Mayotte) : marques comme sommets dans [-180, 180]."""
    points = [
        {"lat": -13.3, "lon": -176.2, "cumNm": 0, "filmCum": 0, "jump": False},
        {"lat": -20.0, "lon": -185.0, "cumNm": 600, "filmCum": 600, "jump": False},
        {"lat": -22.3, "lon": -193.5, "cumNm": 1100, "filmCum": 1100, "jump": False},
        {"lat": -15.0, "lon": -260.0, "cumNm": 5000, "filmCum": 5000, "jump": False},
        {"lat": -12.8, "lon": -314.7, "cumNm": 8000, "filmCum": 8000, "jump": False},
    ]
    marks = [
        {"name": "Mata-Utu (Wallis-et-Futuna)", "nm": 0, "filmNm": 0, "index": 0},
        {"name": "Nouméa (Nouvelle-Calédonie)", "nm": 1100, "filmNm": 1100, "index": 2},
        {"name": "Dzaoudzi (Mayotte)", "nm": 8000, "filmNm": 8000, "index": 4},
    ]
    c = build_voyage_clock(points, marks, "2026-10-15T00:00:00Z", start_at="seam")
    for v in c["vertices"]:
        assert -180.0 <= v["lon"] <= 180.0
    by_name = {m["name"]: m for m in c["marks"]}
    noumea = by_name["Nouméa (Nouvelle-Calédonie)"]
    mayotte = by_name["Dzaoudzi (Mayotte)"]
    assert abs(noumea["lon"] - 166.5) < 1e-6
    assert abs(mayotte["lon"] - 45.3) < 1e-6
    assert noumea["iso"] < mayotte["iso"]


def test_future_clock_keeps_mark_order_after_seam():
    """Avenir depuis la couture : l'index de route complète est recalé sur la tranche."""
    import real_track

    lons = [-170.0, -173.0, -176.2, -180.0, -185.0, -193.5, -200.0, -230.0, -260.0, -290.0, -314.7,
            -330.0, -345.0, -355.0, -358.0, -360.0, -361.2]
    lats = [-15.0, -14.0, -13.3, -18.0, -20.0, -22.3, -21.0, -18.0, -15.0, -13.0, -12.8,
            0.0, 20.0, 35.0, 42.0, 45.0, 46.2]
    pts, cum = [], 0.0
    for k, (la, lo) in enumerate(zip(lats, lons)):
        if k:
            cum += 300.0 * k
        pts.append({"lat": la, "lon": lo, "cumNm": cum, "filmCum": cum, "jump": False, "nonMaritime": False})
    marks = [
        {"name": "Mata-Utu (Wallis-et-Futuna)", "nm": pts[2]["cumNm"], "filmNm": pts[2]["cumNm"], "index": 2},
        {"name": "Nouméa (Nouvelle-Calédonie)", "nm": pts[5]["cumNm"], "filmNm": pts[5]["cumNm"], "index": 5},
        {"name": "Dzaoudzi (Mayotte)", "nm": pts[10]["cumNm"], "filmNm": pts[10]["cumNm"], "index": 10},
        {"name": "La Rochelle", "nm": pts[16]["cumNm"], "filmNm": pts[16]["cumNm"], "index": 16},
    ]
    voy = {"points": pts, "marks": marks, "t0": "2026-05-15T08:00:00Z"}
    seam_i = 3
    track = {
        "clock": {
            "vertices": [{**_v(-178.0, 3600.0, pts[seam_i]["cumNm"] + 50, lat=-18.8),
                          "iso": "2026-10-16T02:05:17Z"}],
            "truncated": {
                "reason": "unpublished",
                "pointIndex": seam_i,
                "pointCumNm": pts[seam_i]["cumNm"] + 50,
                "pointFilmCum": pts[seam_i]["cumNm"] + 50,
            },
        },
    }
    fut = real_track.future_clock(voy, track, None)
    by_name = {m["name"]: m for m in fut["marks"]}
    noumea = by_name["Nouméa (Nouvelle-Calédonie)"]
    mayotte = by_name["Dzaoudzi (Mayotte)"]
    assert abs(noumea["lat"] - (-22.3)) < 1e-6
    assert abs(noumea["lon"] - 166.5) < 1e-6
    assert noumea["iso"] < mayotte["iso"] < by_name["La Rochelle"]["iso"]
    for m in fut["marks"]:
        assert -180.0 <= m["lon"] <= 180.0
    for v in fut["vertices"]:
        assert -180.0 <= v["lon"] <= 180.0


def test_official_clock_keeps_one_cayenne_and_saint_pierre_port():
    from voyage_clock import _dedupe_cayenne_marks, _stop_latlon

    marks = [
        {"name": "Fort-de-France (Martinique)"},
        {"name": "Cayenne (Guyane)", "holdHours": 72},
        {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)"},
        {"name": "Cayenne (Guyane)", "holdHours": 0},
    ]
    out = _dedupe_cayenne_marks(marks)
    assert [m["name"] for m in out].count("Cayenne (Guyane)") == 1
    assert out[1]["holdHours"] == 72
    assert len(out) == 3

    lat, lon = _stop_latlon("Saint-Pierre (Saint-Pierre-et-Miquelon)", {"lat": 10.0, "lon": 10.0}, {})
    assert (lat, lon) == (46.7761, -56.1628)
    lat, lon = _stop_latlon("Papeete (Polynésie française)", {"lat": -17.5, "lon": -149.6}, {"lat": 0, "lon": 0})
    assert (lat, lon) == (-17.5, -149.6)
    lat, lon = _stop_latlon("Papeete (Polynésie française)", {}, {"lat": -17.0, "lon": -149.0})
    assert (lat, lon) == (-17.0, -149.0)
