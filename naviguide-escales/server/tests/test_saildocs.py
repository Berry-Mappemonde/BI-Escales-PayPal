from datetime import datetime, timedelta, timezone

import pytest

from saildocs import (
    GRIB_MISSING,
    GRIB_PRODUCTS,
    MAX_BBOX_LAT_SPAN,
    assert_corridor_not_globe,
    bbox_around,
    bbox_from_around,
    dest_eta_at_next_download,
    ingest_daily,
    last_ready_cycle,
    next_download_at,
    saildocs_queries,
    saildocs_query,
    track_from_clock,
    utc_day,
    wind_at_daily,
)
from voyage_clock import build_voyage_clock, sample_clock_at_time


def test_bbox_is_corridor_not_globe():
    box = bbox_around(46.15, -1.16, 200)
    south, north, west, east = box
    assert north - south < MAX_BBOX_LAT_SPAN
    assert abs(east - west) < 20
    assert_corridor_not_globe(box)
    with pytest.raises(ValueError, match="globe"):
        assert_corridor_not_globe((-80, 80, -180, 180))


def test_saildocs_query_around_boat():
    q = saildocs_query(46.15, -1.16)
    assert q.startswith("GFS:")
    assert "WIND" in q
    assert "PRMSL" in q
    assert "RAIN" in q
    assert "180W" not in q
    assert "90N" not in q


def test_saildocs_queries_three_noaa_products():
    items = saildocs_queries(46.15, -1.16, dest={"lat": 40.0, "lon": -15.0})
    codes = [i["query"].split(":")[0] for i in items]
    assert codes == ["GFS", "WW3", "RTOFS"]
    assert any("WIND,PRMSL,RAIN" in i["query"] for i in items)
    assert any("HTSGW" in i["query"] for i in items)
    assert any("CURRENT" in i["query"] for i in items)
    assert len(GRIB_PRODUCTS) == 3


def test_gfs_cycle_next_download():
    when = datetime(2026, 9, 15, 13, 48, tzinfo=timezone.utc)
    assert last_ready_cycle(when) == datetime(2026, 9, 15, 6, tzinfo=timezone.utc)
    assert next_download_at(when) == datetime(2026, 9, 15, 16, tzinfo=timezone.utc)
    assert dest_eta_at_next_download(when) == datetime(2026, 9, 15, 16, tzinfo=timezone.utc)
    soon = datetime(2026, 9, 15, 15, 50, tzinfo=timezone.utc)
    assert dest_eta_at_next_download(soon) == datetime(2026, 9, 15, 22, tzinfo=timezone.utc)


def test_saildocs_query_covers_dest_at_next_download():
    dest = {"lat": 40.0, "lon": -15.0, "t": "2026-09-16T12:00:00Z"}
    q_disk = saildocs_query(46.15, -1.16)
    q_track = saildocs_query(46.15, -1.16, dest=dest)
    assert q_disk != q_track
    south, north, west, east = bbox_from_around({
        "lat": 46.15,
        "lon": -1.16,
        "dest": dest,
    })
    assert south <= dest["lat"] <= north
    assert west <= dest["lon"] <= east
    assert north - south <= MAX_BBOX_LAT_SPAN


def test_track_from_clock_dest_is_eta_next_download():
    t0 = datetime(2026, 5, 15, 8, tzinfo=timezone.utc)
    clock = build_voyage_clock(
        [
            {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False, "nonMaritime": False},
            {"lat": 40.0, "lon": -15.0, "cumNm": 650, "filmCum": 650, "jump": False, "nonMaritime": False},
            {"lat": 14.6, "lon": -61.07, "cumNm": 3350, "filmCum": 3350, "jump": False, "nonMaritime": False},
        ],
        [
            {"name": "La Rochelle", "nm": 0, "filmNm": 0, "lat": 46.15, "lon": -1.16, "index": 0},
            {"name": "Fort-de-France (Martinique)", "nm": 3350, "filmNm": 3350, "lat": 14.6, "lon": -61.07, "index": 2},
        ],
        t0,
        start_at="la-rochelle",
    )
    when = t0 + timedelta(hours=48)
    around = track_from_clock(clock, when)
    assert around is not None
    dest_t = dest_eta_at_next_download(when)
    later = sample_clock_at_time(clock, dest_t)
    assert later is not None
    assert abs(around["dest"]["lat"] - later["lat"]) < 0.05
    assert abs(around["dest"]["lon"] - later["lon"]) < 0.05
    assert around["horizonHours"] == int(round((dest_t - when).total_seconds() / 3600.0))
    south, north, west, east = bbox_from_around(around)
    assert south <= around["dest"]["lat"] <= north
    assert west <= around["dest"]["lon"] <= east
    assert (around["lat"], around["lon"]) != (around["dest"]["lat"], around["dest"]["lon"])


