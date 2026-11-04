from datetime import datetime, timezone
import pytest

from climatology_zones import zone_wind_at
from isochrone import (
    ISOCHRONE_STEP_COAST_H,
    ISOCHRONE_STEP_OFFSHORE_H,
    is_path_clear,
    is_land,
    isochrone_time_step_h,
    move_position,
    nudge_offshore,
    run_leg_isochrone,
)


def _const_wind(speed=16.0, direc=90.0):
    def fn(lat, lon, t):
        return {
            "speedKnots": speed,
            "dirFromDeg": direc,
            "kind": "forecast",
            "hs": 1.0,
            "model": "synthetic-test",
        }
    return fn


def test_iberia_land_crossing_blocked():
    # West of Portugal → inland peninsula
    assert is_path_clear(38.0, -10.5, 38.0, -10.0)
    assert not is_path_clear(38.0, -10.5, 38.0, -6.0)


def test_is_land_matches_global_land_mask_grid():
    """Direct grid indexing must answer exactly like the library (1 km mask)."""
    import isochrone as iso
    if not iso._USE_GLOBAL_LAND_MASK:
        return
    from global_land_mask import globe
    points = [
        (46.15, -1.16),   # La Rochelle harbour mouth
        (46.16, -1.15),   # town
        (45.0, -5.0),     # Bay of Biscay
        (38.0, -6.0),     # inland Spain
        (14.6, -61.07),   # Fort-de-France
        (0.0, 0.0), (-89.99, 179.99), (89.99, -179.99), (90.0, 180.0), (-90.0, -180.0),
    ]
    for lat, lon in points:
        assert iso.is_land(lat, lon) == bool(globe.is_land(lat, lon)), (lat, lon)


def test_short_leg_arrives_or_splices():
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    searoute = [(46.15, -1.16), (46.10, -2.0), (46.00, -3.2)]
    out = run_leg_isochrone(
        46.15, -1.16, 46.00, -3.2, t0,
        wind_fn=_const_wind(),
        polar_raw=None,
        time_step_h=6,
        heading_step_deg=10,
        max_steps=20,
        arrival_radius_nm=50,
        searoute_coords=searoute,
    )
    assert out["status"] in ("arrived", "spliced")
    coords = out["draft_geojson"]["geometry"]["coordinates"]
    assert len(coords) >= 2
    assert "forecast" in out["kind_mix"] or "climatology" in out["kind_mix"]


def test_wave_nogo_discards_step():
    def wind(lat, lon, t):
        return {"speedKnots": 16, "dirFromDeg": 90, "kind": "forecast", "hs": 4.0}

    def nogo(lat, lon, t):
        return True

    out = run_leg_isochrone(
        46.15, -1.16, 46.00, -3.2,
        datetime(2026, 6, 15, 8, tzinfo=timezone.utc),
        wind_fn=wind,
        wave_nogo_fn=nogo,
        max_steps=8,
        searoute_coords=[(46.15, -1.16), (46.00, -3.2)],
    )
    assert out["status"] in ("failed", "spliced")


def test_nudge_offshore_leaves_iberia():
    lat, lon = nudge_offshore(42.7, -8.8)
    assert not is_land(lat, lon)


def test_zone_june_not_used_as_forecast_label():
    z = zone_wind_at(46.15, -1.16, 6)
    assert z["kind"] == "climatology"


# ── Les ordres du skipper comme contraintes du routage ────────────────

def _field_wind(strong_lat_above=45.5, speed=38.0, hs=2.0):
    """Wind of 38 kn (a gale) north of `strong_lat_above`, 14 kn south of it."""
    def fn(lat, lon, t):
        gale = lat >= strong_lat_above
        return {"speedKnots": speed if gale else 14.0, "dirFromDeg": 270.0, "kind": "forecast", "hs": hs, "model": "synthetic-test"}
    return fn


