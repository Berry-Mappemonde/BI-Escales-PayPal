from datetime import datetime, timedelta, timezone

from climatology_zones import zone_wind_at
from forecast_blend import FORECAST_BLEND_END_HOURS, FORECAST_FULL_HOURS, blended_wind
from forecast_cube import build_synthetic_cube, wind_differs_from_zone


def _route():
    return [
        {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False},
        {"lat": 40.0, "lon": -15.0, "cumNm": 650, "filmCum": 650, "jump": False},
        {"lat": 16.0, "lon": -40.0, "cumNm": 2600, "filmCum": 2600, "jump": False},
    ]


def test_b1_t0_plus_36h_differs_from_june_zone():
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    cube = build_synthetic_cube(_route(), t0, speed_knots=22, dir_from_deg=90)
    sample = cube.at(46.15, -1.16, t0 + timedelta(hours=36))
    assert sample is not None
    assert sample["kind"] == "forecast"
    assert sample["model"] == "synthetic-test"
    assert wind_differs_from_zone(sample, 46.15, -1.16, 6)
    zone = zone_wind_at(46.15, -1.16, 6)
    assert abs(sample["speedKnots"] - zone["speedKnots"]) > 1


def test_b2_ten_days_forecast_then_climo():
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    cube = build_synthetic_cube(_route(), t0)
    early = blended_wind(46.15, -1.16, t0 + timedelta(hours=36), t0, cube, now=t0)
    assert early["kind"] == "forecast"
    late = blended_wind(46.15, -1.16, t0 + timedelta(hours=FORECAST_BLEND_END_HOURS + 24), t0, cube, now=t0)
    assert late["kind"] == "climatology"
    assert late.get("leadHours") is None
    blend = blended_wind(46.15, -1.16, t0 + timedelta(hours=FORECAST_FULL_HOURS + 24), t0, cube, now=t0)
    assert blend.get("source") == "blend"
    assert 0 < blend["blend"] < 1


def test_c2_fade_relative_to_now_not_t0():
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    now = t0 + timedelta(days=8)
    cube = build_synthetic_cube(_route(), t0)
    # now+36 h = t0+8,5 j : fondu si l'origine était t0, prévision pleine depuis maintenant.
    later = blended_wind(46.15, -1.16, now + timedelta(hours=36), t0, cube, now=now)
    assert later["kind"] == "forecast"
    assert later.get("source") != "blend"
    past = blended_wind(
        46.15, -1.16, now - timedelta(hours=3), t0, cube, now=now,
        hindcast_fn=lambda *_a: {"speedKnots": 11.0, "dirFromDeg": 80.0, "sources": ["om-era5"], "spread": 1.5},
    )
    assert past["kind"] == "hindcast"
    assert past["regime"] == "hindcast"
    assert past["sources"] == ["om-era5"]


def test_empty_cube_falls_back_honest():
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    far = blended_wind(-40.0, 80.0, t0 + timedelta(hours=12), t0, None, now=t0)
    assert far["kind"] == "climatology"


def test_cache_only_mode_never_calls_the_atlas(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("network call inside the isochrone loop")

    monkeypatch.setattr("climatology_atlas.fetch_atlas_point", boom)
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    far = blended_wind(-40.0, 80.0, t0 + timedelta(days=20), t0, None, atlas_network=False, now=t0)
    assert far["kind"] == "climatology"
    assert far["source"] == "zone_fallback"
    from forecast_blend import make_wind_fn
    fn = make_wind_fn(t0, None, atlas_network=False, now=t0)
    assert fn(-40.0, 80.0, t0 + timedelta(days=20))["kind"] == "climatology"


def test_cube_memory_under_80mo():
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    cube = build_synthetic_cube(_route(), t0)
    assert cube.estimate_bytes() < 80 * 1024 * 1024