def test_ingest_and_sample(tmp_path, monkeypatch):
    monkeypatch.setattr("saildocs.GRIB_DIR", tmp_path)
    when = datetime(2026, 9, 15, 8, tzinfo=timezone.utc)
    rec = ingest_daily(
        "berry-mappemonde-2026-officiel",
        {
            "model": "GFS",
            "day": utc_day(when),
            "around": {"lat": 46.15, "lon": -1.16},
            "samples": [{
                "lat": 46.15,
                "lon": -1.16,
                "t": "2026-09-15T08:00:00Z",
                "windKnots": 14,
                "dirFromDeg": 270,
            }],
        },
    )
    assert rec["status"] == "ready"
    assert rec["model"] == "GFS"
    wind = wind_at_daily(rec, 46.15, -1.16, when)
    assert wind["windKnots"] == 14
    assert wind["model"] == "GFS"


def test_globe_ingest_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("saildocs.GRIB_DIR", tmp_path)
    with pytest.raises(ValueError, match="globe"):
        ingest_daily(
            "berry-mappemonde-2026-officiel",
            {"bbox": [-80, 80, -180, 180], "model": "GFS", "samples": []},
        )


def test_missing_label():
    assert GRIB_MISSING == "dernière prévision absente"


# ── Antiméridien (parcours du 18/10, NAV-W-06 : bateau près des Fidji) ──────

def _query_lons(q: str):
    box = q.split(":", 1)[1].split("|", 1)[0].split(",")
    return box[2], box[3]


def _lon_value(token: str) -> float:
    v = float(token[:-1])
    assert token[-1] in "EW", token
    assert 0.0 <= v <= 180.0, token
    return v if token[-1] == "E" else -v


@pytest.mark.parametrize(
    "lat, lon, west, east",
    [
        (-18.2, -178.6, "177.9E", "175.1W"),
        (-18.2, 178.6, "175.1E", "177.9W"),
        (-17.0, 179.5, "176.0E", "177.0W"),
        (-17.0, 180.0, "176.5E", "176.5W"),
        (-17.0, -180.0, "176.5E", "176.5W"),
    ],
)
def test_saildocs_query_near_antimeridian_is_valid(lat, lon, west, east):
    q = saildocs_query(lat, lon)
    w, e = _query_lons(q)
    assert (w, e) == (west, east), q
    # Saildocs : lon0 (ouest) puis lon1 (est), chacune dans 0–180 E/W ;
    # une boîte qui passe 180° s'écrit ouest en E, est en W.
    wv, ev = _lon_value(w), _lon_value(e)
    assert wv > 0 > ev
    assert 0 < (ev - wv) % 360 < 20


@pytest.mark.parametrize("lon", [-178.6, 178.6, 179.5, 180.0, -180.0, 540.0])
def test_bbox_around_longitudes_stay_folded(lon):
    south, north, west, east = bbox_around(-17.0, lon)
    assert -180.0 <= west <= 180.0
    assert -180.0 <= east <= 180.0
    assert_corridor_not_globe((south, north, west, east))


def test_saildocs_query_one_point_matches_along_track_convention():
    """Un point seul et une route ici → demain donnent la même écriture."""
    alone = saildocs_query(-18.2, -178.6)
    with_dest = saildocs_query(-18.2, -178.6, dest={"lat": -18.3, "lon": -178.7})
    assert _query_lons(alone)[1].endswith("W")
    assert _query_lons(with_dest)[0].endswith("E")
    assert "182" not in alone and "182" not in with_dest