def test_skipper_nogo_forbids_wind_and_sea_above_the_orders_and_never_a_blank_cell():
    from isochrone import WAVE_NOGO_M, skipper_nogo
    t = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    nogo = skipper_nogo(_field_wind(), wind_max_kt=34, hs_max_m=3.0)
    assert nogo(46.0, -3.0, t) is True, "38 kn ≥ 34 kn : interdit"
    assert nogo(45.0, -3.0, t) is False, "14 kn, Hs 2 m : permis"
    sea = skipper_nogo(lambda la, lo, tt: {"speedKnots": 10, "hs": 3.2}, hs_max_m=3.0)
    assert sea(45.0, -3.0, t) is True, "mer 3,2 m ≥ 3 m : interdit"
    # Without orders: the default sea limit only, the wind never forbids.
    default = skipper_nogo(_field_wind(speed=60.0, hs=1.0))
    assert default(46.0, -3.0, t) is False
    assert skipper_nogo(lambda la, lo, tt: {"speedKnots": 10, "hs": WAVE_NOGO_M})(45, -3, t) is True
    # A blank cell (no data) is never forbidden — nothing invented.
    blank = skipper_nogo(lambda la, lo, tt: {}, wind_max_kt=20, hs_max_m=1.0)
    assert blank(45.0, -3.0, t) is False
    assert skipper_nogo(lambda la, lo, tt: None, wind_max_kt=20)(45.0, -3.0, t) is False


def test_route_advice_stays_out_of_the_gale_when_the_skipper_says_so():
    """Fixture 'coup de vent au nord' : sans contrainte l'isochrone traverse la
    zone ventée ; avec l'ordre du skipper (34 kn) aucun point de la route
    conseillée n'y entre."""
    from isochrone import skipper_nogo
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    wind = _field_wind(strong_lat_above=45.5)
    common = dict(wind_fn=wind, polar_raw=None, time_step_h=6, heading_step_deg=15, max_steps=24, arrival_radius_nm=40)
    # Bay of Biscay, west → east along 45.3°N: the gale sits just north.
    free = run_leg_isochrone(45.3, -8.0, 45.3, -4.0, t0, **common)
    constrained = run_leg_isochrone(45.3, -8.0, 45.3, -4.0, t0, wave_nogo_fn=skipper_nogo(wind, wind_max_kt=34), **common)
    assert constrained["status"] in ("arrived", "spliced", "failed")
    coords = constrained["draft_geojson"]["geometry"]["coordinates"]
    assert coords, "a route is proposed even under constraint"
    assert all(lat < 45.5 for _lon, lat in coords[:-1]), "never a step inside the gale"
    assert free["status"] in ("arrived", "spliced", "failed")


def test_stuck_route_fixtures_never_cross_land():
    """Fixtures des routes coincées : Corse (contournement), détroit de
    Gibraltar, antiméridien — aucun segment de la route conseillée sur terre."""
    from isochrone import is_land
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    cases = {
        "corse-est-ouest": ((42.5, 9.6), (42.5, 8.3)),        # Bastia side → Calvi side, round the cape
        "gibraltar": ((36.0, -6.5), (36.2, -4.5)),             # Atlantic → Med through the strait
        "antimeridien": ((-18.0, 179.0), (-18.0, -179.0)),     # Fiji → across 180°
    }
    for name, ((la1, lo1), (la2, lo2)) in cases.items():
        out = run_leg_isochrone(la1, lo1, la2, lo2, t0, wind_fn=_const_wind(), polar_raw=None,
                                time_step_h=3, heading_step_deg=15, max_steps=30, arrival_radius_nm=25)
        coords = out["draft_geojson"]["geometry"]["coordinates"]
        assert coords, name
        # Every intermediate vertex is at sea (the destination itself may be a harbour).
        for lon, lat in coords[:-1]:
            assert not is_land(lat, lon), (name, lat, lon)
        # The antimeridian case never produces a 360° jump between vertices.
        if name == "antimeridien":
            for (lo_a, _la), (lo_b, _lb) in zip(coords, coords[1:]):
                d = abs(lo_b - lo_a)
                assert min(d, 360 - d) < 30, (lo_a, lo_b)


def test_c4_isochrone_step_1h_at_30nm_from_coast():
    """30 nm d'une côte → pas 1 h ; haute mer → 3 h."""
    import isochrone as iso
    if not iso._USE_GLOBAL_LAND_MASK:
        pytest.skip("global land mask is unavailable; coastal/offshore step sizes cannot be checked")
    la_c, lo_c = move_position(46.15, -1.16, 270.0, 30.0)
    assert isochrone_time_step_h(la_c, lo_c) == ISOCHRONE_STEP_COAST_H
    assert isochrone_time_step_h(45.0, -15.0) == ISOCHRONE_STEP_OFFSHORE_H
